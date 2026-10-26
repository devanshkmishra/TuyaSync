package app.tuyasync.android

import android.content.Context
import android.net.ConnectivityManager
import android.net.wifi.WifiManager
import app.tuyasync.core.DiscoveredDevice
import app.tuyasync.core.Discovery
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.onCompletion
import kotlinx.coroutines.flow.onStart
import java.net.Inet4Address
import java.net.InetAddress

/** Wraps core discovery with what Android needs: a multicast lock and the Wi-Fi broadcast address. */
class LanDiscovery(context: Context) {
    private val wifi = context.applicationContext.getSystemService(WifiManager::class.java)
    private val connectivity = context.applicationContext.getSystemService(ConnectivityManager::class.java)

    fun devices(): Flow<DiscoveredDevice> {
        val lock = wifi.createMulticastLock("tuyasync-discovery").apply { setReferenceCounted(false) }
        val (localIp, broadcast) = localAddresses() ?: (null to null)
        return Discovery.listen(broadcast, localIp)
            .onStart { lock.acquire() }
            .onCompletion { lock.release() }
    }

    /** This phone's IPv4 address on the current network and that network's broadcast address. */
    private fun localAddresses(): Pair<String, InetAddress>? {
        val properties = connectivity.getLinkProperties(connectivity.activeNetwork) ?: return null
        val link = properties.linkAddresses.firstOrNull { it.address is Inet4Address } ?: return null
        val address = link.address.address
        val prefix = link.prefixLength
        val mask = if (prefix == 0) 0 else -1 shl (32 - prefix)
        val ip = ((address[0].toInt() and 0xff) shl 24) or ((address[1].toInt() and 0xff) shl 16) or
            ((address[2].toInt() and 0xff) shl 8) or (address[3].toInt() and 0xff)
        val broadcast = ip or mask.inv()
        val bytes = byteArrayOf((broadcast ushr 24).toByte(), (broadcast ushr 16).toByte(), (broadcast ushr 8).toByte(), broadcast.toByte())
        return link.address.hostAddress!! to InetAddress.getByAddress(bytes)
    }
}
