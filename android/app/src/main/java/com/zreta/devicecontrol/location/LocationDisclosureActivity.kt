package com.zreta.devicecontrol.location

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.databinding.ActivityLocationDisclosureBinding

class LocationDisclosureActivity : AppCompatActivity() {
    private lateinit var binding: ActivityLocationDisclosureBinding
    private lateinit var store: SecureCredentialStore

    private val requestFine = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        val granted = grants.values.any { it }
        if (granted && Build.VERSION.SDK_INT >= 29) {
            requestBackground.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        } else {
            finishAfterPermission(granted)
        }
    }

    private val requestBackground = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        finishAfterPermission(LocationWorker.hasLocationPermission(this))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLocationDisclosureBinding.inflate(layoutInflater)
        setContentView(binding.root)
        store = SecureCredentialStore(this)
        binding.cancel.setOnClickListener { finish() }
        binding.accept.setOnClickListener {
            val permissions = arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            )
            val already = permissions.any {
                ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
            }
            if (already) {
                if (Build.VERSION.SDK_INT >= 29) {
                    requestBackground.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                } else {
                    finishAfterPermission(true)
                }
            } else {
                requestFine.launch(permissions)
            }
        }
    }

    private fun finishAfterPermission(granted: Boolean) {
        if (granted) {
            store.setLocationDisclosureAccepted(true)
            store.setLocationSharingState(
                LocationEligibility.sharingState(
                    enrolled = store.isEnrolled(),
                    serverEnabled = store.locationCollectionEnabled(),
                    disclosureAccepted = true,
                    hasOsLocationPermission = true,
                ),
            )
        }
        finish()
    }
}
