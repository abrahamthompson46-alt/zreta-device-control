package com.zreta.devicecontrol.network

import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.zreta.devicecontrol.databinding.ActivityVpnConsentBinding

/**
 * Disclosed VPN consent flow for the local DNS filter.
 * Launches [VpnService.prepare] from an Activity (never from a Worker).
 */
class VpnConsentActivity : AppCompatActivity() {
    private lateinit var binding: ActivityVpnConsentBinding

    private val prepareLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            onConsentGranted()
        } else {
            Toast.makeText(this, getString(com.zreta.devicecontrol.R.string.vpn_consent_denied), Toast.LENGTH_LONG).show()
            VpnConsentCoordinator.setPending(this, true)
            finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityVpnConsentBinding.inflate(layoutInflater)
        setContentView(binding.root)
        binding.vpnConsentContinue.setOnClickListener { requestConsent() }
        binding.vpnConsentCancel.setOnClickListener { finish() }
    }

    private fun requestConsent() {
        val prepare = VpnService.prepare(this)
        if (prepare == null) {
            onConsentGranted()
        } else {
            prepareLauncher.launch(prepare)
        }
    }

    private fun onConsentGranted() {
        VpnConsentCoordinator.setPending(this, false)
        VpnConsentCoordinator.cancelNotification(this)
        VpnConsentCoordinator.enqueuePolicyReenforce(this)
        Toast.makeText(this, getString(com.zreta.devicecontrol.R.string.vpn_consent_granted), Toast.LENGTH_LONG).show()
        finish()
    }
}
