package app.tuyasync.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.security.SecureRandom

data class DiscoveredDevice(val deviceId: String, val ip: String, val version: String, val productKey: String?)

/** Tuya devices announce themselves on UDP 6666/6667 (and reply on 7000 when asked); this decodes and listens. */
object Discovery {
    val PORTS = listOf(6666, 6667, 7000)
    private const val APP_PORT = 7000
    private val udpKey = Crypto.md5("yGAdlopoPVldABfn".toByteArray())

    /** Decodes one broadcast datagram, or returns null if it is not a Tuya announcement. */
    fun decode(datagram: ByteArray): DiscoveredDevice? = try {
        val text = decodeText(datagram)
        val json = Json.parseToJsonElement(text.trimEnd('\u0000')).jsonObject
        val id = (json["gwId"] ?: json["devId"])?.jsonPrimitive?.content
        val ip = json["ip"]?.jsonPrimitive?.content
        if (id.isNullOrBlank() || ip.isNullOrBlank()) null
        else DiscoveredDevice(id, ip, json["version"]?.jsonPrimitive?.content ?: "3.3", json["productKey"]?.jsonPrimitive?.content)
    } catch (error: Exception) {
        null
    }

    private fun decodeText(datagram: ByteArray): String {
        if (FrameCodec.isFrame6699(datagram)) {
            return FrameCodec.unpack6699(datagram, udpKey, Retcode.DETECT).payload.toString(Charsets.UTF_8)
        }
        val payload = FrameCodec.unpack55AA(datagram, retcode = Retcode.PRESENT).payload
        if (payload.firstOrNull() == '{'.code.toByte()) return payload.toString(Charsets.UTF_8)
        return Crypto.ecbDecrypt(udpKey, payload).toString(Charsets.UTF_8)
    }

    /** The datagram that prompts protocol 3.5 devices to announce themselves on port 7000. */
    fun infoRequest(localIp: String, random: SecureRandom = SecureRandom()): ByteArray {
        val body = buildJsonObject { put("from", "app"); put("ip", localIp) }.toString().toByteArray()
        return FrameCodec.pack6699(0, Commands.REQ_DEVINFO, body, udpKey, ByteArray(12).also(random::nextBytes))
    }

    /**
     * Listens on all discovery ports until the flow is cancelled, emitting each device announcement.
     * On Android the caller must hold a WifiManager.MulticastLock or broadcasts are filtered out.
     * When [broadcastAddress] is given, an info request is sent there every few seconds to wake 3.5 devices.
     */
    fun listen(broadcastAddress: InetAddress? = null, localIp: String? = null): Flow<DiscoveredDevice> = callbackFlow {
        val sockets = PORTS.mapNotNull { port ->
            runCatching {
                DatagramSocket(null).apply {
                    reuseAddress = true
                    broadcast = true
                    soTimeout = 1000
                    bind(InetSocketAddress(port))
                }
            }.getOrNull()
        }
        if (sockets.isEmpty()) {
            close(TuyaProtocolException("Could not open any discovery port"))
            return@callbackFlow
        }
        for (socket in sockets) {
            launch(Dispatchers.IO) {
                val buffer = ByteArray(2048)
                while (isActive && !socket.isClosed) {
                    val packet = DatagramPacket(buffer, buffer.size)
                    try {
                        socket.receive(packet)
                    } catch (_: java.net.SocketTimeoutException) {
                        continue
                    } catch (_: Exception) {
                        break
                    }
                    decode(buffer.copyOfRange(0, packet.length))?.let { trySend(it) }
                }
            }
        }
        if (broadcastAddress != null && localIp != null) {
            launch(Dispatchers.IO) {
                val request = infoRequest(localIp)
                val sender = sockets.firstOrNull { it.localPort == APP_PORT } ?: sockets.first()
                while (isActive) {
                    runCatching { sender.send(DatagramPacket(request, request.size, broadcastAddress, APP_PORT)) }
                    kotlinx.coroutines.delay(6_000)
                }
            }
        }
        awaitClose { sockets.forEach { it.close() } }
    }.flowOn(Dispatchers.IO)
}
