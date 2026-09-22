package com.zreta.devicecontrol.dpc

enum class ManagementState {
    DEVICE_OWNER,
    PROFILE_OWNER,
    DEVICE_ADMIN_ONLY,
    UNMANAGED,
}

object ManagementStateDetector {
    fun detect(context: android.content.Context): ManagementState {
        return when {
            ZretaDeviceAdminReceiver.isDeviceOwner(context) -> ManagementState.DEVICE_OWNER
            ZretaDeviceAdminReceiver.isProfileOwner(context) -> ManagementState.PROFILE_OWNER
            ZretaDeviceAdminReceiver.isDeviceAdmin(context) -> ManagementState.DEVICE_ADMIN_ONLY
            else -> ManagementState.UNMANAGED
        }
    }

    fun userMessage(state: ManagementState): String = when (state) {
        ManagementState.DEVICE_OWNER ->
            "Device Owner is active. This device is managed through Android's supported Device Owner model."
        ManagementState.PROFILE_OWNER ->
            "Profile Owner is active. This is not full-device Device Owner management."
        ManagementState.DEVICE_ADMIN_ONLY ->
            "Legacy device admin is active, but this app is not Device Owner."
        ManagementState.UNMANAGED ->
            "Installed but unmanaged. An ordinary installation on an already-configured phone does not make the phone Device Owner."
    }
}
