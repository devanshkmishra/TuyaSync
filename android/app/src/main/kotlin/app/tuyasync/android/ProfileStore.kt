package app.tuyasync.android

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import app.tuyasync.core.LightProfile
import app.tuyasync.core.ShareCode
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Keeps the light profile (including its Local Key) in app storage, encrypted with a key held by Android Keystore. */
class ProfileStore(context: Context) {
    private val file = File(context.filesDir, "light-profile.bin")

    fun load(): LightProfile? = runCatching {
        if (!file.exists()) return null
        val data = file.readBytes()
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, data.copyOfRange(0, 12)))
        ShareCode.parse(cipher.doFinal(data.copyOfRange(12, data.size)).toString(Charsets.UTF_8))
    }.getOrNull()

    fun save(profile: LightProfile) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.doFinal(profile.toJson().toString().toByteArray(Charsets.UTF_8))
        val temporary = File(file.parentFile, "${file.name}.tmp")
        temporary.writeBytes(cipher.iv + sealed)
        temporary.renameTo(file)
    }

    fun clear() {
        file.delete()
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "tuyasync-light-profile"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
