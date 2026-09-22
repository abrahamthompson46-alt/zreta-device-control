package com.zreta.devicecontrol.policy.enforcement

/**
 * Applies Device Owner user restrictions for calls + internet (+ bedtime outgoing calls).
 * Ownership is tracked in [ManagedEnforcementState.managedUserRestrictions] only.
 */
class UserRestrictionsEnforcer(
    private val gateway: DevicePolicyGateway,
) {
    data class SectionResult(
        val controlResults: List<ControlResult>,
        val working: ManagedEnforcementState,
        val dpmFailures: Int,
    )

    fun apply(
        desiredKeys: Set<String>,
        previous: ManagedEnforcementState,
        onTrackedChange: (ManagedEnforcementState) -> Unit = {},
    ): SectionResult {
        val results = mutableListOf<ControlResult>()
        var failures = 0
        var working = previous

        fun commit(next: ManagedEnforcementState) {
            working = next
            onTrackedChange(working)
        }

        val toAdd = desiredKeys - working.managedUserRestrictions
        val toClear = working.managedUserRestrictions - desiredKeys

        for (key in toAdd) {
            try {
                gateway.addUserRestriction(key)
                commit(working.copy(managedUserRestrictions = working.managedUserRestrictions + key))
                results.add(ControlResult(key, "applied"))
            } catch (ex: Exception) {
                failures++
                results.add(ControlResult(key, "failed", ex.message))
            }
        }
        for (key in toClear) {
            try {
                gateway.clearUserRestriction(key)
                commit(working.copy(managedUserRestrictions = working.managedUserRestrictions - key))
                results.add(ControlResult(key, "cleared"))
            } catch (ex: Exception) {
                failures++
                results.add(ControlResult(key, "failed", ex.message))
            }
        }
        for (key in desiredKeys.intersect(working.managedUserRestrictions)) {
            results.add(ControlResult(key, "unchanged"))
        }

        return SectionResult(
            controlResults = results,
            working = working,
            dpmFailures = failures,
        )
    }

    companion object {
        fun desiredKeys(controls: NormalizedPolicyControls, inBedtime: Boolean): Set<String> {
            val out = linkedSetOf<String>()
            if (controls.blockOutgoingCalls == true ||
                (inBedtime && controls.bedtimeBlockOutgoingCalls)
            ) {
                out.add(UserRestrictionKeys.OUTGOING_CALLS)
            }
            if (controls.blockSms == true) {
                out.add(UserRestrictionKeys.SMS)
            }
            if (controls.disallowConfigWifi == true) {
                out.add(UserRestrictionKeys.CONFIG_WIFI)
            }
            if (controls.disallowConfigMobileNetworks == true) {
                out.add(UserRestrictionKeys.CONFIG_MOBILE)
            }
            if (controls.disallowConfigTethering == true) {
                out.add(UserRestrictionKeys.CONFIG_TETHERING)
            }
            if (controls.disallowConfigVpn == true) {
                out.add(UserRestrictionKeys.CONFIG_VPN)
            }
            return out
        }
    }
}
