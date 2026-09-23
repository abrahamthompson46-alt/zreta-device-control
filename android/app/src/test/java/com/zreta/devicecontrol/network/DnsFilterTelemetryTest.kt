package com.zreta.devicecontrol.network

import com.zreta.devicecontrol.policy.enforcement.ControlResult
import com.zreta.devicecontrol.policy.enforcement.EnforcementOutcome
import com.zreta.devicecontrol.policy.enforcement.EnforcementResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DnsFilterTelemetryTest {
    @Test
    fun detectsConsentRequiredFromControlResult() {
        val result = EnforcementResult(
            outcome = EnforcementOutcome.PARTIAL,
            policyVersionId = "v1",
            versionNumber = 1,
            controlResults = listOf(
                ControlResult("traffic.filter", "failed", "vpn_consent_required"),
            ),
        )
        assertTrue(DnsFilterTelemetry.needsConsent(result))
        assertEquals(
            DnsFilterTelemetry.CONSENT_REQUIRED,
            DnsFilterTelemetry.fromEnforcement(result)!!.state,
        )
    }

    @Test
    fun mapsStartedToRunning() {
        val result = EnforcementResult(
            outcome = EnforcementOutcome.APPLIED,
            policyVersionId = "v1",
            versionNumber = 1,
            controlResults = listOf(
                ControlResult("traffic.filter", "started", "abc"),
            ),
        )
        assertFalse(DnsFilterTelemetry.needsConsent(result))
        assertEquals(DnsFilterTelemetry.RUNNING, DnsFilterTelemetry.fromEnforcement(result)!!.state)
    }

    @Test
    fun mapsStoppedCleared() {
        val result = EnforcementResult(
            outcome = EnforcementOutcome.APPLIED,
            policyVersionId = "v1",
            versionNumber = 1,
            controlResults = listOf(
                ControlResult("traffic.filter", "stopped"),
            ),
        )
        assertEquals(DnsFilterTelemetry.STOPPED, DnsFilterTelemetry.fromEnforcement(result)!!.state)
    }
}
