package com.zreta.devicecontrol.network

import com.zreta.devicecontrol.policy.enforcement.DomainBlocklist
import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicReference

/**
 * Synthetic DNS endpoints and narrow routes for the local DNS filter VPN.
 *
 * Routes are intentionally **not** a full internet tunnel:
 * - IPv4 route: 10.255.255.1/32 only (synthetic DNS)
 * - IPv6 route: fd00:5a74::1/128 only (synthetic DNS)
 * - No 0.0.0.0/0 or ::/0
 *
 * System DNS is pointed at the synthetic addresses via [android.net.VpnService.Builder.addDnsServer].
 * Non-DNS traffic stays on the underlying network.
 */
object DnsFilterAddresses {
    const val IPV4_DNS = "10.255.255.1"
    const val IPV4_TUN = "10.255.255.2"
    const val IPV6_DNS = "fd00:5a74::1"
    const val IPV6_TUN = "fd00:5a74::2"
    const val SESSION_NAME = "Zreta DNS Filter"
    const val MAX_TUN_PACKET = 1500
}

/**
 * Pure decision/response layer used by the TUN loop and JVM tests.
 * Upstream forwarding is injected; this class never opens sockets.
 */
class DnsFilterEngine(
    blockedDomains: List<String> = emptyList(),
) {
    private val blocked = AtomicReference(blockedDomains.toList())

    fun updateBlocked(domains: List<String>) {
        // Expect already-canonical Phase 5.1A list (sorted, validated).
        blocked.set(domains.toList())
    }

    fun currentBlocked(): List<String> = blocked.get()

    /**
     * @param dnsPayload UDP DNS message bytes
     * @param forward invoked only for allowed queries; returns upstream DNS response or null on failure
     * @return DNS response payload, or null to drop (fail-open ignore)
     */
    fun handleDnsPayload(
        dnsPayload: ByteArray,
        forward: (ByteArray) -> ByteArray?,
    ): ByteArray? {
        val query = DnsPacketCodec.parseQuery(dnsPayload) ?: return null
        return if (DomainBlocklist.isBlocked(query.qname, blocked.get())) {
            DnsPacketCodec.buildNxDomain(dnsPayload, 0, dnsPayload.size, query)
        } else {
            forward(dnsPayload)
        }
    }
}

/**
 * Parses IPv4/IPv6 UDP packets addressed to the synthetic DNS endpoints and builds responses.
 */
object DnsTunPacketHandler {
    private val dns4: ByteArray = InetAddress.getByName(DnsFilterAddresses.IPV4_DNS).address
    private val dns6: ByteArray = InetAddress.getByName(DnsFilterAddresses.IPV6_DNS).address
    private val tun4: ByteArray = InetAddress.getByName(DnsFilterAddresses.IPV4_TUN).address
    private val tun6: ByteArray = InetAddress.getByName(DnsFilterAddresses.IPV6_TUN).address

    /**
     * @return full IP packet to write to TUN, or null to ignore (fail-open)
     */
    fun handle(
        packet: ByteArray,
        length: Int,
        engine: DnsFilterEngine,
        forwardDns: (ByteArray) -> ByteArray?,
    ): ByteArray? {
        if (length < 20 || length > DnsFilterAddresses.MAX_TUN_PACKET) return null
        val version = (packet[0].toInt() ushr 4) and 0x0f
        return when (version) {
            4 -> handleIpv4(packet, length, engine, forwardDns)
            6 -> handleIpv6(packet, length, engine, forwardDns)
            else -> null
        }
    }

