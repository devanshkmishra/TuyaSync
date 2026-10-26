package app.tuyasync.core

import java.nio.ByteBuffer

/** Tuya LAN command numbers used by this app. */
object Commands {
    const val SESS_KEY_NEG_START = 0x03
    const val SESS_KEY_NEG_RESP = 0x04
    const val SESS_KEY_NEG_FINISH = 0x05
    const val CONTROL = 0x07
    const val STATUS = 0x08
    const val HEART_BEAT = 0x09
    const val DP_QUERY = 0x0a
    const val CONTROL_NEW = 0x0d
    const val DP_QUERY_NEW = 0x10
    const val UPDATEDPS = 0x12
    const val UDP_NEW = 0x13
    const val BOARDCAST_LPV34 = 0x23
    const val REQ_DEVINFO = 0x25

    /** Commands sent without the "3.x" version header. */
    val NO_VERSION_HEADER = setOf(
        DP_QUERY, DP_QUERY_NEW, UPDATEDPS, HEART_BEAT, SESS_KEY_NEG_START, SESS_KEY_NEG_RESP, SESS_KEY_NEG_FINISH, 0x40,
    )
}

class TuyaProtocolException(message: String, cause: Throwable? = null) : Exception(message, cause)

class TuyaFrame(val seqno: Int, val cmd: Int, val retcode: Int?, val payload: ByteArray)

/** How a received frame carries its 4-byte return code. */
enum class Retcode { PRESENT, ABSENT, DETECT }

/** Byte-level packing of the two Tuya frame formats: 0x55AA (3.1 to 3.4) and 0x6699 (3.5). */
object FrameCodec {
    const val PREFIX_55AA = 0x000055AA
    const val SUFFIX_55AA = 0x0000AA55
    const val PREFIX_6699 = 0x00006699
    const val SUFFIX_6699 = 0x00009966
    const val HEADER_55AA = 16
    const val HEADER_6699 = 18
    const val MAX_PAYLOAD = 64 * 1024

    fun pack55AA(seqno: Int, cmd: Int, payload: ByteArray, hmacKey: ByteArray? = null): ByteArray {
        val endLength = if (hmacKey != null) 36 else 8
        val buffer = ByteBuffer.allocate(HEADER_55AA + payload.size + endLength)
        buffer.putInt(PREFIX_55AA).putInt(seqno).putInt(cmd).putInt(payload.size + endLength).put(payload)
        val signed = buffer.array().copyOfRange(0, HEADER_55AA + payload.size)
        if (hmacKey != null) buffer.put(Crypto.hmacSha256(hmacKey, signed)) else buffer.putInt(Crypto.crc32(signed).toInt())
        buffer.putInt(SUFFIX_55AA)
        return buffer.array()
    }

    fun pack6699(seqno: Int, cmd: Int, payload: ByteArray, key: ByteArray, iv: ByteArray, retcode: Int? = null): ByteArray {
        require(iv.size == Crypto.GCM_IV_BYTES) { "GCM IV must be 12 bytes" }
        val raw = if (retcode != null) ByteBuffer.allocate(4 + payload.size).putInt(retcode).put(payload).array() else payload
        val header = ByteBuffer.allocate(HEADER_6699)
            .putInt(PREFIX_6699).putShort(0).putInt(seqno).putInt(cmd)
            .putInt(raw.size + Crypto.GCM_IV_BYTES + Crypto.GCM_TAG_BYTES)
            .array()
        val sealed = Crypto.gcmEncrypt(key, iv, raw, aad = header.copyOfRange(4, HEADER_6699))
        return ByteBuffer.allocate(header.size + iv.size + sealed.size + 4)
            .put(header).put(iv).put(sealed).putInt(SUFFIX_6699).array()
    }

    /** Bytes needed to read a frame's header and learn its full size. */
    const val MIN_HEADER = HEADER_6699

