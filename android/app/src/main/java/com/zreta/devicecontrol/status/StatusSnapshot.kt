package com.zreta.devicecontrol.status

import android.content.Context
import com.zreta.devicecontrol.BuildConfig
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.dpc.ManagementStateDetector

object StatusSnapshot {
    private fun enforcementSummary(context: Context): String {
        return try {
            val loaded = com.zreta.devicecontrol.policy.enforcement.EnforcementStateStore(context).load()
            val state = loaded.state
            buildString {
                append("camera=${if (state.cameraDisabledManaged) state.cameraDisabledValue else "unmanaged"}")
                append("; capture=${if (state.screenCaptureDisabledManaged) state.screenCaptureDisabledValue else "unmanaged"}")
                append("; suspended=${state.suspendedPackages.size}")
                append("; hidden=${state.hiddenPackages.size}")
                append("; uninstall_blocked=${state.uninstallBlockedPackages.size}")
                if (state.recoveryRequired || loaded.wasCorrupt) append("; recovery_required")
                append("; accepted_v=${state.acceptedVersionNumber}")
            }
        } catch (_: Exception) {
            "unavailable"
        }
    }

    fun render(context: Context): String {
        val store = SecureCredentialStore(context)
        val prefs = context.getSharedPreferences("zreta_status", Context.MODE_PRIVATE)
        val last = prefs.getLong("last_heartbeat", 0L)
        val lastText = if (last == 0L) "never" else java.text.DateFormat.getDateTimeInstance().format(java.util.Date(last))
        val tokenPresent = !store.accessToken().isNullOrBlank()
        return buildString {
            appendLine("Enrollment: ${if (store.isEnrolled()) "enrolled" else "not enrolled"}")
            appendLine("Device ID: ${store.deviceId() ?: "—"}")
            appendLine(ManagementStateDetector.userMessage(ManagementStateDetector.detect(context)))
            appendLine("Backend: ${store.apiBase() ?: "not configured"}")
            appendLine("Credential: ${if (store.publicKeyId() != null) "Keystore key ${store.publicKeyId()}" else "none"}")
            appendLine("Access token present: $tokenPresent (value not shown)")
            appendLine("Last heartbeat: $lastText (${prefs.getString("last_heartbeat_result", "—")})")
            appendLine("Location sharing: ${store.locationSharingState()}")
            appendLine("Policy: ${com.zreta.devicecontrol.policy.PolicyCache(context).statusSummary()}")
            appendLine("Enforcement: ${enforcementSummary(context)}")
            try {
                val dns = com.zreta.devicecontrol.network.DnsFilterTelemetry.current(context)
                appendLine(
                    "DNS filter: ${dns.state}" +
                        if (dns.error != null) " (${dns.error})" else "",
                )
                if (com.zreta.devicecontrol.network.VpnConsentCoordinator.isPending(context)) {
                    appendLine("VPN consent: pending — open Allow DNS filtering VPN")
                }
            } catch (_: Exception) {
                appendLine("DNS filter: unavailable")
            }
            appendLine("DPC version: ${BuildConfig.VERSION_NAME}")
        }
    }
}
