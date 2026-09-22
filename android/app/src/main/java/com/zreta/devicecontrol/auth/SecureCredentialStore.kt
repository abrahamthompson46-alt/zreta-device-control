package com.zreta.devicecontrol.auth

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class SecureCredentialStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "zreta_device_creds",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun saveSession(
        apiBase: String,
        deviceId: String,
        publicKeyId: String,
        accessToken: String,
        expiresAtEpochSeconds: Long,
    ) {
        prefs.edit()
            .putString(KEY_API, apiBase)
            .putString(KEY_DEVICE, deviceId)
            .putString(KEY_KID, publicKeyId)
            .putString(KEY_ACCESS, accessToken)
            .putLong(KEY_EXP, expiresAtEpochSeconds)
            .apply()
    }

    fun clearAccessToken() {
        prefs.edit().remove(KEY_ACCESS).remove(KEY_EXP).apply()
    }

    fun apiBase(): String? = prefs.getString(KEY_API, null)
    fun deviceId(): String? = prefs.getString(KEY_DEVICE, null)
    fun publicKeyId(): String? = prefs.getString(KEY_KID, null)
    fun accessToken(): String? = prefs.getString(KEY_ACCESS, null)
    fun expiresAt(): Long = prefs.getLong(KEY_EXP, 0L)
    fun isEnrolled(): Boolean = !deviceId().isNullOrBlank()

    fun setLocationCollectionEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_LOC_ENABLED, enabled).apply()
    }

    fun locationCollectionEnabled(): Boolean = prefs.getBoolean(KEY_LOC_ENABLED, false)

    fun setLocationDisclosureAccepted(accepted: Boolean) {
        prefs.edit().putBoolean(KEY_LOC_DISCLOSURE, accepted).apply()
    }

    fun locationDisclosureAccepted(): Boolean = prefs.getBoolean(KEY_LOC_DISCLOSURE, false)

    fun setLocationSharingState(state: String) {
        prefs.edit().putString(KEY_LOC_STATE, state).apply()
    }

    fun locationSharingState(): String = prefs.getString(KEY_LOC_STATE, "off") ?: "off"

    companion object {
        private const val KEY_API = "api_base"
        private const val KEY_DEVICE = "device_id"
        private const val KEY_KID = "public_key_id"
        private const val KEY_ACCESS = "access_token"
        private const val KEY_EXP = "expires_at"
        private const val KEY_LOC_ENABLED = "location_collection_enabled"
        private const val KEY_LOC_DISCLOSURE = "location_disclosure_accepted"
        private const val KEY_LOC_STATE = "location_sharing_state"
    }
}
