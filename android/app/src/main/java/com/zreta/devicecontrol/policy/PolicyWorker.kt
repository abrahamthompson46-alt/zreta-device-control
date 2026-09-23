package com.zreta.devicecontrol.policy

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.zreta.devicecontrol.api.ApiException
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.logging.SafeLog
import com.zreta.devicecontrol.policy.enforcement.EnforcementOutcome
import com.zreta.devicecontrol.policy.enforcement.EnforcementResult
import com.zreta.devicecontrol.policy.enforcement.PolicyCompliance
import org.json.JSONObject
import java.util.UUID

/**
 * Pulls authoritative policy, caches LKG (monotonic), enforces, then ACKs.
 * ACK result=applied only when enforcement outcome is APPLIED or NO_CHANGES.
 *
 * HTTP 304: preserves LKG; re-runs the same PolicyCompliance path when the cached
 * document has time-dependent controls (bedtime). Does not rewrite the document.
 */
class PolicyWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val store = SecureCredentialStore(applicationContext)
        val apiBase = store.apiBase()
        val deviceId = store.deviceId()
        val kid = store.publicKeyId()
        if (apiBase.isNullOrBlank() || deviceId.isNullOrBlank() || kid.isNullOrBlank()) {
            return Result.success()
        }
        val cache = PolicyCache(applicationContext)
        val client = DeviceApiClient()
        return try {
            var token = store.accessToken()
            val soon = System.currentTimeMillis() / 1000 + 60
            if (token.isNullOrBlank() || store.expiresAt() <= soon) {
                val refreshed = client.token(apiBase, deviceId, kid)
                token = refreshed.getString("access_token")
                val ttl = refreshed.optInt("expires_in", 900)
                store.saveSession(apiBase, deviceId, kid, token, System.currentTimeMillis() / 1000 + ttl)
            }
            val fetch = client.getPolicy(apiBase, token!!, cache.etag())
            if (fetch.notModified) {
                PolicyPullDecision.fromHttp304()
                val lkg = cache.document()
                if (!PolicyPullDecision.shouldReenforceCachedOnHttp304(lkg)) {
                    return Result.success()
                }
                // Same authoritative path as 200: LKG → PolicyCompliance → ACK.
                // Do not mutate LKG / version floor; use cached metadata only.
                return enforceAndAck(
                    client = client,
                    apiBase = apiBase,
                    token = token,
                    document = lkg!!,
                    policyVersionId = cache.policyVersionId(),
                    versionNumber = cache.versionNumber().takeIf { it > 0 },
                    contentHash = cache.contentHash(),
                )
            }
            val body = fetch.body ?: return Result.retry()
            val state = body.optString("assignment_state", "unassigned")
            if (state == "unassigned" || body.isNull("document") || body.optJSONObject("document") == null) {
                cache.markUnassignedKeepDocument()
                return Result.success()
            }
            val document = body.getJSONObject("document")
            val versionId = body.optString("policy_version_id").ifBlank { null }
            val versionNumber = if (body.has("version_number") && !body.isNull("version_number")) {
                body.getInt("version_number")
            } else {
                null
            }
            val contentHash = body.optString("content_hash").ifBlank { null }
            val schemaVersion = if (body.has("schema_version") && !body.isNull("schema_version")) {
                body.getInt("schema_version")
            } else {
                document.optInt("schema_version", 0)
            }
            val policyId = body.optString("policy_id").ifBlank { null }
            val storeResult = cache.storeValidated(
                assignmentState = "assigned",
                policyId = policyId,
                policyVersionId = versionId,
                versionNumber = versionNumber,
                schemaVersion = schemaVersion,
                contentHash = contentHash,
                etag = fetch.etag,
                document = document,
            )
            val decision = PolicyPullDecision.afterStoreAttempt(storeResult, versionId)
            if (decision.rejectedStale) {
                SafeLog.w("Stale policy version ignored; preserving newer LKG/enforcement")
                return Result.success()
            }
            if (!decision.stored) {
                SafeLog.w("Policy download rejected locally; preserving LKG; skipping enforce/ACK")
                return Result.success()
            }

            return enforceAndAck(
                client = client,
                apiBase = apiBase,
                token = token,
                document = document,
                policyVersionId = versionId,
                versionNumber = versionNumber,
                contentHash = contentHash,
            )
        } catch (ex: ApiException) {
            if (ex.code == 401 || ex.code == 403) {
                Result.success()
            } else {
                SafeLog.w("Policy pull failed HTTP ${ex.code}")
                Result.retry()
            }
        } catch (ex: Exception) {
            SafeLog.e("Policy worker failed", ex)
            Result.retry()
        }
    }

    private suspend fun enforceAndAck(
        client: DeviceApiClient,
        apiBase: String,
        token: String,
        document: JSONObject,
        policyVersionId: String?,
        versionNumber: Int?,
        contentHash: String?,
    ): Result {
        val evaluation = PolicyCompliance.evaluateAndEnforce(
            context = applicationContext,
            document = document,
            policyVersionId = policyVersionId,
            versionNumber = versionNumber,
            contentHash = contentHash,
        )
        val enforcement = evaluation.enforcement
        if (enforcement?.message == "older_version") {
            SafeLog.w("Enforcer rejected older version; no ACK")
            return Result.success()
        }
        com.zreta.devicecontrol.network.VpnConsentCoordinator.handleEnforcementResult(
            applicationContext,
            enforcement,
        )
        val ackResult = ackResultFor(enforcement)
        if (enforcement?.outcome == EnforcementOutcome.FAILED) {
            SafeLog.w("Policy enforcement failed; tracked successes preserved; no applied ACK")
        }
        val ack = JSONObject()
            .put("policy_version_id", policyVersionId)
            .put("version_number", versionNumber)
            .put("content_hash", contentHash)
            .put("applied_at", java.time.Instant.now().toString())
            .put("result", ackResult)
            .put("client_event_id", UUID.randomUUID().toString())
        return try {
            client.ackPolicy(apiBase, token, ack)
            Result.success()
        } catch (ex: ApiException) {
            SafeLog.w("Policy ack failed HTTP ${ex.code}")
            Result.retry()
        }
    }

    companion object {
        const val UNIQUE_NAME = "zreta-policy"

        fun ackResultFor(enforcement: EnforcementResult?): String = when {
            enforcement == null -> "rejected_enforcement"
            enforcement.shouldAckAsApplied() -> "applied"
            else -> enforcement.ackResultOrNull() ?: "rejected_enforcement"
        }
    }
}
