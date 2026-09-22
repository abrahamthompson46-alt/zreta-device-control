package com.zreta.devicecontrol.policy.enforcement

import org.json.JSONArray
import org.json.JSONObject

/**
 * Parses supported Phase 4.7–4.8 / 5.1A controls from an already schema-validated document.
 */
object PolicyControlsParser {
    fun fromValidatedMap(document: Map<String, Any?>): NormalizedPolicyControls {
        val applications = document["applications"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val device = document["device"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val calls = document["calls"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val internet = document["internet"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val screenTime = document["screen_time"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val location = document["location"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val start = parseHhMmMinutes(screenTime["bedtime_start"])
        val end = parseHhMmMinutes(screenTime["bedtime_end"])
        return NormalizedPolicyControls(
            suspendPackages = readPackageList(applications["suspend_packages"]),
            hidePackages = readPackageList(applications["hide_packages"]),
            uninstallBlockedPackages = readPackageList(applications["uninstall_blocked_packages"]),
            cameraDisabled = readOptionalBoolean(device["camera_disabled"]),
            screenCaptureDisabled = readOptionalBoolean(device["screen_capture_disabled"]),
            blockOutgoingCalls = readOptionalBoolean(calls["block_outgoing_calls"]),
            blockSms = readOptionalBoolean(calls["block_sms"]),
            disallowConfigWifi = readOptionalBoolean(internet["disallow_config_wifi"]),
            disallowConfigMobileNetworks = readOptionalBoolean(internet["disallow_config_mobile_networks"]),
            disallowConfigTethering = readOptionalBoolean(internet["disallow_config_tethering"]),
            disallowConfigVpn = readOptionalBoolean(internet["disallow_config_vpn"]),
            bedtimeStartMinutes = start,
            bedtimeEndMinutes = end,
            bedtimeBlockOutgoingCalls = readOptionalBoolean(screenTime["bedtime_block_outgoing_calls"]) == true,
            bedtimeSuspendPackages = readPackageList(screenTime["bedtime_suspend_packages"]),
            locationCollectionDesired = readOptionalBoolean(location["collection_desired"]),
            traffic = parseTrafficMap(internet["traffic"]),
        )
    }

    fun fromValidatedJson(document: JSONObject): NormalizedPolicyControls {
        val applications = document.optJSONObject("applications") ?: JSONObject()
        val device = document.optJSONObject("device") ?: JSONObject()
        val calls = document.optJSONObject("calls") ?: JSONObject()
        val internet = document.optJSONObject("internet") ?: JSONObject()
        val screenTime = document.optJSONObject("screen_time") ?: JSONObject()
        val location = document.optJSONObject("location") ?: JSONObject()
        val start = parseHhMmMinutes(if (screenTime.has("bedtime_start")) screenTime.optString("bedtime_start") else null)
        val end = parseHhMmMinutes(if (screenTime.has("bedtime_end")) screenTime.optString("bedtime_end") else null)
        return NormalizedPolicyControls(
            suspendPackages = readJsonPackageList(applications.opt("suspend_packages")),
            hidePackages = readJsonPackageList(applications.opt("hide_packages")),
            uninstallBlockedPackages = readJsonPackageList(applications.opt("uninstall_blocked_packages")),
            cameraDisabled = readJsonOptionalBoolean(device, "camera_disabled"),
            screenCaptureDisabled = readJsonOptionalBoolean(device, "screen_capture_disabled"),
            blockOutgoingCalls = readJsonOptionalBoolean(calls, "block_outgoing_calls"),
            blockSms = readJsonOptionalBoolean(calls, "block_sms"),
            disallowConfigWifi = readJsonOptionalBoolean(internet, "disallow_config_wifi"),
            disallowConfigMobileNetworks = readJsonOptionalBoolean(internet, "disallow_config_mobile_networks"),
            disallowConfigTethering = readJsonOptionalBoolean(internet, "disallow_config_tethering"),
            disallowConfigVpn = readJsonOptionalBoolean(internet, "disallow_config_vpn"),
            bedtimeStartMinutes = start,
            bedtimeEndMinutes = end,
            bedtimeBlockOutgoingCalls = readJsonOptionalBoolean(screenTime, "bedtime_block_outgoing_calls") == true,
            bedtimeSuspendPackages = readJsonPackageList(screenTime.opt("bedtime_suspend_packages")),
            locationCollectionDesired = readJsonOptionalBoolean(location, "collection_desired"),
            traffic = parseTrafficJson(internet.optJSONObject("traffic")),
        )
    }

    fun parseHhMmMinutes(value: Any?): Int? {
        if (value !is String) return null
        val text = value.trim()
        if (!Regex("^([01]\\d|2[0-3]):([0-5]\\d)$").matches(text)) return null
        val parts = text.split(":")
        return parts[0].toInt() * 60 + parts[1].toInt()
    }

    private fun parseTrafficMap(value: Any?): NormalizedTrafficControls? {
        if (value == null) return null
        if (value !is Map<*, *>) return null
        if (value.isEmpty()) return null
        val enabled = readOptionalBoolean(value["enabled"]) ?: false
        val engine = (value["engine"] as? String)?.trim()
            ?: DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST
        if (engine != DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST) return null
        val rawDomains = value["blocked_domains"]
        val domainList: List<String> = when (rawDomains) {
            null -> emptyList()
            is List<*> -> rawDomains.mapNotNull { it as? String }
            else -> return null
        }
        val normalized = DomainBlocklist.normalizeList(domainList) ?: return null
        return NormalizedTrafficControls(
            enabled = enabled,
            engine = engine,
            blockedDomains = normalized.domains,
            ruleHash = normalized.ruleHash,
        )
    }

    private fun parseTrafficJson(obj: JSONObject?): NormalizedTrafficControls? {
        if (obj == null || obj.length() == 0) return null
        val enabled = if (obj.has("enabled") && !obj.isNull("enabled")) obj.optBoolean("enabled") else false
        val engine = if (obj.has("engine") && !obj.isNull("engine")) {
            obj.optString("engine")
        } else {
            DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST
        }
        if (engine != DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST) return null
        val raw = mutableListOf<String>()
        val arr = obj.optJSONArray("blocked_domains")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                raw.add(arr.optString(i, ""))
            }
        }
        val normalized = DomainBlocklist.normalizeList(raw) ?: return null
        return NormalizedTrafficControls(
            enabled = enabled,
            engine = engine,
            blockedDomains = normalized.domains,
            ruleHash = normalized.ruleHash,
        )
    }

    private fun readOptionalBoolean(value: Any?): Boolean? = when (value) {
        null -> null
        is Boolean -> value
        else -> null
    }

    private fun readJsonOptionalBoolean(obj: JSONObject, key: String): Boolean? {
        if (!obj.has(key) || obj.isNull(key)) return null
        return obj.optBoolean(key)
    }

    private fun readPackageList(value: Any?): List<String> {
        if (value == null) return emptyList()
        if (value !is List<*>) return emptyList()
        val out = linkedSetOf<String>()
        for (item in value) {
            if (item is String && PackageNameRules.isValid(item)) {
                out.add(item.trim())
            }
        }
        return out.toList()
    }

    private fun readJsonPackageList(value: Any?): List<String> {
        if (value == null || value == JSONObject.NULL) return emptyList()
        if (value !is JSONArray) return emptyList()
        val out = linkedSetOf<String>()
        for (i in 0 until value.length()) {
            val item = value.optString(i, "").trim()
            if (PackageNameRules.isValid(item)) out.add(item)
        }
        return out.toList()
    }
}
