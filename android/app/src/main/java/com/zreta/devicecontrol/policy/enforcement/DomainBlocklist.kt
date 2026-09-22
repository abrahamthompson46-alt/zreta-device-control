package com.zreta.devicecontrol.policy.enforcement

import java.security.MessageDigest
import java.util.Locale

/**
 * Domain blocklist normalization, validation, and matching for Phase 5.1 traffic filter.
 *
 * Matching semantics (when VpnService exists in 5.1B):
 * - Query name Q (normalized) is blocked if it equals a blocked domain B, **or**
 *   Q is a subdomain of B (`Q == B` or `Q.endsWith("." + B)`).
 * - No wildcards (`*`), no path/port/scheme, no IP literals.
 */
object DomainBlocklist {
    const val ENGINE_LOCAL_DNS_BLOCKLIST = "local_dns_blocklist"
    const val MAX_DOMAINS = 500
    const val MAX_DOMAIN_LENGTH = 253
    const val MAX_TOTAL_CHARS = 8192

    private val LABEL = Regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    private val IPV4 = Regex("^(?:\\d{1,3}\\.){3}\\d{1,3}$")

    data class NormalizedList(
        val domains: List<String>,
        val ruleHash: String,
        val canonical: String,
    )

    /**
     * Normalize and validate a single domain. Returns null if invalid.
     */
    fun normalizeOne(raw: String?): String? {
        if (raw == null) return null
        var text = raw.trim().lowercase(Locale.ROOT)
        if (text.endsWith(".")) {
            text = text.dropLast(1)
        }
        if (!isValidNormalized(text)) return null
        return text
    }

    fun isValidNormalized(domain: String): Boolean {
        if (domain.isEmpty() || domain.length > MAX_DOMAIN_LENGTH) return false
        if (domain.contains("://") || domain.contains('/') || domain.contains(':') ||
            domain.contains(' ') || domain.contains('*')
        ) {
            return false
        }
        if (IPV4.matches(domain)) return false
        val labels = domain.split('.')
        if (labels.size < 2) return false
        for (label in labels) {
            if (label.isEmpty() || label.length > 63 || !LABEL.matches(label)) return false
        }
        return true
    }

    /**
     * Build a deterministic normalized list + SHA-256 rule hash.
     * Returns null if any entry is invalid or limits are exceeded.
     */
    fun normalizeList(raw: List<String>?): NormalizedList? {
        if (raw == null) return NormalizedList(emptyList(), hashCanonical(""), "")
        if (raw.size > MAX_DOMAINS) return null
        val seen = linkedSetOf<String>()
        var total = 0
        for (item in raw) {
            val domain = normalizeOne(item) ?: return null
            if (!seen.add(domain)) continue
            total += domain.length
            if (total > MAX_TOTAL_CHARS) return null
            if (seen.size > MAX_DOMAINS) return null
        }
        val ordered = seen.sorted()
        val canonical = ordered.joinToString("\n")
        return NormalizedList(ordered, hashCanonical(canonical), canonical)
    }

    /** Exact or parent-domain match. */
    fun isBlocked(queryHost: String?, blockedDomains: List<String>): Boolean {
        val q = normalizeOne(queryHost) ?: return false
        for (b in blockedDomains) {
            if (q == b || q.endsWith(".$b")) return true
        }
        return false
    }

    fun hashCanonical(canonical: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val bytes = digest.digest(canonical.toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { b -> "%02x".format(b) }
    }
}
