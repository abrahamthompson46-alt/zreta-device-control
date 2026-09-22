package com.zreta.devicecontrol.logging

import android.util.Log

object SafeLog {
    private const val TAG = "ZretaDpc"

    fun i(message: String) {
        Log.i(TAG, LogSanitizer.sanitize(message))
    }

    fun w(message: String) {
        Log.w(TAG, LogSanitizer.sanitize(message))
    }

    fun e(message: String, error: Throwable? = null) {
        val combined = if (error == null) {
            message
        } else {
            "$message ${error.javaClass.simpleName}: ${error.message ?: ""}"
        }
        Log.e(TAG, LogSanitizer.sanitize(combined))
    }
}
