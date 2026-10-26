package app.tuyasync.core

import kotlinx.serialization.json.JsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ModelTest {
    @Test
    fun `reads the desktop share code`() {
        // Output of screensync.phone_share.share_payload for a saved profile.
        val text = """{"format":"tuyasync-light-profile","version":2,"profile":{"profile_id":"abc","name":"Desk batten",""" +
            """"device_id":"bf1234567890abcdefgh","ip_address":"192.168.1.40","protocol":3.5,"local_key":"0123456789abcdef"}}"""
        assertEquals(
            LightProfile("Desk batten", "bf1234567890abcdefgh", "0123456789abcdef", "192.168.1.40", "3.5"),
            ShareCode.parse(text),
        )
    }

    @Test
    fun `round trips a profile and rejects bad input`() {
        val profile = LightProfile("Batten", "bf00", "0123456789abcdef", "", "3.4")
        assertEquals(profile, ShareCode.parse(profile.toJson().toString()))
        assertFailsWith<IllegalArgumentException> { ShareCode.parse("hello") }
        assertFailsWith<IllegalArgumentException> { ShareCode.parse("""{"format":"other","version":2}""") }
        assertFailsWith<IllegalArgumentException> { LightProfile("x", "bf00", "short") }
    }

    @Test
    fun `parses light state from data points`() {
        val state = LightState.from(mapOf(
            "20" to JsonPrimitive(true), "21" to JsonPrimitive("white"), "22" to JsonPrimitive(640),
            "23" to JsonPrimitive(120), "24" to JsonPrimitive("007803e801f4"),
        ))
        assertEquals(LightState(true, WorkMode.WHITE, 640, 120, Hsv(120, 1000, 500)), state)
    }

    @Test
    fun `clamps writes to the light's ranges`() {
        assertEquals(
            mapOf("21" to JsonPrimitive("white"), "22" to JsonPrimitive(10), "23" to JsonPrimitive(1000)),
            Ds22000.white(0, 4000),
        )
        assertEquals(mapOf("21" to JsonPrimitive("colour"), "24" to JsonPrimitive("016803e8000a")), Ds22000.colour(Hsv(360, 1000, 0)))
    }
}
