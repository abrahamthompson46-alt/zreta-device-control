package com.zreta.devicecontrol.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PolicyDocumentValidatorTest {
    private fun base(): MutableMap<String, Any?> = mutableMapOf(
        "schema_version" to 1,
        "internet" to emptyMap<String, Any>(),
        "calls" to emptyMap<String, Any>(),
        "applications" to emptyMap<String, Any>(),
        "screen_time" to emptyMap<String, Any>(),
        "device" to emptyMap<String, Any>(),
        "location" to emptyMap<String, Any>(),
    )

    @Test
    fun acceptsSchemaV1Empty() {
        assertNotNull(PolicyDocumentValidator.validateMapOrNull(base()))
    }

    @Test
    fun acceptsApplicationAndDeviceFields() {
        val doc = base()
        doc["applications"] = mapOf(
            "suspend_packages" to listOf("com.example.game"),
            "hide_packages" to listOf("com.example.hidden"),
            "uninstall_blocked_packages" to listOf("com.example.keep"),
        )
        doc["device"] = mapOf(
            "camera_disabled" to true,
            "screen_capture_disabled" to false,
        )
        assertNotNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsUnknownApplicationKey() {
        val doc = base()
        doc["applications"] = mapOf("mode" to "blocklist")
        assertNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsUnknownDeviceKey() {
        val doc = base()
        doc["device"] = mapOf("wipe" to true)
        assertNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun acceptsCallsInternetScreenTimeLocationFields() {
        val doc = base()
        doc["calls"] = mapOf("block_outgoing_calls" to true, "block_sms" to false)
        doc["internet"] = mapOf(
            "disallow_config_wifi" to true,
            "disallow_config_mobile_networks" to false,
            "disallow_config_tethering" to true,
            "disallow_config_vpn" to false,
        )
        doc["screen_time"] = mapOf(
            "bedtime_start" to "21:00",
            "bedtime_end" to "07:00",
            "bedtime_block_outgoing_calls" to true,
            "bedtime_suspend_packages" to listOf("com.example.game"),
        )
        doc["location"] = mapOf("collection_desired" to true)
        assertNotNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsUnknownInternetKey() {
        val doc = base()
        doc["internet"] = mapOf("mode" to "block")
        assertNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsPartialBedtimeWindow() {
        val doc = base()
        doc["screen_time"] = mapOf("bedtime_start" to "21:00")
        assertNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsEqualBedtimeStartAndEnd() {
        val doc = base()
        doc["screen_time"] = mapOf("bedtime_start" to "22:00", "bedtime_end" to "22:00")
        assertNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun acceptsInternetTrafficObject() {
        val doc = base()
        doc["internet"] = mapOf(
            "disallow_config_wifi" to true,
            "traffic" to mapOf(
                "enabled" to true,
                "engine" to "local_dns_blocklist",
                "blocked_domains" to listOf("Ads.Example.COM.", "tracker.net"),
            ),
        )
        assertNotNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsTrafficAlwaysOnAndBadEngine() {
        val alwaysOn = base()
        alwaysOn["internet"] = mapOf(
            "traffic" to mapOf(
                "enabled" to true,
                "engine" to "local_dns_blocklist",
                "always_on" to false,
            ),
        )
        assertNull(PolicyDocumentValidator.validateMapOrNull(alwaysOn))
        val badEngine = base()
        badEngine["internet"] = mapOf(
            "traffic" to mapOf("enabled" to true, "engine" to "other", "blocked_domains" to emptyList<String>()),
        )
        assertNull(PolicyDocumentValidator.validateMapOrNull(badEngine))
    }

    @Test
    fun rejectsInvalidPackageName() {
        val doc = base()
        doc["applications"] = mapOf("suspend_packages" to listOf("not a package"))
        assertNull(PolicyDocumentValidator.validateMapOrNull(doc))
    }

    @Test
    fun rejectsUnknownKeyAndWrongSchema() {
        val unknown = base()
        unknown["extra"] = emptyMap<String, Any>()
        assertNull(PolicyDocumentValidator.validateMapOrNull(unknown))
        val badSchema = base()
        badSchema["schema_version"] = 2
        assertNull(PolicyDocumentValidator.validateMapOrNull(badSchema))
    }
}

class PolicyPullDecisionTest {
    @Test
    fun validStoreSendsAppliedAck() {
        val outcome = PolicyPullDecision.afterStoreAttempt(stored = true, versionId = "vid")
        assertTrue(PolicyPullDecision.shouldAckApplied(outcome))
        assertTrue(outcome.stored)
        assertFalse(outcome.preserveLkg)
    }

    @Test
    fun malformedStoreDoesNotAck() {
        val outcome = PolicyPullDecision.afterStoreAttempt(stored = false, versionId = "vid")
        assertFalse(PolicyPullDecision.shouldAckApplied(outcome))
        assertTrue(outcome.preserveLkg)
    }

    @Test
    fun schemaInvalidClassifiedAndNoAck() {
        val bad = org.json.JSONObject(
            """{"schema_version":2,"internet":{},"calls":{},"applications":{},"screen_time":{},"device":{},"location":{}}""",
        )
        assertTrue(PolicyDownloadClassifier.isSchemaInvalid(bad))
        val outcome = PolicyPullDecision.afterStoreAttempt(stored = false, versionId = "vid")
        assertFalse(outcome.sendAppliedAck)
    }

    @Test
    fun http304PreservesLkgWithoutAck() {
        val outcome = PolicyPullDecision.fromHttp304()
        assertTrue(outcome.preserveLkg)
        assertTrue(outcome.skipBecauseNotModified)
        assertFalse(outcome.sendAppliedAck)
    }

    @Test
    fun http304ReenforceOnlyWhenCachedPolicyIsTimeDependent() {
        val bedtime = org.json.JSONObject()
            .put("schema_version", 1)
            .put("internet", org.json.JSONObject())
            .put("calls", org.json.JSONObject())
            .put("applications", org.json.JSONObject())
            .put(
                "screen_time",
                org.json.JSONObject()
                    .put("bedtime_start", "22:00")
                    .put("bedtime_end", "06:00"),
            )
            .put("device", org.json.JSONObject())
            .put("location", org.json.JSONObject())
        assertTrue(PolicyPullDecision.shouldReenforceCachedOnHttp304(bedtime))

        val cameraOnly = org.json.JSONObject()
            .put("schema_version", 1)
            .put("internet", org.json.JSONObject())
            .put("calls", org.json.JSONObject())
            .put("applications", org.json.JSONObject())
            .put("screen_time", org.json.JSONObject())
            .put("device", org.json.JSONObject().put("camera_disabled", true))
            .put("location", org.json.JSONObject())
        assertFalse(PolicyPullDecision.shouldReenforceCachedOnHttp304(cameraOnly))
        assertFalse(PolicyPullDecision.shouldReenforceCachedOnHttp304(null))
    }

    @Test
    fun unassignedKeepsLkgWithoutAck() {
        val outcome = PolicyPullDecision.fromUnassignedOrEmptyDocument()
        assertTrue(outcome.preserveLkg)
        assertTrue(outcome.unassignedKeepLkg)
        assertFalse(outcome.sendAppliedAck)
    }

    @Test
    fun storedWithoutVersionIdDoesNotAck() {
        val outcome = PolicyPullDecision.afterStoreAttempt(stored = true, versionId = null)
        assertFalse(outcome.sendAppliedAck)
    }
}
