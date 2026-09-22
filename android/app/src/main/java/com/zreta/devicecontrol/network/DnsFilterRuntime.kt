package com.zreta.devicecontrol.network

import com.zreta.devicecontrol.policy.enforcement.DnsFilterServiceState
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Process-wide bridge between [VpnDnsFilterController] and [DnsFilterVpnService].
 * Policy never talks to the backend from the VPN path — only already-validated domains.
 */
class DnsFilterRuntime {
    private val state = AtomicReference(DnsFilterServiceState.STOPPED)
    private val blockedDomains = AtomicReference<List<String>>(emptyList())
    private val lastError = AtomicReference<String?>(null)
    private val engine = DnsFilterEngine()

    @Volatile
    private var waitLatch: CountDownLatch? = null

    fun observedState(): DnsFilterServiceState = state.get()

    fun lastError(): String? = lastError.get()

    fun engine(): DnsFilterEngine = engine

    fun blockedDomains(): List<String> = blockedDomains.get()

    fun setBlockedDomains(domains: List<String>) {
        val copy = domains.toList()
        blockedDomains.set(copy)
        engine.updateBlocked(copy)
    }

    fun beginStart(domains: List<String>): CountDownLatch {
        setBlockedDomains(domains)
        lastError.set(null)
        state.set(DnsFilterServiceState.STARTING)
        val latch = CountDownLatch(1)
        waitLatch = latch
        return latch
    }

    /** Hot-reload ack latch; does not change rules until the service applies them. */
    fun beginReloadAck(): CountDownLatch {
        lastError.set(null)
        val latch = CountDownLatch(1)
        waitLatch = latch
        return latch
    }

    fun beginStop(): CountDownLatch {
        lastError.set(null)
        val latch = CountDownLatch(1)
        waitLatch = latch
        return latch
    }

    fun noteConsentRequired() {
        lastError.set("vpn_consent_required")
        state.set(DnsFilterServiceState.STOPPED)
    }

    fun awaitLatch(latch: CountDownLatch, timeoutMs: Long): Boolean =
        latch.await(timeoutMs, TimeUnit.MILLISECONDS)

    fun signalRunning() {
        state.set(DnsFilterServiceState.RUNNING)
        lastError.set(null)
        waitLatch?.countDown()
    }

    fun signalStopped() {
        state.set(DnsFilterServiceState.STOPPED)
        waitLatch?.countDown()
    }

    fun signalFailed(error: String) {
        lastError.set(error)
        state.set(DnsFilterServiceState.FAILED)
        waitLatch?.countDown()
    }

    /** After FAILED, map to STOPPED for fail-open observed queries used by health checks. */
    fun observedForEnforcer(): DnsFilterServiceState {
        return when (val s = state.get()) {
            DnsFilterServiceState.FAILED -> DnsFilterServiceState.STOPPED
            DnsFilterServiceState.STARTING -> DnsFilterServiceState.STOPPED
            else -> s
        }
    }

    fun resetForTests() {
        state.set(DnsFilterServiceState.STOPPED)
        blockedDomains.set(emptyList())
        engine.updateBlocked(emptyList())
        lastError.set(null)
        waitLatch = null
    }

    companion object {
        val instance = DnsFilterRuntime()
    }
}
