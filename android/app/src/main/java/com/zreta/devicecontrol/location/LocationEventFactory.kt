package com.zreta.devicecontrol.location

import org.json.JSONObject
import java.util.UUID

data class LocationPoint(
    val clientEventId: String,
    val capturedAtIso: String,
    val latitude: Double,
    val longitude: Double,
    val accuracyM: Double?,
    val source: String,
    val isMock: Boolean,
    val locationDisclosureAccepted: Boolean = true,
) {
    fun toJsonObject(): JSONObject {
        val obj = JSONObject()
            .put("client_event_id", clientEventId)
            .put("captured_at", capturedAtIso)
            .put("latitude", latitude)
            .put("longitude", longitude)
            .put("source", source)
            .put("is_mock", isMock)
            .put("location_disclosure_accepted", locationDisclosureAccepted)
        if (accuracyM != null) {
            obj.put("accuracy_m", accuracyM)
        }
        return obj
    }

    fun toDebugString(): String {
        return "client_event_id=$clientEventId source=$source disclosure=$locationDisclosureAccepted mock=$isMock"
    }
}

object LocationEventFactory {
    fun create(
        latitude: Double,
        longitude: Double,
        accuracyM: Float?,
        source: String,
        isMock: Boolean,
        capturedAtEpochMs: Long,
        clientEventId: String = UUID.randomUUID().toString(),
    ): LocationPoint {
        val iso = java.time.Instant.ofEpochMilli(capturedAtEpochMs).toString()
        return LocationPoint(
            clientEventId = clientEventId,
            capturedAtIso = iso,
            latitude = latitude,
            longitude = longitude,
            accuracyM = accuracyM?.toDouble(),
            source = source,
            isMock = isMock,
        )
    }
}
