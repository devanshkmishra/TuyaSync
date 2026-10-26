package app.tuyasync.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import java.io.DataInputStream
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException

sealed interface ConnectionState {
    data object Disconnected : ConnectionState
    data object Connecting : ConnectionState
    data object Connected : ConnectionState
    data class Failed(val reason: String, val keyRejected: Boolean = false) : ConnectionState
}

/**
 * One persistent connection to a light on port 6668. Status pushes from the light (including changes made with the
 * wall switch or another controller) are merged into [dps]. Writes are serialised, matching the desktop driver.
 */
class TuyaClient(
    private val host: String,
    private val protocol: TuyaProtocol,
    private val scope: CoroutineScope,
    private val port: Int = 6668,
    private val connectTimeoutMs: Int = 5_000,
    private val heartbeatMs: Long = 10_000,
) {
    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    private val _dps = MutableStateFlow<Map<String, JsonPrimitive>>(emptyMap())
    val dps: StateFlow<Map<String, JsonPrimitive>> = _dps.asStateFlow()

    private val _messages = MutableSharedFlow<TuyaMessage>(extraBufferCapacity = 16)
    val messages: SharedFlow<TuyaMessage> = _messages.asSharedFlow()

    private val writeLock = Mutex()
    private var socket: Socket? = null
    private var output: OutputStream? = null
    private var jobs: List<Job> = emptyList()
    @Volatile private var lastReceived = 0L

    /** Opens the connection, performs the session handshake and requests the full status. */
    suspend fun connect() = withContext(Dispatchers.IO) {
        close()
        _state.value = ConnectionState.Connecting
        try {
            val address = InetSocketAddress(host, port)
            val socket = Socket()
            socket.tcpNoDelay = true
            socket.soTimeout = connectTimeoutMs
            socket.connect(address, connectTimeoutMs)
            val input = DataInputStream(socket.getInputStream())
            val output = socket.getOutputStream()
            if (protocol.needsSessionKey) {
                output.write(protocol.startHandshake())
                output.flush()
                val reply = try {
                    readFrame(input)
                } catch (error: java.io.EOFException) {
                    // A light that cannot decrypt the handshake simply hangs up.
                    throw TuyaProtocolException("The light hung up during the handshake; the Local Key is probably wrong", error)
                }
                output.write(protocol.finishHandshake(reply))
                output.flush()
            }
            socket.soTimeout = 0
            this@TuyaClient.socket = socket
            this@TuyaClient.output = output
            lastReceived = System.currentTimeMillis()
            _state.value = ConnectionState.Connected
            jobs = listOf(scope.launch(Dispatchers.IO) { readLoop(input) }, scope.launch { heartbeatLoop() })
            send { protocol.queryFrame() }
        } catch (error: TuyaProtocolException) {
            fail(error.message ?: "Protocol error", keyRejected = true)
            throw error
        } catch (error: IOException) {
            fail(if (error is SocketTimeoutException) "The light did not answer" else (error.message ?: "Network error"))
            throw error
        }
    }

    /** Writes data points, for example `Ds22000.power(true)`. */
    suspend fun set(dps: Map<String, JsonElement>) = send { protocol.controlFrame(dps) }

    suspend fun refresh() = send { protocol.queryFrame() }

    /** Encodes and writes under one lock so sequence numbers go out in order. */
    private suspend fun send(build: () -> ByteArray) = withContext(Dispatchers.IO) {
        writeLock.withLock {
            val out = output ?: throw IOException("Not connected")
            try {
                out.write(build())
                out.flush()
            } catch (error: IOException) {
                fail(error.message ?: "Connection lost")
                throw error
            }
        }
    }

    private suspend fun readLoop(input: DataInputStream) {
        try {
            while (scope.isActive) {
                val frame = readFrame(input)
                lastReceived = System.currentTimeMillis()
                val message = writeLock.withLock { protocol.decode(frame) }
                val update = message.dps
                if (update.isNotEmpty()) _dps.update { it + update }
                _messages.tryEmit(message)
            }
        } catch (error: Exception) {
            if (socket != null) fail(error.message ?: "Connection lost")
        }
    }

    private suspend fun heartbeatLoop() {
        while (scope.isActive && socket != null) {
            delay(heartbeatMs)
            if (System.currentTimeMillis() - lastReceived > heartbeatMs * 3) {
                fail("The light stopped answering")
                return
            }
            runCatching { send { protocol.heartbeatFrame() } }
        }
    }

    private fun readFrame(input: DataInputStream): ByteArray {
        val header = ByteArray(FrameCodec.MIN_HEADER)
        input.readFully(header, 0, 4)
        val prefix = java.nio.ByteBuffer.wrap(header).getInt(0)
        val headerSize = if (prefix == FrameCodec.PREFIX_6699) FrameCodec.HEADER_6699 else FrameCodec.HEADER_55AA
        input.readFully(header, 4, headerSize - 4)
        val total = FrameCodec.frameLength(header, headerSize) ?: throw TuyaProtocolException("Bad frame header")
        val frame = header.copyOf(total)
        input.readFully(frame, headerSize, total - headerSize)
        return frame
    }

    private fun fail(reason: String, keyRejected: Boolean = false) {
        closeSocket()
        _state.value = ConnectionState.Failed(reason, keyRejected)
    }

    private fun closeSocket() {
        val current = socket
        socket = null
        output = null
        runCatching { current?.close() }
    }

    fun close() {
        jobs.forEach { it.cancel() }
        jobs = emptyList()
        closeSocket()
        if (_state.value !is ConnectionState.Failed) _state.value = ConnectionState.Disconnected
    }
}
