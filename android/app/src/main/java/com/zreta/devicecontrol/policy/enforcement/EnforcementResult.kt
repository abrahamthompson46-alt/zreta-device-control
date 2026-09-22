package com.zreta.devicecontrol.policy.enforcement

/**
 * Aggregate outcome of applying a validated policy document.
 */
enum class EnforcementOutcome {
    /** Desired enforceable state fully applied (including skipped unsafe packages). */
    APPLIED,

    /** Same version already enforced; no DevicePolicyManager mutations performed. */
    NO_CHANGES,

    /** Some safe controls failed via DPM; others may have applied. */
    PARTIAL,

    /** Policy/document/role rejected before or instead of applying. */
    REJECTED,

    /** Hard failure; previous managed state preserved where possible. */
    FAILED,
}

data class PackageActionResult(
    val packageName: String,
    val action: String,
    val status: String,
    val detail: String? = null,
)

data class ControlResult(
    val control: String,
    val status: String,
    val detail: String? = null,
)

data class EnforcementResult(
    val outcome: EnforcementOutcome,
    val policyVersionId: String?,
    val versionNumber: Int?,
    val packageResults: List<PackageActionResult> = emptyList(),
    val controlResults: List<ControlResult> = emptyList(),
    val message: String? = null,
) {
    /** Maps to backend ACK result; null means do not send an applied-style ACK. */
    fun ackResultOrNull(): String? = when (outcome) {
        EnforcementOutcome.APPLIED, EnforcementOutcome.NO_CHANGES -> "applied"
        EnforcementOutcome.PARTIAL -> "enforcement_partial"
        EnforcementOutcome.REJECTED, EnforcementOutcome.FAILED -> "rejected_enforcement"
    }

    fun shouldAckAsApplied(): Boolean =
        outcome == EnforcementOutcome.APPLIED || outcome == EnforcementOutcome.NO_CHANGES
}
