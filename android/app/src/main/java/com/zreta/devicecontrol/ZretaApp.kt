package com.zreta.devicecontrol

import android.app.Application
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.zreta.devicecontrol.location.LocationWorker
import com.zreta.devicecontrol.policy.PolicyWorker
import com.zreta.devicecontrol.status.HeartbeatWorker
import java.util.concurrent.TimeUnit

class ZretaApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val request = PeriodicWorkRequestBuilder<HeartbeatWorker>(15, TimeUnit.MINUTES)
            .setBackoffCriteria(
                androidx.work.BackoffPolicy.EXPONENTIAL,
                10,
                TimeUnit.MINUTES,
            )
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            HeartbeatWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
        val locationRequest = PeriodicWorkRequestBuilder<LocationWorker>(15, TimeUnit.MINUTES)
            .setBackoffCriteria(
                androidx.work.BackoffPolicy.EXPONENTIAL,
                10,
                TimeUnit.MINUTES,
            )
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            LocationWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            locationRequest,
        )
        val policyRequest = PeriodicWorkRequestBuilder<PolicyWorker>(15, TimeUnit.MINUTES)
            .setBackoffCriteria(
                androidx.work.BackoffPolicy.EXPONENTIAL,
                10,
                TimeUnit.MINUTES,
            )
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            PolicyWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            policyRequest,
        )
    }
}
