package com.zreta.devicecontrol.api

import com.zreta.devicecontrol.crypto.DeviceKeystore
import com.zreta.devicecontrol.crypto.Es256Jwt
import com.zreta.devicecontrol.dpc.ManagementState
import com.zreta.devicecontrol.enrollment.EnrollmentPayload
import com.zreta.devicecontrol.logging.SafeLog
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

class DeviceApiClient(
    private val client: OkHttpClient = OkHttpClient.Builder()
        .callTimeout(30, TimeUnit.SECONDS)
        .build(),
) {
    fun enroll(
        payload: EnrollmentPayload,
        disclosureAccepted: Boolean,
        managementState: ManagementState,
        manufacturer: String,
        model: String,
        androidVersion: String,
        dpcVersion: String,
        displayName: String,
    ): JSONObject {
        require(disclosureAccepted) { "Disclosure must be accepted" }
        val publicKey = DeviceKeystore.publicKeyPem()
        val body = JSONObject()
            .put("enrollment_session_id", payload.enrollmentSessionId)
            .put("enrollment_secret", payload.enrollmentSecret)
            .put("disclosure_accepted", true)
            .put("public_key_id", DeviceKeystore.keyId())
            .put("public_key", publicKey)
            .put("management_mode", managementModeValue(managementState))
            .put("manufacturer", manufacturer)
            .put("model", model)
            .put("android_version", androidVersion)
            .put("dpc_version", dpcVersion)
            .put("display_name", displayName)
        SafeLog.i("POST /api/v1/device/enroll")
        return postJson(payload.apiBase, "/api/v1/device/enroll", body, bearer = null)
    }

    fun token(apiBase: String, deviceId: String, publicKeyId: String): JSONObject {
        val now = System.currentTimeMillis() / 1000
        val claims = JSONObject()
            .put("iss", deviceId)
            .put("sub", deviceId)
            .put("kid", publicKeyId)
            .put("aud", "zreta-device")
            .put("iat", now)
            .put("exp", now + 90)
            .put("jti", UUID.randomUUID().toString().replace("-", ""))
        val assertion = Es256Jwt.create(claims, mapOf("kid" to publicKeyId))
        val body = JSONObject()
            .put("device_id", deviceId)
            .put("public_key_id", publicKeyId)
            .put("client_assertion", assertion)
        SafeLog.i("POST /api/v1/device/token")
        return postJson(apiBase, "/api/v1/device/token", body, bearer = null)
    }

    fun heartbeat(
        apiBase: String,
        accessToken: String,
        appVersion: String,
        androidVersion: String,
        manufacturer: String,
        model: String,
        managementActive: Boolean,
        managementMode: String,
        connectivity: String,
        batteryLevel: Int?,
        dpcVersion: String,
        dnsFilterState: String? = null,
        dnsFilterError: String? = null,
    ): JSONObject {
        val body = JSONObject()
            .put("app_version", appVersion)
            .put("android_version", androidVersion)
            .put("manufacturer", manufacturer)
            .put("model", model)
            .put("management_active", managementActive)
            .put("management_mode", managementMode)
            .put("connectivity", connectivity)
            .put("dpc_version", dpcVersion)
        if (batteryLevel != null) {
            body.put("battery_level", batteryLevel)
        }
        if (!dnsFilterState.isNullOrBlank()) {
            body.put("dns_filter_state", dnsFilterState)
        }
        if (!dnsFilterError.isNullOrBlank()) {
            body.put("dns_filter_error", dnsFilterError)
        }
        SafeLog.i("POST /api/v1/device/heartbeat")
        return postJson(apiBase, "/api/v1/device/heartbeat", body, bearer = accessToken)
    }

    fun uploadLocations(apiBase: String, accessToken: String, body: JSONObject): JSONObject {
        SafeLog.i("POST /api/v1/device/location")
        return postJson(apiBase, "/api/v1/device/location", body, bearer = accessToken)
    }

    fun me(apiBase: String, accessToken: String): JSONObject {
        val request = Request.Builder()
            .url(join(apiBase, "/api/v1/device/me"))
            .header("Authorization", "Bearer $accessToken")
            .get()
            .build()
        return execute(request)
    }

    data class PolicyFetch(
        val notModified: Boolean,
        val body: JSONObject?,
        val etag: String?,
    )

    fun getPolicy(apiBase: String, accessToken: String, ifNoneMatch: String?): PolicyFetch {
        SafeLog.i("GET /api/v1/device/policy")
        val builder = Request.Builder()
            .url(join(apiBase, "/api/v1/device/policy"))
            .header("Authorization", "Bearer $accessToken")
            .get()
        if (!ifNoneMatch.isNullOrBlank()) {
            builder.header("If-None-Match", ifNoneMatch)
        }
        client.newCall(builder.build()).execute().use { response ->
            val text = response.body?.string().orEmpty()
            val etag = response.header("ETag")
            if (response.code == 304) {
                return PolicyFetch(notModified = true, body = null, etag = etag ?: ifNoneMatch)
            }
            if (!response.isSuccessful) {
                SafeLog.w("HTTP ${response.code}")
                throw ApiException(response.code, text)
            }
            val body = if (text.isBlank()) JSONObject() else JSONObject(text)
            return PolicyFetch(notModified = false, body = body, etag = etag)
        }
    }

    fun ackPolicy(apiBase: String, accessToken: String, body: JSONObject): JSONObject {
        SafeLog.i("POST /api/v1/device/policy/ack")
        return postJson(apiBase, "/api/v1/device/policy/ack", body, bearer = accessToken)
    }

    fun registerFcmToken(apiBase: String, accessToken: String, token: String): JSONObject {
        val body = JSONObject().put("token", token)
        SafeLog.i("POST /api/v1/device/fcm-token")
        return postJson(apiBase, "/api/v1/device/fcm-token", body, bearer = accessToken)
    }

    private fun postJson(apiBase: String, path: String, body: JSONObject, bearer: String?): JSONObject {
        val builder = Request.Builder()
            .url(join(apiBase, path))
            .post(body.toString().toRequestBody(JSON))
        if (bearer != null) {
            builder.header("Authorization", "Bearer $bearer")
        }
        return execute(builder.build())
    }

    private fun execute(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                SafeLog.w("HTTP ${response.code}")
                throw ApiException(response.code, text)
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun join(base: String, path: String): String = base.trimEnd('/') + path

        fun managementModeValue(state: ManagementState): String = when (state) {
            ManagementState.DEVICE_OWNER -> "device_owner"
            ManagementState.PROFILE_OWNER -> "profile_owner"
            else -> "unmanaged"
        }
    }
}

class ApiException(val code: Int, val body: String) : RuntimeException("HTTP $code")
