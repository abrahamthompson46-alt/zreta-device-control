package com.zreta.devicecontrol.policy.enforcement

/**
 * Applies Phase 5.1 traffic filter desired state through [DnsFilterController]
 * (production: VpnService-backed DNS filter; tests may use Fake).
 */
class InternetTrafficEnforcer(
    private val controller: DnsFilterController,
) {
    data class SectionResult(
        val controlResults: List<ControlResult>,
        val working: ManagedEnforcementState,
        val failures: Int,
    )

    fun apply(
        controls: NormalizedPolicyControls,
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

        val traffic = controls.traffic
        if (traffic == null) {
            // No traffic section: clear Zreta-managed filter if we own it.
            if (working.trafficFilterManaged ||
                working.trafficServiceObserved == DnsFilterServiceState.RUNNING ||
                working.trafficServiceDesired == DnsFilterServiceState.RUNNING
            ) {
                val op = controller.stop()
                if (op.success && op.observed == DnsFilterServiceState.STOPPED) {
                    commit(
                        working.copy(
                            trafficFilterManaged = false,
                            trafficFilterDesiredEnabled = false,
                            trafficRuleHash = null,
                            trafficServiceDesired = DnsFilterServiceState.STOPPED,
                            trafficServiceObserved = DnsFilterServiceState.STOPPED,
                            trafficLastError = null,
                        ),
                    )
                    results.add(ControlResult("traffic.filter", "cleared"))
                } else {
                    failures++
                    commit(
                        working.copy(
                            trafficServiceObserved = op.observed,
                            trafficLastError = op.error ?: "stop_failed",
                        ),
                    )
                    results.add(ControlResult("traffic.filter", "failed", op.error))
                }
            } else {
                results.add(ControlResult("traffic.filter", "absent"))
            }
            return SectionResult(results, working, failures)
        }

        val wantEnabled = traffic.enabled
        val wantHash = traffic.ruleHash
        val wantDomains = traffic.blockedDomains
        val wantState =
            if (wantEnabled) DnsFilterServiceState.RUNNING else DnsFilterServiceState.STOPPED

        val already =
            working.trafficFilterManaged &&
                working.trafficFilterDesiredEnabled == wantEnabled &&
                working.trafficRuleHash == wantHash &&
                working.trafficServiceDesired == wantState &&
                working.trafficServiceObserved == wantState &&
                controller.observedState() == wantState &&
                (!wantEnabled || controller.observedState() == DnsFilterServiceState.RUNNING)

        if (already) {
            results.add(ControlResult("traffic.filter", "unchanged", wantHash))
            return SectionResult(results, working, failures)
        }

        if (!wantEnabled) {
            val op = controller.stop()
            if (op.success && op.observed == DnsFilterServiceState.STOPPED) {
                commit(
                    working.copy(
                        trafficFilterManaged = true,
                        trafficFilterDesiredEnabled = false,
                        trafficRuleHash = wantHash,
                        trafficServiceDesired = DnsFilterServiceState.STOPPED,
                        trafficServiceObserved = DnsFilterServiceState.STOPPED,
                        trafficLastError = null,
                    ),
                )
                results.add(ControlResult("traffic.filter", "stopped"))
            } else {
                failures++
                // Preserve prior ownership/hash; do not newly claim managed ownership on failed stop.
                commit(
                    working.copy(
                        trafficFilterDesiredEnabled = false,
                        trafficServiceDesired = DnsFilterServiceState.STOPPED,
                        trafficServiceObserved = op.observed,
                        trafficLastError = op.error ?: "stop_failed",
                    ),
                )
                results.add(ControlResult("traffic.filter", "failed", op.error))
            }
            return SectionResult(results, working, failures)
        }

        // wantEnabled == true
        val priorHash = working.trafficRuleHash
        val op = when {
            working.trafficServiceObserved == DnsFilterServiceState.RUNNING &&
                controller.observedState() == DnsFilterServiceState.RUNNING &&
                priorHash != null &&
                priorHash != wantHash -> controller.reload(wantDomains)
            else -> controller.start(wantDomains)
        }

        if (op.success && op.observed == DnsFilterServiceState.RUNNING) {
            commit(
                working.copy(
                    trafficFilterManaged = true,
                    trafficFilterDesiredEnabled = true,
                    trafficRuleHash = wantHash,
                    trafficServiceDesired = DnsFilterServiceState.RUNNING,
                    trafficServiceObserved = DnsFilterServiceState.RUNNING,
                    trafficLastError = null,
                ),
            )
            results.add(
                ControlResult(
                    "traffic.filter",
                    if (priorHash != null && priorHash != wantHash) {
                        "reloaded"
                    } else {
                        "started"
                    },
                    wantHash,
                ),
            )
        } else {
            failures++
            // Fail-open: do not claim ownership or update applied rule hash unless start/reload succeeded.
            // Preserve existing managed ownership + applied hash so health checks cannot falsely go green.
            commit(
                working.copy(
                    trafficFilterDesiredEnabled = true,
                    trafficServiceDesired = DnsFilterServiceState.RUNNING,
                    trafficServiceObserved = op.observed,
                    trafficLastError = op.error ?: "start_failed",
                ),
            )
            results.add(ControlResult("traffic.filter", "failed", op.error))
        }
        return SectionResult(results, working, failures)
    }
}
