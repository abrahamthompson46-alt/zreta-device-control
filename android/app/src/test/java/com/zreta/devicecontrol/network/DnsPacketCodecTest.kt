package com.zreta.devicecontrol.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DnsPacketCodecTest {
    @Test
    fun parsesQueryAndPreservesTransactionIdInNxDomain() {
        val query = buildQuery(0xABCD, "www.example.com", DnsPacketCodec.TYPE_A)
        val parsed = DnsPacketCodec.parseQuery(query)!!
        assertEquals(0xABCD, parsed.transactionId)
        assertEquals("www.example.com", parsed.qname)
        assertEquals(DnsPacketCodec.TYPE_A, parsed.qtype)
        assertEquals(DnsPacketCodec.CLASS_IN, parsed.qclass)

        val nx = DnsPacketCodec.buildNxDomain(query, 0, query.size, parsed)!!
        assertEquals(0xAB.toByte(), nx[0])
        assertEquals(0xCD.toByte(), nx[1])
        val flags = ((nx[2].toInt() and 0xff) shl 8) or (nx[3].toInt() and 0xff)
        assertTrue(flags and 0x8000 != 0) // QR
        assertEquals(DnsPacketCodec.RCODE_NXDOMAIN, flags and 0x0f)
        assertEquals(1, ((nx[4].toInt() and 0xff) shl 8) or (nx[5].toInt() and 0xff))
        assertEquals(0, ((nx[6].toInt() and 0xff) shl 8) or (nx[7].toInt() and 0xff))
    }

    @Test
    fun rejectsMalformedPackets() {
        assertNull(DnsPacketCodec.parseQuery(ByteArray(0)))
        assertNull(DnsPacketCodec.parseQuery(ByteArray(11)))
        val tooLarge = ByteArray(DnsPacketCodec.MAX_UDP_DNS_PAYLOAD + 1)
        assertNull(DnsPacketCodec.parseQuery(tooLarge))
        // QR=1 (response) rejected
        val responseLike = buildQuery(1, "a.example.com", DnsPacketCodec.TYPE_A)
        responseLike[2] = (responseLike[2].toInt() or 0x80).toByte()
        assertNull(DnsPacketCodec.parseQuery(responseLike))
    }

    @Test
    fun rejectsNonInetClass() {
        val q = buildQuery(1, "example.com", DnsPacketCodec.TYPE_A, qclass = 2)
        assertNull(DnsPacketCodec.parseQuery(q))
    }

    companion object {
        fun buildQuery(
            id: Int,
            name: String,
            qtype: Int,
            qclass: Int = DnsPacketCodec.CLASS_IN,
        ): ByteArray {
            val labels = name.split('.')
            val nameBytes = ArrayList<Byte>()
            for (label in labels) {
                val raw = label.toByteArray(Charsets.US_ASCII)
                nameBytes.add(raw.size.toByte())
                raw.forEach { nameBytes.add(it) }
            }
            nameBytes.add(0)
            val out = ByteArray(12 + nameBytes.size + 4)
            out[0] = ((id shr 8) and 0xff).toByte()
            out[1] = (id and 0xff).toByte()
            out[2] = 0x01 // RD
            out[3] = 0x00
            out[4] = 0
            out[5] = 1
            var i = 12
            for (b in nameBytes) out[i++] = b
            out[i++] = ((qtype shr 8) and 0xff).toByte()
            out[i++] = (qtype and 0xff).toByte()
            out[i++] = ((qclass shr 8) and 0xff).toByte()
            out[i] = (qclass and 0xff).toByte()
            return out
        }
    }
}

class DnsFilterEngineTest {
    @Test
    fun blockedReturnsNxDomainAllowedForwards() {
        val engine = DnsFilterEngine(listOf("example.com"))
        val blockedQuery = DnsPacketCodecTest.buildQuery(0x1111, "www.example.com", DnsPacketCodec.TYPE_A)
        val blockedResp = engine.handleDnsPayload(blockedQuery) { error("should not forward") }!!
        val flags = ((blockedResp[2].toInt() and 0xff) shl 8) or (blockedResp[3].toInt() and 0xff)
        assertEquals(DnsPacketCodec.RCODE_NXDOMAIN, flags and 0x0f)

        val allowedQuery = DnsPacketCodecTest.buildQuery(0x2222, "allowed.example.org", DnsPacketCodec.TYPE_A)
        var forwarded = false
        val upstream = ByteArray(12) { 0 }.also {
            it[0] = 0x22
            it[1] = 0x22
            it[2] = 0x81.toByte()
            it[3] = 0x80.toByte()
        }
        val allowedResp = engine.handleDnsPayload(allowedQuery) {
            forwarded = true
            upstream
        }
        assertTrue(forwarded)
        assertTrue(upstream.contentEquals(allowedResp))
    }

    @Test
    fun badexampleDoesNotMatchExampleCom() {
        val engine = DnsFilterEngine(listOf("example.com"))
        val q = DnsPacketCodecTest.buildQuery(1, "badexample.com", DnsPacketCodec.TYPE_A)
        var forwarded = false
        engine.handleDnsPayload(q) {
            forwarded = true
            ByteArray(12)
        }
        assertTrue(forwarded)
    }

