package com.zreta.devicecontrol.location

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocationEligibilityTest {
    @Test
    fun refusesWithoutDisclosurePermissionOrServerFlag() {
        assertFalse(LocationEligibility.canCollect(true, true, false, true))
        assertFalse(LocationEligibility.canCollect(true, true, true, false))
        assertFalse(LocationEligibility.canCollect(true, false, true, true))
        assertFalse(LocationEligibility.canCollect(false, true, true, true))
        assertTrue(LocationEligibility.canCollect(true, true, true, true))
    }

    @Test
    fun sharingStateIsVisible() {
        val state = LocationEligibility.sharingState(true, false, true, true)
        assertTrue(state.contains("off"))
        assertFalse(state.contains("51.5"))
    }
}

class LocationEventFactoryTest {
    @Test
    fun keepsStableClientEventIdAndOmitsSpeed() {
        val id = "11111111-1111-1111-1111-111111111111"
        val first = LocationEventFactory.create(
            latitude = 1.0,
            longitude = 2.0,
            accuracyM = 8f,
            source = "fused",
            isMock = false,
            capturedAtEpochMs = 1_700_000_000_000L,
            clientEventId = id,
        )
        val retry = LocationEventFactory.create(
            latitude = 1.0,
            longitude = 2.0,
            accuracyM = 8f,
            source = "fused",
            isMock = false,
            capturedAtEpochMs = 1_700_000_000_000L,
            clientEventId = first.clientEventId,
        )
        assertEquals(id, retry.clientEventId)
        assertTrue(first.locationDisclosureAccepted)
        val blob = first.toDebugString()
        assertFalse(blob.contains("speed"))
        assertFalse(blob.contains("bearing"))
        assertFalse(blob.contains("ssid"))
        assertEquals(id, first.clientEventId)
    }
}

class LocationWorkPolicyTest {
    @Test
    fun queueNonEmptyNeverRequestsGpsEvenWhenEligible() {
        val plan = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = true,
            queuePending = true,
        )
        assertFalse(plan.requestGps)
        assertTrue(plan.uploadPending)
        assertEquals(true, plan.cacheServerEnabled)
    }

    @Test
    fun emptyQueueAndEligibleMayRequestGps() {
        val plan = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = true,
            queuePending = false,
        )
        assertTrue(plan.requestGps)
        assertTrue(plan.uploadPending)
    }

    @Test
    fun serverDisabledNeverRequestsGpsEvenWithStaleLocalTrueAssumptions() {
        val plan = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = false,
            queuePending = false,
        )
        assertFalse(plan.requestGps)
        assertFalse(plan.uploadPending)
        assertEquals(false, plan.cacheServerEnabled)
    }

    @Test
    fun serverDisabledWithPendingQueueUploadsOnly() {
        val plan = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = false,
            queuePending = true,
        )
        assertFalse(plan.requestGps)
        assertTrue(plan.uploadPending)
        assertEquals(false, plan.cacheServerEnabled)
    }

    @Test
    fun serverStateUnavailableNeverRequestsGps() {
        val empty = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = null,
            queuePending = false,
        )
        assertFalse(empty.requestGps)
        assertFalse(empty.uploadPending)
        assertEquals(null, empty.cacheServerEnabled)

        val pending = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = null,
            queuePending = true,
        )
        assertFalse(pending.requestGps)
        assertTrue(pending.uploadPending)
        assertEquals(null, pending.cacheServerEnabled)
    }

    @Test
    fun serverEnabledWithoutDisclosureOrPermissionDoesNotCollect() {
        assertFalse(
            LocationWorkPolicy.plan(
                enrolled = true,
                disclosureAccepted = false,
                hasOsLocationPermission = true,
                serverEnabled = true,
                queuePending = false,
            ).requestGps,
        )
        assertFalse(
            LocationWorkPolicy.plan(
                enrolled = true,
                disclosureAccepted = true,
                hasOsLocationPermission = false,
                serverEnabled = true,
                queuePending = false,
            ).requestGps,
        )
    }

    @Test
    fun retryPathKeepsUploadOnlyWhenQueueHasEvents() {
        // Simulates a failed upload that left an event queued: next run must upload, not GPS.
        val retry = LocationWorkPolicy.plan(
            enrolled = true,
            disclosureAccepted = true,
            hasOsLocationPermission = true,
            serverEnabled = true,
            queuePending = true,
        )
        assertFalse("retry must not request a new GPS fix", retry.requestGps)
        assertTrue("retry must upload the same queued client_event_id", retry.uploadPending)
    }
}

class LocationUploadParserTest {
    @Test
    fun acceptedAndDuplicateIdsAreRemoved() {
        val remove = LocationUploadParser.idsToRemove(
            accepted = listOf("a"),
            duplicates = listOf("b"),
            rejected = emptyList(),
        )
        assertEquals(setOf("a", "b"), remove)
    }

    @Test
    fun terminalRejectsAreRemovedButRateLimitedKeepsQueued() {
        val remove = LocationUploadParser.idsToRemove(
            accepted = emptyList(),
            duplicates = emptyList(),
            rejected = listOf(
                "c" to "disabled",
                "d" to "rate_limited",
                "e" to "invalid_coordinates",
            ),
        )
        assertTrue(remove.contains("c"))
        assertTrue(remove.contains("e"))
        assertFalse("transient rate_limited must keep the same client_event_id queued", remove.contains("d"))
    }

    @Test
    fun emptyResponseRemovesNothingSoTransientFailureKeepsIds() {
        // Mimics a failed upload path where the worker retries without calling idsToRemove.
        val remove = LocationUploadParser.idsToRemove(emptyList(), emptyList(), emptyList())
        assertTrue(remove.isEmpty())
    }
}

class LocationLogRedactionTest {
    @Test
    fun sanitizerRedactsCoordinates() {
        val sanitized = com.zreta.devicecontrol.logging.LogSanitizer.sanitize("latitude=51.5")
        assertEquals("redacted diagnostic", sanitized)
    }

    @Test
    fun safeLogSanitizesExceptionMessages() {
        val combined = com.zreta.devicecontrol.logging.LogSanitizer.sanitize(
            "Location worker failed RuntimeException: latitude=1.23 longitude=4.56",
        )
        assertEquals("redacted diagnostic", combined)
    }
}
