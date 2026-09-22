package com.zreta.devicecontrol.policy

import com.zreta.devicecontrol.policy.enforcement.DomainBlocklist
import com.zreta.devicecontrol.policy.enforcement.PackageNameRules

/**
 * Schema v1 validation for cached policy documents (Map form for JVM unit tests).
 * Unknown top-level keys and unknown schema versions fail closed.
 * Phase 4.7–4.8: applications/device/calls/internet/screen_time/location may include
 * supported enforcement fields; empty section objects remain valid.
 */
object PolicyDocumentValidator {
    val REQUIRED = setOf(
        "schema_version",
        "internet",
        "calls",
        "applications",
        "screen_time",
        "device",
        "location",
    )

    private val APPLICATIONS_KEYS = setOf(
        "suspend_packages",
        "hide_packages",
        "uninstall_blocked_packages",
    )
    private val DEVICE_KEYS = setOf(
        "camera_disabled",
        "screen_capture_disabled",
    )
    private val CALLS_KEYS = setOf(
        "block_outgoing_calls",
        "block_sms",
    )
    private val INTERNET_KEYS = setOf(
        "disallow_config_wifi",
        "disallow_config_mobile_networks",
        "disallow_config_tethering",
        "disallow_config_vpn",
        "traffic",
    )
    private val TRAFFIC_KEYS = setOf(
        "enabled",
        "engine",
        "blocked_domains",
    )
    private val SCREEN_TIME_KEYS = setOf(
        "bedtime_start",
        "bedtime_end",
        "bedtime_block_outgoing_calls",
        "bedtime_suspend_packages",
    )
    private val LOCATION_KEYS = setOf(
        "collection_desired",
    )
    private val HHMM = Regex("^([01]\\d|2[0-3]):([0-5]\\d)$")

    fun validateMapOrNull(document: Map<*, *>?): Map<String, Any?>? {
        if (document == null) return null
        val keys = document.keys.map { it.toString() }.toSet()
        if (keys != REQUIRED) return null
        val schema = document["schema_version"]
        if (schema !is Number || schema.toInt() != 1) return null
        for (section in REQUIRED - setOf("schema_version")) {
            val value = document[section]
            if (value !is Map<*, *>) return null
        }
        if (!validateApplications(document["applications"] as Map<*, *>)) return null
        if (!validateDevice(document["device"] as Map<*, *>)) return null
        if (!validateBoolSection(document["calls"] as Map<*, *>, CALLS_KEYS)) return null
        if (!validateInternet(document["internet"] as Map<*, *>)) return null
        if (!validateScreenTime(document["screen_time"] as Map<*, *>)) return null
        if (!validateBoolSection(document["location"] as Map<*, *>, LOCATION_KEYS)) return null
        @Suppress("UNCHECKED_CAST")
        return document as Map<String, Any?>
    }

    fun validateJsonObjectOrNull(document: org.json.JSONObject): org.json.JSONObject? {
        val map = linkedMapOf<String, Any?>()
        val iterator = document.keys()
        while (iterator.hasNext()) {
            val key = iterator.next()
            val value = document.get(key)
            map[key] = when (value) {
                is org.json.JSONObject -> jsonObjectToMap(value)
                is org.json.JSONArray -> jsonArrayToList(value)
                else -> value
            }
        }
        return if (validateMapOrNull(map) != null) document else null
    }

    private fun validateApplications(section: Map<*, *>): Boolean {
        for (key in section.keys.map { it.toString() }) {
            if (key !in APPLICATIONS_KEYS) return false
        }
        for (field in APPLICATIONS_KEYS) {
            if (!section.containsKey(field)) continue
            val value = section[field]
            if (value !is List<*>) return false
            for (item in value) {
                if (item !is String) return false
                if (!PackageNameRules.isValid(item.trim())) return false
            }
        }
        return true
    }

