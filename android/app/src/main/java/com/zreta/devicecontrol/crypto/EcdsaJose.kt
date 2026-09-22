package com.zreta.devicecontrol.crypto

import java.math.BigInteger

object EcdsaJose {
    fun derToJose(der: ByteArray, componentLength: Int): ByteArray {
        require(der.size >= 8 && der[0] == 0x30.toByte()) { "Not a DER ECDSA signature" }
        var offset = 2
        if (der[1].toInt() and 0x80 != 0) {
            offset = 2 + (der[1].toInt() and 0x7f)
        }
        require(der[offset] == 0x02.toByte())
        val rLen = der[offset + 1].toInt() and 0xff
        val r = der.copyOfRange(offset + 2, offset + 2 + rLen)
        offset = offset + 2 + rLen
        require(der[offset] == 0x02.toByte())
        val sLen = der[offset + 1].toInt() and 0xff
        val s = der.copyOfRange(offset + 2, offset + 2 + sLen)
        return toFixed(r, componentLength) + toFixed(s, componentLength)
    }

    private fun toFixed(value: ByteArray, length: Int): ByteArray {
        val bi = BigInteger(1, value)
        val raw = bi.toByteArray()
        val out = ByteArray(length)
        val srcStart = maxOf(0, raw.size - length)
        val destStart = length - (raw.size - srcStart)
        System.arraycopy(raw, srcStart, out, destStart, raw.size - srcStart)
        return out
    }
}
