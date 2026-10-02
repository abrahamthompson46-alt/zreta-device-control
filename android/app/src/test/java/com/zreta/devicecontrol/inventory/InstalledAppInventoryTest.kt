package com.zreta.devicecontrol.inventory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class InstalledAppInventoryTest {
    @Test
    fun requestOmitsNothingButSelectedApps() {
        val json = InstalledAppInventory.toRequestJson(
            listOf(
                InstalledAppRecord("com.example.game", "Game", "1.0", 12),
            ),
            collectedCount = 1,
        )
        val app = json.getJSONArray("apps").getJSONObject(0)
        assertEquals("com.example.game", app.getString("package_name"))
        assertEquals("Game", app.getString("label"))
        assertEquals(12L, app.getLong("version_code"))
        assertEquals(true, json.getBoolean("complete"))
        assertFalse(json.has("device_id"))
    }

    @Test
    fun truncatedUploadIsNotComplete() {
        val apps = (1..5).map {
            InstalledAppRecord("com.example.app$it", "App $it", "1", it.toLong())
        }
        val selected = InstalledAppInventory.selectForUpload(
            apps,
            launcherPackages = setOf("com.example.app5"),
            limit = 2,
        )
        val json = InstalledAppInventory.toRequestJson(selected, collectedCount = apps.size)
        assertEquals(false, json.getBoolean("complete"))
        assertEquals(2, json.getJSONArray("apps").length())
    }

    @Test
    fun emptyScanIsComplete() {
        val json = InstalledAppInventory.toRequestJson(emptyList(), collectedCount = 0)
        assertEquals(true, json.getBoolean("complete"))
        assertEquals(0, json.getJSONArray("apps").length())
    }

    @Test
    fun uploadCapPrefersLauncherApps() {
        val apps = (1..5).map {
            InstalledAppRecord("com.example.app$it", "App $it", "1", it.toLong())
        }
        val selected = InstalledAppInventory.selectForUpload(
            apps,
            launcherPackages = setOf("com.example.app5"),
            limit = 2,
        )
        assertEquals(listOf("com.example.app5", "com.example.app1"), selected.map { it.packageName })
    }
}
