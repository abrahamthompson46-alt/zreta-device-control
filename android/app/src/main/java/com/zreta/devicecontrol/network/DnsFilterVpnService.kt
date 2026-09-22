package com.zreta.devicecontrol.network

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import com.zreta.devicecontrol.R
import com.zreta.devicecontrol.ui.MainActivity
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramSocket
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Local DNS-filter VPN (Phase 5.1B).
 *
 * Visible foreground service; narrow DNS routes only; fail-open; not always-on / lockdown.
 * Does not fetch policy or talk to the Zreta backend.
 */
class DnsFilterVpnService : VpnService() {
    private val runtime = DnsFilterRuntime.instance
    private val running = AtomicBoolean(false)
    private var tun: ParcelFileDescriptor? = null
    private var loopThread: Thread? = null
    private var upstream: UdpDnsUpstream? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopFilter("stopped")
                return START_NOT_STICKY
            }
            ACTION_RELOAD -> {
                val domains = intent.getStringArrayListExtra(EXTRA_DOMAINS)?.toList().orEmpty()
                if (running.get()) {
                    // Apply new rules only while TUN loop is live (hot reload).
                    runtime.setBlockedDomains(domains)
                    runtime.signalRunning()
                } else {
                    runtime.signalFailed("vpn_reload_not_running")
                }
                return START_NOT_STICKY
            }
            else -> {
                val domains = intent?.getStringArrayListExtra(EXTRA_DOMAINS)?.toList()
                    ?: runtime.blockedDomains()
                runtime.setBlockedDomains(domains)
                startFilter()
                return START_NOT_STICKY
            }
        }
    }

    override fun onRevoke() {
        stopFilter("vpn_revoked")
        super.onRevoke()
    }

    override fun onDestroy() {
        stopFilter("destroyed")
        super.onDestroy()
    }

    private fun startFilter() {
        if (running.get()) {
            runtime.signalRunning()
            return
        }
        try {
            startForegroundNotification()
            val established = establishTun()
            if (established == null) {
                runtime.signalFailed("vpn_establish_failed")
                stopForegroundCompat()
                stopSelf()
                return
            }
            tun = established
            val protectedUpstream = UdpDnsUpstream(protect = { socket ->
                protectSocket(socket)
            })
            // Probe protect before claiming RUNNING.
            val probe = DatagramSocket()
            val protectOk = try {
                protectSocket(probe)
            } finally {
                try {
                    probe.close()
                } catch (_: Exception) {
                }
            }
            if (!protectOk) {
                closeTun()
                runtime.signalFailed("vpn_upstream_protect_failed")
                stopForegroundCompat()
                stopSelf()
                return
            }
            upstream = protectedUpstream
            running.set(true)
            loopThread = thread(name = "zreta-dns-tun", isDaemon = true) {
                runPacketLoop(established)
            }
            runtime.signalRunning()
        } catch (_: Exception) {
            closeTun()
            running.set(false)
            runtime.signalFailed("vpn_start_failed")
            stopForegroundCompat()
            stopSelf()
        }
    }

    private fun stopFilter(reason: String) {
        if (!running.getAndSet(false) && tun == null) {
            runtime.signalStopped()
            stopForegroundCompat()
            stopSelf()
            return
        }
        closeTun()
        loopThread = null
        upstream = null
        if (reason == "vpn_revoked" || reason == "vpn_upstream_protect_failed") {
            runtime.signalFailed(reason)
        } else {
            runtime.signalStopped()
        }
        stopForegroundCompat()
        stopSelf()
    }

    private fun closeTun() {
        try {
            tun?.close()
        } catch (_: Exception) {
        }
        tun = null
    }

    private fun protectSocket(socket: DatagramSocket): Boolean {
        return try {
            protect(socket)
        } catch (_: Exception) {
            false
        }
    }

    private fun establishTun(): ParcelFileDescriptor? {
        return try {
            val builder = Builder()
                .setSession(DnsFilterAddresses.SESSION_NAME)
                .setMtu(DnsFilterAddresses.MAX_TUN_PACKET)
                .addAddress(DnsFilterAddresses.IPV4_TUN, 32)
                .addAddress(DnsFilterAddresses.IPV6_TUN, 128)
                .addDnsServer(DnsFilterAddresses.IPV4_DNS)
                .addDnsServer(DnsFilterAddresses.IPV6_DNS)
                // Narrow routes — DNS endpoints only (not full tunnel).
                .addRoute(DnsFilterAddresses.IPV4_DNS, 32)
                .addRoute(DnsFilterAddresses.IPV6_DNS, 128)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                builder.setMetered(false)
            }
            builder.establish()
        } catch (_: Exception) {
            null
        }
    }

    private fun runPacketLoop(pfd: ParcelFileDescriptor) {
        val input = FileInputStream(pfd.fileDescriptor)
        val output = FileOutputStream(pfd.fileDescriptor)
        val buffer = ByteArray(DnsFilterAddresses.MAX_TUN_PACKET)
        val engine = runtime.engine()
        try {
            while (running.get()) {
                val length = try {
                    input.read(buffer)
                } catch (_: Exception) {
                    break
                }
                if (length <= 0) break
                if (length > DnsFilterAddresses.MAX_TUN_PACKET) continue
                val up = upstream
                val response = try {
                    DnsTunPacketHandler.handle(
                        packet = buffer,
                        length = length,
                        engine = engine,
                        forwardDns = { payload ->
                            if (up == null) null else up.query(payload)
                        },
                    )
                } catch (_: Exception) {
                    null
                }
                if (response != null && running.get()) {
                    try {
                        output.write(response)
                    } catch (_: Exception) {
                        break
                    }
                }
            }
        } finally {
            try {
                input.close()
            } catch (_: Exception) {
            }
            try {
                output.close()
            } catch (_: Exception) {
            }
            if (running.get()) {
                // Unexpected loop exit → fail-open.
                running.set(false)
                closeTun()
                runtime.signalFailed("vpn_loop_exited")
                stopForegroundCompat()
                stopSelf()
            }
        }
    }

    private fun startForegroundNotification() {
        ensureChannel()
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.dns_filter_notification_title))
            .setContentText(getString(R.string.dns_filter_notification_text))
            .setSmallIcon(R.drawable.ic_dns_filter_notification)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun stopForegroundCompat() {
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (_: Exception) {
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val mgr = getSystemService(NotificationManager::class.java) ?: return
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.dns_filter_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.dns_filter_channel_description)
        }
        mgr.createNotificationChannel(channel)
    }

    companion object {
        const val ACTION_START = "com.zreta.devicecontrol.network.action.START"
        const val ACTION_STOP = "com.zreta.devicecontrol.network.action.STOP"
        const val ACTION_RELOAD = "com.zreta.devicecontrol.network.action.RELOAD"
        const val EXTRA_DOMAINS = "blocked_domains"
        const val CHANNEL_ID = "zreta_dns_filter"
        const val NOTIFICATION_ID = 5101
    }
}
