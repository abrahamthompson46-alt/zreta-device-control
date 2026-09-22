package com.zreta.devicecontrol.dpc

import android.app.admin.DeviceAdminReceiver
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import com.zreta.devicecontrol.logging.SafeLog
import com.zreta.devicecontrol.ui.MainActivity

class ZretaDeviceAdminReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        SafeLog.i("DPC enabled (visible device admin).")
    }

    override fun onDisabled(context: Context, intent: Intent) {
        SafeLog.i("DPC disabled.")
    }

    override fun onProfileProvisioningComplete(context: Context, intent: Intent) {
        SafeLog.i("Provisioning complete; launching status UI.")
        val launch = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            putExtra(EXTRA_ADMIN_EXTRAS, intent.getBundleExtra(DevicePolicyManager.EXTRA_PROVISIONING_ADMIN_EXTRAS_BUNDLE))
        }
        context.startActivity(launch)
    }

    companion object {
        const val EXTRA_ADMIN_EXTRAS = "admin_extras"

        fun component(context: Context): ComponentName =
            ComponentName(context, ZretaDeviceAdminReceiver::class.java)

        fun isDeviceOwner(context: Context): Boolean {
            val dpm = context.getSystemService(DevicePolicyManager::class.java)
            return dpm.isDeviceOwnerApp(context.packageName)
        }

        fun isProfileOwner(context: Context): Boolean {
            val dpm = context.getSystemService(DevicePolicyManager::class.java)
            return dpm.isProfileOwnerApp(context.packageName)
        }

        fun isDeviceAdmin(context: Context): Boolean {
            val dpm = context.getSystemService(DevicePolicyManager::class.java)
            return dpm.isAdminActive(component(context))
        }
    }
}
