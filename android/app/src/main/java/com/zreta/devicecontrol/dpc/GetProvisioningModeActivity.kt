package com.zreta.devicecontrol.dpc

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.Intent
import android.os.Bundle

/**
 * Required for Device Owner provisioning on Android 12+.
 * Chooses fully managed device mode. Does not silently become owner on an already-set-up phone.
 */
class GetProvisioningModeActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val result = Intent()
        result.putExtra(
            DevicePolicyManager.EXTRA_PROVISIONING_MODE,
            DevicePolicyManager.PROVISIONING_MODE_FULLY_MANAGED_DEVICE,
        )
        setResult(RESULT_OK, result)
        finish()
    }
}
