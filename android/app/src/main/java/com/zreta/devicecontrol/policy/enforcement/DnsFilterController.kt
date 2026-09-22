package com.zreta.devicecontrol.policy.enforcement

/**
 * Observed / desired state of the DNS filter engine (VpnService in 5.1B).
 * Enforcement success requires [RUNNING]; STARTING/FAILED are transitional and fail-open.
 */
enum class DnsFilterServiceState {
    STOPPED,
    STARTING,
    RUNNING,
    FAILED,
}

data class DnsFilterOpResult(
    val success: Boolean,
    val observed: DnsFilterServiceState,
    val error: String? = null,
)

/**
 * Abstraction over the DNS filter engine so PolicyEnforcer can be tested without a real VpnService.
 * Phase 5.1B will provide a VpnService-backed implementation.
 */
interface DnsFilterController {
    fun start(blockedDomains: List<String>): DnsFilterOpResult

    fun stop(): DnsFilterOpResult

    fun reload(blockedDomains: List<String>): DnsFilterOpResult

    fun observedState(): DnsFilterServiceState

    fun lastError(): String?
}

/**
 * Production placeholder kept for tests that need a non-VPN controller.
 * Prefer [com.zreta.devicecontrol.network.VpnDnsFilterController] in production.
 */
class UnimplementedDnsFilterController : DnsFilterController {
    override fun start(blockedDomains: List<String>): DnsFilterOpResult =
        DnsFilterOpResult(false, DnsFilterServiceState.STOPPED, "vpn_not_implemented")

    override fun stop(): DnsFilterOpResult =
        DnsFilterOpResult(true, DnsFilterServiceState.STOPPED, null)

    override fun reload(blockedDomains: List<String>): DnsFilterOpResult = start(blockedDomains)

    override fun observedState(): DnsFilterServiceState = DnsFilterServiceState.STOPPED

    override fun lastError(): String? = "vpn_not_implemented"
}
