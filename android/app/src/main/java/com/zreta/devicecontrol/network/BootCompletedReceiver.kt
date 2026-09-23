package com.zreta.devicecontrol.network

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.zreta.devicecontrol.auth.SecureCredentialStore

/**
 * After reboot, re-run policy enforcement against LKG via PolicyWorker.
 * Does not start VpnService directly (consent + readiness remain on the enforce path).
 */
class BootCompletedReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val store = SecureCredentialStore(context)
        if (!store.isEnrolled()) return
        VpnConsentCoordinator.enqueuePolicyReenforce(
            context,
            uniqueName = VpnConsentCoordinator.BOOT_WORK_NAME,
        )
    }
}
