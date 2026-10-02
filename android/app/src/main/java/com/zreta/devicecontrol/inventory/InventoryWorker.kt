package com.zreta.devicecontrol.inventory

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.zreta.devicecontrol.api.ApiException
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.logging.SafeLog

/**
 * Uploads the installed-app snapshot. Failures retry this work only and do not affect heartbeat.
 */
class InventoryWorker(
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
            val body = InstalledAppInventory.collect(applicationContext)
            client.uploadInstalledApps(apiBase, token!!, body)
            Result.success()
        } catch (ex: ApiException) {
            if (ex.code == 401 || ex.code == 403) Result.success() else Result.retry()
        } catch (ex: Exception) {
            SafeLog.w("Inventory upload failed: ${ex.javaClass.simpleName}")
            Result.retry()
        }
    }
}
