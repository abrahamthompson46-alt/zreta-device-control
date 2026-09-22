package com.zreta.devicecontrol.policy.enforcement

/**
 * UserManager restriction key strings (stable API values) — no Android framework import
 * so JVM unit tests can reference them.
 */
object UserRestrictionKeys {
    const val OUTGOING_CALLS = "no_outgoing_calls"
    const val SMS = "no_sms"
    const val CONFIG_WIFI = "no_config_wifi"
    const val CONFIG_MOBILE = "no_config_mobile_networks"
    const val CONFIG_TETHERING = "no_config_tethering"
    const val CONFIG_VPN = "no_config_vpn"
}
