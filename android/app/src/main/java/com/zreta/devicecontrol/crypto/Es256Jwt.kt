package com.zreta.devicecontrol.crypto

import android.util.Base64
import org.json.JSONObject

object Es256Jwt {
    fun create(claims: JSONObject, headerExtra: Map<String, String> = emptyMap()): String {
        val header = JSONObject()
        header.put("alg", DeviceKeystore.JWT_ALG)
        header.put("typ", "JWT")
        headerExtra.forEach { (k, v) -> header.put(k, v) }
        val signingInput = "${b64(header.toString().toByteArray())}.${b64(claims.toString().toByteArray())}"
        val der = DeviceKeystore.sign(signingInput.toByteArray(Charsets.US_ASCII))
        val jose = EcdsaJose.derToJose(der, 32)
        return "$signingInput.${b64(jose)}"
    }

    fun b64(data: ByteArray): String =
        Base64.encodeToString(data, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
}
