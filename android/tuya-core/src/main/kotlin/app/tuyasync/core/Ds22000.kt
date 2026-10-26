package app.tuyasync.core

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlin.math.roundToInt

/** Data points of the Wipro DS22000 batten (Tuya "dj" lighting schema, v2 DPs). */
object Dp {
    const val SWITCH = "20"
    const val WORK_MODE = "21"
    const val BRIGHTNESS = "22"
    const val COLOUR_TEMP = "23"
    const val COLOUR = "24"
    const val SCENE = "25"
    const val COUNTDOWN = "26"
    const val MUSIC = "27"
    const val CONTROL = "28"
    const val SLEEP = "31"
    const val WAKE_UP = "32"
    const val POWER_MEMORY = "33"
    const val DO_NOT_DISTURB = "34"

    val NAMES = mapOf(
        SWITCH to "Power", WORK_MODE to "Mode", BRIGHTNESS to "White brightness", COLOUR_TEMP to "Colour temperature",
        COLOUR to "Colour (HSV)", SCENE to "Scene", COUNTDOWN to "Countdown (s)", MUSIC to "Music data",
        CONTROL to "Live control", SLEEP to "Sleep routine", WAKE_UP to "Wake-up routine",
        POWER_MEMORY to "Power-on behaviour", DO_NOT_DISTURB to "Do not disturb",
    )
}

enum class WorkMode(val wire: String) {
    WHITE("white"), COLOUR("colour"), SCENE("scene"), MUSIC("music");

    companion object {
        fun fromWire(value: String?): WorkMode? = entries.firstOrNull { it.wire == value }
    }
}

/** Hue 0..360, saturation and value 0..1000, as the light stores them. */
data class Hsv(val hue: Int, val saturation: Int, val value: Int) {
    fun encode(): String = "%04x%04x%04x".format(hue.coerceIn(0, 360), saturation.coerceIn(0, 1000), value.coerceIn(0, 1000))

    companion object {
        fun decode(hex: String): Hsv? {
            if (hex.length != 12) return null
            return runCatching {
                Hsv(hex.substring(0, 4).toInt(16), hex.substring(4, 8).toInt(16), hex.substring(8, 12).toInt(16))
            }.getOrNull()
        }

        fun fromRgb(r: Int, g: Int, b: Int): Hsv {
            val red = r / 255.0; val green = g / 255.0; val blue = b / 255.0
            val max = maxOf(red, green, blue); val min = minOf(red, green, blue); val delta = max - min
            val hue = when {
                delta == 0.0 -> 0.0
                max == red -> ((green - blue) / delta).mod(6.0)
                max == green -> (blue - red) / delta + 2
                else -> (red - green) / delta + 4
            } / 6.0
            val saturation = if (max == 0.0) 0.0 else delta / max
            return Hsv((hue * 360).toInt(), (saturation * 1000).toInt(), (max * 1000).toInt())
        }
    }
}

/** What the app shows, read from the light's data points. */
data class LightState(
    val on: Boolean = false,
    val mode: WorkMode? = null,
    val brightness: Int = 1000,
    val colourTemp: Int = 500,
    val colour: Hsv = Hsv(0, 1000, 1000),
    val countdownSeconds: Int = 0,
) {
    companion object {
        fun from(dps: Map<String, JsonPrimitive>): LightState {
            val base = LightState()
            return LightState(
                on = dps[Dp.SWITCH]?.booleanOrNull ?: base.on,
                mode = WorkMode.fromWire(dps[Dp.WORK_MODE]?.content),
                brightness = dps[Dp.BRIGHTNESS]?.intOrNull ?: base.brightness,
                colourTemp = dps[Dp.COLOUR_TEMP]?.intOrNull ?: base.colourTemp,
                colour = dps[Dp.COLOUR]?.content?.let(Hsv::decode) ?: base.colour,
                countdownSeconds = dps[Dp.COUNTDOWN]?.intOrNull ?: base.countdownSeconds,
            )
        }
    }
}

/** Builds the data-point writes for each control. */
object Ds22000 {
    const val MIN_BRIGHTNESS = 10
    const val MAX_LEVEL = 1000

    fun power(on: Boolean): Map<String, JsonElement> = mapOf(Dp.SWITCH to JsonPrimitive(on))

    fun white(brightness: Int, colourTemp: Int): Map<String, JsonElement> = mapOf(
        Dp.WORK_MODE to JsonPrimitive(WorkMode.WHITE.wire),
        Dp.BRIGHTNESS to JsonPrimitive(brightness.coerceIn(MIN_BRIGHTNESS, MAX_LEVEL)),
        Dp.COLOUR_TEMP to JsonPrimitive(colourTemp.coerceIn(0, MAX_LEVEL)),
    )

    fun colour(hsv: Hsv): Map<String, JsonElement> = mapOf(
        Dp.WORK_MODE to JsonPrimitive(WorkMode.COLOUR.wire),
        Dp.COLOUR to JsonPrimitive(hsv.copy(value = hsv.value.coerceIn(MIN_BRIGHTNESS, MAX_LEVEL)).encode()),
    )

    fun countdown(seconds: Int): Map<String, JsonElement> = mapOf(Dp.COUNTDOWN to JsonPrimitive(seconds.coerceIn(0, 86_400)))

    /**
     * DP 28 live-control frame, as the desktop app streams it: mode nibble (0 direct, 1 gradient), HSV, then white
     * brightness and temperature. The light shows it immediately without storing it.
     */
    fun controlData(r: Int, g: Int, b: Int, gradient: Boolean = true): String {
        val hsv = Hsv.fromRgb(r, g, b)
        return "%x%04x%04x%04x00000000".format(if (gradient) 1 else 0, hsv.hue, hsv.saturation, hsv.value)
    }

    fun percent(level: Int): Int = (level / 10.0).roundToInt()
}
