package app.tuyasync.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** Checks the Kotlin protocol byte-for-byte against frames produced by TinyTuya (android/tools/make_vectors.py). */
class ProtocolVectorsTest {
    private val vectors = Json.parseToJsonElement(
        javaClass.getResource("/vectors.json")!!.readText(),
    ).jsonObject
    private val key = vectors.string("key")
    private val keyBytes = key.toByteArray()
    private val deviceId = vectors.string("device_id")
    private val iv = vectors.string("iv").hex()

    private fun group(name: String) = vectors[name]!!.jsonObject
    private fun JsonObject.string(name: String) = this[name]!!.jsonPrimitive.content
    private fun String.hex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    private fun ByteArray.hex(): String = joinToString("") { "%02x".format(it) }
    private fun protocol(version: ProtocolVersion) = TuyaProtocol(deviceId, key, version)

    @Test
    fun `packs 3_5 frames like TinyTuya`() {
        val v = group("v35_control")
        val payload = ProtocolVersion.V35.header + v.string("json").toByteArray()
        val frame = FrameCodec.pack6699(v["seq"]!!.jsonPrimitive.int, Commands.CONTROL_NEW, payload, keyBytes, iv)
        assertEquals(v.string("frame"), frame.hex())
    }

    @Test
    fun `protocol 3_5 control frame carries the version header`() {
        val p = protocol(ProtocolVersion.V35)
        p.seqno = 7
        val frame = p.encode(Commands.CONTROL_NEW, Json.parseToJsonElement(group("v35_control").string("json")).jsonObject, iv)
        assertEquals(group("v35_control").string("frame"), frame.hex())
    }

    @Test
    fun `decodes 3_5 status pushes and query replies`() {
        val p = protocol(ProtocolVersion.V35)
        val status = p.decode(group("v35_status").string("frame").hex())
        assertEquals(Commands.STATUS, status.cmd)
        assertEquals(0, status.retcode)
        assertEquals(mapOf("20" to JsonPrimitive(true), "21" to JsonPrimitive("colour"), "24" to JsonPrimitive("00f003e803e8")), status.dps)
        val reply = p.decode(group("v35_query_reply").string("frame").hex())
        assertEquals(mapOf("20" to JsonPrimitive(false), "22" to JsonPrimitive(500)), reply.dps)
    }

    @Test
    fun `negotiates the 3_5 session key`() {
        val v = group("v35_session")
        val p = protocol(ProtocolVersion.V35)
        val step1 = FrameCodec.unpack6699(p.startHandshake(v.string("local_nonce").toByteArray()), keyBytes, Retcode.ABSENT)
        assertEquals(Commands.SESS_KEY_NEG_START, step1.cmd)
        assertContentEquals(v.string("local_nonce").toByteArray(), step1.payload)

        val step3 = FrameCodec.unpack6699(p.finishHandshake(v.string("step2").hex()), keyBytes, Retcode.ABSENT)
        val expected3 = FrameCodec.unpack6699(v.string("step3").hex(), keyBytes, Retcode.ABSENT)
        assertEquals(Commands.SESS_KEY_NEG_FINISH, step3.cmd)
        assertContentEquals(expected3.payload, step3.payload)
        assertEquals(v.string("session_key"), p.sessionKey.hex())
    }

    @Test
    fun `negotiates the 3_4 session key and signs frames with it`() {
        val v = group("v34_session")
        val p = protocol(ProtocolVersion.V34)
        assertEquals(v.string("step1"), p.startHandshake(v.string("local_nonce").toByteArray()).hex())
        assertEquals(v.string("step3"), p.finishHandshake(v.string("step2").hex()).hex())
        assertEquals(v.string("session_key"), p.sessionKey.hex())

        p.seqno = group("v34_control")["seq"]!!.jsonPrimitive.int
        assertEquals(group("v34_control").string("frame"), p.controlFrame(mapOf("20" to JsonPrimitive(true)), 1_700_000_000).hex())
        val status = p.decode(group("v34_status").string("frame").hex())
        assertEquals(JsonPrimitive("00f003e803e8"), status.dps["24"])
    }

    @Test
    fun `rejects a wrong local key during the handshake`() {
        val p = TuyaProtocol(deviceId, "ffffffffffffffff", ProtocolVersion.V35)
        p.startHandshake(group("v35_session").string("local_nonce").toByteArray())
        assertFailsWith<TuyaProtocolException> { p.finishHandshake(group("v35_session").string("step2").hex()) }
    }

    @Test
    fun `builds 3_3 control and query frames`() {
        val p = protocol(ProtocolVersion.V33)
        p.seqno = 4
        assertEquals(group("v33_control").string("frame"), p.controlFrame(mapOf("20" to JsonPrimitive(true)), 1_700_000_000).hex())
        assertEquals(group("v33_query").string("frame"), p.queryFrame(1_700_000_000).hex())
        val status = p.decode(group("v33_status").string("frame").hex())
        assertEquals(JsonPrimitive("colour"), status.dps["21"])
    }

    @Test
    fun `decodes discovery broadcasts`() {
        val found = vectors["udp"]!!.jsonArray.map { Discovery.decode(it.jsonObject.string("frame").hex()) }
        assertEquals(listOf(
            DiscoveredDevice(deviceId, "192.168.1.40", "3.5", "keyabc"),
            DiscoveredDevice(deviceId, "192.168.1.40", "3.3", "keyabc"),
        ), found)
        assertEquals(null, Discovery.decode(byteArrayOf(1, 2, 3)))
    }

    @Test
    fun `encodes scenes exactly like the desktop app`() {
        val expected = vectors["scenes"]!!.jsonArray.associate { it.jsonObject.string("name") to it.jsonObject.string("encoded") }
        assertEquals(expected, Scenes.BUILTIN.associate { it.name to Scenes.encode(it) })
    }

    @Test
    fun `encodes DP 28 control data exactly like the desktop app`() {
        for (item in vectors["control_data"]!!.jsonArray.map { it.jsonObject }) {
            val (r, g, b) = item["rgb"]!!.jsonArray.map { it.jsonPrimitive.int }
            assertEquals(item.string("encoded"), Ds22000.controlData(r, g, b, item.string("transition") == "gradient"), "rgb $r,$g,$b")
        }
    }
}
