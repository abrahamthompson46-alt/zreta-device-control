package com.zreta.devicecontrol.location

/**
 * Decides whether this worker run may request GPS and/or upload the queue.
 *
 * Rules:
 * - Never request GPS when the encrypted queue already has pending events (retry must re-upload
 *   the same client_event_id values).
 * - Never request GPS when the server reports location_collection_enabled=false.
 * - Never request GPS when the server enabled flag cannot be confirmed (offline / unreachable).
 * - Upload of already-queued events may still proceed when the queue is non-empty.
 */
data class LocationWorkPlan(
    val requestGps: Boolean,
    val uploadPending: Boolean,
    val cacheServerEnabled: Boolean?,
)

object LocationWorkPolicy {
    /**
     * @param serverEnabled true/false from authenticated `/device/me`, or null if unreachable.
     * @param queuePending true when the encrypted location queue already holds events.
     */
    fun plan(
        enrolled: Boolean,
        disclosureAccepted: Boolean,
        hasOsLocationPermission: Boolean,
        serverEnabled: Boolean?,
        queuePending: Boolean,
    ): LocationWorkPlan {
        if (!enrolled) {
            return LocationWorkPlan(requestGps = false, uploadPending = false, cacheServerEnabled = null)
        }
        when (serverEnabled) {
            false -> return LocationWorkPlan(
                requestGps = false,
                uploadPending = queuePending,
                cacheServerEnabled = false,
            )
            null -> return LocationWorkPlan(
                // Offline / unknown: never collect a fresh GPS fix. Upload-only retries are OK.
                requestGps = false,
                uploadPending = queuePending,
                cacheServerEnabled = null,
            )
            true -> {
                val mayCollect = LocationEligibility.canCollect(
                    enrolled = true,
                    serverEnabled = true,
                    disclosureAccepted = disclosureAccepted,
                    hasOsLocationPermission = hasOsLocationPermission,
                )
                // Pending queue always wins: upload existing client_event_id values first.
                val requestGps = mayCollect && !queuePending
                return LocationWorkPlan(
                    requestGps = requestGps,
                    uploadPending = queuePending || requestGps,
                    cacheServerEnabled = true,
                )
            }
        }
    }
}

object LocationUploadParser {
    fun idsToRemove(
        accepted: List<String>,
        duplicates: List<String>,
        rejected: List<Pair<String, String>>,
    ): Set<String> {
        val done = (accepted + duplicates).toMutableSet()
        rejected.forEach { (id, code) ->
            if (code in TERMINAL_REJECT) {
                done.add(id)
            }
        }
        return done
    }

    /** Transient rejects (e.g. rate_limited) must keep the event queued for retry. */
    private val TERMINAL_REJECT = setOf(
        "disabled",
        "disclosure_required",
        "invalid_coordinates",
        "invalid_timestamp",
        "invalid_event_id",
    )
}
