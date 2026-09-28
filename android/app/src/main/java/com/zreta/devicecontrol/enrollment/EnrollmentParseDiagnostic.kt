package com.zreta.devicecontrol.enrollment

/**
 * Temporary on-device diagnostic for enrollment parse failures.
 * Must never include the pasted JSON, enrollment secret, tokens, or keys.
 */
object EnrollmentParseDiagnostic {
    fun format(raw: String, error: Throwable): String {
        val name = error.javaClass.simpleName.ifBlank { "Exception" }
        val detail = sanitizeMessage(error.message.orEmpty(), raw)
        val normalizedLength = runCatching { EnrollmentPayload.normalizeRaw(raw).length }.getOrDefault(-1)
        return "Invalid enrollment QR/JSON. $name; $detail; rawLen=${raw.length}; normLen=$normalizedLength"
    }

    /**
     * Keep short parser reasons. Drop any message that could carry the payload or secret.
     */
    internal fun sanitizeMessage(message: String, raw: String): String {
        if (message.isBlank()) return "no-message"
        if (embedsPayload(message, raw)) return "message-redacted"
        val stripped = message
            .replace(Regex("\"[^\"]*\""), "\"\"")
            .replace(Regex("[A-Za-z0-9_\\-]{20,}"), "…")
        if (embedsPayload(stripped, raw)) return "message-redacted"
        if (stripped.length > 120) return "message-redacted"
        return stripped
    }

    private fun embedsPayload(message: String, raw: String): Boolean {
        if (message.contains('{') || message.contains('}') || message.contains("enrollment_secret", ignoreCase = true)) {
            return true
        }
        val trimmed = raw.trim()
        if (trimmed.length >= 8 && message.contains(trimmed)) return true
        // Any long slice of the pasted input is treated as secret-bearing.
        if (trimmed.length >= 12) {
            val window = 12
            var index = 0
            while (index + window <= trimmed.length) {
                if (message.contains(trimmed.substring(index, index + window))) return true
                index += 4
            }
        }
        return false
    }
}
