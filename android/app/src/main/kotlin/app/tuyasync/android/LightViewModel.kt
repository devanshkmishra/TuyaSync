package app.tuyasync.android

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.tuyasync.core.ConnectionState
import app.tuyasync.core.DiscoveredDevice
import app.tuyasync.core.Ds22000
import app.tuyasync.core.Hsv
import app.tuyasync.core.LightProfile
import app.tuyasync.core.LightState
import app.tuyasync.core.ShareCode
import app.tuyasync.core.WorkMode
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

class LightViewModel(application: Application) : AndroidViewModel(application) {
    private val repository = (application as TuyaSyncApp).repository

    val profile: StateFlow<LightProfile?> = repository.profile
    val connection: StateFlow<ConnectionState> = repository.connection
    val dps: StateFlow<Map<String, JsonPrimitive>> = repository.dps

    private val _light = MutableStateFlow(LightState())
    /** The light as shown: the device's state, with the user's latest slider moves applied immediately. */
    val light: StateFlow<LightState> = _light.asStateFlow()

    private val _nearby = MutableStateFlow<List<DiscoveredDevice>>(emptyList())
    val nearby: StateFlow<List<DiscoveredDevice>> = _nearby.asStateFlow()
    private val _scanning = MutableStateFlow(false)
    val scanning: StateFlow<Boolean> = _scanning.asStateFlow()
    private var scanJob: Job? = null

    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()

    /** Slider writes: only the latest is kept, and at most one goes out every 90 ms. */
    private val outbox = Channel<Map<String, JsonElement>>(Channel.CONFLATED)
    private var lastTouch = 0L

    init {
        viewModelScope.launch {
            repository.dps.collect { dps ->
                // Ignore echoes for a moment after the user touches a control, so sliders don't jump back.
                if (SystemClock.elapsedRealtime() - lastTouch > 800) _light.value = LightState.from(dps)
            }
        }
        viewModelScope.launch {
            for (write in outbox) {
                repository.set(write)
                delay(90)
            }
        }
    }

    fun start() = repository.start()
    fun stop() = repository.stop()
    fun retry() = repository.retry()
    fun refresh() = viewModelScope.launch { repository.refresh() }
    fun dismissMessage() { _message.value = null }

    private fun touch() {
        lastTouch = SystemClock.elapsedRealtime()
    }

    fun setPower(on: Boolean) {
        touch()
        _light.update { it.copy(on = on) }
        viewModelScope.launch { repository.set(Ds22000.power(on)) }
    }

    fun setMode(mode: WorkMode) {
        touch()
        val current = _light.value
        _light.update { it.copy(mode = mode) }
        val write = when (mode) {
            WorkMode.WHITE -> Ds22000.white(current.brightness, current.colourTemp)
            WorkMode.COLOUR -> Ds22000.colour(current.colour)
            else -> return
        }
        viewModelScope.launch { repository.set(write) }
    }

    fun setWhite(brightness: Int, colourTemp: Int) {
        touch()
        _light.update { it.copy(mode = WorkMode.WHITE, brightness = brightness, colourTemp = colourTemp) }
        outbox.trySend(Ds22000.white(brightness, colourTemp))
    }

    fun setColour(hsv: Hsv) {
        touch()
        _light.update { it.copy(mode = WorkMode.COLOUR, colour = hsv) }
        outbox.trySend(Ds22000.colour(hsv))
    }

    fun importShareText(text: String): Boolean = try {
        repository.save(ShareCode.parse(text))
        true
    } catch (error: IllegalArgumentException) {
        _message.value = error.message ?: "That isn't a TuyaSync light profile"
        false
    }

    fun saveManual(name: String, deviceId: String, localKey: String, ip: String, protocol: String): Boolean = try {
        repository.save(LightProfile(name.ifBlank { "My light" }, deviceId.trim(), localKey, ip.trim(), protocol.trim().ifBlank { "3.5" }))
        true
    } catch (error: IllegalArgumentException) {
        _message.value = error.message
        false
    }

    fun forget() {
        stopScan()
        repository.forget()
        _light.value = LightState()
    }

    fun scanNearby() {
        if (scanJob?.isActive == true) return
        _nearby.value = emptyList()
        _scanning.value = true
        scanJob = viewModelScope.launch {
            try {
                withTimeoutOrNull(15_000) {
                    repository.nearby().collect { device ->
                        _nearby.update { list -> if (list.any { it.deviceId == device.deviceId }) list else list + device }
                    }
                }
            } catch (error: Exception) {
                _message.value = "Couldn't listen for lights: ${error.message}"
            } finally {
                _scanning.value = false
            }
        }
    }

    fun stopScan() {
        scanJob?.cancel()
        _scanning.value = false
    }
}
