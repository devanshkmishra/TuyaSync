package app.tuyasync.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import java.io.DataInputStream
import java.net.ServerSocket
import java.nio.ByteBuffer
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

/** Runs the client against a minimal fake protocol 3.5 light on localhost. */
class ClientLoopbackTest {
    private val key = "0123456789abcdef"
    private val keyBytes = key.toByteArray()

    private fun iv() = ByteArray(12).also { java.security.SecureRandom().nextBytes(it) }

    private fun readFrame(input: DataInputStream): ByteArray {
        val header = ByteArray(18)
        input.readFully(header)
        val total = FrameCodec.frameLength(header)!!
        return header + ByteArray(total - 18).also { input.readFully(it) }
    }

    /** Accepts one connection, completes the handshake, then answers queries and echoes writes as status pushes. */
    private fun fakeLight(server: ServerSocket, initial: Map<String, JsonPrimitive>, acceptKey: String = key) = thread(isDaemon = true) {
        server.accept().use { socket ->
            val input = DataInputStream(socket.getInputStream())
            val out = socket.getOutputStream()
            val deviceKey = acceptKey.toByteArray()
            val start = FrameCodec.unpack6699(readFrame(input), deviceKey, Retcode.ABSENT)
            val localNonce = start.payload
            val remoteNonce = "fedcba9876543210".toByteArray()
            out.write(FrameCodec.pack6699(1, Commands.SESS_KEY_NEG_RESP, remoteNonce + Crypto.hmacSha256(deviceKey, localNonce), deviceKey, iv(), retcode = 0))
            FrameCodec.unpack6699(readFrame(input), deviceKey, Retcode.ABSENT)
            val mixed = ByteArray(16) { (localNonce[it].toInt() xor remoteNonce[it].toInt()).toByte() }
            val session = Crypto.gcmEncrypt(deviceKey, localNonce.copyOfRange(0, 12), mixed).copyOfRange(0, 16)
            val state = initial.toMutableMap()
            var seq = 10
            while (true) {
                val frame = try { FrameCodec.unpack6699(readFrame(input), session, Retcode.ABSENT) } catch (_: Exception) { return@use }
                when (frame.cmd) {
                    Commands.DP_QUERY_NEW -> {
                        val body = """{"dps":${JsonObject(state)}}""".toByteArray()
                        out.write(FrameCodec.pack6699(seq++, Commands.DP_QUERY_NEW, body, session, iv(), retcode = 0))
                    }
                    Commands.CONTROL_NEW -> {
                        val json = Json.parseToJsonElement(frame.payload.copyOfRange(15, frame.payload.size).toString(Charsets.UTF_8)).jsonObject
                        val dps = json["data"]!!.jsonObject["dps"]!!.jsonObject
                        dps.forEach { (k, v) -> state[k] = v as JsonPrimitive }
                        val body = ProtocolVersion.V35.header + """{"protocol":4,"t":1,"data":{"dps":$dps}}""".toByteArray()
                        out.write(FrameCodec.pack6699(seq++, Commands.STATUS, body, session, iv(), retcode = 0))
                    }
                    Commands.HEART_BEAT -> out.write(FrameCodec.pack6699(seq++, Commands.HEART_BEAT, ByteArray(0), session, iv(), retcode = 0))
                }
                out.flush()
            }
        }
    }

    @Test
    fun `connects, reads status and applies writes`() = runBlocking {
        ServerSocket(0, 5, java.net.InetAddress.getLoopbackAddress()).use { server ->
            fakeLight(server, mapOf("20" to JsonPrimitive(true), "22" to JsonPrimitive(500)))
            val client = TuyaClient(server.inetAddress.hostAddress, TuyaProtocol("bf00", key, ProtocolVersion.V35), this, port = server.localPort)
            withTimeout(5_000) {
                client.connect()
                assertEquals(JsonPrimitive(500), client.dps.first { it.isNotEmpty() }["22"])
                client.set(Ds22000.power(false))
                client.dps.first { it["20"] == JsonPrimitive(false) }
                assertEquals(LightState(on = false, brightness = 500), LightState.from(client.dps.value))
            }
            client.close()
        }
    }

    @Test
    fun `reports a rejected local key`() = runBlocking(Dispatchers.IO) {
        ServerSocket(0, 5, java.net.InetAddress.getLoopbackAddress()).use { server ->
            fakeLight(server, emptyMap(), acceptKey = "ffffffffffffffff")
            val client = TuyaClient(server.inetAddress.hostAddress, TuyaProtocol("bf00", key, ProtocolVersion.V35), this, port = server.localPort)
            runCatching { client.connect() }
            val state = client.state.value
            assertIs<ConnectionState.Failed>(state)
            assertEquals(true, state.keyRejected)
        }
    }
}
