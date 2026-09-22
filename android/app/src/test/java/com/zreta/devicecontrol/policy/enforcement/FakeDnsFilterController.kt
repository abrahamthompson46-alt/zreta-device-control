package com.zreta.devicecontrol.policy.enforcement

/**
 * In-memory fake for JVM tests. Can be configured to fail start/reload/stop.
 * Test-only — not used by production [PolicyEnforcer.create].
 */
class FakeDnsFilterController(
    var failStart: Boolean = false,
    var failReload: Boolean = false,
    var failStop: Boolean = false,
) : DnsFilterController {
    var observed: DnsFilterServiceState = DnsFilterServiceState.STOPPED
        private set
    var loadedDomains: List<String> = emptyList()
        private set
    var startCount: Int = 0
    var stopCount: Int = 0
    var reloadCount: Int = 0
    private var error: String? = null

    override fun start(blockedDomains: List<String>): DnsFilterOpResult {
        startCount++
        if (failStart) {
            error = "start_failed"
            observed = DnsFilterServiceState.STOPPED
            return DnsFilterOpResult(false, observed, error)
        }
        loadedDomains = blockedDomains.toList()
        observed = DnsFilterServiceState.RUNNING
        error = null
        return DnsFilterOpResult(true, observed, null)
    }

    override fun stop(): DnsFilterOpResult {
        stopCount++
        if (failStop) {
            error = "stop_failed"
            return DnsFilterOpResult(false, observed, error)
        }
        loadedDomains = emptyList()
        observed = DnsFilterServiceState.STOPPED
        error = null
        return DnsFilterOpResult(true, observed, null)
    }

    override fun reload(blockedDomains: List<String>): DnsFilterOpResult {
        reloadCount++
        if (failReload) {
            error = "reload_failed"
            return DnsFilterOpResult(false, observed, error)
        }
        if (observed != DnsFilterServiceState.RUNNING) {
            return start(blockedDomains)
        }
        loadedDomains = blockedDomains.toList()
        error = null
        return DnsFilterOpResult(true, observed, null)
    }

    override fun observedState(): DnsFilterServiceState = observed

    override fun lastError(): String? = error

    /** Simulate crash: service down without going through stop(). */
    fun simulateCrash() {
        observed = DnsFilterServiceState.STOPPED
        loadedDomains = emptyList()
        error = "crashed"
    }
}
