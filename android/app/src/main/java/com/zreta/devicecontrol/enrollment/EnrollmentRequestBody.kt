package com.zreta.devicecontrol.enrollment

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

@Serializable
data class EnrollmentRequestBody(
    @SerialName("enrollment_session_id") val enrollmentSessionId: String,
    @SerialName("enrollment_secret") val enrollmentSecret: String,
    @SerialName("disclosure_accepted") val disclosureAccepted: Boolean,
    @SerialName("public_key_id") val publicKeyId: String,
    @SerialName("public_key") val publicKey: String,
    @SerialName("management_mode") val managementMode: String,
    @SerialName("manufacturer") val manufacturer: String,
    @SerialName("model") val model: String,
    @SerialName("android_version") val androidVersion: String,
    @SerialName("dpc_version") val dpcVersion: String,
    @SerialName("display_name") val displayName: String,
) {
    init {
        require(disclosureAccepted)
        require(!publicKey.contains("PRIVATE", ignoreCase = true))
        require(publicKey.contains("BEGIN PUBLIC KEY"))
    }

    fun toJson(): String = Json.encodeToString(this)
}

@Serializable
data class HeartbeatRequestBody(
    @SerialName("app_version") val appVersion: String,
    @SerialName("android_version") val androidVersion: String,
    @SerialName("manufacturer") val manufacturer: String,
    @SerialName("model") val model: String,
    @SerialName("management_active") val managementActive: Boolean,
    @SerialName("management_mode") val managementMode: String,
    @SerialName("connectivity") val connectivity: String,
    @SerialName("dpc_version") val dpcVersion: String,
    @SerialName("battery_level") val batteryLevel: Int? = null,
) {
    fun toJson(): String = Json.encodeToString(this)
}
