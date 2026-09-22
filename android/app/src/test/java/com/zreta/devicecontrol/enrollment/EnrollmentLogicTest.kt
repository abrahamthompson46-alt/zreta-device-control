package com.zreta.devicecontrol.enrollment

import com.zreta.devicecontrol.enrollment.EnrollmentPayload
import com.zreta.devicecontrol.enrollment.EnrollmentRequestBody
import com.zreta.devicecontrol.enrollment.HeartbeatRequestBody
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class EnrollmentPayloadTest {
    private val sample = """
        {"v":1,"api_base":"http://10.0.2.2:8000","enrollment_session_id":"11111111-1111-1111-1111-111111111111","enrollment_secret":"one-time"}
    """.trimIndent()

    @Test
    fun parseValidPayload() {
        val payload = EnrollmentPayload.parse(sample)
        assertEquals("http://10.0.2.2:8000", payload.apiBase)
        assertEquals("one-time", payload.enrollmentSecret)
    }

    @Test(expected = Exception::class)
    fun rejectMissingFields() {
        EnrollmentPayload.parse("""{"v":1,"api_base":"http://x"}""")
    }
}

class EnrollmentRequestBodyTest {
    @Test
    fun jsonContainsPublicKeyNotPrivate() {
        val body = EnrollmentRequestBody(
            enrollmentSessionId = "sid",
            enrollmentSecret = "secret",
            disclosureAccepted = true,
            publicKeyId = "zreta_device_identity",
            publicKey = "-----BEGIN PUBLIC KEY-----\nMFkw\n-----END PUBLIC KEY-----",
            managementMode = "device_owner",
            manufacturer = "Google",
            model = "sdk",
            androidVersion = "15",
            dpcVersion = "0.2.0",
            displayName = "sdk",
        )
        val json = body.toJson()
        assertTrue(json.contains("BEGIN PUBLIC KEY"))
        assertFalse(json.contains("PRIVATE"))
        assertTrue(json.contains("\"disclosure_accepted\":true"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectPrivateKeyMaterial() {
        EnrollmentRequestBody(
            enrollmentSessionId = "sid",
            enrollmentSecret = "secret",
            disclosureAccepted = true,
            publicKeyId = "k",
            publicKey = "-----BEGIN PRIVATE KEY-----",
            managementMode = "device_owner",
            manufacturer = "x",
            model = "y",
            androidVersion = "1",
            dpcVersion = "0.2.0",
            displayName = "d",
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectWithoutDisclosure() {
        EnrollmentRequestBody(
            enrollmentSessionId = "sid",
            enrollmentSecret = "secret",
            disclosureAccepted = false,
            publicKeyId = "k",
            publicKey = "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----",
            managementMode = "device_owner",
            manufacturer = "x",
            model = "y",
            androidVersion = "1",
            dpcVersion = "0.2.0",
            displayName = "d",
        )
    }
}

class HeartbeatRequestBodyTest {
    @Test
    fun heartbeatOmitsLocation() {
        val json = HeartbeatRequestBody(
            appVersion = "0.2.0",
            androidVersion = "15",
            manufacturer = "Google",
            model = "sdk",
            managementActive = true,
            managementMode = "device_owner",
            connectivity = "online",
            dpcVersion = "0.2.0",
            batteryLevel = 50,
        ).toJson()
        assertFalse(json.contains("lat", ignoreCase = true))
        assertFalse(json.contains("location", ignoreCase = true))
        assertTrue(json.contains("battery_level"))
    }
}

class SafeLogSanitizeTest {
    @Test
    fun redactsSecrets() {
        val sanitized = com.zreta.devicecontrol.logging.LogSanitizer.sanitize("enrollment_secret=abc")
        assertEquals("redacted diagnostic", sanitized)
        val ok = com.zreta.devicecontrol.logging.LogSanitizer.sanitize("heartbeat ok")
        assertEquals("heartbeat ok", ok)
    }
}

class DerToJoseTest {
    @Test
    fun convertsShortDer() {
        // SEQUENCE { INTEGER 1, INTEGER 2 } padded to 4 bytes for the unit test helper length
        val der = byteArrayOf(
            0x30, 0x06,
            0x02, 0x01, 0x01,
            0x02, 0x01, 0x02,
        )
        val jose = com.zreta.devicecontrol.crypto.EcdsaJose.derToJose(der, 4)
        assertEquals(8, jose.size)
        assertEquals(1.toByte(), jose[3])
        assertEquals(2.toByte(), jose[7])
    }
}
