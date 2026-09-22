package com.zreta.devicecontrol.policy.enforcement

/**
 * Normalized Phase 4.7–4.8 (+5.1A traffic) controls from a validated schema v1 document.
 */
data class NormalizedTrafficControls(
    val enabled: Boolean,
    val engine: String,
    val blockedDomains: List<String>,
    val ruleHash: String,
)

data class NormalizedPolicyControls(
    val suspendPackages: List<String> = emptyList(),
    val hidePackages: List<String> = emptyList(),
    val uninstallBlockedPackages: List<String> = emptyList(),
    val cameraDisabled: Boolean? = null,
    val screenCaptureDisabled: Boolean? = null,
    val blockOutgoingCalls: Boolean? = null,
    val blockSms: Boolean? = null,
    val disallowConfigWifi: Boolean? = null,
    val disallowConfigMobileNetworks: Boolean? = null,
    val disallowConfigTethering: Boolean? = null,
    val disallowConfigVpn: Boolean? = null,
    val bedtimeStartMinutes: Int? = null,
    val bedtimeEndMinutes: Int? = null,
    val bedtimeBlockOutgoingCalls: Boolean = false,
    val bedtimeSuspendPackages: List<String> = emptyList(),
    /** Advisory only — never overrides Phase 3 Device.location_collection_enabled. */
    val locationCollectionDesired: Boolean? = null,
    /** Null when internet.traffic is absent. */
    val traffic: NormalizedTrafficControls? = null,
) {
    fun hasBedtimeWindow(): Boolean =
        bedtimeStartMinutes != null && bedtimeEndMinutes != null

    fun hasTimeDependentControls(): Boolean = hasBedtimeWindow()

    fun hasAnySupportedControl(): Boolean =
        suspendPackages.isNotEmpty() ||
            hidePackages.isNotEmpty() ||
            uninstallBlockedPackages.isNotEmpty() ||
            cameraDisabled != null ||
            screenCaptureDisabled != null ||
            blockOutgoingCalls == true ||
            blockSms == true ||
            disallowConfigWifi == true ||
            disallowConfigMobileNetworks == true ||
            disallowConfigTethering == true ||
            disallowConfigVpn == true ||
            hasBedtimeWindow() ||
            locationCollectionDesired != null ||
            traffic != null

    companion object {
        fun empty() = NormalizedPolicyControls()
    }
}

/**
 * Snapshot of restrictions currently managed by Zreta (authoritative for safe clear).
 */
data class ManagedEnforcementState(
    val schemaVersion: Int = 1,
    val policyVersionId: String? = null,
    val versionNumber: Int = 0,
    val acceptedVersionNumber: Int = 0,
    val contentHash: String? = null,
    val suspendedPackages: Set<String> = emptySet(),
    val hiddenPackages: Set<String> = emptySet(),
    val uninstallBlockedPackages: Set<String> = emptySet(),
    val cameraDisabledManaged: Boolean = false,
    val cameraDisabledValue: Boolean = false,
    val screenCaptureDisabledManaged: Boolean = false,
    val screenCaptureDisabledValue: Boolean = false,
    val managedUserRestrictions: Set<String> = emptySet(),
    val bedtimeSuspendedPackages: Set<String> = emptySet(),
    val locationAdvisoryValue: Boolean? = null,
    val trafficFilterManaged: Boolean = false,
    val trafficFilterDesiredEnabled: Boolean = false,
    val trafficRuleHash: String? = null,
    val trafficServiceDesired: DnsFilterServiceState = DnsFilterServiceState.STOPPED,
    val trafficServiceObserved: DnsFilterServiceState = DnsFilterServiceState.STOPPED,
    val trafficLastError: String? = null,
    val successfullyEnforced: Boolean = false,
    val recoveryRequired: Boolean = false,
) {
    companion object {
        const val STATE_SCHEMA = 1

        fun empty() = ManagedEnforcementState()
    }
}

data class ManagedStateLoad(
    val state: ManagedEnforcementState,
    val wasCorrupt: Boolean,
)
