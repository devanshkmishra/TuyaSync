package app.tuyasync.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** Everything needed to talk to one light. */
data class LightProfile(
    val name: String,
    val deviceId: String,
    val localKey: String,
    val ipAddress: String = "",
    val protocol: String = "3.5",
) {
    init {
        require(deviceId.isNotBlank()) { "Device ID is missing" }
        require(localKey.length == 16) { "The Local Key must be exactly 16 characters" }
        ProtocolVersion.parse(protocol)
    }

    val version: ProtocolVersion get() = ProtocolVersion.parse(protocol)

    fun toJson(): JsonObject = buildJsonObject {
        put("format", ShareCode.FORMAT)
        put("version", ShareCode.VERSION)
        put("profile", buildJsonObject {
            put("name", name); put("device_id", deviceId); put("ip_address", ipAddress)
            put("protocol", protocol.toDouble()); put("local_key", localKey)
        })
    }
}

/**
 * Reads the desktop app's light-profile export: both the "Share to phone" QR text and a
 * `.tuyasync-profile.json` file use this format (see screensync/phone_share.py).
 */
object ShareCode {
    const val FORMAT = "tuyasync-light-profile"
    const val VERSION = 2

    fun parse(text: String): LightProfile {
        val root = try {
            Json.parseToJsonElement(text.trim()).jsonObject
        } catch (error: Exception) {
            throw IllegalArgumentException("This is not a TuyaSync light profile", error)
        }
        require(root["format"]?.jsonPrimitive?.contentOrNull == FORMAT) { "This is not a TuyaSync light profile" }
        require(root["version"]?.jsonPrimitive?.intOrNull == VERSION) { "This light profile comes from a newer TuyaSync; update the app" }
        val profile = root["profile"]?.jsonObject ?: throw IllegalArgumentException("The light profile is empty")
        fun field(name: String) = profile[name]?.jsonPrimitive?.contentOrNull.orEmpty().trim()
        return LightProfile(
            name = field("name").ifBlank { "Tuya light" },
            deviceId = field("device_id"),
            localKey = profile["local_key"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            ipAddress = field("ip_address"),
            protocol = field("protocol").ifBlank { "3.5" },
        )
    }
}
