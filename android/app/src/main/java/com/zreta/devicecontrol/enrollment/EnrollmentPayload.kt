package com.zreta.devicecontrol.enrollment

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class EnrollmentPayload(
    val v: Int = 1,
    @SerialName("api_base") val apiBase: String,
    @SerialName("enrollment_session_id") val enrollmentSessionId: String,
    @SerialName("enrollment_secret") val enrollmentSecret: String,
) {
    init {
        require(apiBase.isNotBlank()) { "api_base is required" }
        require(enrollmentSessionId.isNotBlank()) { "enrollment_session_id is required" }
        require(enrollmentSecret.isNotBlank()) { "enrollment_secret is required" }
        require(!apiBase.contains(" ")) { "api_base looks invalid" }
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(raw: String): EnrollmentPayload {
            val payload = json.decodeFromString(serializer(), raw.trim())
            require(payload.v == 1) { "Unsupported enrollment payload version" }
            return payload
        }
    }
}
