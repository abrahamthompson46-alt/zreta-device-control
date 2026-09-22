package com.zreta.devicecontrol.policy.enforcement

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class InternetTrafficEnforcerTest {
    private lateinit var gateway: FakeDevicePolicyGateway
    private lateinit var store: InMemoryEnforcementStateStore
    private lateinit var filter: FakeDnsFilterController
    private lateinit var enforcer: PolicyEnforcer

    @Before
    fun setUp() {
        gateway = FakeDevicePolicyGateway(deviceOwner = true)
        store = InMemoryEnforcementStateStore()
        filter = FakeDnsFilterController()
        enforcer = PolicyEnforcer.createForTests(gateway, store, dnsFilterController = filter)
    }

    private fun baseDoc(internet: JSONObject = JSONObject()): JSONObject =
        JSONObject()
            .put("schema_version", 1)
            .put("internet", internet)
            .put("calls", JSONObject())
            .put("applications", JSONObject())
            .put("screen_time", JSONObject())
            .put("device", JSONObject())
            .put("location", JSONObject())

    private fun trafficDoc(
        enabled: Boolean,
        domains: List<String> = emptyList(),
        engine: String = DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST,
    ): JSONObject {
        val traffic = JSONObject()
            .put("enabled", enabled)
            .put("engine", engine)
            .put("blocked_domains", JSONArray(domains))
        return baseDoc(JSONObject().put("traffic", traffic))
    }

    @Test
    fun disabledStopsFilter() {
        filter.start(listOf("a.example.com"))
        store.state = store.state.copy(
            trafficFilterManaged = true,
            trafficFilterDesiredEnabled = true,
            trafficServiceObserved = DnsFilterServiceState.RUNNING,
            trafficServiceDesired = DnsFilterServiceState.RUNNING,
        )
        val result = enforcer.enforceValidatedDocument(trafficDoc(enabled = false), "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertEquals(DnsFilterServiceState.STOPPED, filter.observedState())
        assertTrue(store.state.trafficFilterManaged)
        assertFalse(store.state.trafficFilterDesiredEnabled)
        assertEquals(DnsFilterServiceState.STOPPED, store.state.trafficServiceObserved)
    }

    @Test
    fun enabledStartsFilter() {
        val result = enforcer.enforceValidatedDocument(
            trafficDoc(true, listOf("ads.example.com")),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertEquals(DnsFilterServiceState.RUNNING, filter.observedState())
        assertEquals(listOf("ads.example.com"), filter.loadedDomains)
        assertTrue(store.state.trafficFilterManaged)
        assertTrue(store.state.trafficFilterDesiredEnabled)
        assertEquals(DnsFilterServiceState.RUNNING, store.state.trafficServiceObserved)
        assertNotNull(store.state.trafficRuleHash)
        assertNull(store.state.trafficLastError)
    }

    @Test
    fun enableFailureIsPartialNeverApplied() {
        filter.failStart = true
        val result = enforcer.enforceValidatedDocument(
            trafficDoc(true, listOf("ads.example.com")),
            "v1",
            1,
            "h",
        )
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertFalse(result.shouldAckAsApplied())
        assertEquals(DnsFilterServiceState.STOPPED, filter.observedState())
        assertEquals(DnsFilterServiceState.STOPPED, store.state.trafficServiceObserved)
        assertFalse(store.state.trafficFilterManaged)
        assertTrue(store.state.trafficFilterDesiredEnabled)
        assertNull(store.state.trafficRuleHash)
        assertEquals("start_failed", store.state.trafficLastError)
    }

    @Test
    fun unimplementedControllerCannotApplyEnabled() {
        val local = PolicyEnforcer.createForTests(
            gateway,
            store,
            dnsFilterController = UnimplementedDnsFilterController(),
        )
        val result = local.enforceValidatedDocument(trafficDoc(true), "v1", 1, "h")
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertFalse(result.shouldAckAsApplied())
    }

    @Test
    fun reloadChangedRules() {
        enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h1")
        assertEquals(1, filter.startCount)
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("b.example.com")), "v2", 2, "h2")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertTrue(filter.reloadCount >= 1 || filter.startCount >= 2)
        assertEquals(listOf("b.example.com"), filter.loadedDomains)
    }

    @Test
    fun unchangedRulesYieldNoChangesWhenHealthy() {
        enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h")
        val startCount = filter.startCount
        val second = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h")
        assertEquals(EnforcementOutcome.NO_CHANGES, second.outcome)
        assertEquals(startCount, filter.startCount)
    }

    @Test
    fun emptyBlocklistEnabledIsValid() {
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, emptyList()), "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertEquals(DnsFilterServiceState.RUNNING, filter.observedState())
        assertTrue(filter.loadedDomains.isEmpty())
    }

    @Test
    fun laterFailurePreservesPriorOwnershipHash() {
        enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h1")
        val hash = store.state.trafficRuleHash
        assertNotNull(hash)
        filter.failReload = true
        filter.failStart = true
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("b.example.com")), "v2", 2, "h2")
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertTrue(store.state.trafficFilterManaged)
        // Applied hash must remain the last successfully loaded rules (not the failed desired hash).
        assertEquals(hash, store.state.trafficRuleHash)
        assertEquals(listOf("a.example.com"), filter.loadedDomains)
        assertEquals(DnsFilterServiceState.RUNNING, filter.observedState())
        // Must not falsely become healthy with the new policy hash.
        val retry = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("b.example.com")), "v2", 2, "h2")
        assertEquals(EnforcementOutcome.PARTIAL, retry.outcome)
        assertTrue(filter.reloadCount >= 2 || filter.startCount >= 2)
    }

    @Test
    fun cameraStillWorksAlongsideTraffic() {
        val internet = JSONObject()
            .put(
                "traffic",
                JSONObject()
                    .put("enabled", true)
                    .put("engine", DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST)
                    .put("blocked_domains", JSONArray(listOf("ads.example.com"))),
            )
        val doc = baseDoc(internet).put("device", JSONObject().put("camera_disabled", true))
        val result = enforcer.enforceValidatedDocument(doc, "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertTrue(gateway.cameraDisabledFlag)
        assertEquals(DnsFilterServiceState.RUNNING, filter.observedState())
    }

    @Test
    fun trafficDoesNotRequireDeviceOwner() {
        gateway.deviceOwner = false
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
    }
}
