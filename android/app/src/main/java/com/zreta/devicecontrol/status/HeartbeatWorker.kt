package com.zreta.devicecontrol.status

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.zreta.devicecontrol.BuildConfig
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.dpc.ManagementState
import com.zreta.devicecontrol.dpc.ManagementStateDetector
import com.zreta.devicecontrol.logging.SafeLog

class HeartbeatWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val store = SecureCredentialStore(applicationContext)
        val apiBase = store.apiBase()
        val deviceId = store.deviceId()
        val kid = store.publicKeyId()
        if (apiBase.isNullOrBlank() || deviceId.isNullOrBlank() || kid.isNullOrBlank()) {
            return Result.success()
        }
        val client = DeviceApiClient()
        return try {
            var token = store.accessToken()
            val soon = System.currentTimeMillis() / 1000 + 60
            if (token.isNullOrBlank() || store.expiresAt() <= soon) {
                val refreshed = client.token(apiBase, deviceId, kid)
                token = refreshed.getString("access_token")
                val ttl = refreshed.optInt("expires_in", 900)
                store.saveSession(apiBase, deviceId, kid, token, System.currentTimeMillis() / 1000 + ttl)
            }
            val state = ManagementStateDetector.detect(applicationContext)
            val heartbeat = client.heartbeat(
                apiBase = apiBase,
                accessToken = token!!,
                appVersion = BuildConfig.VERSION_NAME,
                androidVersion = Build.VERSION.RELEASE,
                manufacturer = Build.MANUFACTURER,
                model = Build.MODEL,
                managementActive = state == ManagementState.DEVICE_OWNER,
                managementMode = DeviceApiClient.managementModeValue(state),
                connectivity = "online",
                batteryLevel = batteryPct(applicationContext),
                dpcVersion = BuildConfig.VERSION_NAME,
            )
            if (heartbeat.has("location_collection_enabled")) {
                store.setLocationCollectionEnabled(heartbeat.getBoolean("location_collection_enabled"))
            }
            store.setLocationSharingState(
                com.zreta.devicecontrol.location.LocationEligibility.sharingState(
                    enrolled = true,
                    serverEnabled = store.locationCollectionEnabled(),
                    disclosureAccepted = store.locationDisclosureAccepted(),
                    hasOsLocationPermission = com.zreta.devicecontrol.location.LocationWorker.hasLocationPermission(applicationContext),
                ),
            )
            applicationContext.getSharedPreferences("zreta_status", Context.MODE_PRIVATE)
                .edit()
                .putLong("last_heartbeat", System.currentTimeMillis())
                .putString("last_heartbeat_result", "ok")
                .apply()
            Result.success()
        } catch (ex: Exception) {
            SafeLog.e("Heartbeat failed", ex)
            applicationContext.getSharedPreferences("zreta_status", Context.MODE_PRIVATE)
                .edit()
                .putString("last_heartbeat_result", "error")
                .apply()
            Result.retry()
        }
    }

    companion object {
        const val UNIQUE_NAME = "zreta-heartbeat"

        fun batteryPct(context: Context): Int? {
            val filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
            val battery = context.registerReceiver(null, filter) ?: return null
            val level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            if (level < 0 || scale <= 0) return null
            return (level * 100) / scale
        }
    }
}
