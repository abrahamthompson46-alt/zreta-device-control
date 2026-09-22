package com.zreta.devicecontrol.network

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/**
 * UDP-only upstream DNS forwarder.
 *
 * TCP DNS, DoH, and DoT are **not** implemented in this slice — document as a known gap.
 * The socket must be [protect]ed so it is not captured by the VPN TUN.
 */
class UdpDnsUpstream(
    private val protect: (DatagramSocket) -> Boolean,
    private val servers: List<InetSocketAddress> = DEFAULT_SERVERS,
    private val timeoutMs: Int = 2_500,
) {
    fun query(dnsPayload: ByteArray): ByteArray? {
        if (dnsPayload.isEmpty() || dnsPayload.size > DnsPacketCodec.MAX_UDP_DNS_PAYLOAD) return null
        for (server in servers) {
            val result = queryOne(server, dnsPayload)
            if (result != null) return result
        }
        return null
    }

    private fun queryOne(server: InetSocketAddress, dnsPayload: ByteArray): ByteArray? {
        var socket: DatagramSocket? = null
        return try {
            socket = DatagramSocket()
            if (!protect(socket)) {
                socket.close()
                return null
            }
            socket.soTimeout = timeoutMs
            val send = DatagramPacket(dnsPayload, dnsPayload.size, server)
            socket.send(send)
            val buf = ByteArray(DnsPacketCodec.MAX_UDP_DNS_PAYLOAD)
            val recv = DatagramPacket(buf, buf.size)
            socket.receive(recv)
            if (recv.length <= 0 || recv.length > DnsPacketCodec.MAX_UDP_DNS_PAYLOAD) return null
            buf.copyOf(recv.length)
        } catch (_: SocketTimeoutException) {
            null
        } catch (_: Exception) {
            null
        } finally {
            try {
                socket?.close()
            } catch (_: Exception) {
            }
        }
    }

    companion object {
        val DEFAULT_SERVERS: List<InetSocketAddress> = listOf(
            InetSocketAddress(InetAddress.getByName("8.8.8.8"), 53),
            InetSocketAddress(InetAddress.getByName("1.1.1.1"), 53),
        )
    }
}
