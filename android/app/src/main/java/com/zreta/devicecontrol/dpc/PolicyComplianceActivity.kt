package com.zreta.devicecontrol.dpc

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import com.zreta.devicecontrol.logging.SafeLog
import com.zreta.devicecontrol.policy.PolicyCache
import com.zreta.devicecontrol.policy.enforcement.PolicyCompliance
import com.zreta.devicecontrol.ui.MainActivity

/**
 * AFW provisioning compliance hook. Uses the same enforcement path as PolicyWorker.
 * Empty policy → success. Invalid/unsupported documents → not compliant.
 */
class PolicyComplianceActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val cache = PolicyCache(applicationContext)
        val document = cache.document() ?: PolicyCompliance.emptyDocument()
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            context = applicationContext,
            document = document,
            policyVersionId = cache.policyVersionId(),
            versionNumber = cache.versionNumber().takeIf { it > 0 },
            contentHash = cache.contentHash(),
        )
        com.zreta.devicecontrol.network.VpnConsentCoordinator.handleEnforcementResult(
            applicationContext,
            evaluation.enforcement,
        )
        if (evaluation.compliant) {
            setResult(RESULT_OK)
        } else {
            SafeLog.w("Policy compliance failed: ${evaluation.reason}")
            setResult(RESULT_CANCELED)
        }
        startActivity(
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        finish()
    }
}
