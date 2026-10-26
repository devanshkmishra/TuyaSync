package app.tuyasync.core

import kotlin.math.round

/** One colour stop in a scene: an RGB colour, its brightness (0..1000) and timings in seconds (0..100). */
data class SceneStop(
    val r: Int,
    val g: Int,
    val b: Int,
    val brightness: Int = 700,
    val transitionSeconds: Double = 4.0,
    val holdSeconds: Double = 0.0,
)

data class ScenePreset(val name: String, val stops: List<SceneStop>)

/** Port of the desktop app's DP 25 scene compiler (screensync/scenes.py); both must produce identical strings. */
object Scenes {
    private fun stop(r: Int, g: Int, b: Int, brightness: Int, transition: Double) = SceneStop(r, g, b, brightness, transition)

    val BUILTIN = listOf(
        ScenePreset("Vaporwave", listOf(stop(255, 35, 165, 720, 7.0), stop(142, 45, 255, 740, 7.0), stop(38, 215, 255, 700, 7.0), stop(95, 35, 210, 700, 7.0))),
        ScenePreset("Cyberpunk", listOf(stop(15, 50, 225, 720, 4.0), stop(130, 35, 255, 760, 4.0), stop(255, 25, 155, 740, 4.0))),
        ScenePreset("Aurora", listOf(stop(5, 95, 105, 580, 9.0), stop(15, 210, 125, 620, 9.0), stop(30, 225, 225, 600, 9.0), stop(125, 75, 235, 560, 9.0))),
        ScenePreset("Sunset", listOf(stop(255, 170, 35, 680, 5.0), stop(255, 90, 35, 720, 5.0), stop(245, 65, 105, 700, 5.0), stop(150, 35, 180, 620, 5.0))),
        ScenePreset("Ocean", listOf(stop(10, 30, 115, 620, 7.0), stop(20, 90, 220, 680, 7.0), stop(20, 190, 205, 650, 7.0), stop(0, 215, 255, 650, 7.0))),
        ScenePreset("Dream", listOf(stop(150, 120, 230, 450, 8.0), stop(245, 145, 190, 460, 8.0), stop(135, 220, 230, 460, 8.0))),
        ScenePreset("City Pop", listOf(stop(230, 30, 170, 720, 3.0), stop(255, 120, 190, 700, 3.0), stop(20, 220, 240, 720, 3.0), stop(130, 40, 235, 720, 3.0))),
    )

    /** Encodes a scene as the DS22000's DP 25 scene_data_v2 string. */
    fun encode(scene: ScenePreset, sceneNumber: Int = 1, maxBrightness: Int = 1000): String {
        require(sceneNumber in 1..8) { "The DS22000 accepts scene numbers from 1 to 8" }
        require(scene.stops.isNotEmpty()) { "A scene must contain at least one colour stop" }
        require(scene.stops.size <= 64) { "A scene cannot contain more than 64 stops" }
        val ceiling = maxBrightness.coerceIn(0, 1000)
        val out = StringBuilder("%02x".format(sceneNumber))
        for (stop in scene.stops) {
            val (hue, saturation, value) = pythonHsv(stop.r, stop.g, stop.b)
            val level = minOf(ceiling, pyRound(value * stop.brightness.coerceIn(0, 1000) / 1000.0))
            val duration = pyRound(stop.transitionSeconds.coerceIn(0.0, 100.0))
            val hold = pyRound(stop.holdSeconds.coerceIn(0.0, 100.0))
            val mode = if (duration == 0) 0 else 2 // static or gradient
            out.append("%02x%02x%02x%04x%04x%04x%04x%04x".format(
                hold, duration, mode, hue.coerceIn(0, 360), saturation.coerceIn(0, 1000), level.coerceIn(0, 1000), 0, 0,
            ))
        }
        return out.toString()
    }

    /** colorsys.rgb_to_hsv scaled and rounded the way scenes.py does it (round half to even). */
    private fun pythonHsv(r: Int, g: Int, b: Int): Triple<Int, Int, Int> {
        val red = r / 255.0; val green = g / 255.0; val blue = b / 255.0
        val max = maxOf(red, green, blue); val min = minOf(red, green, blue)
        if (min == max) return Triple(0, 0, pyRound(max * 1000))
        val saturation = (max - min) / max
        val rc = (max - red) / (max - min); val gc = (max - green) / (max - min); val bc = (max - blue) / (max - min)
        val h = when (max) {
            red -> bc - gc
            green -> 2.0 + rc - bc
            else -> 4.0 + gc - rc
        }
        val hue = (h / 6.0).mod(1.0)
        return Triple(pyRound(hue * 360), pyRound(saturation * 1000), pyRound(max * 1000))
    }

    private fun pyRound(value: Double): Int = round(value).toInt() // ties to even, like Python
}
