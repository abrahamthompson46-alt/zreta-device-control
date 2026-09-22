package com.zreta.devicecontrol.policy.enforcement

/**
 * Applies camera / screen-capture policy using Zreta-managed ownership for safe clear.
 * Each successful DPM call updates [working] and invokes [onTrackedChange] before continuing.
 */
class DeviceEnforcer(
    private val gateway: DevicePolicyGateway,
) {
    data class SectionResult(
        val controlResults: List<ControlResult>,
        val working: ManagedEnforcementState,
        val dpmFailures: Int,
    )

    fun apply(
        desired: NormalizedPolicyControls,
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

        when (val want = desired.cameraDisabled) {
            null -> {
                if (working.cameraDisabledManaged) {
                    try {
                        gateway.setCameraDisabled(false)
                        commit(
                            working.copy(
                                cameraDisabledManaged = false,
                                cameraDisabledValue = false,
                            ),
                        )
                        results.add(ControlResult("camera_disabled", "cleared"))
                    } catch (ex: Exception) {
                        failures++
                        results.add(ControlResult("camera_disabled", "failed", ex.message))
                    }
                }
            }
            else -> {
                if (working.cameraDisabledManaged && working.cameraDisabledValue == want) {
                    results.add(ControlResult("camera_disabled", "unchanged"))
                } else {
                    try {
                        gateway.setCameraDisabled(want)
                        commit(
                            working.copy(
                                cameraDisabledManaged = true,
                                cameraDisabledValue = want,
                            ),
                        )
                        results.add(ControlResult("camera_disabled", "applied", want.toString()))
                    } catch (ex: Exception) {
                        failures++
                        results.add(ControlResult("camera_disabled", "failed", ex.message))
                    }
                }
            }
        }

        when (val want = desired.screenCaptureDisabled) {
            null -> {
                if (working.screenCaptureDisabledManaged) {
                    try {
                        gateway.setScreenCaptureDisabled(false)
                        commit(
                            working.copy(
                                screenCaptureDisabledManaged = false,
                                screenCaptureDisabledValue = false,
                            ),
                        )
                        results.add(ControlResult("screen_capture_disabled", "cleared"))
                    } catch (ex: Exception) {
                        failures++
                        results.add(ControlResult("screen_capture_disabled", "failed", ex.message))
                    }
                }
            }
            else -> {
                if (working.screenCaptureDisabledManaged && working.screenCaptureDisabledValue == want) {
                    results.add(ControlResult("screen_capture_disabled", "unchanged"))
                } else {
                    try {
                        gateway.setScreenCaptureDisabled(want)
                        commit(
                            working.copy(
                                screenCaptureDisabledManaged = true,
                                screenCaptureDisabledValue = want,
                            ),
                        )
                        results.add(ControlResult("screen_capture_disabled", "applied", want.toString()))
                    } catch (ex: Exception) {
                        failures++
                        results.add(ControlResult("screen_capture_disabled", "failed", ex.message))
                    }
                }
            }
        }

        return SectionResult(
            controlResults = results,
            working = working,
            dpmFailures = failures,
        )
    }
}