    private fun handleIpv4(
        packet: ByteArray,
        length: Int,
        engine: DnsFilterEngine,
        forwardDns: (ByteArray) -> ByteArray?,
    ): ByteArray? {
        val ihl = (packet[0].toInt() and 0x0f) * 4
        if (ihl < 20 || length < ihl + 8) return null
        if ((packet[9].toInt() and 0xff) != 17) return null // UDP
        if (!addressEquals(packet, 16, dns4)) return null // dest = synthetic DNS

        val udpOff = ihl
        val dstPort = ((packet[udpOff + 2].toInt() and 0xff) shl 8) or (packet[udpOff + 3].toInt() and 0xff)
        if (dstPort != 53) return null
        val udpLen = ((packet[udpOff + 4].toInt() and 0xff) shl 8) or (packet[udpOff + 5].toInt() and 0xff)
        if (udpLen < 8 || udpOff + udpLen > length) return null
        val dnsLen = udpLen - 8
        if (dnsLen <= 0 || dnsLen > DnsPacketCodec.MAX_UDP_DNS_PAYLOAD) return null
        val dnsPayload = packet.copyOfRange(udpOff + 8, udpOff + 8 + dnsLen)
        val dnsResponse = engine.handleDnsPayload(dnsPayload, forwardDns) ?: return null

        val srcPort = ((packet[udpOff].toInt() and 0xff) shl 8) or (packet[udpOff + 1].toInt() and 0xff)
        val srcIp = packet.copyOfRange(12, 16)
        return buildIpv4UdpResponse(
            srcIp = dns4,
            dstIp = srcIp,
            srcPort = 53,
            dstPort = srcPort,
            dnsPayload = dnsResponse,
        )
    }

    private fun handleIpv6(
        packet: ByteArray,
        length: Int,
        engine: DnsFilterEngine,
        forwardDns: (ByteArray) -> ByteArray?,
    ): ByteArray? {
        if (length < 40 + 8) return null
        // Only handle UDP directly in next-header (no extension headers in this slice).
        if ((packet[6].toInt() and 0xff) != 17) return null
        if (!addressEquals(packet, 24, dns6)) return null
        val udpOff = 40
        val dstPort = ((packet[udpOff + 2].toInt() and 0xff) shl 8) or (packet[udpOff + 3].toInt() and 0xff)
        if (dstPort != 53) return null
        val udpLen = ((packet[udpOff + 4].toInt() and 0xff) shl 8) or (packet[udpOff + 5].toInt() and 0xff)
        if (udpLen < 8 || udpOff + udpLen > length) return null
        val dnsLen = udpLen - 8
        if (dnsLen <= 0 || dnsLen > DnsPacketCodec.MAX_UDP_DNS_PAYLOAD) return null
        val dnsPayload = packet.copyOfRange(udpOff + 8, udpOff + 8 + dnsLen)
        val dnsResponse = engine.handleDnsPayload(dnsPayload, forwardDns) ?: return null
        val srcPort = ((packet[udpOff].toInt() and 0xff) shl 8) or (packet[udpOff + 1].toInt() and 0xff)
        val srcIp = packet.copyOfRange(8, 24)
        return buildIpv6UdpResponse(
            srcIp = dns6,
            dstIp = srcIp,
            srcPort = 53,
            dstPort = srcPort,
            dnsPayload = dnsResponse,
        )
    }

    private fun addressEquals(packet: ByteArray, offset: Int, expected: ByteArray): Boolean {
        if (offset + expected.size > packet.size) return false
        for (i in expected.indices) {
            if (packet[offset + i] != expected[i]) return false
        }
        return true
    }

    private fun buildIpv4UdpResponse(
        srcIp: ByteArray,
        dstIp: ByteArray,
        srcPort: Int,
        dstPort: Int,
        dnsPayload: ByteArray,
    ): ByteArray {
        val udpLen = 8 + dnsPayload.size
        val total = 20 + udpLen
        val out = ByteArray(total)
        out[0] = 0x45
        out[1] = 0
        out[2] = ((total shr 8) and 0xff).toByte()
        out[3] = (total and 0xff).toByte()
        out[4] = 0
        out[5] = 0
        out[6] = 0x40 // DF
        out[7] = 0
        out[8] = 64
        out[9] = 17
        // checksum later
        System.arraycopy(srcIp, 0, out, 12, 4)
        System.arraycopy(dstIp, 0, out, 16, 4)
        val csum = ipv4HeaderChecksum(out, 0, 20)
        out[10] = ((csum shr 8) and 0xff).toByte()
        out[11] = (csum and 0xff).toByte()

        out[20] = ((srcPort shr 8) and 0xff).toByte()
        out[21] = (srcPort and 0xff).toByte()
        out[22] = ((dstPort shr 8) and 0xff).toByte()
        out[23] = (dstPort and 0xff).toByte()
        out[24] = ((udpLen shr 8) and 0xff).toByte()
        out[25] = (udpLen and 0xff).toByte()
        out[26] = 0 // UDP checksum optional for IPv4
        out[27] = 0
        System.arraycopy(dnsPayload, 0, out, 28, dnsPayload.size)
        return out
    }

