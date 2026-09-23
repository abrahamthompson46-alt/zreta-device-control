package com.zreta.devicecontrol.network

import android.content.Context
import android.net.VpnService
import com.zreta.devicecontrol.policy.enforcement.DnsFilterServiceState
import com.zreta.devicecontrol.policy.enforcement.EnforcementOutcome
import com.zreta.devicecontrol.policy.enforcement.EnforcementResult
import com.zreta.devicecontrol.policy.enforcement.EnforcementStateStore

/**
 * Telemetry values aligned with backend DeviceStatus.DnsFilterReportedState.
 */
object DnsFilterTelemetry {
    const val UNKNOWN = "unknown"
    const val STOPPED = "stopped"
    const val RUNNING = "running"
    const val CONSENT_REQUIRED = "consent_required"
    const val FAILED = "failed"

    data class Snapshot(val state: String, val error: String?)

    fun needsConsent(result: EnforcementResult?): Boolean =
        result?.controlResults?.any {
            it.control == "traffic.filter" && it.detail == "vpn_consent_required"
        } == true

    fun fromEnforcement(result: EnforcementResult?): Snapshot? {
        if (result == null) return null
        if (needsConsent(result)) {
            return Snapshot(CONSENT_REQUIRED, "vpn_consent_required")
        }
        val traffic = result.controlResults.find { it.control == "traffic.filter" }
        return when {
            traffic == null -> null
            traffic.status == "failed" -> Snapshot(FAILED, traffic.detail?.take(64))
            result.outcome == EnforcementOutcome.APPLIED ||
                result.outcome == EnforcementOutcome.NO_CHANGES -> {
                if (result.controlResults.any {
                        it.control == "traffic.filter" &&
                            (it.status == "started" || it.status == "reloaded" || it.status == "unchanged")
                    }
                ) {
                    Snapshot(RUNNING, null)
                } else if (result.controlResults.any {
                        it.control == "traffic.filter" &&
                            (it.status == "stopped" || it.status == "cleared" || it.status == "absent")
                    }
                ) {
                    Snapshot(STOPPED, null)
                } else {
                    null
                }
            }
            else -> traffic.detail?.let { Snapshot(FAILED, it.take(64)) }
        }
    }

    fun current(context: Context): Snapshot {
        val managed = EnforcementStateStore(context).load().state
        val prepareNeeded = try {
            VpnService.prepare(context) != null
        } catch (_: Exception) {
            false
        }
        if (managed.trafficFilterDesiredEnabled && prepareNeeded) {
            return Snapshot(CONSENT_REQUIRED, "vpn_consent_required")
        }
        return when (DnsFilterRuntime.instance.observedForEnforcer()) {
            DnsFilterServiceState.RUNNING -> Snapshot(RUNNING, null)
            else -> {
                val err = managed.trafficLastError ?: DnsFilterRuntime.instance.lastError()
                when {
                    err == "vpn_consent_required" -> Snapshot(CONSENT_REQUIRED, err)
                    !err.isNullOrBlank() && managed.trafficFilterDesiredEnabled ->
                        Snapshot(FAILED, err.take(64))
                    else -> Snapshot(STOPPED, null)
                }
            }
        }
    }
}
