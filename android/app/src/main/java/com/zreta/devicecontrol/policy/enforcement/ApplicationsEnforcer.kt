package com.zreta.devicecontrol.policy.enforcement

/**
 * Applies package suspend / hide / uninstall-block diffs against Zreta-managed state only.
 * Each DPM call is isolated: successes update [working] immediately and invoke [onSuccess].
 */
class ApplicationsEnforcer(
    private val gateway: DevicePolicyGateway,
    private val selfPackageName: String,
) {
    data class SectionResult(
        val packageResults: List<PackageActionResult>,
        val working: ManagedEnforcementState,
        val dpmFailures: Int,
        val hardFailure: Boolean = false,
    )

    fun apply(
        desired: NormalizedPolicyControls,
        previous: ManagedEnforcementState,
        onTrackedChange: (ManagedEnforcementState) -> Unit = {},
    ): SectionResult {
        val results = mutableListOf<PackageActionResult>()
        var dpmFailures = 0
        var working = previous

        fun commit(next: ManagedEnforcementState) {
            working = next
            onTrackedChange(working)
        }

        val desiredSuspend = filterDesired(desired.suspendPackages, "suspend", results)
        val desiredHide = filterDesired(desired.hidePackages, "hide", results)
        val desiredUninstall = filterDesired(desired.uninstallBlockedPackages, "uninstall_block", results)

        val toSuspend = desiredSuspend - working.suspendedPackages
        val toUnsuspend = working.suspendedPackages - desiredSuspend
        for (pkg in toSuspend) {
            try {
                val failed = gateway.setPackagesSuspended(arrayOf(pkg), true).toSet()
                if (pkg in failed) {
                    dpmFailures++
                    results.add(PackageActionResult(pkg, "suspend", "failed", "dpm_rejected"))
                } else {
                    commit(working.copy(suspendedPackages = working.suspendedPackages + pkg))
                    results.add(PackageActionResult(pkg, "suspend", "applied"))
                }
            } catch (ex: Exception) {
                dpmFailures++
                results.add(PackageActionResult(pkg, "suspend", "failed", ex.message))
            }
        }
        for (pkg in toUnsuspend) {
            try {
                val failed = gateway.setPackagesSuspended(arrayOf(pkg), false).toSet()
                if (pkg in failed) {
                    dpmFailures++
                    results.add(PackageActionResult(pkg, "unsuspend", "failed", "dpm_rejected"))
                } else {
                    commit(working.copy(suspendedPackages = working.suspendedPackages - pkg))
                    results.add(PackageActionResult(pkg, "unsuspend", "applied"))
                }
            } catch (ex: Exception) {
                dpmFailures++
                results.add(PackageActionResult(pkg, "unsuspend", "failed", ex.message))
            }
        }
        for (pkg in desiredSuspend.intersect(working.suspendedPackages)) {
            results.add(PackageActionResult(pkg, "suspend", "unchanged"))
        }

        val toHide = desiredHide - working.hiddenPackages
        val toUnhide = working.hiddenPackages - desiredHide
        for (pkg in toHide) {
            try {
                if (gateway.setApplicationHidden(pkg, true)) {
                    commit(working.copy(hiddenPackages = working.hiddenPackages + pkg))
                    results.add(PackageActionResult(pkg, "hide", "applied"))
                } else {
                    dpmFailures++
                    results.add(PackageActionResult(pkg, "hide", "failed", "dpm_rejected"))
                }
            } catch (ex: Exception) {
                dpmFailures++
                results.add(PackageActionResult(pkg, "hide", "failed", ex.message))
            }
        }
        for (pkg in toUnhide) {
            try {
                if (gateway.setApplicationHidden(pkg, false)) {
                    commit(working.copy(hiddenPackages = working.hiddenPackages - pkg))
                    results.add(PackageActionResult(pkg, "unhide", "applied"))
                } else {
                    dpmFailures++
                    results.add(PackageActionResult(pkg, "unhide", "failed", "dpm_rejected"))
                }
            } catch (ex: Exception) {
                dpmFailures++
                results.add(PackageActionResult(pkg, "unhide", "failed", ex.message))
            }
        }
        for (pkg in desiredHide.intersect(working.hiddenPackages)) {
            results.add(PackageActionResult(pkg, "hide", "unchanged"))
        }

        val toBlock = desiredUninstall - working.uninstallBlockedPackages
        val toUnblock = working.uninstallBlockedPackages - desiredUninstall
        for (pkg in toBlock) {
            try {
                gateway.setUninstallBlocked(pkg, true)
                commit(working.copy(uninstallBlockedPackages = working.uninstallBlockedPackages + pkg))
                results.add(PackageActionResult(pkg, "uninstall_block", "applied"))
            } catch (ex: Exception) {
                dpmFailures++
                results.add(PackageActionResult(pkg, "uninstall_block", "failed", ex.message))
            }
        }
        for (pkg in toUnblock) {
            try {
                gateway.setUninstallBlocked(pkg, false)
                commit(working.copy(uninstallBlockedPackages = working.uninstallBlockedPackages - pkg))
                results.add(PackageActionResult(pkg, "uninstall_unblock", "applied"))
            } catch (ex: Exception) {
                dpmFailures++
                results.add(PackageActionResult(pkg, "uninstall_unblock", "failed", ex.message))
            }
        }
        for (pkg in desiredUninstall.intersect(working.uninstallBlockedPackages)) {
            results.add(PackageActionResult(pkg, "uninstall_block", "unchanged"))
        }

        return SectionResult(
            packageResults = results,
            working = working,
            dpmFailures = dpmFailures,
        )
    }

    private fun filterDesired(
        packages: List<String>,
        action: String,
        results: MutableList<PackageActionResult>,
    ): Set<String> {
        val out = linkedSetOf<String>()
        for (raw in packages) {
            val pkg = raw.trim()
            if (!PackageNameRules.isValid(pkg)) {
                results.add(PackageActionResult(pkg, action, "rejected_invalid_package"))
                continue
            }
            if (CriticalPackages.isProtected(pkg, selfPackageName)) {
                results.add(PackageActionResult(pkg, action, "rejected_unsafe_package"))
                continue
            }
            out.add(pkg)
        }
        return out
    }
}
