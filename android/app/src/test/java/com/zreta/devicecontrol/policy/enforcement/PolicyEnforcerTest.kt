package com.zreta.devicecontrol.policy.enforcement

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PolicyEnforcerTest {
    private lateinit var gateway: FakeDevicePolicyGateway
    private lateinit var store: InMemoryEnforcementStateStore
    private lateinit var enforcer: PolicyEnforcer

    @Before
    fun setUp() {
        gateway = FakeDevicePolicyGateway(deviceOwner = true)
        store = InMemoryEnforcementStateStore()
        enforcer = PolicyEnforcer.createForTests(gateway, store)
    }

    private fun emptyDoc(): JSONObject = PolicyCompliance.emptyDocument()

    private fun docWith(
        suspend: List<String> = emptyList(),
        hide: List<String> = emptyList(),
        uninstall: List<String> = emptyList(),
        camera: Boolean? = null,
        capture: Boolean? = null,
        internetExtra: Boolean = false,
    ): JSONObject {
        val applications = JSONObject()
        if (suspend.isNotEmpty()) applications.put("suspend_packages", JSONArray(suspend))
        if (hide.isNotEmpty()) applications.put("hide_packages", JSONArray(hide))
        if (uninstall.isNotEmpty()) applications.put("uninstall_blocked_packages", JSONArray(uninstall))
        val device = JSONObject()
        if (camera != null) device.put("camera_disabled", camera)
        if (capture != null) device.put("screen_capture_disabled", capture)
        val internet = JSONObject()
        if (internetExtra) internet.put("mode", "block")
        return JSONObject()
            .put("schema_version", 1)
            .put("internet", internet)
            .put("calls", JSONObject())
            .put("applications", applications)
            .put("screen_time", JSONObject())
            .put("device", device)
            .put("location", JSONObject())
    }

    @Test
    fun emptyApplicationsAndDeviceMeansNoDpmMutations() {
        val result = enforcer.enforceValidatedDocument(emptyDoc(), "v1", 1, "hash1")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertTrue(gateway.suspended.isEmpty())
        assertEquals(0, gateway.suspendCallCount)
        assertFalse(gateway.cameraDisabledFlag)
    }

    @Test
    fun validSuspendHideUninstallAndDeviceControls() {
        val result = enforcer.enforceValidatedDocument(
            docWith(
                suspend = listOf("com.example.game"),
                hide = listOf("com.example.hidden"),
                uninstall = listOf("com.example.keep"),
                camera = true,
                capture = true,
            ),
            "v1",
            1,
            "h1",
        )
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertTrue(gateway.suspended.contains("com.example.game"))
        assertTrue(gateway.hidden.contains("com.example.hidden"))
        assertTrue(gateway.uninstallBlocked.contains("com.example.keep"))
        assertTrue(gateway.cameraDisabledFlag)
        assertTrue(gateway.screenCaptureDisabledFlag)
    }

    @Test
    fun cameraAndScreenCaptureToggle() {
        enforcer.enforceValidatedDocument(docWith(camera = true, capture = true), "v1", 1, "a")
        assertTrue(gateway.cameraDisabledFlag)
        assertTrue(gateway.screenCaptureDisabledFlag)
        enforcer.enforceValidatedDocument(docWith(camera = false, capture = false), "v2", 2, "b")
        assertFalse(gateway.cameraDisabledFlag)
        assertFalse(gateway.screenCaptureDisabledFlag)
    }

    @Test
    fun zretaPackageCannotBeSuspended() {
        val result = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.zreta.devicecontrol", "com.example.ok")),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertFalse(gateway.suspended.contains("com.zreta.devicecontrol"))
        assertTrue(gateway.suspended.contains("com.example.ok"))
        assertTrue(result.packageResults.any { it.status == "rejected_unsafe_package" })
    }

    @Test
    fun criticalPackageProtectionWorks() {
        val result = enforcer.enforceValidatedDocument(
            docWith(hide = listOf("com.android.systemui", "com.example.app")),
            "v1",
            1,
            "h",
        )
        assertFalse(gateway.hidden.contains("com.android.systemui"))
        assertTrue(gateway.hidden.contains("com.example.app"))
    }

    @Test
    fun oneInvalidPackageDoesNotCrashOperation() {
        gateway.failSuspend = setOf("com.example.bad")
        val result = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.bad", "com.example.good"), camera = true),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertTrue(gateway.suspended.contains("com.example.good"))
        assertTrue(gateway.cameraDisabledFlag)
        assertFalse(result.shouldAckAsApplied())
    }

    @Test
    fun suspendHideUninstallIdempotentForSameVersion() {
        enforcer.enforceValidatedDocument(
            docWith(
                suspend = listOf("com.example.game"),
                hide = listOf("com.example.h"),
                uninstall = listOf("com.example.u"),
            ),
            "v1",
            1,
            "h",
        )
        val suspendCalls = gateway.suspendCallCount
        val hideCalls = gateway.hideCallCount
        val second = enforcer.enforceValidatedDocument(
            docWith(
                suspend = listOf("com.example.game"),
                hide = listOf("com.example.h"),
                uninstall = listOf("com.example.u"),
            ),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.NO_CHANGES, second.outcome)
        assertEquals(suspendCalls, gateway.suspendCallCount)
        assertEquals(hideCalls, gateway.hideCallCount)
    }

    @Test
    fun clearOnlyZretaManagedPackages() {
        gateway.suspended.add("com.other.mdm")
        gateway.hidden.add("com.other.hidden")
        gateway.uninstallBlocked.add("com.other.block")
        enforcer.enforceValidatedDocument(
            docWith(
                suspend = listOf("com.example.game"),
                hide = listOf("com.example.h"),
                uninstall = listOf("com.example.u"),
            ),
            "v1",
            1,
            "a",
        )
        enforcer.enforceValidatedDocument(emptyDoc(), "v2", 2, "b")
        assertFalse(gateway.suspended.contains("com.example.game"))
        assertFalse(gateway.hidden.contains("com.example.h"))
        assertFalse(gateway.uninstallBlocked.contains("com.example.u"))
        assertTrue(gateway.suspended.contains("com.other.mdm"))
        assertTrue(gateway.hidden.contains("com.other.hidden"))
        assertTrue(gateway.uninstallBlocked.contains("com.other.block"))
    }

    @Test
    fun olderVersionNotEnforced() {
        enforcer.enforceValidatedDocument(docWith(camera = true), "v2", 2, "h2")
        val result = enforcer.enforceValidatedDocument(docWith(camera = false), "v1", 1, "h1")
        assertEquals(EnforcementOutcome.REJECTED, result.outcome)
        assertEquals("older_version", result.message)
        assertTrue(gateway.cameraDisabledFlag)
    }

    @Test
    fun hardFailurePreservesPriorManagedState() {
        enforcer.enforceValidatedDocument(docWith(camera = true), "v1", 1, "a")
        assertTrue(store.state.cameraDisabledManaged)
        val throwing = object : DevicePolicyGateway by gateway {
            override fun isDeviceOwner(): Boolean = throw IllegalStateException("boom")
        }
        val bad = PolicyEnforcer.createForTests(throwing, store)
        val result = bad.enforceValidatedDocument(docWith(camera = false), "v2", 2, "b")
        assertEquals(EnforcementOutcome.FAILED, result.outcome)
        // Camera remains as previously tracked; DPM not cleared by the failed attempt.
        assertTrue(store.state.cameraDisabledManaged)
        assertTrue(store.state.cameraDisabledValue)
        assertTrue(gateway.cameraDisabledFlag)
        assertEquals(2, store.state.acceptedVersionNumber)
    }

    @Test
    fun unknownInternetKeyRejectedAtValidation() {
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            document = docWith(internetExtra = true),
            policyVersionId = "v1",
            versionNumber = 1,
            enforcer = enforcer,
        )
        assertFalse(evaluation.compliant)
        assertEquals("invalid_document", evaluation.reason)
    }

    @Test
    fun emptyPolicyComplianceSucceeds() {
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            document = emptyDoc(),
            enforcer = enforcer,
        )
        assertTrue(evaluation.compliant)
        assertTrue(evaluation.enforcement!!.shouldAckAsApplied())
    }

    @Test
    fun supportedPolicyComplianceUsesSamePath() {
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            document = docWith(camera = true),
            policyVersionId = "v1",
            versionNumber = 1,
            contentHash = "h",
            enforcer = enforcer,
        )
        assertTrue(evaluation.compliant)
        assertTrue(gateway.cameraDisabledFlag)
    }

    @Test
    fun notDeviceOwnerRejectedWhenControlsPresent() {
        gateway.deviceOwner = false
        val result = enforcer.enforceValidatedDocument(docWith(camera = true), "v1", 1, "h")
        assertEquals(EnforcementOutcome.REJECTED, result.outcome)
    }

    @Test
    fun managedStateRoundTrip() {
        val state = ManagedEnforcementState(
            policyVersionId = "abc",
            versionNumber = 3,
            acceptedVersionNumber = 3,
            contentHash = "sha",
            suspendedPackages = setOf("com.example.a"),
            hiddenPackages = setOf("com.example.b"),
            uninstallBlockedPackages = setOf("com.example.c"),
            cameraDisabledManaged = true,
            cameraDisabledValue = true,
            successfullyEnforced = true,
        )
        val raw = EnforcementStateStore.serialize(state)
        val parsed = EnforcementStateStore.parseOrEmpty(raw)
        assertEquals(state, parsed)
        val corrupt = EnforcementStateStore.parse("{not json")
        assertTrue(corrupt.wasCorrupt)
        assertTrue(corrupt.state.recoveryRequired)
    }
}
