package com.zreta.devicecontrol.policy.enforcement

import com.zreta.devicecontrol.policy.PolicyPullDecision
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class Phase48RemainingEnforcerTest {
    private lateinit var gateway: FakeDevicePolicyGateway
    private lateinit var store: InMemoryEnforcementStateStore
    private var clock: Int = 12 * 60
    private lateinit var enforcer: PolicyEnforcer

    @Before
    fun setUp() {
        gateway = FakeDevicePolicyGateway(deviceOwner = true)
        store = InMemoryEnforcementStateStore()
        clock = 12 * 60
        enforcer = PolicyEnforcer.createForTests(gateway, store, clockMinutes = { clock })
    }

    private fun baseDoc(
        calls: JSONObject = JSONObject(),
        internet: JSONObject = JSONObject(),
        screenTime: JSONObject = JSONObject(),
        location: JSONObject = JSONObject(),
        applications: JSONObject = JSONObject(),
        device: JSONObject = JSONObject(),
    ): JSONObject = JSONObject()
        .put("schema_version", 1)
        .put("internet", internet)
        .put("calls", calls)
        .put("applications", applications)
        .put("screen_time", screenTime)
        .put("device", device)
        .put("location", location)

    private fun overnightBedtimeDoc(): JSONObject {
        val screen = JSONObject()
            .put("bedtime_start", "22:00")
            .put("bedtime_end", "06:00")
            .put("bedtime_block_outgoing_calls", true)
            .put("bedtime_suspend_packages", JSONArray(listOf("com.example.game")))
        return baseDoc(screenTime = screen)
    }

    @Test
    fun callsAndInternetRestrictionsAppliedAndCleared() {
        val result = enforcer.enforceValidatedDocument(
            baseDoc(
                calls = JSONObject()
                    .put("block_outgoing_calls", true)
                    .put("block_sms", true),
                internet = JSONObject()
                    .put("disallow_config_wifi", true)
                    .put("disallow_config_mobile_networks", true)
                    .put("disallow_config_tethering", true)
                    .put("disallow_config_vpn", true),
            ),
            "v1",
            1,
            "h1",
        )
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.OUTGOING_CALLS))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.SMS))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.CONFIG_WIFI))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.CONFIG_MOBILE))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.CONFIG_TETHERING))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.CONFIG_VPN))

        val clear = enforcer.enforceValidatedDocument(PolicyCompliance.emptyDocument(), "v2", 2, "h2")
        assertEquals(EnforcementOutcome.APPLIED, clear.outcome)
        assertTrue(gateway.userRestrictions.isEmpty())
        assertTrue(store.state.managedUserRestrictions.isEmpty())
    }

    @Test
    fun foreignUserRestrictionPreservedWhenZretaClears() {
        val foreignKey = "no_outgoing_beam" // not managed by Zreta schemas
        gateway.userRestrictions.add(foreignKey)

        enforcer.enforceValidatedDocument(
            baseDoc(calls = JSONObject().put("block_sms", true)),
            "v1",
            1,
            "h1",
        )
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.SMS))
        assertTrue(store.state.managedUserRestrictions.contains(UserRestrictionKeys.SMS))
        assertTrue(gateway.userRestrictions.contains(foreignKey))
        assertFalse(store.state.managedUserRestrictions.contains(foreignKey))

        enforcer.enforceValidatedDocument(PolicyCompliance.emptyDocument(), "v2", 2, "h2")
        assertFalse(gateway.userRestrictions.contains(UserRestrictionKeys.SMS))
        assertTrue(store.state.managedUserRestrictions.isEmpty())
        assertTrue(
            "foreign restriction must remain after Zreta clear",
            gateway.userRestrictions.contains(foreignKey),
        )
    }

    @Test
    fun bedtimeInactiveJustBeforeWindow() {
        val doc = overnightBedtimeDoc()
        clock = 21 * 60 + 59
        val result = enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertFalse(gateway.suspended.contains("com.example.game"))
        assertFalse(gateway.userRestrictions.contains(UserRestrictionKeys.OUTGOING_CALLS))
    }

    @Test
    fun bedtimeActiveInsideWindow() {
        val doc = overnightBedtimeDoc()
        clock = 22 * 60
        val atStart = enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, atStart.outcome)
        assertTrue(gateway.suspended.contains("com.example.game"))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.OUTGOING_CALLS))

        clock = 23 * 60
        val later = enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, later.outcome)
        assertTrue(gateway.suspended.contains("com.example.game"))
    }

    @Test
    fun bedtimeInactiveAfterWindow() {
        val doc = overnightBedtimeDoc()
        clock = 22 * 60
        enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertTrue(gateway.suspended.contains("com.example.game"))

        clock = 6 * 60
        val after = enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, after.outcome)
        assertFalse(gateway.suspended.contains("com.example.game"))
        assertFalse(gateway.userRestrictions.contains(UserRestrictionKeys.OUTGOING_CALLS))
        assertTrue(store.state.bedtimeSuspendedPackages.isEmpty())
    }

    @Test
    fun overnightWindowEdges() {
        val start = 22 * 60
        val end = 6 * 60
        assertFalse(ScreenTimeWindows.isActive(21 * 60 + 59, start, end))
        assertTrue(ScreenTimeWindows.isActive(22 * 60, start, end))
        assertTrue(ScreenTimeWindows.isActive(23 * 60 + 59, start, end))
        assertTrue(ScreenTimeWindows.isActive(1, start, end))
        assertTrue(ScreenTimeWindows.isActive(5 * 60 + 59, start, end))
        assertFalse(ScreenTimeWindows.isActive(6 * 60, start, end))
        assertFalse(ScreenTimeWindows.isActive(start, start, start)) // equal → inactive
    }

    @Test
    fun http304TimeDependentReevaluatesCachedPolicyInsideBedtime() {
        val doc = overnightBedtimeDoc()
        clock = 21 * 60 + 59
        enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertFalse(gateway.suspended.contains("com.example.game"))
        assertTrue(PolicyPullDecision.shouldReenforceCachedOnHttp304(doc))

        // Simulate later worker HTTP 304: same LKG document, clock now inside bedtime.
        clock = 22 * 60
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            document = doc,
            policyVersionId = "v1",
            versionNumber = 1,
            contentHash = "h",
            enforcer = enforcer,
        )
        assertTrue(evaluation.compliant)
        assertTrue(gateway.suspended.contains("com.example.game"))
        assertTrue(gateway.userRestrictions.contains(UserRestrictionKeys.OUTGOING_CALLS))
        assertEquals(1, store.state.acceptedVersionNumber)
        assertEquals("v1", store.state.policyVersionId)
    }

    @Test
    fun http304TimeDependentReevaluatesCachedPolicyOutsideBedtime() {
        val doc = overnightBedtimeDoc()
        clock = 23 * 60
        enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertTrue(gateway.suspended.contains("com.example.game"))

        clock = 12 * 60
        assertTrue(PolicyPullDecision.shouldReenforceCachedOnHttp304(doc))
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            document = doc,
            policyVersionId = "v1",
            versionNumber = 1,
            contentHash = "h",
            enforcer = enforcer,
        )
        assertTrue(evaluation.compliant)
        assertFalse(gateway.suspended.contains("com.example.game"))
        assertFalse(gateway.userRestrictions.contains(UserRestrictionKeys.OUTGOING_CALLS))
    }

    @Test
    fun http304NonTimeDependentKeepsEfficientSkipDecision() {
        val doc = baseDoc(device = JSONObject().put("camera_disabled", true))
        assertFalse(PolicyPullDecision.shouldReenforceCachedOnHttp304(doc))
        assertFalse(PolicyPullDecision.shouldReenforceCachedOnHttp304(null))
        assertFalse(PolicyPullDecision.shouldReenforceCachedOnHttp304(PolicyCompliance.emptyDocument()))
    }

    @Test
    fun bedtimeDoesNotClearApplicationOwnedSuspend() {
        val apps = JSONObject().put("suspend_packages", JSONArray(listOf("com.example.game")))
        val screen = JSONObject()
            .put("bedtime_start", "21:00")
            .put("bedtime_end", "07:00")
            .put("bedtime_suspend_packages", JSONArray(listOf("com.example.game")))

        clock = 22 * 60
        enforcer.enforceValidatedDocument(baseDoc(applications = apps, screenTime = screen), "v1", 1, "h")
        assertTrue(gateway.suspended.contains("com.example.game"))

        clock = 12 * 60
        enforcer.enforceValidatedDocument(baseDoc(applications = apps, screenTime = screen), "v1", 1, "h")
        assertTrue(gateway.suspended.contains("com.example.game"))
        assertTrue(store.state.suspendedPackages.contains("com.example.game"))
    }

    @Test
    fun locationAdvisoryDoesNotRequireDeviceOwner() {
        gateway.deviceOwner = false
        val result = enforcer.enforceValidatedDocument(
            baseDoc(location = JSONObject().put("collection_desired", true)),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertEquals(true, store.state.locationAdvisoryValue)
        assertTrue(result.controlResults.any { it.control == "location.collection_desired" })
        assertTrue(gateway.userRestrictions.isEmpty())
    }

    @Test
    fun locationAdvisoryClearsWhenSectionEmpty() {
        enforcer.enforceValidatedDocument(
            baseDoc(location = JSONObject().put("collection_desired", false)),
            "v1",
            1,
            "h1",
        )
        assertEquals(false, store.state.locationAdvisoryValue)
        enforcer.enforceValidatedDocument(PolicyCompliance.emptyDocument(), "v2", 2, "h2")
        assertNull(store.state.locationAdvisoryValue)
    }

    @Test
    fun managedStateRoundTripIncludesNewFields() {
        val state = ManagedEnforcementState(
            policyVersionId = "abc",
            versionNumber = 3,
            acceptedVersionNumber = 3,
            managedUserRestrictions = setOf(UserRestrictionKeys.SMS),
            bedtimeSuspendedPackages = setOf("com.example.game"),
            locationAdvisoryValue = true,
            successfullyEnforced = true,
        )
        val parsed = EnforcementStateStore.parseOrEmpty(EnforcementStateStore.serialize(state))
        assertEquals(state, parsed)
    }
}
