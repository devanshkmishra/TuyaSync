package app.tuyasync.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.security.SecureRandom

enum class ProtocolVersion(val label: String) {
    V33("3.3"),
    V34("3.4"),
    V35("3.5");

    internal val header: ByteArray get() = label.toByteArray() + ByteArray(12)

    companion object {
        fun parse(value: String): ProtocolVersion = when (value.trim().toDoubleOrNull()) {
            3.3, 3.2 -> V33
            3.4 -> V34
            3.5 -> V35
            else -> throw IllegalArgumentException("Unsupported Tuya protocol version \"$value\"; use 3.3, 3.4 or 3.5")
        }
    }
}

/** A decoded message from the light: its command and JSON body, if any. */
class TuyaMessage(val cmd: Int, val seqno: Int, val retcode: Int?, val json: JsonObject?, val raw: ByteArray) {
    /** The data points carried by a status push or query reply, if any. */
    val dps: Map<String, JsonPrimitive>
        get() {
            val body = json ?: return emptyMap()
            val dps = (body["dps"] ?: (body["data"] as? JsonObject)?.get("dps")) as? JsonObject ?: return emptyMap()
            return dps.mapNotNull { (key, value) -> (value as? JsonPrimitive)?.let { key to it } }.toMap()
        }
}

/**
 * Encodes and decodes the Tuya local protocol for one device and one connection: sequence numbers, the 3.4/3.5
 * session key handshake, and per-version framing. Not thread-safe; callers serialise access.
 */
