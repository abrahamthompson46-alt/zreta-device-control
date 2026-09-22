package com.zreta.devicecontrol.policy.enforcement

import com.zreta.devicecontrol.policy.PolicyStoreResult
import com.zreta.devicecontrol.policy.PolicyVersionGuard
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Corrective-pass regression tests (audit HIGH/MEDIUM fixes).
 */
class PolicyEnforcerCorrectiveTest {
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
    ): JSONObject {
        val applications = JSONObject()
        if (suspend.isNotEmpty()) applications.put("suspend_packages", JSONArray(suspend))
        if (hide.isNotEmpty()) applications.put("hide_packages", JSONArray(hide))
        if (uninstall.isNotEmpty()) applications.put("uninstall_blocked_packages", JSONArray(uninstall))
        val device = JSONObject()
        if (camera != null) device.put("camera_disabled", camera)
        if (capture != null) device.put("screen_capture_disabled", capture)
        return JSONObject()
            .put("schema_version", 1)
            .put("internet", JSONObject())
            .put("calls", JSONObject())
            .put("applications", applications)
            .put("screen_time", JSONObject())
            .put("device", device)
            .put("location", JSONObject())
    }

    // A — suspend exception after success
    @Test
    fun partialSuspendExceptionTracksSuccessfulPackage() {
        gateway.throwSuspend = setOf("com.example.b")
        val result = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.a", "com.example.b")),
            "v10",
            10,
            "h10",
        )
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertFalse(result.shouldAckAsApplied())
        assertTrue(gateway.suspended.contains("com.example.a"))
        assertFalse(gateway.suspended.contains("com.example.b"))
        assertTrue(store.state.suspendedPackages.contains("com.example.a"))
        assertFalse(store.state.suspendedPackages.contains("com.example.b"))
        assertEquals(10, store.state.acceptedVersionNumber)

        // Retry can converge when throw removed
        gateway.throwSuspend = emptySet()
        val retry = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.a", "com.example.b")),
            "v10",
            10,
            "h10",
        )
        assertEquals(EnforcementOutcome.APPLIED, retry.outcome)
        assertTrue(store.state.suspendedPackages.containsAll(setOf("com.example.a", "com.example.b")))
    }

    // B — hide exception
    @Test
    fun partialHideExceptionTracksSuccessfulPackage() {
        gateway.throwHide = setOf("com.example.b")
        val result = enforcer.enforceValidatedDocument(
            docWith(hide = listOf("com.example.a", "com.example.b")),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertTrue(store.state.hiddenPackages.contains("com.example.a"))
        assertFalse(store.state.hiddenPackages.contains("com.example.b"))
    }

    // C — uninstall-block exception
    @Test
    fun partialUninstallBlockExceptionTracksSuccessfulPackage() {
        gateway.throwUninstallBlock = setOf("com.example.b")
        val result = enforcer.enforceValidatedDocument(
            docWith(uninstall = listOf("com.example.a", "com.example.b")),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertTrue(store.state.uninstallBlockedPackages.contains("com.example.a"))
        assertFalse(store.state.uninstallBlockedPackages.contains("com.example.b"))
    }

    // D — device control exception
    @Test
    fun cameraTrackedOnlyAfterSuccessfulDpm() {
        gateway.failCamera = true
        val result = enforcer.enforceValidatedDocument(docWith(camera = true, capture = true), "v1", 1, "h")
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertFalse(store.state.cameraDisabledManaged)
        assertTrue(store.state.screenCaptureDisabledManaged)
        assertTrue(gateway.screenCaptureDisabledFlag)
    }

    // E — state save failure
    @Test
    fun statePersistFailureDoesNotClaimApplied() {
        enforcer.enforceValidatedDocument(emptyDoc(), "v0", 1, "h0")
        store.failNextSave = true
        val result = enforcer.enforceValidatedDocument(docWith(camera = true), "v2", 2, "h2")
        assertEquals(EnforcementOutcome.FAILED, result.outcome)
        assertEquals("state_persist_failed", result.message)
        assertFalse(result.shouldAckAsApplied())
        assertFalse(gateway.cameraDisabledFlag)
    }

    @Test
    fun statePersistFailureAfterDpmSuccessYieldsPartialNotApplied() {
        // save #1 = version accept checkpoint; #2 = after first suspend success
        store.failOnSaveNumber = 2
        val result = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.a", "com.example.b")),
            "v4",
            4,
            "h4",
        )
        assertTrue(result.outcome == EnforcementOutcome.PARTIAL || result.outcome == EnforcementOutcome.FAILED)
        assertFalse(result.shouldAckAsApplied())
        // DPM may have suspended A; disk may lag — retry without fail converges
        store.failOnSaveNumber = 0
        gateway.throwSuspend = emptySet()
        val retry = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.a", "com.example.b")),
            "v4",
            4,
            "h4",
        )
        assertTrue(retry.shouldAckAsApplied() || retry.outcome == EnforcementOutcome.APPLIED || retry.outcome == EnforcementOutcome.NO_CHANGES)
    }

    // F — newer PARTIAL then older worker
    @Test
    fun newerPartialThenOlderWorkerRejected() {
        gateway.failSuspend = setOf("com.example.b")
        val partial = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.a", "com.example.b")),
            "v10",
            10,
            "h10",
        )
        assertEquals(EnforcementOutcome.PARTIAL, partial.outcome)
        assertEquals(10, store.state.acceptedVersionNumber)
        assertFalse(store.state.successfullyEnforced)
        val before = store.state.copy()

        val older = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.old")),
            "v9",
            9,
            "h9",
        )
        assertEquals(EnforcementOutcome.REJECTED, older.outcome)
        assertEquals("older_version", older.message)
        assertFalse(older.shouldAckAsApplied())
        assertEquals(before.suspendedPackages, store.state.suspendedPackages)
        assertEquals(10, store.state.acceptedVersionNumber)
        assertFalse(gateway.suspended.contains("com.example.old"))
    }

    // G — newer FAILED (after accept) then older rejected
    @Test
    fun newerFailedAcceptStillBlocksOlder() {
        // Accept v10 boundary then hard-fail via not device owner on needsOwner path —
        // use throw on isDeviceOwner after version accept: first persist succeeds.
        val throwing = object : DevicePolicyGateway by gateway {
            var calls = 0
            override fun isDeviceOwner(): Boolean {
                calls++
                if (calls > 0) throw IllegalStateException("boom")
                return true
            }
        }
        // Simpler approach: PARTIAL already sets acceptedVersionNumber; for FAILED after accept:
        gateway.throwSuspend = setOf("com.example.a")
        enforcer.enforceValidatedDocument(docWith(suspend = listOf("com.example.a")), "v10", 10, "h10")
        assertEquals(10, store.state.acceptedVersionNumber)

        val older = enforcer.enforceValidatedDocument(docWith(camera = true), "v8", 8, "h8")
        assertEquals(EnforcementOutcome.REJECTED, older.outcome)
        assertEquals("older_version", older.message)
    }

    // H — corrupt managed state
    @Test
    fun corruptManagedStateNoBlindClearAndRecoveryPartial() {
        gateway.suspended.add("com.foreign.mdm")
        gateway.suspended.add("com.example.prior")
        store.wasCorruptOnLastLoad = true
        store.state = ManagedEnforcementState.empty().copy(recoveryRequired = true)

        val result = enforcer.enforceValidatedDocument(
            docWith(suspend = listOf("com.example.lkg"), camera = true),
            "v5",
            5,
            "h5",
        )
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertEquals("recovery_reconcile", result.message)
        assertFalse(result.shouldAckAsApplied())
        // Foreign untouched
        assertTrue(gateway.suspended.contains("com.foreign.mdm"))
        // Prior orphan may remain (cannot clear without ownership)
        assertTrue(gateway.suspended.contains("com.example.prior"))
        // LKG desired applied and owned
        assertTrue(gateway.suspended.contains("com.example.lkg"))
        assertTrue(store.state.suspendedPackages.contains("com.example.lkg"))
        assertFalse(store.state.suspendedPackages.contains("com.example.prior"))
        assertTrue(gateway.cameraDisabledFlag)
    }

    // I — complete A → B replacement
    @Test
    fun completePolicyReplacementClearsOnlyZretaManaged() {
        gateway.suspended.add("com.foreign.mdm")
        gateway.hidden.add("com.foreign.hidden")
        enforcer.enforceValidatedDocument(
            docWith(
                suspend = listOf("com.example.a"),
                hide = listOf("com.example.b"),
                uninstall = listOf("com.example.c"),
                camera = true,
                capture = true,
            ),
            "v1",
            1,
            "a",
        )
        val result = enforcer.enforceValidatedDocument(
            docWith(
                suspend = listOf("com.example.d"),
                hide = listOf("com.example.e"),
                uninstall = listOf("com.example.f"),
                camera = false,
                capture = false,
            ),
            "v2",
            2,
            "b",
        )
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertFalse(gateway.suspended.contains("com.example.a"))
        assertTrue(gateway.suspended.contains("com.example.d"))
        assertTrue(gateway.suspended.contains("com.foreign.mdm"))
        assertFalse(gateway.hidden.contains("com.example.b"))
        assertTrue(gateway.hidden.contains("com.example.e"))
        assertTrue(gateway.hidden.contains("com.foreign.hidden"))
        assertFalse(gateway.uninstallBlocked.contains("com.example.c"))
        assertTrue(gateway.uninstallBlocked.contains("com.example.f"))
        assertFalse(gateway.cameraDisabledFlag)
        assertFalse(gateway.screenCaptureDisabledFlag)
    }

    @Test
    fun versionGuardDetectsStale() {
        assertTrue(PolicyVersionGuard.isStaleIncoming(10, 9))
        assertFalse(PolicyVersionGuard.isStaleIncoming(10, 10))
        assertFalse(PolicyVersionGuard.isStaleIncoming(10, 11))
        assertFalse(PolicyVersionGuard.isStaleIncoming(0, 1))
    }

    @Test
    fun pullDecisionRejectsStaleWithoutAppliedAck() {
        val outcome = com.zreta.devicecontrol.policy.PolicyPullDecision.afterStoreAttempt(
            PolicyStoreResult.REJECTED_STALE,
            "vid",
        )
        assertTrue(outcome.rejectedStale)
        assertFalse(outcome.sendAppliedAck)
        assertTrue(outcome.preserveLkg)
    }

    @Test
    fun managedStateRoundTripIncludesAcceptedVersion() {
        val state = ManagedEnforcementState(
            policyVersionId = "abc",
            versionNumber = 3,
            acceptedVersionNumber = 3,
            contentHash = "sha",
            suspendedPackages = setOf("com.example.a"),
            successfullyEnforced = false,
            recoveryRequired = true,
        )
        val raw = EnforcementStateStore.serialize(state)
        val parsed = EnforcementStateStore.parse(raw)
        assertFalse(parsed.wasCorrupt)
        assertEquals(state, parsed.state)
        assertTrue(EnforcementStateStore.parse("{bad").wasCorrupt)
    }
}
