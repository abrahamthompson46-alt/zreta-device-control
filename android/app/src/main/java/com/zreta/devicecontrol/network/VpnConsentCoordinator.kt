package com.zreta.devicecontrol.network

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.zreta.devicecontrol.R
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.policy.PolicyWorker
import com.zreta.devicecontrol.policy.enforcement.EnforcementResult

/**
 * Handles VPN consent pending state after PolicyWorker enforcement.
 * Never launches the system VPN consent Intent from a Worker — only notifies / stores pending.
 */
object VpnConsentCoordinator {
    private const val PREFS = "zreta_vpn_consent"
    private const val KEY_PENDING = "consent_pending"
    private const val CHANNEL_ID = "zreta_vpn_consent"
    private const val NOTIFICATION_ID = 5102
    const val BOOT_WORK_NAME = "zreta-policy-boot"
    const val REENFORCE_WORK_NAME = "zreta-policy-reenforce"

    fun handleEnforcementResult(context: Context, result: EnforcementResult?) {
        val app = context.applicationContext
        if (DnsFilterTelemetry.needsConsent(result)) {
            setPending(app, true)
            showNotification(app)
            return
        }
        val snap = DnsFilterTelemetry.fromEnforcement(result)
        if (snap?.state == DnsFilterTelemetry.RUNNING ||
            (result?.shouldAckAsApplied() == true && !DnsFilterTelemetry.needsConsent(result))
        ) {
            setPending(app, false)
            cancelNotification(app)
        }
    }

    fun isPending(context: Context): Boolean =
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_PENDING, false)

    fun setPending(context: Context, pending: Boolean) {
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_PENDING, pending)
            .apply()
    }

    fun enqueuePolicyReenforce(context: Context, uniqueName: String = REENFORCE_WORK_NAME) {
        val store = SecureCredentialStore(context)
        if (!store.isEnrolled()) return
        val request = OneTimeWorkRequestBuilder<PolicyWorker>().build()
        WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
            uniqueName,
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }

    fun showNotification(context: Context) {
        ensureChannel(context)
        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, VpnConsentActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setContentTitle(context.getString(R.string.vpn_consent_notification_title))
            .setContentText(context.getString(R.string.vpn_consent_notification_text))
            .setSmallIcon(R.drawable.ic_dns_filter_notification)
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        val mgr = context.getSystemService(NotificationManager::class.java) ?: return
        mgr.notify(NOTIFICATION_ID, notification)
    }

    fun cancelNotification(context: Context) {
        val mgr = context.getSystemService(NotificationManager::class.java) ?: return
        mgr.cancel(NOTIFICATION_ID)
    }

    private fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val mgr = context.getSystemService(NotificationManager::class.java) ?: return
        mgr.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.vpn_consent_channel_name),
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = context.getString(R.string.vpn_consent_channel_description)
            },
        )
    }
}
