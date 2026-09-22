package com.zreta.devicecontrol.policy.enforcement

import android.content.Context
import com.zreta.devicecontrol.policy.PolicyDocumentValidator
import org.json.JSONObject

/**
 * Shared compliance / enforcement entry used by PolicyWorker and PolicyComplianceActivity.
 */
object PolicyCompliance {
    data class Evaluation(
        val compliant: Boolean,
        val enforcement: EnforcementResult?,
        val reason: String?,
    )

    fun emptyDocument(): JSONObject = JSONObject()
        .put("schema_version", 1)
        .put("internet", JSONObject())
        .put("calls", JSONObject())
        .put("applications", JSONObject())
        .put("screen_time", JSONObject())
        .put("device", JSONObject())
        .put("location", JSONObject())

    fun evaluateAndEnforce(
        context: Context,
        document: JSONObject,
        policyVersionId: String? = null,
        versionNumber: Int? = null,
        contentHash: String? = null,
    ): Evaluation = evaluateAndEnforce(
        document = document,
        policyVersionId = policyVersionId,
        versionNumber = versionNumber,
        contentHash = contentHash,
        enforcer = PolicyEnforcer.create(context),
    )

    fun evaluateAndEnforce(
        document: JSONObject,
        policyVersionId: String? = null,
        versionNumber: Int? = null,
        contentHash: String? = null,
        enforcer: PolicyEnforcer,
    ): Evaluation {
        if (PolicyDocumentValidator.validateJsonObjectOrNull(document) == null) {
            return Evaluation(compliant = false, enforcement = null, reason = "invalid_document")
        }
        val result = enforcer.enforceValidatedDocument(
            document = document,
            policyVersionId = policyVersionId,
            versionNumber = versionNumber,
            contentHash = contentHash,
        )
        return Evaluation(
            compliant = result.shouldAckAsApplied(),
            enforcement = result,
            reason = result.message,
        )
    }
}