    private fun buildIpv6UdpResponse(
        srcIp: ByteArray,
        dstIp: ByteArray,
        srcPort: Int,
        dstPort: Int,
        dnsPayload: ByteArray,
    ): ByteArray {
        val udpLen = 8 + dnsPayload.size
        val total = 40 + udpLen
        val out = ByteArray(total)
        out[0] = 0x60
        out[1] = 0
        out[2] = 0
        out[3] = 0
        out[4] = ((udpLen shr 8) and 0xff).toByte()
        out[5] = (udpLen and 0xff).toByte()
        out[6] = 17
        out[7] = 64
        System.arraycopy(srcIp, 0, out, 8, 16)
        System.arraycopy(dstIp, 0, out, 24, 16)
        out[40] = ((srcPort shr 8) and 0xff).toByte()
        out[41] = (srcPort and 0xff).toByte()
        out[42] = ((dstPort shr 8) and 0xff).toByte()
        out[43] = (dstPort and 0xff).toByte()
        out[44] = ((udpLen shr 8) and 0xff).toByte()
        out[45] = (udpLen and 0xff).toByte()
        out[46] = 0
        out[47] = 0
        System.arraycopy(dnsPayload, 0, out, 48, dnsPayload.size)
        val udpCsum = ipv6UdpChecksum(out, 8, 24, 40, udpLen)
        out[46] = ((udpCsum shr 8) and 0xff).toByte()
        out[47] = (udpCsum and 0xff).toByte()
        return out
    }

    private fun ipv4HeaderChecksum(buf: ByteArray, offset: Int, length: Int): Int {
        var sum = 0
        var i = offset
        val end = offset + length
        while (i < end) {
            if (i == offset + 10) {
                i += 2
                continue
            }
            val word = ((buf[i].toInt() and 0xff) shl 8) or (buf[i + 1].toInt() and 0xff)
            sum += word
            i += 2
        }
        while (sum ushr 16 != 0) {
            sum = (sum and 0xffff) + (sum ushr 16)
        }
        return sum.inv() and 0xffff
    }

    private fun ipv6UdpChecksum(
        packet: ByteArray,
        srcOff: Int,
        dstOff: Int,
        udpOff: Int,
        udpLen: Int,
    ): Int {
        var sum = 0L
        fun addBytes(off: Int, len: Int) {
            var i = off
            val end = off + len
            while (i + 1 < end) {
                sum += ((packet[i].toInt() and 0xff) shl 8) or (packet[i + 1].toInt() and 0xff)
                i += 2
            }
            if (i < end) sum += (packet[i].toInt() and 0xff) shl 8
        }
        addBytes(srcOff, 16)
        addBytes(dstOff, 16)
        sum += udpLen ushr 16
        sum += udpLen and 0xffff
        sum += 17
        addBytes(udpOff, udpLen)
        while (sum ushr 16 != 0L) {
            sum = (sum and 0xffff) + (sum ushr 16)
        }
        var result = sum.inv().toInt() and 0xffff
        if (result == 0) result = 0xffff
        return result
    }

    /** Exposed for tests. */
    fun isDns4(addr: InetAddress): Boolean =
        addr is Inet4Address && addr.address.contentEquals(dns4)

    fun isDns6(addr: InetAddress): Boolean =
        addr is Inet6Address && addr.address.contentEquals(dns6)

    fun tun4Address(): ByteArray = tun4.copyOf()
    fun tun6Address(): ByteArray = tun6.copyOf()
}
