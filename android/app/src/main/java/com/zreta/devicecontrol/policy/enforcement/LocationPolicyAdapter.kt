package com.zreta.devicecontrol.policy.enforcement

/**
 * Location policy section adapter.
 *
 * Advisory only: records [NormalizedPolicyControls.locationCollectionDesired] in managed
 * state / control results. Does **not** enable GPS, mutate SecureCredentialStore, or
 * override Phase 3 [Device.location_collection_enabled] authority.
 */
class LocationPolicyAdapter {
    data class SectionResult(
        val controlResults: List<ControlResult>,
        val working: ManagedEnforcementState,
    )

    fun apply(
        controls: NormalizedPolicyControls,
        previous: ManagedEnforcementState,
        onTrackedChange: (ManagedEnforcementState) -> Unit = {},
    ): SectionResult {
        val desired = controls.locationCollectionDesired
        if (desired == previous.locationAdvisoryValue) {
            return SectionResult(
                controlResults = listOf(
                    ControlResult(
                        "location.collection_desired",
                        if (desired == null) "absent" else "advisory_unchanged",
                        desired?.toString(),
                    ),
                ),
                working = previous,
            )
        }
        val next = previous.copy(locationAdvisoryValue = desired)
        onTrackedChange(next)
        return SectionResult(
            controlResults = listOf(
                ControlResult(
                    "location.collection_desired",
                    "advisory_recorded",
                    desired?.toString() ?: "cleared",
                ),
            ),
            working = next,
        )
    }
}
