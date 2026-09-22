package com.zreta.devicecontrol.policy

/**
 * Monotonic policy version comparison for LKG and enforcement.
 */
object PolicyVersionGuard {
    /**
     * Returns true when [incoming] would downgrade an already-accepted [current] version.
     */
    fun isStaleIncoming(currentVersionNumber: Int, incomingVersionNumber: Int?): Boolean {
        val incoming = incomingVersionNumber ?: 0
        return currentVersionNumber > 0 && incoming > 0 && incoming < currentVersionNumber
    }
}
