package com.zreta.devicecontrol.policy

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONObject

enum class PolicyStoreResult {
    STORED,
    REJECTED_INVALID,
    REJECTED_STALE,
}

/**
 * Last-known-good encrypted policy cache.
 * Never replaces a valid cache with a malformed or older-version document.
 */
class PolicyCache(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "zreta_policy_cache",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun assignmentState(): String = prefs.getString(KEY_STATE, "none") ?: "none"

    fun policyVersionId(): String? = prefs.getString(KEY_VERSION_ID, null)

    fun versionNumber(): Int = prefs.getInt(KEY_VERSION_NUMBER, 0)

    fun contentHash(): String? = prefs.getString(KEY_HASH, null)

    fun etag(): String? = prefs.getString(KEY_ETAG, null)

    fun documentJson(): String? = prefs.getString(KEY_DOCUMENT, null)

    fun document(): JSONObject? {
        val raw = documentJson() ?: return null
        return try {
            JSONObject(raw)
        } catch (_: Exception) {
            null
        }
    }

    fun statusSummary(): String {
        return when (assignmentState()) {
            "unassigned" -> "no policy assigned (cached LKG kept if any)"
            "assigned" -> {
                val v = versionNumber()
                val hash = contentHash()
                if (v > 0) {
                    val suffix = if (!hash.isNullOrBlank()) " ($hash)" else ""
                    "applied version $v$suffix"
                } else {
                    "assigned (waiting for published version)"
                }
            }
            else -> "no cached policy"
        }
    }

    /**
     * Store a validated policy document.
     * Rejects invalid documents and version downgrades (monotonic LKG).
     */
    fun storeValidated(
        assignmentState: String,
        policyId: String?,
        policyVersionId: String?,
        versionNumber: Int?,
        schemaVersion: Int?,
        contentHash: String?,
        etag: String?,
        document: JSONObject?,
    ): PolicyStoreResult {
        if (document != null && PolicyDocumentValidator.validateJsonObjectOrNull(document) == null) {
            return PolicyStoreResult.REJECTED_INVALID
        }
        val incoming = versionNumber ?: 0
        val current = prefs.getInt(KEY_VERSION_NUMBER, 0)
        if (PolicyVersionGuard.isStaleIncoming(current, incoming)) {
            return PolicyStoreResult.REJECTED_STALE
        }
        prefs.edit()
            .putString(KEY_STATE, assignmentState)
            .putString(KEY_POLICY_ID, policyId)
            .putString(KEY_VERSION_ID, policyVersionId)
            .putInt(KEY_VERSION_NUMBER, versionNumber ?: 0)
            .putInt(KEY_SCHEMA, schemaVersion ?: 0)
            .putString(KEY_HASH, contentHash)
            .putString(KEY_ETAG, etag)
            .putString(KEY_DOCUMENT, document?.toString())
            .putLong(KEY_RECEIVED, System.currentTimeMillis())
            .putLong(KEY_APPLIED, if (document != null) System.currentTimeMillis() else prefs.getLong(KEY_APPLIED, 0L))
            .apply()
        return PolicyStoreResult.STORED
    }

    fun markUnassignedKeepDocument() {
        prefs.edit().putString(KEY_STATE, "unassigned").apply()
    }

    companion object {
        private const val KEY_STATE = "assignment_state"
        private const val KEY_POLICY_ID = "policy_id"
        private const val KEY_VERSION_ID = "policy_version_id"
        private const val KEY_VERSION_NUMBER = "version_number"
        private const val KEY_SCHEMA = "schema_version"
        private const val KEY_HASH = "content_hash"
        private const val KEY_ETAG = "etag"
        private const val KEY_DOCUMENT = "document_json"
        private const val KEY_RECEIVED = "received_at"
        private const val KEY_APPLIED = "applied_at"
    }
}
