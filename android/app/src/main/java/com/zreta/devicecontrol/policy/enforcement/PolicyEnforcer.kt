package com.zreta.devicecontrol.policy.enforcement

import android.content.Context
import com.zreta.devicecontrol.network.VpnDnsFilterController
import org.json.JSONObject

/**
 * Orchestrates Applications + Device + calls/internet restrictions + screen-time + location
 * advisory + Phase 5.1A traffic filter controller against a validated local policy document.
 */
class PolicyEnforcer(
    private val gateway: DevicePolicyGateway,
    private val loadState: () -> ManagedStateLoad,
    private val saveState: (ManagedEnforcementState) -> Unit,
    private val selfPackageName: String,
    private val clockMinutes: () -> Int = { ScreenTimeWindows.localNowMinutes() },
    private val dnsFilterController: DnsFilterController = UnimplementedDnsFilterController(),
) {
    private val applicationsEnforcer = ApplicationsEnforcer(gateway, selfPackageName)
    private val deviceEnforcer = DeviceEnforcer(gateway)
    private val restrictionsEnforcer = UserRestrictionsEnforcer(gateway)
    private val screenTimeEnforcer = ScreenTimeEnforcer(gateway, selfPackageName)
    private val locationAdapter = LocationPolicyAdapter()
    private val trafficEnforcer = InternetTrafficEnforcer(dnsFilterController)

    fun enforceValidatedDocument(
        document: JSONObject,
        policyVersionId: String?,
        versionNumber: Int?,
        contentHash: String?,
    ): EnforcementResult {
        val controls = PolicyControlsParser.fromValidatedJson(document)
        return enforceControls(controls, policyVersionId, versionNumber, contentHash)
    }

    fun enforceControls(
        controls: NormalizedPolicyControls,
        policyVersionId: String?,
        versionNumber: Int?,
        contentHash: String?,
    ): EnforcementResult {
        val loaded = loadState()
        var previous = loaded.state
        val recovering = loaded.wasCorrupt || previous.recoveryRequired
        if (recovering) {
            previous = previous.copy(recoveryRequired = true)
        }

        val trafficHealthy = trafficStateHealthy(controls, previous)
        if (
            previous.successfullyEnforced &&
            !recovering &&
            trafficHealthy &&
            !controls.hasTimeDependentControls() &&
            !policyVersionId.isNullOrBlank() &&
            policyVersionId == previous.policyVersionId &&
            (contentHash == null || contentHash == previous.contentHash)
        ) {
            return EnforcementResult(
                outcome = EnforcementOutcome.NO_CHANGES,
                policyVersionId = policyVersionId,
                versionNumber = versionNumber,
                message = "already_enforced",
            )
        }

        val floor = maxOf(previous.acceptedVersionNumber, previous.versionNumber)
        if (versionNumber != null && floor > 0 && versionNumber < floor) {
            return EnforcementResult(
                outcome = EnforcementOutcome.REJECTED,
                policyVersionId = policyVersionId,
                versionNumber = versionNumber,
                message = "older_version",
            )
        }

        val hasDpmManaged = previous.suspendedPackages.isNotEmpty() ||
            previous.hiddenPackages.isNotEmpty() ||
            previous.uninstallBlockedPackages.isNotEmpty() ||
            previous.cameraDisabledManaged ||
            previous.screenCaptureDisabledManaged ||
            previous.managedUserRestrictions.isNotEmpty() ||
            previous.bedtimeSuspendedPackages.isNotEmpty()

        val hasManaged = hasDpmManaged ||
            previous.locationAdvisoryValue != null ||
            previous.trafficFilterManaged

        // Location advisory + traffic filter do not require Device Owner.
        val needsOwnerForDpm =
            controls.suspendPackages.isNotEmpty() ||
                controls.hidePackages.isNotEmpty() ||
                controls.uninstallBlockedPackages.isNotEmpty() ||
                controls.cameraDisabled != null ||
                controls.screenCaptureDisabled != null ||
                controls.blockOutgoingCalls == true ||
                controls.blockSms == true ||
                controls.disallowConfigWifi == true ||
                controls.disallowConfigMobileNetworks == true ||
                controls.disallowConfigTethering == true ||
                controls.disallowConfigVpn == true ||
                controls.hasBedtimeWindow() ||
                hasDpmManaged ||
                recovering && hasDpmManaged


        var persistFailed = false
        fun persist(state: ManagedEnforcementState) {
            try {
                saveState(state)
            } catch (_: Exception) {
                persistFailed = true
            }
        }

        val incomingVersion = versionNumber ?: 0
        var working = previous.copy(
            policyVersionId = policyVersionId ?: previous.policyVersionId,
            versionNumber = if (incomingVersion > 0) incomingVersion else previous.versionNumber,
            acceptedVersionNumber = maxOf(floor, incomingVersion),
            contentHash = contentHash ?: previous.contentHash,
            successfullyEnforced = false,
            recoveryRequired = recovering,
        )
        persist(working)
        if (persistFailed && incomingVersion > floor) {
            return EnforcementResult(
                outcome = EnforcementOutcome.FAILED,
                policyVersionId = policyVersionId,
                versionNumber = versionNumber,
                message = "state_persist_failed",
            )
        }

        return try {
            if (needsOwnerForDpm && !gateway.isDeviceOwner()) {
                return EnforcementResult(
                    outcome = EnforcementOutcome.REJECTED,
                    policyVersionId = policyVersionId,
                    versionNumber = versionNumber,
                    message = "not_device_owner",
                )
            }

            if (!controls.hasAnySupportedControl() && !hasManaged && !recovering) {
                val cleared = working.copy(
                    successfullyEnforced = !persistFailed,
                    recoveryRequired = false,
                )
                persist(cleared)
                return EnforcementResult(
                    outcome = when {
                        persistFailed -> EnforcementOutcome.PARTIAL
                        previous.successfullyEnforced && previous.policyVersionId == policyVersionId ->
                            EnforcementOutcome.NO_CHANGES
                        else -> EnforcementOutcome.APPLIED
                    },
                    policyVersionId = policyVersionId,
                    versionNumber = versionNumber,
                    message = if (persistFailed) "state_persist_failed" else null,
                )
            }

            val inBedtime = ScreenTimeWindows.isActive(controls, clockMinutes())

            val appResult = applicationsEnforcer.apply(controls, working) { next ->
                working = next
                persist(working)
            }
            working = appResult.working

            val deviceResult = deviceEnforcer.apply(controls, working) { next ->
                working = next
                persist(working)
            }
            working = deviceResult.working

            val desiredRestrictions = UserRestrictionsEnforcer.desiredKeys(controls, inBedtime)
            val restrictionResult = restrictionsEnforcer.apply(desiredRestrictions, working) { next ->
                working = next
                persist(working)
            }
            working = restrictionResult.working

            val screenResult = screenTimeEnforcer.apply(controls, inBedtime, working) { next ->
                working = next
                persist(working)
            }
            working = screenResult.working

            val locationResult = locationAdapter.apply(controls, working) { next ->
                working = next
                persist(working)
            }
            working = locationResult.working

            val trafficResult = trafficEnforcer.apply(controls, working) { next ->
                working = next
                persist(working)
            }
            working = trafficResult.working

            val dpmFailures = appResult.dpmFailures +
                deviceResult.dpmFailures +
                restrictionResult.dpmFailures +
                screenResult.dpmFailures +
                trafficResult.failures
            val clean = dpmFailures == 0 && !persistFailed
            val finalState = working.copy(
                successfullyEnforced = clean,
                recoveryRequired = if (clean) false else recovering,
            )
            persist(finalState)

            val outcome = when {
                persistFailed -> EnforcementOutcome.PARTIAL
                recovering -> EnforcementOutcome.PARTIAL
                dpmFailures == 0 -> EnforcementOutcome.APPLIED
                else -> EnforcementOutcome.PARTIAL
            }
            EnforcementResult(
                outcome = outcome,
                policyVersionId = policyVersionId,
                versionNumber = versionNumber,
                packageResults = appResult.packageResults + screenResult.packageResults,
                controlResults = deviceResult.controlResults +
                    restrictionResult.controlResults +
                    locationResult.controlResults +
                    trafficResult.controlResults,
                message = when {
                    persistFailed -> "state_persist_failed"
                    recovering -> "recovery_reconcile"
                    else -> null
                },
            )
        } catch (ex: Exception) {
            persist(working.copy(successfullyEnforced = false))
            EnforcementResult(
                outcome = EnforcementOutcome.FAILED,
                policyVersionId = policyVersionId,
                versionNumber = versionNumber,
                message = ex.message ?: "enforcement_failed",
            )
        }
    }

    private fun trafficStateHealthy(
        controls: NormalizedPolicyControls,
        previous: ManagedEnforcementState,
    ): Boolean {
        val traffic = controls.traffic ?: return !previous.trafficFilterManaged ||
            previous.trafficServiceObserved == DnsFilterServiceState.STOPPED
        return if (traffic.enabled) {
            previous.trafficFilterDesiredEnabled &&
                previous.trafficRuleHash == traffic.ruleHash &&
                previous.trafficServiceObserved == DnsFilterServiceState.RUNNING &&
                dnsFilterController.observedState() == DnsFilterServiceState.RUNNING
        } else {
            previous.trafficServiceObserved == DnsFilterServiceState.STOPPED &&
                dnsFilterController.observedState() == DnsFilterServiceState.STOPPED
        }
    }

    companion object {
        fun create(context: Context): PolicyEnforcer {
            val store = EnforcementStateStore(context)
            return PolicyEnforcer(
                gateway = AndroidDevicePolicyGateway(context),
                loadState = { store.load() },
                saveState = { store.save(it) },
                selfPackageName = context.packageName,
                dnsFilterController = VpnDnsFilterController.create(context),
            )
        }

        fun createForTests(
            gateway: DevicePolicyGateway,
            stateStore: InMemoryEnforcementStateStore,
            selfPackageName: String = "com.zreta.devicecontrol",
            clockMinutes: () -> Int = { 12 * 60 },
            dnsFilterController: DnsFilterController = UnimplementedDnsFilterController(),
        ): PolicyEnforcer = PolicyEnforcer(
            gateway = gateway,
            loadState = { stateStore.load() },
            saveState = { stateStore.save(it) },
            selfPackageName = selfPackageName,
            clockMinutes = clockMinutes,
            dnsFilterController = dnsFilterController,
        )
    }
}
