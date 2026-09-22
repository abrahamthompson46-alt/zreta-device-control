package com.zreta.devicecontrol.policy.enforcement

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DomainBlocklistTest {
    @Test
    fun normalizesCaseAndTrailingDot() {
        assertEquals("example.com", DomainBlocklist.normalizeOne("Example.COM."))
        assertEquals("ads.example.com", DomainBlocklist.normalizeOne("  ADS.Example.Com  "))
    }

    @Test
    fun rejectsMalformed() {
        assertNull(DomainBlocklist.normalizeOne(""))
        assertNull(DomainBlocklist.normalizeOne(" "))
        assertNull(DomainBlocklist.normalizeOne("https://example.com"))
        assertNull(DomainBlocklist.normalizeOne("example.com/path"))
        assertNull(DomainBlocklist.normalizeOne("example.com:443"))
        assertNull(DomainBlocklist.normalizeOne("*.example.com"))
        assertNull(DomainBlocklist.normalizeOne("1.2.3.4"))
        assertNull(DomainBlocklist.normalizeOne("localhost"))
        assertNull(DomainBlocklist.normalizeOne("bad_label.com"))
        assertNull(DomainBlocklist.normalizeOne("-bad.com"))
    }

    @Test
    fun normalizeListDedupesSortsAndHashesStably() {
        val a = DomainBlocklist.normalizeList(listOf("b.example.com", "A.Example.COM.", "b.example.com"))
        val b = DomainBlocklist.normalizeList(listOf("a.example.com", "b.example.com"))
        assertNotNull(a)
        assertNotNull(b)
        assertEquals(listOf("a.example.com", "b.example.com"), a!!.domains)
        assertEquals(a.domains, b!!.domains)
        assertEquals(a.ruleHash, b.ruleHash)
        assertEquals(a.canonical, "a.example.com\nb.example.com")
    }

    @Test
    fun hashChangesWhenListChanges() {
        val a = DomainBlocklist.normalizeList(listOf("a.example.com"))!!
        val b = DomainBlocklist.normalizeList(listOf("b.example.com"))!!
        assertNotEquals(a.ruleHash, b.ruleHash)
    }

    @Test
    fun parentDomainMatching() {
        val blocked = listOf("example.com", "ads.net")
        assertTrue(DomainBlocklist.isBlocked("example.com", blocked))
        assertTrue(DomainBlocklist.isBlocked("www.example.com", blocked))
        assertTrue(DomainBlocklist.isBlocked("a.b.example.com", blocked))
        assertFalse(DomainBlocklist.isBlocked("example.org", blocked))
        assertFalse(DomainBlocklist.isBlocked("notexample.com", blocked))
        assertTrue(DomainBlocklist.isBlocked("x.ads.net", blocked))
    }

    @Test
    fun rejectsOverlongList() {
        val many = (1..DomainBlocklist.MAX_DOMAINS + 1).map { "host$it.example.com" }
        assertNull(DomainBlocklist.normalizeList(many))
    }

    @Test
    fun auditCanonicalCases() {
        assertEquals("example.com", DomainBlocklist.normalizeOne("example.com"))
        assertEquals("example.com", DomainBlocklist.normalizeOne("EXAMPLE.COM"))
        assertEquals("example.com", DomainBlocklist.normalizeOne("example.com."))
        assertEquals("www.example.com", DomainBlocklist.normalizeOne("www.example.com"))
        assertEquals("badexample.com", DomainBlocklist.normalizeOne("badexample.com"))
        assertEquals("a.b", DomainBlocklist.normalizeOne("a.b"))
        assertNull(DomainBlocklist.normalizeOne("example.com/path"))
        assertNull(DomainBlocklist.normalizeOne("https://example.com"))
        assertNull(DomainBlocklist.normalizeOne("example.com:443"))
        assertNull(DomainBlocklist.normalizeOne("*.example.com"))
        assertNull(DomainBlocklist.normalizeOne("192.168.1.1"))
        assertNull(DomainBlocklist.normalizeOne("localhost"))
        assertNull(DomainBlocklist.normalizeOne(""))
        assertNull(DomainBlocklist.normalizeOne("   "))
    }

    @Test
    fun auditParentMatchingExactCases() {
        val blocked = listOf("example.com")
        assertTrue(DomainBlocklist.isBlocked("example.com", blocked))
        assertTrue(DomainBlocklist.isBlocked("www.example.com", blocked))
        assertTrue(DomainBlocklist.isBlocked("deep.www.example.com", blocked))
        assertFalse(DomainBlocklist.isBlocked("badexample.com", blocked))
        assertFalse(DomainBlocklist.isBlocked("example.com.evil.com", blocked))
    }

    @Test
    fun backendParityHashForRepresentativeList() {
        // Must match Python SHA-256 of "example.com\nwww.example.com" (UTF-8).
        val n = DomainBlocklist.normalizeList(
            listOf("EXAMPLE.com", "example.com.", "www.Example.com"),
        )!!
        assertEquals(listOf("example.com", "www.example.com"), n.domains)
        assertEquals("example.com\nwww.example.com", n.canonical)
        assertEquals(
            "d0153bd58ceefd23eaf3c18ab3d2affc04f3a5fb6d6041c01b23284506a987e2",
            n.ruleHash,
        )
    }
}