class TuyaProtocol(
    val deviceId: String,
    localKey: String,
    val version: ProtocolVersion,
    private val random: SecureRandom = SecureRandom(),
) {
    private val realKey = localKey.toByteArray(Charsets.UTF_8).also {
        require(it.size == 16) { "The Local Key must be exactly 16 characters" }
    }
    private var key = realKey
    /** Sequence number of the next frame; exposed to tests. */
    internal var seqno = 1
    private var localNonce = ByteArray(0)

    val needsSessionKey: Boolean get() = version != ProtocolVersion.V33

    /** Starts a new connection: resets the sequence and returns the first handshake frame (3.4 and 3.5 only). */
    fun startHandshake(nonce: ByteArray = ByteArray(16).also(random::nextBytes)): ByteArray {
        require(nonce.size == 16)
        key = realKey
        seqno = 1
        localNonce = nonce
        return encodeRaw(Commands.SESS_KEY_NEG_START, nonce)
    }

    /** Checks the light's handshake reply and returns the frame that completes it; the session key is then active. */
    fun finishHandshake(replyFrame: ByteArray): ByteArray {
        val reply = decodeFrame(replyFrame)
        if (reply.cmd != Commands.SESS_KEY_NEG_RESP) throw TuyaProtocolException("Handshake reply had command ${reply.cmd}")
        val payload = when (version) {
            ProtocolVersion.V34 -> Crypto.ecbDecrypt(realKey, reply.payload)
            else -> reply.payload
        }
        if (payload.size < 48) throw TuyaProtocolException("Handshake reply too short")
        val remoteNonce = payload.copyOfRange(0, 16)
        if (!Crypto.hmacSha256(realKey, localNonce).contentEquals(payload.copyOfRange(16, 48))) {
            throw TuyaProtocolException("The light rejected the Local Key")
        }
        val finish = encodeRaw(Commands.SESS_KEY_NEG_FINISH, Crypto.hmacSha256(realKey, remoteNonce))
        val mixed = ByteArray(16) { (localNonce[it].toInt() xor remoteNonce[it].toInt()).toByte() }
        key = when (version) {
            ProtocolVersion.V34 -> Crypto.ecbEncrypt(realKey, mixed, pad = false)
            else -> Crypto.gcmEncrypt(realKey, localNonce.copyOfRange(0, 12), mixed).copyOfRange(0, 16)
        }
        return finish
    }

    internal val sessionKey: ByteArray get() = key

    fun controlFrame(dps: Map<String, JsonElement>, nowSeconds: Long = System.currentTimeMillis() / 1000): ByteArray {
        val dpsObject = JsonObject(dps)
        return when (version) {
            ProtocolVersion.V33 -> encode(Commands.CONTROL, buildJsonObject {
                put("devId", deviceId); put("uid", deviceId); put("t", nowSeconds.toString()); put("dps", dpsObject)
            })
            else -> encode(Commands.CONTROL_NEW, buildJsonObject {
                put("protocol", 5); put("t", nowSeconds); put("data", buildJsonObject { put("dps", dpsObject) })
            })
        }
    }

    fun queryFrame(nowSeconds: Long = System.currentTimeMillis() / 1000): ByteArray = when (version) {
        ProtocolVersion.V33 -> encode(Commands.DP_QUERY, buildJsonObject {
            put("gwId", deviceId); put("devId", deviceId); put("uid", deviceId); put("t", nowSeconds.toString())
        })
        else -> encode(Commands.DP_QUERY_NEW, JsonObject(emptyMap()))
    }

    fun heartbeatFrame(): ByteArray = when (version) {
        ProtocolVersion.V33 -> encode(Commands.HEART_BEAT, buildJsonObject { put("gwId", deviceId); put("devId", deviceId) })
        else -> encode(Commands.HEART_BEAT, JsonObject(emptyMap()))
    }

    fun encode(cmd: Int, body: JsonObject, iv: ByteArray? = null): ByteArray =
        encodeRaw(cmd, body.toString().toByteArray(Charsets.UTF_8), iv)

    fun encodeRaw(cmd: Int, payload: ByteArray, iv: ByteArray? = null): ByteArray {
        val withHeader = cmd !in Commands.NO_VERSION_HEADER
        val seq = seqno++
        return when (version) {
            ProtocolVersion.V35 -> FrameCodec.pack6699(
                seq, cmd, if (withHeader) version.header + payload else payload, key,
                iv ?: ByteArray(Crypto.GCM_IV_BYTES).also(random::nextBytes),
            )
            ProtocolVersion.V34 -> FrameCodec.pack55AA(
                seq, cmd, Crypto.ecbEncrypt(key, if (withHeader) version.header + payload else payload), hmacKey = key,
            )
            ProtocolVersion.V33 -> {
                val sealed = Crypto.ecbEncrypt(key, payload)
                FrameCodec.pack55AA(seq, cmd, if (withHeader) version.header + sealed else sealed)
            }
        }
    }

    /** Decodes one complete frame from the light. */
    fun decode(frame: ByteArray): TuyaMessage {
        val unpacked = decodeFrame(frame)
        var body = unpacked.payload
        if (version == ProtocolVersion.V34 && body.isNotEmpty()) body = Crypto.ecbDecrypt(key, body)
        if (body.startsWith(version.header.copyOfRange(0, 3))) body = body.copyOfRange(15, body.size)
        if (version == ProtocolVersion.V33 && body.isNotEmpty() && body[0] != '{'.code.toByte()) {
            body = Crypto.ecbDecrypt(key, body)
        }
        val json = if (body.isEmpty()) null else parseJson(body)
        return TuyaMessage(unpacked.cmd, unpacked.seqno, unpacked.retcode, json, body)
    }

    private fun decodeFrame(frame: ByteArray): TuyaFrame =
        if (version == ProtocolVersion.V35) FrameCodec.unpack6699(frame, key)
        else FrameCodec.unpack55AA(frame, hmacKey = if (version == ProtocolVersion.V34) key else null)

    private fun parseJson(body: ByteArray): JsonObject? = try {
        Json.parseToJsonElement(body.toString(Charsets.UTF_8).trimEnd('\u0000')).jsonObject
    } catch (error: Exception) {
        null
    }

    private fun ByteArray.startsWith(prefix: ByteArray): Boolean =
        size >= prefix.size && prefix.indices.all { this[it] == prefix[it] }
}
