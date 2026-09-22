package com.zreta.devicecontrol.policy.enforcement

import android.app.admin.DevicePolicyManager
import android.content.Context
import com.zreta.devicecontrol.dpc.ZretaDeviceAdminReceiver

class AndroidDevicePolicyGateway(private val context: Context) : DevicePolicyGateway {
    private val dpm: DevicePolicyManager =
        context.getSystemService(DevicePolicyManager::class.java)
    private val admin = ZretaDeviceAdminReceiver.component(context)

    override fun isDeviceOwner(): Boolean = dpm.isDeviceOwnerApp(context.packageName)

    override fun setPackagesSuspended(packageNames: Array<String>, suspended: Boolean): Array<String> =
        dpm.setPackagesSuspended(admin, packageNames, suspended) ?: emptyArray()

    override fun setApplicationHidden(packageName: String, hidden: Boolean): Boolean =
        dpm.setApplicationHidden(admin, packageName, hidden)

    override fun setUninstallBlocked(packageName: String, uninstallBlocked: Boolean) {
        dpm.setUninstallBlocked(admin, packageName, uninstallBlocked)
    }

    override fun setCameraDisabled(disabled: Boolean) {
        dpm.setCameraDisabled(admin, disabled)
    }

    override fun setScreenCaptureDisabled(disabled: Boolean) {
        dpm.setScreenCaptureDisabled(admin, disabled)
    }

    override fun addUserRestriction(key: String) {
        dpm.addUserRestriction(admin, key)
    }

    override fun clearUserRestriction(key: String) {
        dpm.clearUserRestriction(admin, key)
    }
}
