package com.zreta.devicecontrol.network

import android.content.Context
import android.content.Intent
import android.os.Build
import com.zreta.devicecontrol.policy.enforcement.DnsFilterController
import com.zreta.devicecontrol.policy.enforcement.DnsFilterOpResult
import com.zreta.devicecontrol.policy.enforcement.DnsFilterServiceState

/** Command dispatched to start/stop/reload the VPN service (testable without Android Intent stubs). */
data class DnsFilterServiceCommand(
    val action: String,
    val domains: List<String> = emptyList(),
)

/**
 * Production [DnsFilterController] backed by [DnsFilterVpnService].
 *
 * Does not launch VPN consent UI from a Worker — returns `vpn_consent_required` instead.
 * Reports RUNNING only after the service signals TUN + packet loop readiness.
 */
class VpnDnsFilterController(
    private val runtime: DnsFilterRuntime = DnsFilterRuntime.instance,
    private val prepareIntent: () -> Any? = { null },
    private val dispatch: (DnsFilterServiceCommand) -> Unit,
    private val readinessTimeoutMs: Long = 20_000L,
) : DnsFilterController {

    override fun start(blockedDomains: List<String>): DnsFilterOpResult {
        if (prepareIntent() != null) {
            runtime.noteConsentRequired()
            return DnsFilterOpResult(false, DnsFilterServiceState.STOPPED, "vpn_consent_required")
        }
        if (runtime.observedState() == DnsFilterServiceState.RUNNING) {
            return reload(blockedDomains)
        }
        val latch = runtime.beginStart(blockedDomains)
        return try {
            dispatch(DnsFilterServiceCommand(DnsFilterVpnService.ACTION_START, blockedDomains))
            if (!runtime.awaitLatch(latch, readinessTimeoutMs)) {
                return DnsFilterOpResult(
                    false,
                    runtime.observedForEnforcer(),
                    "vpn_start_timeout",
                )
            }
            when (runtime.observedState()) {
                DnsFilterServiceState.RUNNING ->
                    DnsFilterOpResult(true, DnsFilterServiceState.RUNNING, null)
                else ->
                    DnsFilterOpResult(
                        false,
                        runtime.observedForEnforcer(),
                        runtime.lastError() ?: "vpn_start_failed",
                    )
            }
        } catch (ex: Exception) {
            val code = classifyDispatchFailure(ex, "vpn_start_failed")
            runtime.signalFailed(code)
            DnsFilterOpResult(false, DnsFilterServiceState.STOPPED, code)
        }
    }

    override fun stop(): DnsFilterOpResult {
        val current = runtime.observedState()
        if (current == DnsFilterServiceState.STOPPED || current == DnsFilterServiceState.FAILED) {
            runtime.signalStopped()
            return DnsFilterOpResult(true, DnsFilterServiceState.STOPPED, null)
        }
        val latch = runtime.beginStop()
        return try {
            dispatch(DnsFilterServiceCommand(DnsFilterVpnService.ACTION_STOP))
            if (!runtime.awaitLatch(latch, readinessTimeoutMs)) {
                return DnsFilterOpResult(
                    false,
                    runtime.observedForEnforcer(),
                    "vpn_stop_timeout",
                )
            }
            val observed = runtime.observedForEnforcer()
            if (observed == DnsFilterServiceState.STOPPED) {
                DnsFilterOpResult(true, DnsFilterServiceState.STOPPED, null)
            } else {
                DnsFilterOpResult(false, observed, runtime.lastError() ?: "vpn_stop_failed")
            }
        } catch (_: Exception) {
            DnsFilterOpResult(false, runtime.observedForEnforcer(), "vpn_stop_failed")
        }
    }

    override fun reload(blockedDomains: List<String>): DnsFilterOpResult {
        if (prepareIntent() != null) {
            runtime.noteConsentRequired()
            return DnsFilterOpResult(false, DnsFilterServiceState.STOPPED, "vpn_consent_required")
        }
        if (runtime.observedState() != DnsFilterServiceState.RUNNING) {
            return start(blockedDomains)
        }
        val latch = runtime.beginReloadAck()
        return try {
            dispatch(DnsFilterServiceCommand(DnsFilterVpnService.ACTION_RELOAD, blockedDomains))
            if (!runtime.awaitLatch(latch, readinessTimeoutMs)) {
                return DnsFilterOpResult(
                    false,
                    runtime.observedForEnforcer(),
                    "vpn_reload_timeout",
                )
            }
            when (runtime.observedState()) {
                DnsFilterServiceState.RUNNING -> {
                    // Service applied domains before signaling RUNNING.
                    if (runtime.blockedDomains() != blockedDomains) {
                        // Defensive: require engine list to match desired after ack.
                        return DnsFilterOpResult(
                            false,
                            runtime.observedForEnforcer(),
                            "vpn_reload_rules_mismatch",
                        )
                    }
                    DnsFilterOpResult(true, DnsFilterServiceState.RUNNING, null)
                }
                else ->
                    DnsFilterOpResult(
                        false,
                        runtime.observedForEnforcer(),
                        runtime.lastError() ?: "vpn_reload_failed",
                    )
            }
        } catch (ex: Exception) {
            val code = classifyDispatchFailure(ex, "vpn_reload_failed")
            // Do not change applied engine rules on dispatch failure; service never applied.
            DnsFilterOpResult(false, runtime.observedForEnforcer(), code)
        }
    }

    override fun observedState(): DnsFilterServiceState = runtime.observedForEnforcer()

    override fun lastError(): String? = runtime.lastError()

    companion object {
        fun create(context: Context): VpnDnsFilterController {
            val app = context.applicationContext
            return VpnDnsFilterController(
                runtime = DnsFilterRuntime.instance,
                prepareIntent = { android.net.VpnService.prepare(app) },
                dispatch = { command ->
                    val intent = Intent(app, DnsFilterVpnService::class.java).apply {
                        action = command.action
                        putStringArrayListExtra(
                            DnsFilterVpnService.EXTRA_DOMAINS,
                            ArrayList(command.domains),
                        )
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        app.startForegroundService(intent)
                    } else {
                        app.startService(intent)
                    }
                },
                readinessTimeoutMs = 20_000L,
            )
        }

        internal fun classifyDispatchFailure(ex: Exception, fallback: String): String {
            val name = ex.javaClass.name
            return when {
                name.contains("ForegroundServiceStartNotAllowedException") ->
                    "vpn_fgs_start_not_allowed"
                else -> fallback
            }
        }
    }
}
