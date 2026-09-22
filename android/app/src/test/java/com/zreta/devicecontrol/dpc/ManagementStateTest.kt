package com.zreta.devicecontrol.dpc

import org.junit.Assert.assertEquals
import org.junit.Test

class ManagementStateTest {
    @Test
    fun unmanagedMessageDoesNotClaimOwner() {
        val message = ManagementStateDetector.userMessage(ManagementState.UNMANAGED)
        assertEquals(true, message.contains("does not make the phone Device Owner"))
    }
}
