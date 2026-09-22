package com.zreta.devicecontrol.policy

import com.zreta.devicecontrol.policy.enforcement.PolicyControlsParser
import org.json.JSONObject

/**
 * Pure decision helper for policy pull → store → ACK gating (unit-testable).
 */
object PolicyPullDecision {
    data class Outcome(
        val storeAttempted: Boolean,
        val stored: Boolean,
        val sendAppliedAck: Boolean,
        val preserveLkg: Boolean,
        val skipBecauseNotModified: Boolean = false,
        val unassignedKeepLkg: Boolean = false,
        val rejectedStale: Boolean = false,
    )

    fun fromHttp304(): Outcome = Outcome(
        storeAttempted = false,
        stored = false,
        sendAppliedAck = false,
        preserveLkg = true,
        skipBecauseNotModified = true,
    )

    /**
     * HTTP 304 must re-run the single PolicyEnforcer path when LKG has time-dependent
     * controls (e.g. bedtime). Non-time-dependent LKG keeps the efficient 304 skip.
     * Never mutates LKG; caller must enforce the existing cached document only.
     */
    fun shouldReenforceCachedOnHttp304(cachedDocument: JSONObject?): Boolean {
        if (cachedDocument == null) return false
        if (PolicyDocumentValidator.validateJsonObjectOrNull(cachedDocument) == null) return false
        return PolicyControlsParser.fromValidatedJson(cachedDocument).hasTimeDependentControls()
    }

    fun fromUnassignedOrEmptyDocument(): Outcome = Outcome(
        storeAttempted = false,
        stored = false,
        sendAppliedAck = false,
        preserveLkg = true,
        unassignedKeepLkg = true,
    )

    fun afterStoreAttempt(result: PolicyStoreResult, versionId: String?): Outcome = when (result) {
        PolicyStoreResult.STORED -> Outcome(
            storeAttempted = true,
            stored = true,
            sendAppliedAck = !versionId.isNullOrBlank(),
            preserveLkg = false,
        )
        PolicyStoreResult.REJECTED_INVALID -> Outcome(
            storeAttempted = true,
            stored = false,
            sendAppliedAck = false,
            preserveLkg = true,
        )
        PolicyStoreResult.REJECTED_STALE -> Outcome(
            storeAttempted = true,
            stored = false,
            sendAppliedAck = false,
            preserveLkg = true,
            rejectedStale = true,
        )
    }

    /** @deprecated use [afterStoreAttempt] with [PolicyStoreResult] */
    fun afterStoreAttempt(stored: Boolean, versionId: String?): Outcome = afterStoreAttempt(
        if (stored) PolicyStoreResult.STORED else PolicyStoreResult.REJECTED_INVALID,
        versionId,
    )

    fun shouldAckApplied(outcome: Outcome): Boolean = outcome.sendAppliedAck
}

/**
 * Classify a downloaded document before store (for tests / worker).
 */
object PolicyDownloadClassifier {
    fun isSchemaInvalid(document: JSONObject): Boolean {
        val schema = document.optInt("schema_version", -1)
        return schema != 1
    }

    fun isMalformed(document: JSONObject): Boolean {
        return PolicyDocumentValidator.validateJsonObjectOrNull(document) == null
    }
}
