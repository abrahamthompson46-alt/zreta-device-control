package com.zreta.devicecontrol.location

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.google.android.gms.tasks.Tasks
import com.zreta.devicecontrol.api.ApiException
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.logging.SafeLog
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Periodic location worker.
 *
 * Retry-safe:
 * - Pending encrypted-queue events are uploaded with their original client_event_id values.
 * - A new fused GPS fix is requested only when the queue is empty and the server has confirmed
 *   location_collection_enabled=true (plus disclosure + OS permission).
 * - Network failures return Result.retry() without minting a new GPS event.
 */
class LocationWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val store = SecureCredentialStore(applicationContext)
        if (!store.isEnrolled()) {
            return Result.success()
        }

        val permission = hasLocationPermission(applicationContext)
        val queue = LocationQueue(applicationContext)
        // Inspect the queue BEFORE any GPS request so retries never amplify collection.
        val pendingBefore = queue.snapshot()

        // Fresh server flag BEFORE any GPS request. null = unreachable (no new collection).
        val serverEnabled = refreshServerEnabled(store)
        val plan = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = store.locationDisclosureAccepted(),
            hasOsLocationPermission = permission,
            serverEnabled = serverEnabled,
            queuePending = pendingBefore.isNotEmpty(),
        )
        if (plan.cacheServerEnabled != null) {
            store.setLocationCollectionEnabled(plan.cacheServerEnabled)
        }
        store.setLocationSharingState(
            LocationEligibility.sharingState(
                enrolled = true,
                serverEnabled = store.locationCollectionEnabled(),
                disclosureAccepted = store.locationDisclosureAccepted(),
                hasOsLocationPermission = permission,
            ),
        )

        if (!plan.requestGps && !plan.uploadPending) {
            return Result.success()
        }

        try {
            if (plan.requestGps) {
                val fix = currentFix() ?: return Result.success()
                val mock = if (Build.VERSION.SDK_INT >= 31) {
                    fix.isMock
                } else {
                    @Suppress("DEPRECATION")
                    fix.isFromMockProvider
                }
                queue.enqueue(
                    LocationEventFactory.create(
                        latitude = fix.latitude,
                        longitude = fix.longitude,
                        accuracyM = if (fix.hasAccuracy()) fix.accuracy else null,
                        source = "fused",
                        isMock = mock,
                        capturedAtEpochMs = fix.time.takeIf { it > 0 } ?: System.currentTimeMillis(),
                    ).toJsonObject(),
                )
            }
            if (plan.uploadPending || queue.snapshot().isNotEmpty()) {
                return uploadQueue(store, queue)
            }
            return Result.success()
        } catch (ex: Exception) {
            SafeLog.e("Location worker failed", ex)
            // Keep queued events; next retry uploads the same client_event_id values.
            return Result.retry()
        }
    }

    private fun refreshServerEnabled(store: SecureCredentialStore): Boolean? {
        val apiBase = store.apiBase() ?: return null
        val token = store.accessToken() ?: return null
        return try {
            val me = DeviceApiClient().me(apiBase, token)
            if (me.has("location_collection_enabled")) {
                me.getBoolean("location_collection_enabled")
            } else {
                null
            }
        } catch (ex: ApiException) {
            if (ex.code == 401 || ex.code == 403) {
                store.setLocationCollectionEnabled(false)
                false
            } else {
                SafeLog.w("Could not refresh location_collection_enabled")
                null
            }
        } catch (ex: Exception) {
            SafeLog.e("Could not refresh location_collection_enabled", ex)
            null
        }
    }

    private fun currentFix(): Location? {
        val fused = LocationServices.getFusedLocationProviderClient(applicationContext)
        val token = CancellationTokenSource()
        return try {
            fused.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, token.token)
                .let { Tasks.await(it, 20, TimeUnit.SECONDS) }
        } catch (_: SecurityException) {
            SafeLog.w("Location permission missing at collection time")
            null
        } catch (ex: Exception) {
            SafeLog.e("Fused location unavailable", ex)
            null
        }
    }

    private fun uploadQueue(store: SecureCredentialStore, queue: LocationQueue): Result {
        val apiBase = store.apiBase() ?: return Result.retry()
        val token = store.accessToken() ?: return Result.retry()
        val pending = queue.snapshot()
        if (pending.isEmpty()) return Result.success()
        val array = JSONArray()
        pending.forEach { array.put(it) }
        val body = JSONObject().put("locations", array)
        return try {
            val response = DeviceApiClient().uploadLocations(apiBase, token, body)
            val accepted = jsonStringList(response.optJSONArray("accepted"))
            val duplicates = jsonStringList(response.optJSONArray("duplicates"))
            val rejected = jsonRejected(response.optJSONArray("rejected"))
            if (rejected.any { it.second == "disabled" }) {
                store.setLocationCollectionEnabled(false)
            }
            // Only remove accepted / idempotent duplicates / terminal rejects.
            // Transient rejects (e.g. rate_limited) and network failures keep the same IDs queued.
            queue.remove(LocationUploadParser.idsToRemove(accepted, duplicates, rejected))
            Result.success()
        } catch (ex: ApiException) {
            if (ex.code == 401 || ex.code == 403) {
                store.setLocationCollectionEnabled(false)
                Result.success()
            } else {
                Result.retry()
            }
        }
    }

    companion object {
        const val UNIQUE_NAME = "zreta-location"

        fun hasLocationPermission(context: Context): Boolean {
            val fine = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION)
            val coarse = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION)
            return fine == PackageManager.PERMISSION_GRANTED || coarse == PackageManager.PERMISSION_GRANTED
        }

        private fun jsonStringList(array: JSONArray?): List<String> {
            if (array == null) return emptyList()
            return buildList {
                for (i in 0 until array.length()) add(array.getString(i))
            }
        }

        private fun jsonRejected(array: JSONArray?): List<Pair<String, String>> {
            if (array == null) return emptyList()
            return buildList {
                for (i in 0 until array.length()) {
                    val item = array.getJSONObject(i)
                    add(item.optString("client_event_id") to item.optString("code"))
                }
            }
        }
    }
}
