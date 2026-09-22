package com.zreta.devicecontrol.logging

object LogSanitizer {
    fun sanitize(message: String): String {
        var out = message
        listOf(
            "enrollment_secret",
            "access_token",
            "refresh_token",
            "client_assertion",
            "Authorization",
            "Bearer ",
            "BEGIN PRIVATE",
            "latitude",
            "longitude",
        ).forEach { needle ->
            if (out.contains(needle, ignoreCase = true)) {
                out = "redacted diagnostic"
            }
        }
        return out
    }
}
