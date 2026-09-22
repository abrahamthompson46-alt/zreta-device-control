package com.zreta.devicecontrol.policy.enforcement

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

/**
 * Encrypted bookkeeping of Zreta-managed enforcement (separate from LKG policy document).
 * Corrupted snapshots become empty with [ManagedStateLoad.wasCorrupt]=true — never blind-clear DPM.
 */
class EnforcementStateStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "zreta_enforcement_state",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun load(): ManagedStateLoad {
        val raw = prefs.getString(KEY_JSON, null)
        if (raw.isNullOrBlank()) {
            return ManagedStateLoad(ManagedEnforcementState.empty(), wasCorrupt = false)
        }
        return parse(raw)
    }

    fun save(state: ManagedEnforcementState) {
        val ok = prefs.edit().putString(KEY_JSON, serialize(state)).commit()
        if (!ok) {
            throw IllegalStateException("enforcement_state_persist_failed")
        }
    }

    companion object {
        private const val KEY_JSON = "managed_state_json"

        fun serialize(state: ManagedEnforcementState): String {
            val json = JSONObject()
                .put("state_schema", ManagedEnforcementState.STATE_SCHEMA)
                .put("schema_version", state.schemaVersion)
                .put("policy_version_id", state.policyVersionId)
                .put("version_number", state.versionNumber)
                .put("accepted_version_number", state.acceptedVersionNumber)
                .put("content_hash", state.contentHash)
                .put("suspended_packages", JSONArray(state.suspendedPackages.sorted()))
                .put("hidden_packages", JSONArray(state.hiddenPackages.sorted()))
                .put("uninstall_blocked_packages", JSONArray(state.uninstallBlockedPackages.sorted()))
                .put("camera_disabled_managed", state.cameraDisabledManaged)
                .put("camera_disabled_value", state.cameraDisabledValue)
                .put("screen_capture_disabled_managed", state.screenCaptureDisabledManaged)
                .put("screen_capture_disabled_value", state.screenCaptureDisabledValue)
                .put("managed_user_restrictions", JSONArray(state.managedUserRestrictions.sorted()))
                .put("bedtime_suspended_packages", JSONArray(state.bedtimeSuspendedPackages.sorted()))
                .put("traffic_filter_managed", state.trafficFilterManaged)
                .put("traffic_filter_desired_enabled", state.trafficFilterDesiredEnabled)
                .put("traffic_rule_hash", state.trafficRuleHash)
                .put("traffic_service_desired", state.trafficServiceDesired.name)
                .put("traffic_service_observed", state.trafficServiceObserved.name)
                .put("traffic_last_error", state.trafficLastError)
                .put("successfully_enforced", state.successfullyEnforced)
                .put("recovery_required", state.recoveryRequired)
            if (state.locationAdvisoryValue == null) {
                json.put("location_advisory_value", JSONObject.NULL)
            } else {
                json.put("location_advisory_value", state.locationAdvisoryValue)
            }
            return json.toString()
        }

        fun parse(raw: String): ManagedStateLoad {
            return try {
                val json = JSONObject(raw)
                val stateSchema = json.optInt("state_schema", -1)
                if (stateSchema != ManagedEnforcementState.STATE_SCHEMA) {
                    return ManagedStateLoad(
                        ManagedEnforcementState.empty().copy(recoveryRequired = true),
                        wasCorrupt = true,
                    )
                }
                val versionNumber = json.optInt("version_number", 0)
                val accepted = json.optInt("accepted_version_number", versionNumber)
                val advisory = when {
                    !json.has("location_advisory_value") || json.isNull("location_advisory_value") -> null
                    else -> json.optBoolean("location_advisory_value")
                }
                ManagedStateLoad(
                    ManagedEnforcementState(
                        schemaVersion = json.optInt("schema_version", 1),
                        policyVersionId = json.optString("policy_version_id").ifBlank { null },
                        versionNumber = versionNumber,
                        acceptedVersionNumber = maxOf(accepted, versionNumber),
                        contentHash = json.optString("content_hash").ifBlank { null },
                        suspendedPackages = readStringSet(json.optJSONArray("suspended_packages")),
                        hiddenPackages = readStringSet(json.optJSONArray("hidden_packages")),
                        uninstallBlockedPackages = readStringSet(json.optJSONArray("uninstall_blocked_packages")),
                        cameraDisabledManaged = json.optBoolean("camera_disabled_managed", false),
                        cameraDisabledValue = json.optBoolean("camera_disabled_value", false),
                        screenCaptureDisabledManaged = json.optBoolean("screen_capture_disabled_managed", false),
                        screenCaptureDisabledValue = json.optBoolean("screen_capture_disabled_value", false),
                        managedUserRestrictions = readStringSet(json.optJSONArray("managed_user_restrictions")),
                        bedtimeSuspendedPackages = readStringSet(json.optJSONArray("bedtime_suspended_packages")),
                        locationAdvisoryValue = advisory,
                        trafficFilterManaged = json.optBoolean("traffic_filter_managed", false),
                        trafficFilterDesiredEnabled = json.optBoolean("traffic_filter_desired_enabled", false),
                        trafficRuleHash = json.optString("traffic_rule_hash").ifBlank { null },
                        trafficServiceDesired = readServiceState(json.optString("traffic_service_desired")),
                        trafficServiceObserved = readServiceState(json.optString("traffic_service_observed")),
                        trafficLastError = json.optString("traffic_last_error").ifBlank { null },
                        successfullyEnforced = json.optBoolean("successfully_enforced", false),
                        recoveryRequired = json.optBoolean("recovery_required", false),
                    ),
                    wasCorrupt = false,
                )
            } catch (_: Exception) {
                ManagedStateLoad(
                    ManagedEnforcementState.empty().copy(recoveryRequired = true),
                    wasCorrupt = true,
                )
            }
        }

        /** @deprecated use [parse]; kept for tests that expect empty on corrupt */
        fun parseOrEmpty(raw: String): ManagedEnforcementState = parse(raw).state

        private fun readServiceState(raw: String?): DnsFilterServiceState =
            when (raw?.uppercase()) {
                "RUNNING" -> DnsFilterServiceState.RUNNING
                "STARTING" -> DnsFilterServiceState.STARTING
                "FAILED" -> DnsFilterServiceState.FAILED
                else -> DnsFilterServiceState.STOPPED
            }

        private fun readStringSet(array: JSONArray?): Set<String> {
            if (array == null) return emptySet()
            val out = linkedSetOf<String>()
            for (i in 0 until array.length()) {
                val value = array.optString(i, "").trim()
                if (value.isNotEmpty()) out.add(value)
            }
            return out
        }
    }
}

/**
 * In-memory store for JVM tests. Can simulate persist failures.
 */
class InMemoryEnforcementStateStore(
    initial: ManagedEnforcementState = ManagedEnforcementState.empty(),
) {
    var state: ManagedEnforcementState = initial
    var failNextSave: Boolean = false
    /** Fail when saveCount would reach this value (1-based). 0 = disabled. */
    var failOnSaveNumber: Int = 0
    var saveCount: Int = 0
    var wasCorruptOnLastLoad: Boolean = false

    fun load(): ManagedStateLoad {
        return ManagedStateLoad(state, wasCorrupt = wasCorruptOnLastLoad)
    }

    fun save(next: ManagedEnforcementState) {
        saveCount++
        if (failNextSave || (failOnSaveNumber > 0 && saveCount == failOnSaveNumber)) {
            failNextSave = false
            throw IllegalStateException("enforcement_state_persist_failed")
        }
        state = next
    }
}
