package com.zreta.devicecontrol.policy.enforcement

/**
 * Narrow DevicePolicyManager facade for testability.
 */
interface DevicePolicyGateway {
    fun isDeviceOwner(): Boolean

    fun setPackagesSuspended(packageNames: Array<String>, suspended: Boolean): Array<String>

    fun setApplicationHidden(packageName: String, hidden: Boolean): Boolean

    fun setUninstallBlocked(packageName: String, uninstallBlocked: Boolean)

    fun setCameraDisabled(disabled: Boolean)

    fun setScreenCaptureDisabled(disabled: Boolean)

    fun addUserRestriction(key: String)

    fun clearUserRestriction(key: String)
}

/**
 * In-memory gateway for JVM unit tests.
 */
class FakeDevicePolicyGateway(
    var deviceOwner: Boolean = true,
) : DevicePolicyGateway {
    val suspended = mutableSetOf<String>()
    val hidden = mutableSetOf<String>()
    val uninstallBlocked = mutableSetOf<String>()
    val userRestrictions = mutableSetOf<String>()
    var cameraDisabledFlag: Boolean = false
    var screenCaptureDisabledFlag: Boolean = false
    var failSuspend: Set<String> = emptySet()
    var throwSuspend: Set<String> = emptySet()
    var failHide: Set<String> = emptySet()
    var throwHide: Set<String> = emptySet()
    var failUninstallBlock: Set<String> = emptySet()
    var throwUninstallBlock: Set<String> = emptySet()
    var failCamera: Boolean = false
    var failScreenCapture: Boolean = false
    var failRestrictions: Set<String> = emptySet()
    var suspendCallCount: Int = 0
    var hideCallCount: Int = 0

    override fun isDeviceOwner(): Boolean = deviceOwner

    override fun setPackagesSuspended(packageNames: Array<String>, suspended: Boolean): Array<String> {
        suspendCallCount++
        val failed = mutableListOf<String>()
        for (pkg in packageNames) {
            if (pkg in throwSuspend) {
                throw SecurityException("suspend denied for $pkg")
            }
            if (pkg in failSuspend) {
                failed.add(pkg)
                continue
            }
            if (suspended) this.suspended.add(pkg) else this.suspended.remove(pkg)
        }
        return failed.toTypedArray()
    }

    override fun setApplicationHidden(packageName: String, hidden: Boolean): Boolean {
        hideCallCount++
        if (packageName in throwHide) {
            throw SecurityException("hide denied for $packageName")
        }
        if (packageName in failHide) return false
        if (hidden) this.hidden.add(packageName) else this.hidden.remove(packageName)
        return true
    }

    override fun setUninstallBlocked(packageName: String, uninstallBlocked: Boolean) {
        if (packageName in throwUninstallBlock || packageName in failUninstallBlock) {
            throw IllegalStateException("uninstall block failed for $packageName")
        }
        if (uninstallBlocked) this.uninstallBlocked.add(packageName) else this.uninstallBlocked.remove(packageName)
    }

    override fun setCameraDisabled(disabled: Boolean) {
        if (failCamera) throw IllegalStateException("camera failed")
        cameraDisabledFlag = disabled
    }

    override fun setScreenCaptureDisabled(disabled: Boolean) {
        if (failScreenCapture) throw IllegalStateException("screen capture failed")
        screenCaptureDisabledFlag = disabled
    }

    override fun addUserRestriction(key: String) {
        if (key in failRestrictions) throw IllegalStateException("restriction add failed for $key")
        userRestrictions.add(key)
    }

    override fun clearUserRestriction(key: String) {
        if (key in failRestrictions) throw IllegalStateException("restriction clear failed for $key")
        userRestrictions.remove(key)
    }
}
