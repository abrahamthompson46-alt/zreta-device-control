package com.zreta.devicecontrol.location

object LocationEligibility {
    fun canCollect(
        enrolled: Boolean,
        serverEnabled: Boolean,
        disclosureAccepted: Boolean,
        hasOsLocationPermission: Boolean,
    ): Boolean {
        return enrolled && serverEnabled && disclosureAccepted && hasOsLocationPermission
    }

    fun sharingState(
        enrolled: Boolean,
        serverEnabled: Boolean,
        disclosureAccepted: Boolean,
        hasOsLocationPermission: Boolean,
    ): String {
        if (!enrolled) return "off (not enrolled)"
        if (!serverEnabled) return "off (parent disabled or not enabled)"
        if (!disclosureAccepted) return "waiting for on-device disclosure"
        if (!hasOsLocationPermission) return "waiting for OS location permission"
        return "on (periodic, every 15 minutes)"
    }
}
