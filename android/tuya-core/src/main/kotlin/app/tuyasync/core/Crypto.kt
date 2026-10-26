package app.tuyasync.core

import java.security.MessageDigest
import java.util.zip.CRC32
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** The handful of primitives the Tuya LAN protocol uses. */
internal object Crypto {
    const val GCM_IV_BYTES = 12
    const val GCM_TAG_BYTES = 16

    fun ecbEncrypt(key: ByteArray, data: ByteArray, pad: Boolean = true): ByteArray {
        val input = if (pad) pkcs7Pad(data) else data
        val cipher = Cipher.getInstance("AES/ECB/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"))
        return cipher.doFinal(input)
    }

    fun ecbDecrypt(key: ByteArray, data: ByteArray, unpad: Boolean = true): ByteArray {
        require(data.size % 16 == 0) { "ECB payload length ${data.size} is not a multiple of 16" }
        val cipher = Cipher.getInstance("AES/ECB/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"))
        val plain = cipher.doFinal(data)
        return if (unpad) pkcs7Unpad(plain) else plain
    }

    /** Returns ciphertext followed by the 16-byte tag. */
    fun gcmEncrypt(key: ByteArray, iv: ByteArray, plain: ByteArray, aad: ByteArray? = null): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BYTES * 8, iv))
        if (aad != null) cipher.updateAAD(aad)
        return cipher.doFinal(plain)
    }

    /** [cipherAndTag] is ciphertext followed by the 16-byte tag; throws if the tag does not verify. */
    fun gcmDecrypt(key: ByteArray, iv: ByteArray, cipherAndTag: ByteArray, aad: ByteArray? = null): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BYTES * 8, iv))
        if (aad != null) cipher.updateAAD(aad)
        return cipher.doFinal(cipherAndTag)
    }

    fun hmacSha256(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }

    fun crc32(data: ByteArray, length: Int = data.size): Long = CRC32().apply { update(data, 0, length) }.value

    fun md5(data: ByteArray): ByteArray = MessageDigest.getInstance("MD5").digest(data)

    private fun pkcs7Pad(data: ByteArray): ByteArray {
        val padding = 16 - data.size % 16
        return data + ByteArray(padding) { padding.toByte() }
    }

    private fun pkcs7Unpad(data: ByteArray): ByteArray {
        require(data.isNotEmpty()) { "empty ECB payload" }
        val padding = data.last().toInt() and 0xff
        require(padding in 1..16) { "invalid padding length $padding" }
        return data.copyOfRange(0, data.size - padding)
    }
}
