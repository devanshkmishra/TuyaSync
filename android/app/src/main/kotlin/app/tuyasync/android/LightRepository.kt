package app.tuyasync.android

import app.tuyasync.core.ConnectionState
import app.tuyasync.core.DiscoveredDevice
import app.tuyasync.core.LightProfile
import app.tuyasync.core.ProtocolVersion
import app.tuyasync.core.TuyaClient
import app.tuyasync.core.TuyaProtocol
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/**
 * Owns the saved light and its connection. While started, it keeps one connection open, rediscovers the light's IP
 * on the Wi-Fi when the connection drops, and backs off between attempts.
 */
class LightRepository(private val store: ProfileStore, private val discovery: LanDiscovery) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _profile = MutableStateFlow(store.load())
    val profile: StateFlow<LightProfile?> = _profile.asStateFlow()

    private val _connection = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val connection: StateFlow<ConnectionState> = _connection.asStateFlow()

    private val _dps = MutableStateFlow<Map<String, JsonPrimitive>>(emptyMap())
    val dps: StateFlow<Map<String, JsonPrimitive>> = _dps.asStateFlow()

    private var client: TuyaClient? = null
    private var session: Job? = null

    fun save(profile: LightProfile) {
        stop()
        store.save(profile)
        _profile.value = profile
        _dps.value = emptyMap()
        start()
    }

    fun forget() {
        stop()
        store.clear()
        _profile.value = null
        _dps.value = emptyMap()
    }

    fun start() {
        if (session?.isActive == true || _profile.value == null) return
        session = scope.launch { runSession() }
    }

    fun stop() {
        session?.cancel()
        session = null
        client?.close()
        client = null
        _connection.value = ConnectionState.Disconnected
    }

    fun retry() {
        stop()
        start()
    }

    suspend fun set(dps: Map<String, JsonElement>) {
        runCatching { client?.set(dps) }
    }

    suspend fun refresh() {
        runCatching { client?.refresh() }
    }

    fun nearby(): Flow<DiscoveredDevice> = discovery.devices()

    private suspend fun runSession() {
        var backoff = 1_000L
        while (currentCoroutineContext().isActive) {
            var profile = _profile.value ?: return
            if (profile.ipAddress.isBlank()) {
                _connection.value = ConnectionState.Connecting
                profile = rediscover(profile) ?: run {
                    _connection.value = ConnectionState.Failed("Can't find the light on this Wi-Fi")
                    delay(backoff)
                    backoff = (backoff * 2).coerceAtMost(30_000)
                    null
                } ?: continue
            }
            val client = TuyaClient(profile.ipAddress, TuyaProtocol(profile.deviceId, profile.localKey, profile.version), scope)
            this.client = client
            val mirror = scope.launch {
                launch { client.dps.collect { _dps.value = it } }
                client.state.collect { _connection.value = it }
            }
            try {
                client.connect()
                backoff = 1_000L
                client.state.first { it is ConnectionState.Failed }
            } catch (error: CancellationException) {
                mirror.cancel()
                client.close()
                throw error
            } catch (_: Exception) {
                // The failure is reported through client.state.
            }
            mirror.cancel()
            val failure = client.state.value
            client.close()
            _connection.value = failure
            if (failure is ConnectionState.Failed && failure.keyRejected) return
            // The router may have given the light a new address; look for it before retrying.
            val moved = rediscover(profile)
            if (moved == null || moved.ipAddress == profile.ipAddress) {
                delay(backoff)
                backoff = (backoff * 2).coerceAtMost(30_000)
            }
        }
    }

    /** Finds the light's current IP and protocol from its broadcasts and saves them if they changed. */
    private suspend fun rediscover(profile: LightProfile): LightProfile? {
        val found = withTimeoutOrNull(10_000) {
            runCatching { discovery.devices().first { it.deviceId == profile.deviceId } }.getOrNull()
        } ?: return null
        val version = runCatching { ProtocolVersion.parse(found.version).label }.getOrDefault(profile.protocol)
        val updated = profile.copy(ipAddress = found.ip, protocol = version)
        if (updated != profile) {
            store.save(updated)
            _profile.value = updated
        }
        return updated
    }
}