    @Test
    fun evilSuffixDoesNotMatch() {
        val engine = DnsFilterEngine(listOf("example.com"))
        val q = DnsPacketCodecTest.buildQuery(1, "example.com.evil.com", DnsPacketCodec.TYPE_A)
        var forwarded = false
        engine.handleDnsPayload(q) {
            forwarded = true
            ByteArray(12)
        }
        assertTrue(forwarded)
    }

    @Test
    fun hotReloadUpdatesRules() {
        val engine = DnsFilterEngine(emptyList())
        val q = DnsPacketCodecTest.buildQuery(1, "ads.example.com", DnsPacketCodec.TYPE_A)
        assertNotNull(engine.handleDnsPayload(q) { ByteArray(12) })
        engine.updateBlocked(listOf("ads.example.com"))
        val nx = engine.handleDnsPayload(q) { error("blocked") }!!
        assertEquals(DnsPacketCodec.RCODE_NXDOMAIN, nx[3].toInt() and 0x0f)
    }
}

class DnsTunPacketHandlerTest {
    @Test
    fun ipv4DnsToSyntheticEndpointProducesResponse() {
        val engine = DnsFilterEngine(listOf("blocked.test"))
        val dnsQuery = DnsPacketCodecTest.buildQuery(0x42, "blocked.test", DnsPacketCodec.TYPE_A)
        val packet = buildIpv4Udp(
            srcIp = byteArrayOf(10, 0, 0, 5),
            dstIp = byteArrayOf(10, 255.toByte(), 255.toByte(), 1),
            srcPort = 53_000,
            dstPort = 53,
            payload = dnsQuery,
        )
        val response = DnsTunPacketHandler.handle(packet, packet.size, engine) { error("no forward") }
        assertNotNull(response)
        assertEquals(0x45.toByte(), response!![0])
        // response dest should be original src
        assertEquals(10.toByte(), response[16])
        assertEquals(0.toByte(), response[17])
        assertEquals(0.toByte(), response[18])
        assertEquals(5.toByte(), response[19])
    }

    @Test
    fun nonDnsDestinationIgnored() {
        val engine = DnsFilterEngine(listOf("blocked.test"))
        val dnsQuery = DnsPacketCodecTest.buildQuery(1, "blocked.test", DnsPacketCodec.TYPE_A)
        val packet = buildIpv4Udp(
            srcIp = byteArrayOf(10, 0, 0, 5),
            dstIp = byteArrayOf(8, 8, 8, 8),
            srcPort = 53000,
            dstPort = 53,
            payload = dnsQuery,
        )
        assertNull(DnsTunPacketHandler.handle(packet, packet.size, engine) { error("x") })
    }

    @Test
    fun ipv6DnsToSyntheticEndpointProducesResponse() {
        val engine = DnsFilterEngine(listOf("blocked.test"))
        val dnsQuery = DnsPacketCodecTest.buildQuery(0x7, "blocked.test", DnsPacketCodec.TYPE_AAAA)
        val dns6 = byteArrayOf(
            0xfd.toByte(), 0x00, 0x5a, 0x74, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
        )
        val src6 = ByteArray(16) { 0 }.also { it[15] = 9 }
        val packet = buildIpv6Udp(src6, dns6, 45000, 53, dnsQuery)
        val response = DnsTunPacketHandler.handle(packet, packet.size, engine) { error("no") }
        assertNotNull(response)
        assertEquals(0x60.toByte(), response!![0])
    }

    private fun buildIpv4Udp(
        srcIp: ByteArray,
        dstIp: ByteArray,
        srcPort: Int,
        dstPort: Int,
        payload: ByteArray,
    ): ByteArray {
        val udpLen = 8 + payload.size
        val total = 20 + udpLen
        val out = ByteArray(total)
        out[0] = 0x45
        out[2] = ((total shr 8) and 0xff).toByte()
        out[3] = (total and 0xff).toByte()
        out[8] = 64
        out[9] = 17
        System.arraycopy(srcIp, 0, out, 12, 4)
        System.arraycopy(dstIp, 0, out, 16, 4)
        out[20] = ((srcPort shr 8) and 0xff).toByte()
        out[21] = (srcPort and 0xff).toByte()
        out[22] = ((dstPort shr 8) and 0xff).toByte()
        out[23] = (dstPort and 0xff).toByte()
        out[24] = ((udpLen shr 8) and 0xff).toByte()
        out[25] = (udpLen and 0xff).toByte()
        System.arraycopy(payload, 0, out, 28, payload.size)
        return out
    }

    private fun buildIpv6Udp(
        srcIp: ByteArray,
        dstIp: ByteArray,
        srcPort: Int,
        dstPort: Int,
        payload: ByteArray,
    ): ByteArray {
        val udpLen = 8 + payload.size
        val out = ByteArray(40 + udpLen)
        out[0] = 0x60
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
        System.arraycopy(payload, 0, out, 48, payload.size)
        return out
    }
}
