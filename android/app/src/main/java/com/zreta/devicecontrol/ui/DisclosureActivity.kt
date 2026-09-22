package com.zreta.devicecontrol.ui

import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.zreta.devicecontrol.BuildConfig
import com.zreta.devicecontrol.R
import com.zreta.devicecontrol.api.DeviceApiClient
import com.zreta.devicecontrol.auth.SecureCredentialStore
import com.zreta.devicecontrol.databinding.ActivityDisclosureBinding
import com.zreta.devicecontrol.dpc.ManagementStateDetector
import com.zreta.devicecontrol.enrollment.EnrollmentPayload
import com.zreta.devicecontrol.logging.SafeLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class DisclosureActivity : AppCompatActivity() {
    private lateinit var binding: ActivityDisclosureBinding
    private lateinit var payload: EnrollmentPayload

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityDisclosureBinding.inflate(layoutInflater)
        setContentView(binding.root)
        val raw = intent.getStringExtra(EXTRA_PAYLOAD).orEmpty()
        payload = EnrollmentPayload.parse(raw)
        val state = ManagementStateDetector.userMessage(ManagementStateDetector.detect(this))
        binding.disclosureBody.text = getString(
            R.string.disclosure_body,
            payload.apiBase,
            BuildConfig.SUPPORT_CONTACT,
        ) + "\n\nCurrent management state:\n" + state
        binding.cancel.setOnClickListener { finish() }
        binding.accept.setOnClickListener { enroll() }
    }

    private fun enroll() {
        binding.accept.isEnabled = false
        lifecycleScope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    DeviceApiClient().enroll(
                        payload = payload,
                        disclosureAccepted = true,
                        managementState = ManagementStateDetector.detect(this@DisclosureActivity),
                        manufacturer = Build.MANUFACTURER,
                        model = Build.MODEL,
                        androidVersion = Build.VERSION.RELEASE,
                        dpcVersion = BuildConfig.VERSION_NAME,
                        displayName = "${Build.MANUFACTURER} ${Build.MODEL}",
                    )
                }
                val ttl = result.optInt("expires_in", 900)
                SecureCredentialStore(this@DisclosureActivity).saveSession(
                    apiBase = payload.apiBase,
                    deviceId = result.getString("device_id"),
                    publicKeyId = result.getString("public_key_id"),
                    accessToken = result.getString("access_token"),
                    expiresAtEpochSeconds = System.currentTimeMillis() / 1000 + ttl,
                )
                Toast.makeText(this@DisclosureActivity, "Enrollment complete.", Toast.LENGTH_LONG).show()
                finish()
            } catch (ex: Exception) {
                SafeLog.e("Enrollment failed", ex)
                Toast.makeText(this@DisclosureActivity, "Enrollment failed.", Toast.LENGTH_LONG).show()
                binding.accept.isEnabled = true
            }
        }
    }

    companion object {
        const val EXTRA_PAYLOAD = "enrollment_payload_json"
    }
}
