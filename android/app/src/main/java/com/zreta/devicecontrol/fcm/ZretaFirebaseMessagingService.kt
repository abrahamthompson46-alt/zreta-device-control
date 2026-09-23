package com.zreta.devicecontrol.fcm

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.logging.SafeLog
import com.zreta.devicecontrol.policy.PolicyWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await

/**
 * FCM is wake-only. Authoritative policy still comes from GET /device/policy via PolicyWorker.
 */
class ZretaFirebaseMessagingService : FirebaseMessagingService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNewToken(token: String) {
        scope.launch {
            FcmTokenRegistrar.register(applicationContext, token)
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val type = message.data["type"].orEmpty()
        if (type != WAKE_TYPE) {
            SafeLog.i("FCM ignored type=$type")
            return
        }
        val store = SecureCredentialStore(applicationContext)
        if (!store.isEnrolled()) return
        val request = OneTimeWorkRequestBuilder<PolicyWorker>().build()
        WorkManager.getInstance(applicationContext).enqueueUniqueWork(
            FCM_WAKE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request,
        )
        SafeLog.i("FCM policy wake enqueued")
    }

    companion object {
        const val WAKE_TYPE = "policy_wake"
        const val FCM_WAKE_WORK_NAME = "zreta-policy-fcm-wake"
    }
}

object FcmTokenRegistrar {
    /**
     * Fetch current FCM token (when Play services / google-services.json present) and POST to backend.
     * No-ops safely when Firebase is unavailable.
     */
    fun refreshAndRegister(context: Context) {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val token = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await()
                if (!token.isNullOrBlank()) {
                    register(context, token)
                }
            } catch (ex: Exception) {
                SafeLog.i("FCM token refresh skipped: ${ex.javaClass.simpleName}")
            }
        }
    }

    suspend fun register(context: Context, token: String) {
        val store = SecureCredentialStore(context)
        val apiBase = store.apiBase()
        val deviceId = store.deviceId()
        val kid = store.publicKeyId()
        if (apiBase.isNullOrBlank() || deviceId.isNullOrBlank() || kid.isNullOrBlank()) return
        if (token.isBlank() || token.length > 512) return
        try {
            val client = DeviceApiClient()
            var access = store.accessToken()
            val soon = System.currentTimeMillis() / 1000 + 60
            if (access.isNullOrBlank() || store.expiresAt() <= soon) {
                val refreshed = client.token(apiBase, deviceId, kid)
                access = refreshed.getString("access_token")
                val ttl = refreshed.optInt("expires_in", 900)
                store.saveSession(apiBase, deviceId, kid, access, System.currentTimeMillis() / 1000 + ttl)
            }
            client.registerFcmToken(apiBase, access!!, token)
            SafeLog.i("FCM token registered")
        } catch (ex: Exception) {
            SafeLog.w("FCM token register failed: ${ex.javaClass.simpleName}")
        }
    }
}
