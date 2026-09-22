package com.zreta.devicecontrol.network

/**
 * Minimal DNS query/response codec for Phase 5.1B local DNS filter.
 *
 * Supported: classic UDP DNS messages (header + single question).
 * Blocked response: NXDOMAIN (RCODE=3), QR=1, question preserved, no answers.
 * Does not implement EDNS, DNSSEC, compression-aware rewriting, DoH, or DoT.
 */
object DnsPacketCodec {
    const val MAX_UDP_DNS_PAYLOAD = 1232
    const val TYPE_A = 1
    const val TYPE_AAAA = 28
    const val TYPE_ANY = 255
    const val CLASS_IN = 1
    const val RCODE_NXDOMAIN = 3

    data class ParsedQuery(
        val transactionId: Int,
        /** Wire-decoded name, lowercase ASCII labels joined by '.', no trailing dot. */
        val qname: String,
        val qtype: Int,
        val qclass: Int,
        /** Byte offset where the question section begins (after 12-byte header). */
        val questionStart: Int,
        /** Length of question section (QNAME + QTYPE + QCLASS). */
        val questionLength: Int,
    )

    /**
     * Parse a DNS query. Returns null if malformed or outside supported subset.
     */
    fun parseQuery(packet: ByteArray, offset: Int = 0, length: Int = packet.size - offset): ParsedQuery? {
        if (length < 12 || length > MAX_UDP_DNS_PAYLOAD) return null
        if (offset < 0 || offset + length > packet.size) return null

        val id = ((packet[offset].toInt() and 0xff) shl 8) or (packet[offset + 1].toInt() and 0xff)
        val flags = ((packet[offset + 2].toInt() and 0xff) shl 8) or (packet[offset + 3].toInt() and 0xff)
        if ((flags and 0x8000) != 0) return null // must be a query (QR=0)
        val opcode = (flags shr 11) and 0x0f
        if (opcode != 0) return null // QUERY only

        val qd = ((packet[offset + 4].toInt() and 0xff) shl 8) or (packet[offset + 5].toInt() and 0xff)
        if (qd != 1) return null

        val an = ((packet[offset + 6].toInt() and 0xff) shl 8) or (packet[offset + 7].toInt() and 0xff)
        val ns = ((packet[offset + 8].toInt() and 0xff) shl 8) or (packet[offset + 9].toInt() and 0xff)
        val ar = ((packet[offset + 10].toInt() and 0xff) shl 8) or (packet[offset + 11].toInt() and 0xff)
        // Allow empty answer/authority; tolerate optional additional (EDNS) by ignoring past question.
        if (an != 0 || ns != 0) return null

        val questionStart = offset + 12
        val nameParsed = decodeName(packet, questionStart, offset + length) ?: return null
        if (nameParsed.nextOffset + 4 > offset + length) return null
        val qtype = ((packet[nameParsed.nextOffset].toInt() and 0xff) shl 8) or
            (packet[nameParsed.nextOffset + 1].toInt() and 0xff)
        val qclass = ((packet[nameParsed.nextOffset + 2].toInt() and 0xff) shl 8) or
            (packet[nameParsed.nextOffset + 3].toInt() and 0xff)
        if (qclass != CLASS_IN) return null
        // ar may be >0 (EDNS); we only need the first question.
        if (ar > 1) return null

        val questionLength = (nameParsed.nextOffset + 4) - questionStart
        return ParsedQuery(
            transactionId = id,
            qname = nameParsed.name,
            qtype = qtype,
            qclass = qclass,
            questionStart = questionStart - offset,
            questionLength = questionLength,
        )
    }

    /**
     * Build NXDOMAIN response preserving transaction ID and question bytes from [request].
     * Deterministic; no attacker-controlled bytes beyond the validated question section.
     */
    fun buildNxDomain(request: ByteArray, offset: Int, length: Int, query: ParsedQuery): ByteArray? {
        if (length < 12 || offset < 0 || offset + length > request.size) return null
        val absQuestionStart = offset + query.questionStart
        if (absQuestionStart + query.questionLength > offset + length) return null

        val outLen = 12 + query.questionLength
        if (outLen > MAX_UDP_DNS_PAYLOAD) return null
        val out = ByteArray(outLen)

        // ID
        out[0] = request[offset]
        out[1] = request[offset + 1]

        // Flags: QR=1, copy OPCODE/RD from request, RCODE=NXDOMAIN
        val reqFlags = ((request[offset + 2].toInt() and 0xff) shl 8) or (request[offset + 3].toInt() and 0xff)
        val opcode = (reqFlags shr 11) and 0x0f
        val rd = reqFlags and 0x0100
        val flags = 0x8000 or (opcode shl 11) or rd or RCODE_NXDOMAIN
        out[2] = ((flags shr 8) and 0xff).toByte()
        out[3] = (flags and 0xff).toByte()

        // QDCOUNT=1, ANCOUNT=0, NSCOUNT=0, ARCOUNT=0
        out[4] = 0
        out[5] = 1
        out[6] = 0
        out[7] = 0
        out[8] = 0
        out[9] = 0
        out[10] = 0
        out[11] = 0

        System.arraycopy(request, absQuestionStart, out, 12, query.questionLength)
        return out
    }

    private data class NameParse(val name: String, val nextOffset: Int)

    private fun decodeName(packet: ByteArray, start: Int, endExclusive: Int): NameParse? {
        val labels = ArrayList<String>(8)
        var pos = start
        var jumped = false
        var next = -1
        var safety = 0
        while (pos < endExclusive && safety++ < 64) {
            val len = packet[pos].toInt() and 0xff
            when {
                len == 0 -> {
                    if (!jumped) next = pos + 1
                    if (labels.isEmpty()) return null
                    return NameParse(labels.joinToString(".").lowercase(), next)
                }
                (len and 0xc0) == 0xc0 -> {
                    if (pos + 1 >= endExclusive) return null
                    val pointer = ((len and 0x3f) shl 8) or (packet[pos + 1].toInt() and 0xff)
                    // Compression pointers are absolute within the message; reject out of bounds.
                    if (pointer < 0 || pointer >= endExclusive) return null
                    if (!jumped) next = pos + 2
                    jumped = true
                    pos = pointer
                }
                else -> {
                    if (len > 63) return null
                    if (pos + 1 + len >= endExclusive) return null
                    val label = packet.copyOfRange(pos + 1, pos + 1 + len)
                    for (b in label) {
                        val c = b.toInt() and 0xff
                        // LDH + allow uppercase (normalized later)
                        if (!(c in 0x30..0x39 || c in 0x41..0x5a || c in 0x61..0x7a || c == 0x2d)) {
                            return null
                        }
                    }
                    labels.add(String(label, Charsets.US_ASCII))
                    pos += 1 + len
                    if (!jumped) next = pos
                }
            }
        }
        return null
    }
}
