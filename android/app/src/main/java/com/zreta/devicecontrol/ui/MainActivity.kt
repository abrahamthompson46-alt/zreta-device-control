package com.zreta.devicecontrol.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.zxing.integration.android.IntentIntegrator
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.databinding.ActivityMainBinding
import com.zreta.devicecontrol.dpc.ZretaDeviceAdminReceiver
import com.zreta.devicecontrol.enrollment.EnrollmentPayload
import com.zreta.devicecontrol.location.LocationDisclosureActivity
import com.zreta.devicecontrol.location.LocationEligibility
import com.zreta.devicecontrol.location.LocationWorker
import com.zreta.devicecontrol.logging.SafeLog
import com.zreta.devicecontrol.status.StatusSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

    private val cameraPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startQrScan() else Toast.makeText(this, "Camera permission is required to scan QR codes.", Toast.LENGTH_LONG).show()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        maybeConsumeProvisioningExtras()
        binding.scanQr.setOnClickListener {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                startQrScan()
            } else {
                cameraPermission.launch(Manifest.permission.CAMERA)
            }
        }
        binding.usePasted.setOnClickListener {
            openDisclosure(binding.payloadInput.text?.toString().orEmpty())
        }
        binding.locationDisclosure.setOnClickListener {
            startActivity(Intent(this, LocationDisclosureActivity::class.java))
        }
    }

    override fun onResume() {
        super.onResume()
        refreshLocationFlag()
        refreshStatus()
    }

    private fun refreshLocationFlag() {
        val store = SecureCredentialStore(this)
        val apiBase = store.apiBase()
        val token = store.accessToken()
        if (!store.isEnrolled() || apiBase.isNullOrBlank() || token.isNullOrBlank()) {
            return
        }
        lifecycleScope.launch {
            try {
                val captured = apiBase
                val bearer = token
                val me = withContext(Dispatchers.IO) {
                    DeviceApiClient().me(captured, bearer)
                }
                if (me.has("location_collection_enabled")) {
                    store.setLocationCollectionEnabled(me.getBoolean("location_collection_enabled"))
                }
                store.setLocationSharingState(
                    LocationEligibility.sharingState(
                        enrolled = true,
                        serverEnabled = store.locationCollectionEnabled(),
                        disclosureAccepted = store.locationDisclosureAccepted(),
                        hasOsLocationPermission = LocationWorker.hasLocationPermission(this@MainActivity),
                    ),
                )
            } catch (ex: Exception) {
                SafeLog.e("Could not refresh location flag", ex)
            }
            refreshStatus()
        }
    }

    private fun refreshStatus() {
        binding.ownerStatus.text = StatusSnapshot.render(this).lineSequence().first()
        binding.details.text = StatusSnapshot.render(this)
    }

    private fun startQrScan() {
        IntentIntegrator(this)
            .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
            .setPrompt("Scan the Zreta enrollment QR")
            .setBeepEnabled(false)
            .initiateScan()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (result != null) {
            if (result.contents != null) {
                openDisclosure(result.contents)
            }
        } else {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }

    private fun maybeConsumeProvisioningExtras() {
        val extras = intent.getBundleExtra(ZretaDeviceAdminReceiver.EXTRA_ADMIN_EXTRAS)
            ?: intent.getBundleExtra("android.app.extra.PROVISIONING_ADMIN_EXTRAS_BUNDLE")
        if (extras != null) {
            val json = org.json.JSONObject()
                .put("v", 1)
                .put("api_base", extras.getString("api_base").orEmpty())
                .put("enrollment_session_id", extras.getString("enrollment_session_id").orEmpty())
                .put("enrollment_secret", extras.getString("enrollment_secret").orEmpty())
            openDisclosure(json.toString())
        }
    }

    private fun openDisclosure(raw: String) {
        try {
            EnrollmentPayload.parse(raw)
            startActivity(
                Intent(this, DisclosureActivity::class.java)
                    .putExtra(DisclosureActivity.EXTRA_PAYLOAD, raw),
            )
        } catch (ex: Exception) {
            SafeLog.w("Invalid enrollment payload")
            Toast.makeText(this, "Invalid enrollment QR/JSON.", Toast.LENGTH_LONG).show()
        }
    }
}