    /** Total length of the frame whose header starts [data], or null if more header bytes are needed. */
    fun frameLength(data: ByteArray, available: Int = data.size): Int? {
        if (available < 4) return null
        val buffer = ByteBuffer.wrap(data, 0, available)
        return when (val prefix = buffer.getInt(0)) {
            PREFIX_55AA -> if (available < HEADER_55AA) null else HEADER_55AA + checkedLength(buffer.getInt(12))
            PREFIX_6699 -> if (available < HEADER_6699) null else HEADER_6699 + checkedLength(buffer.getInt(14)) + 4
            else -> throw TuyaProtocolException("Unexpected frame prefix %08X".format(prefix))
        }
    }

    private fun checkedLength(length: Int): Int {
        if (length < 0 || length > MAX_PAYLOAD) throw TuyaProtocolException("Implausible frame length $length")
        return length
    }

    fun unpack55AA(frame: ByteArray, hmacKey: ByteArray? = null, retcode: Retcode = Retcode.PRESENT): TuyaFrame {
        val total = frameLength(frame) ?: throw TuyaProtocolException("Truncated frame header")
        if (frame.size < total) throw TuyaProtocolException("Truncated frame")
        val buffer = ByteBuffer.wrap(frame)
        val endLength = if (hmacKey != null) 36 else 8
        val signedEnd = total - endLength
        if (signedEnd < HEADER_55AA) throw TuyaProtocolException("Frame too short")
        val good = if (hmacKey != null) {
            Crypto.hmacSha256(hmacKey, frame.copyOfRange(0, signedEnd)).contentEquals(frame.copyOfRange(signedEnd, signedEnd + 32))
        } else {
            Crypto.crc32(frame, signedEnd).toInt() == buffer.getInt(signedEnd)
        }
        if (!good) throw TuyaProtocolException(if (hmacKey != null) "HMAC check failed (wrong local key?)" else "CRC check failed")
        var body = frame.copyOfRange(HEADER_55AA, signedEnd)
        var code: Int? = null
        val hasRetcode = when (retcode) {
            Retcode.PRESENT -> true
            Retcode.ABSENT -> false
            Retcode.DETECT -> body.size >= 4 && body[0] != '{'.code.toByte() && body[0] == 0.toByte()
        }
        if (hasRetcode && body.size >= 4) {
            code = ByteBuffer.wrap(body).getInt(0)
            body = body.copyOfRange(4, body.size)
        }
        return TuyaFrame(buffer.getInt(4), buffer.getInt(8), code, body)
    }

    fun unpack6699(frame: ByteArray, key: ByteArray, retcode: Retcode = Retcode.PRESENT): TuyaFrame {
        val total = frameLength(frame) ?: throw TuyaProtocolException("Truncated frame header")
        if (frame.size < total || total < HEADER_6699 + Crypto.GCM_IV_BYTES + Crypto.GCM_TAG_BYTES + 4) {
            throw TuyaProtocolException("Truncated frame")
        }
        val buffer = ByteBuffer.wrap(frame)
        val iv = frame.copyOfRange(HEADER_6699, HEADER_6699 + Crypto.GCM_IV_BYTES)
        val sealed = frame.copyOfRange(HEADER_6699 + Crypto.GCM_IV_BYTES, total - 4)
        var body = try {
            Crypto.gcmDecrypt(key, iv, sealed, aad = frame.copyOfRange(4, HEADER_6699))
        } catch (error: Exception) {
            throw TuyaProtocolException("Could not decrypt frame (wrong local key?)", error)
        }
        var code: Int? = null
        val hasRetcode = when (retcode) {
            Retcode.PRESENT -> true
            Retcode.ABSENT -> false
            Retcode.DETECT -> body.size > 4 && body[0] != '{'.code.toByte() && body[4] == '{'.code.toByte()
        }
        if (hasRetcode && body.size >= 4) {
            code = ByteBuffer.wrap(body).getInt(0)
            body = body.copyOfRange(4, body.size)
        }
        return TuyaFrame(buffer.getInt(6), buffer.getInt(10), code, body)
    }

    fun isFrame6699(frame: ByteArray): Boolean = frame.size >= 4 && ByteBuffer.wrap(frame).getInt(0) == PREFIX_6699
}
