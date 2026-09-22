package com.zreta.devicecontrol.crypto

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec

/**
 * EC P-256 (secp256r1) signing key in Android Keystore.
 * Private key material never leaves the Keystore; [PrivateKey.encoded] is expected to be null.
 */
object DeviceKeystore {
    const val ANDROID_KEYSTORE = "AndroidKeyStore"
    const val ALGORITHM = "EC"
    const val CURVE = "secp256r1"
    const val SIGNATURE = "SHA256withECDSA"
    const val JWT_ALG = "ES256"
    private const val ALIAS = "zreta_device_identity"

    fun keyId(): String = ALIAS

    fun ensureKey(): ECPublicKey {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        if (ks.containsAlias(ALIAS)) {
            return ks.getCertificate(ALIAS).publicKey as ECPublicKey
        }
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            ALIAS,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
        )
            .setAlgorithmParameterSpec(ECGenParameterSpec(CURVE))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setUserAuthenticationRequired(false)
            .build()
        generator.initialize(spec)
        return generator.generateKeyPair().public as ECPublicKey
    }

    fun publicKeyPem(): String {
        val publicKey = ensureKey()
        val b64 = Base64.encodeToString(publicKey.encoded, Base64.NO_WRAP)
        val chunks = b64.chunked(64).joinToString("\n")
        return "-----BEGIN PUBLIC KEY-----\n$chunks\n-----END PUBLIC KEY-----"
    }

    fun sign(data: ByteArray): ByteArray {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val privateKey = ks.getKey(ALIAS, null) as PrivateKey
        val signature = Signature.getInstance(SIGNATURE)
        signature.initSign(privateKey)
        signature.update(data)
        return signature.sign()
    }

    fun privateKeyEncodedOrNull(): ByteArray? {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val privateKey = ks.getKey(ALIAS, null) as? PrivateKey ?: return null
        return privateKey.encoded
    }
}
