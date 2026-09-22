package com.zreta.devicecontrol.location

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

class LocationQueue(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "zreta_location_queue",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    @Synchronized
    fun enqueue(event: JSONObject) {
        val items = snapshot()
        val id = event.optString("client_event_id")
        val without = items.filter { it.optString("client_event_id") != id }
        val next = (without + event).takeLast(MAX)
        persist(next)
    }

    @Synchronized
    fun snapshot(): List<JSONObject> {
        val raw = prefs.getString(KEY, "[]") ?: "[]"
        val array = JSONArray(raw)
        return buildList {
            for (i in 0 until array.length()) {
                add(array.getJSONObject(i))
            }
        }
    }

    @Synchronized
    fun remove(clientEventIds: Collection<String>) {
        val keep = snapshot().filter { it.optString("client_event_id") !in clientEventIds }
        persist(keep)
    }

    private fun persist(items: List<JSONObject>) {
        val array = JSONArray()
        items.forEach { array.put(it) }
        prefs.edit().putString(KEY, array.toString()).apply()
    }

    companion object {
        private const val KEY = "queued"
        private const val MAX = 20
    }
}
