package com.zreta.devicecontrol.policy.enforcement

/**
 * Best-effort screen-time bedtime package suspension.
 * Does not use lockNow. Daily limits / UsageStats are out of scope.
 */
class ScreenTimeEnforcer(
    private val gateway: DevicePolicyGateway,
    private val selfPackageName: String,
) {
    data class SectionResult(
        val packageResults: List<PackageActionResult>,
        val working: ManagedEnforcementState,
        val dpmFailures: Int,
    )

    fun apply(
        controls: NormalizedPolicyControls,
        inBedtime: Boolean,
        previous: ManagedEnforcementState,
        onTrackedChange: (ManagedEnforcementState) -> Unit = {},
    ): SectionResult {
        val results = mutableListOf<PackageActionResult>()
        var failures = 0
        var working = previous

        fun commit(next: ManagedEnforcementState) {
            working = next
            onTrackedChange(working)
        }

        val desiredBedtime: Set<String> =
            if (inBedtime && controls.hasBedtimeWindow()) {
                filterDesired(controls.bedtimeSuspendPackages, results)
            } else {
                emptySet()
            }

        // Never unsuspend packages still required by applications section.
        val appOwned = controls.suspendPackages.map { it.trim() }.filter { PackageNameRules.isValid(it) }.toSet()

        val toSuspend = desiredBedtime - working.bedtimeSuspendedPackages
        val toUnsuspend = working.bedtimeSuspendedPackages - desiredBedtime

        for (pkg in toSuspend) {
            if (pkg in working.suspendedPackages || pkg in appOwned) {
                // Already suspended via applications — still mark bedtime ownership for clear later.
                commit(working.copy(bedtimeSuspendedPackages = working.bedtimeSuspendedPackages + pkg))
                results.add(PackageActionResult(pkg, "bedtime_suspend", "unchanged", "app_owned"))
                continue
            }
            try {
                val failed = gateway.setPackagesSuspended(arrayOf(pkg), true).toSet()
                if (pkg in failed) {
                    failures++
                    results.add(PackageActionResult(pkg, "bedtime_suspend", "failed", "dpm_rejected"))
                } else {
                    commit(
                        working.copy(
                            bedtimeSuspendedPackages = working.bedtimeSuspendedPackages + pkg,
                            // Track under suspended if apps also owns? Keep separate; apps list is authoritative for apps.
                        ),
                    )
                    results.add(PackageActionResult(pkg, "bedtime_suspend", "applied"))
                }
            } catch (ex: Exception) {
                failures++
                results.add(PackageActionResult(pkg, "bedtime_suspend", "failed", ex.message))
            }
        }

        for (pkg in toUnsuspend) {
            if (pkg in appOwned || pkg in working.suspendedPackages) {
                commit(working.copy(bedtimeSuspendedPackages = working.bedtimeSuspendedPackages - pkg))
                results.add(PackageActionResult(pkg, "bedtime_unsuspend", "skipped", "app_owned"))
                continue
            }
            try {
                val failed = gateway.setPackagesSuspended(arrayOf(pkg), false).toSet()
                if (pkg in failed) {
                    failures++
                    results.add(PackageActionResult(pkg, "bedtime_unsuspend", "failed", "dpm_rejected"))
                } else {
                    commit(working.copy(bedtimeSuspendedPackages = working.bedtimeSuspendedPackages - pkg))
                    results.add(PackageActionResult(pkg, "bedtime_unsuspend", "applied"))
                }
            } catch (ex: Exception) {
                failures++
                results.add(PackageActionResult(pkg, "bedtime_unsuspend", "failed", ex.message))
            }
        }

        for (pkg in desiredBedtime.intersect(working.bedtimeSuspendedPackages)) {
            results.add(PackageActionResult(pkg, "bedtime_suspend", "unchanged"))
        }

        return SectionResult(
            packageResults = results,
            working = working,
            dpmFailures = failures,
        )
    }

    private fun filterDesired(
        packages: List<String>,
        results: MutableList<PackageActionResult>,
    ): Set<String> {
        val out = linkedSetOf<String>()
        for (raw in packages) {
            val pkg = raw.trim()
            if (!PackageNameRules.isValid(pkg)) {
                results.add(PackageActionResult(pkg, "bedtime_suspend", "rejected_invalid_package"))
                continue
            }
            if (CriticalPackages.isProtected(pkg, selfPackageName)) {
                results.add(PackageActionResult(pkg, "bedtime_suspend", "rejected_unsafe_package"))
                continue
            }
            out.add(pkg)
        }
        return out
    }
}

/**
 * Local-time bedtime window helpers (minutes from midnight).
 */
object ScreenTimeWindows {
    fun isActive(nowMinutes: Int, startMinutes: Int, endMinutes: Int): Boolean {
        val now = ((nowMinutes % (24 * 60)) + (24 * 60)) % (24 * 60)
        // Equal start/end is rejected at schema validation; fail closed if reached.
        if (startMinutes == endMinutes) return false
        return if (startMinutes < endMinutes) {
            now in startMinutes until endMinutes
        } else {
            now >= startMinutes || now < endMinutes
        }
    }

    fun isActive(controls: NormalizedPolicyControls, nowMinutes: Int): Boolean {
        val start = controls.bedtimeStartMinutes ?: return false
        val end = controls.bedtimeEndMinutes ?: return false
        return isActive(nowMinutes, start, end)
    }

    fun localNowMinutes(): Int {
        val cal = java.util.Calendar.getInstance()
        return cal.get(java.util.Calendar.HOUR_OF_DAY) * 60 + cal.get(java.util.Calendar.MINUTE)
    }
}