    private fun validateDevice(section: Map<*, *>): Boolean =
        validateBoolSection(section, DEVICE_KEYS)

    private fun validateInternet(section: Map<*, *>): Boolean {
        for (key in section.keys.map { it.toString() }) {
            if (key !in INTERNET_KEYS) return false
        }
        for (field in INTERNET_KEYS) {
            if (field == "traffic") continue
            if (!section.containsKey(field)) continue
            if (section[field] !is Boolean) return false
        }
        if (!section.containsKey("traffic")) return true
        val traffic = section["traffic"]
        if (traffic !is Map<*, *>) return false
        return validateTraffic(traffic)
    }

    private fun validateTraffic(section: Map<*, *>): Boolean {
        for (key in section.keys.map { it.toString() }) {
            if (key !in TRAFFIC_KEYS) return false
        }
        if (section.containsKey("enabled") && section["enabled"] !is Boolean) return false
        if (section.containsKey("engine")) {
            val engine = section["engine"]
            if (engine !is String) return false
            if (engine != DomainBlocklist.ENGINE_LOCAL_DNS_BLOCKLIST) return false
        }
        if (section.containsKey("blocked_domains")) {
            val value = section["blocked_domains"]
            if (value !is List<*>) return false
            if (value.size > DomainBlocklist.MAX_DOMAINS) return false
            val raw = value.map {
                if (it !is String) return false
                it
            }
            if (DomainBlocklist.normalizeList(raw) == null) return false
        }
        return true
    }

    private fun validateBoolSection(section: Map<*, *>, allowed: Set<String>): Boolean {
        for (key in section.keys.map { it.toString() }) {
            if (key !in allowed) return false
        }
        for (field in allowed) {
            if (!section.containsKey(field)) continue
            if (section[field] !is Boolean) return false
        }
        return true
    }

    private fun validateScreenTime(section: Map<*, *>): Boolean {
        for (key in section.keys.map { it.toString() }) {
            if (key !in SCREEN_TIME_KEYS) return false
        }
        val hasStart = section.containsKey("bedtime_start")
        val hasEnd = section.containsKey("bedtime_end")
        if (hasStart != hasEnd) return false
        if (hasStart) {
            val start = section["bedtime_start"]
            val end = section["bedtime_end"]
            if (start !is String || end !is String) return false
            val startText = start.trim()
            val endText = end.trim()
            if (!HHMM.matches(startText) || !HHMM.matches(endText)) return false
            if (startText == endText) return false
        }
        if (section.containsKey("bedtime_block_outgoing_calls")) {
            if (!hasStart) return false
            if (section["bedtime_block_outgoing_calls"] !is Boolean) return false
        }
        if (section.containsKey("bedtime_suspend_packages")) {
            if (!hasStart) return false
            val value = section["bedtime_suspend_packages"]
            if (value !is List<*>) return false
            for (item in value) {
                if (item !is String) return false
                if (!PackageNameRules.isValid(item.trim())) return false
            }
        }
        return true
    }

    private fun jsonObjectToMap(obj: org.json.JSONObject): Map<String, Any?> {
        val nested = linkedMapOf<String, Any?>()
        val nestedKeys = obj.keys()
        while (nestedKeys.hasNext()) {
            val nk = nestedKeys.next()
            val nv = obj.get(nk)
            nested[nk] = when (nv) {
                is org.json.JSONObject -> jsonObjectToMap(nv)
                is org.json.JSONArray -> jsonArrayToList(nv)
                else -> nv
            }
        }
        return nested
    }

    private fun jsonArrayToList(array: org.json.JSONArray): List<Any?> {
        val list = ArrayList<Any?>(array.length())
        for (i in 0 until array.length()) {
            val item = array.get(i)
            list.add(
                when (item) {
                    is org.json.JSONObject -> jsonObjectToMap(item)
                    is org.json.JSONArray -> jsonArrayToList(item)
                    else -> item
                },
            )
        }
        return list
    }
}
