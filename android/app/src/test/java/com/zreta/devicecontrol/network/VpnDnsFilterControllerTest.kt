package com.zreta.devicecontrol.network

import com.zreta.devicecontrol.policy.enforcement.DnsFilterServiceState
import com.zreta.devicecontrol.policy.enforcement.EnforcementOutcome
import com.zreta.devicecontrol.policy.enforcement.FakeDevicePolicyGateway
import com.zreta.devicecontrol.policy.enforcement.FakeDnsFilterController
import com.zreta.devicecontrol.policy.enforcement.InMemoryEnforcementStateStore
import com.zreta.devicecontrol.policy.enforcement.PolicyEnforcer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * JVM tests for controller readiness / consent / fail-open.
 * These do **not** prove real TUN routing on a device.
 */
class VpnDnsFilterControllerTest {
    private lateinit var runtime: DnsFilterRuntime
    private val startedActions = mutableListOf<String>()

    @Before
    fun setUp() {
        runtime = DnsFilterRuntime()
        startedActions.clear()
    }

    @After
    fun tearDown() {
        runtime.resetForTests()
    }

    private fun controller(
        consentRequired: Boolean = false,
        timeoutMs: Long = 2_000,
        onDispatch: (DnsFilterServiceCommand) -> Unit,
    ): VpnDnsFilterController =
        VpnDnsFilterController(
            runtime = runtime,
            prepareIntent = { if (consentRequired) Any() else null },
            dispatch = onDispatch,
            readinessTimeoutMs = timeoutMs,
        )

    @Test
    fun consentRequiredDoesNotClaimRunning() {
        val ctrl = controller(consentRequired = true) { error("must not start") }
        val result = ctrl.start(listOf("ads.example.com"))
        assertFalse(result.success)
        assertEquals(DnsFilterServiceState.STOPPED, result.observed)
        assertEquals("vpn_consent_required", result.error)
        assertEquals(DnsFilterServiceState.STOPPED, ctrl.observedState())
    }

    @Test
    fun startSignalsRunningOnlyAfterReady() {
        val ctrl = controller {
            startedActions.add(it.action)
            Thread {
                Thread.sleep(30)
                runtime.signalRunning()
            }.start()
        }
        val result = ctrl.start(listOf("a.example.com"))
        assertTrue(result.success)
        assertEquals(DnsFilterServiceState.RUNNING, result.observed)
        assertEquals(DnsFilterVpnService.ACTION_START, startedActions.single())
        assertEquals(listOf("a.example.com"), runtime.blockedDomains())
    }

    @Test
    fun startTimeoutIsFailOpen() {
        val ctrl = controller(timeoutMs = 80) { /* never signals */ }
        val result = ctrl.start(listOf("a.example.com"))
        assertFalse(result.success)
        assertEquals("vpn_start_timeout", result.error)
        assertEquals(DnsFilterServiceState.STOPPED, ctrl.observedState())
    }

    @Test
    fun protectFailureMappedViaFailedState() {
        val ctrl = controller {
            Thread { runtime.signalFailed("vpn_upstream_protect_failed") }.start()
        }
        val result = ctrl.start(emptyList())
        assertFalse(result.success)
        assertEquals("vpn_upstream_protect_failed", result.error)
        assertEquals(DnsFilterServiceState.STOPPED, result.observed)
    }

    @Test
    fun reloadHotPathKeepsRunningSemantics() {
        runtime.signalRunning()
        runtime.setBlockedDomains(listOf("old.example.com"))
        val ctrl = controller {
            startedActions.add(it.action)
            runtime.setBlockedDomains(it.domains)
            runtime.signalRunning()
        }
        val result = ctrl.reload(listOf("new.example.com"))
        assertTrue(result.success)
        assertEquals(DnsFilterVpnService.ACTION_RELOAD, startedActions.single())
        assertEquals(listOf("new.example.com"), runtime.blockedDomains())
        assertEquals(DnsFilterServiceState.RUNNING, ctrl.observedState())
    }

