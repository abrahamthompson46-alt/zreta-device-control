package com.zreta.devicecontrol.policy.enforcement

/**
 * Packages that must never be suspended/hidden/uninstall-blocked by Zreta.
 */
object CriticalPackages {
    private val PROTECTED_EXACT = setOf(
        "android",
        "com.android.systemui",
        "com.android.settings",
        "com.android.phone",
        "com.android.server.telecom",
        "com.android.providers.settings",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.vpndialogs",
        "com.android.keychain",
        "com.android.shell",
    )

    private val PROTECTED_PREFIXES = listOf(
        "com.android.systemui",
        "com.android.providers.",
    )

    fun isProtected(packageName: String, selfPackageName: String): Boolean {
        val name = packageName.trim()
        if (name.isEmpty()) return true
        if (name == selfPackageName) return true
        if (name in PROTECTED_EXACT) return true
        if (PROTECTED_PREFIXES.any { name.startsWith(it) }) return true
        // Single-segment names are invalid Android packages and treated as unsafe.
        if (!name.contains('.')) return true
        return false
    }
}

object PackageNameRules {
    private val PATTERN = Regex("^(?:[A-Za-z_][A-Za-z0-9_]*)(?:\\.[A-Za-z_][A-Za-z0-9_]*)+$")

    fun isValid(packageName: String): Boolean = PATTERN.matches(packageName.trim())
}