    @Test
    fun failedReloadDoesNotReplaceEngineRules() {
        runtime.signalRunning()
        runtime.setBlockedDomains(listOf("old.example.com"))
        val ctrl = controller(timeoutMs = 80) { /* never acks */ }
        val result = ctrl.reload(listOf("new.example.com"))
        assertFalse(result.success)
        assertEquals("vpn_reload_timeout", result.error)
        assertEquals(listOf("old.example.com"), runtime.blockedDomains())
        assertEquals(DnsFilterServiceState.RUNNING, ctrl.observedState())
    }

    @Test
    fun fgsStartNotAllowedIsFailOpenPartialCode() {
        val ctrl = controller {
            throw ForegroundServiceStartNotAllowedException("background start blocked")
        }
        val result = ctrl.start(listOf("a.example.com"))
        assertFalse(result.success)
        assertEquals("vpn_fgs_start_not_allowed", result.error)
        assertEquals(DnsFilterServiceState.STOPPED, result.observed)
    }

    @Test
    fun classifyDispatchFailureDetectsFgsRestriction() {
        assertEquals(
            "vpn_fgs_start_not_allowed",
            VpnDnsFilterController.classifyDispatchFailure(
                ForegroundServiceStartNotAllowedException("x"),
                "vpn_start_failed",
            ),
        )
    }

    @Test
    fun stopFromRunning() {
        runtime.signalRunning()
        val ctrl = controller { runtime.signalStopped() }
        val result = ctrl.stop()
        assertTrue(result.success)
        assertEquals(DnsFilterServiceState.STOPPED, result.observed)
    }
}

/** Test stand-in; production classifier matches by class-name substring. */
private class ForegroundServiceStartNotAllowedException(message: String) : IllegalStateException(message)

class VpnDnsFilterPolicyIntegrationTest {
    private lateinit var store: InMemoryEnforcementStateStore
    private lateinit var gateway: FakeDevicePolicyGateway

    @Before
    fun setUp() {
        store = InMemoryEnforcementStateStore()
        gateway = FakeDevicePolicyGateway(deviceOwner = true)
    }

    @Test
    fun consentRequiredYieldsPartialNeverApplied() {
        val runtime = DnsFilterRuntime()
        val ctrl = VpnDnsFilterController(
            runtime = runtime,
            prepareIntent = { Any() },
            dispatch = { error("no") },
            readinessTimeoutMs = 500,
        )
        val enforcer = PolicyEnforcer.createForTests(gateway, store, dnsFilterController = ctrl)
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("ads.example.com")), "v1", 1, "h")
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertFalse(result.shouldAckAsApplied())
        assertFalse(store.state.trafficFilterManaged)
    }

    @Test
    fun successfulReadySignalsAppliedWithFakeStillWorks() {
        val filter = FakeDnsFilterController()
        val enforcer = PolicyEnforcer.createForTests(gateway, store, dnsFilterController = filter)
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h")
        assertEquals(EnforcementOutcome.APPLIED, result.outcome)
        assertTrue(store.state.trafficFilterManaged)
    }

    @Test
    fun hashPreservedOnControllerFailure() {
        val filter = FakeDnsFilterController()
        val enforcer = PolicyEnforcer.createForTests(gateway, store, dnsFilterController = filter)
        enforcer.enforceValidatedDocument(trafficDoc(true, listOf("a.example.com")), "v1", 1, "h1")
        val hash = store.state.trafficRuleHash
        filter.failReload = true
        filter.failStart = true
        val result = enforcer.enforceValidatedDocument(trafficDoc(true, listOf("b.example.com")), "v2", 2, "h2")
        assertEquals(EnforcementOutcome.PARTIAL, result.outcome)
        assertEquals(hash, store.state.trafficRuleHash)
        assertTrue(store.state.trafficFilterManaged)
    }

    private fun trafficDoc(enabled: Boolean, domains: List<String>): JSONObject {
        val traffic = JSONObject()
            .put("enabled", enabled)
            .put("engine", "local_dns_blocklist")
            .put("blocked_domains", JSONArray(domains))
        return JSONObject()
            .put("schema_version", 1)
            .put("internet", JSONObject().put("traffic", traffic))
            .put("calls", JSONObject())
            .put("applications", JSONObject())
            .put("screen_time", JSONObject())
            .put("device", JSONObject())
            .put("location", JSONObject())
    }
}
