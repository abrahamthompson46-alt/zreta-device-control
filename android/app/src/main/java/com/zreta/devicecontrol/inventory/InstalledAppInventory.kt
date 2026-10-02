package com.zreta.devicecontrol.inventory

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject

data class InstalledAppRecord(
    val packageName: String,
    val label: String,
    val versionName: String,
    val versionCode: Long,
)

object InstalledAppInventory {
    const val MAX_BATCH = 400

    /**
     * complete is true only when every collected package is in the upload.
     * An empty scan is complete when collection finished and found nothing.
     */
    fun toRequestJson(apps: List<InstalledAppRecord>, collectedCount: Int): JSONObject {
        val array = JSONArray()
        for (app in apps) {
            array.put(
                JSONObject()
                    .put("package_name", app.packageName)
                    .put("label", app.label)
                    .put("version_name", app.versionName)
                    .put("version_code", app.versionCode),
            )
        }
        return JSONObject()
            .put("apps", array)
            .put("complete", apps.size == collectedCount)
    }

    /**
     * Launcher apps first, then the rest, both ordered by package name.
     * The server rejects batches above [MAX_BATCH], so the phone sends a bounded snapshot.
     */
    fun selectForUpload(apps: List<InstalledAppRecord>, launcherPackages: Set<String>, limit: Int = MAX_BATCH): List<InstalledAppRecord> {
        val launchers = apps.filter { it.packageName in launcherPackages }.sortedBy { it.packageName }
        val others = apps.filter { it.packageName !in launcherPackages }.sortedBy { it.packageName }
        return (launchers + others).take(limit)
    }

    fun collect(context: Context): JSONObject {
        val pm = context.packageManager
        val packages = installedPackages(pm)
        val launcher = launcherPackages(pm)
        val records = packages.mapNotNull { info -> toRecord(pm, info) }
        return toRequestJson(selectForUpload(records, launcher), collectedCount = records.size)
    }

    private fun toRecord(pm: PackageManager, info: PackageInfo): InstalledAppRecord? {
        val name = info.packageName ?: return null
        if (!PACKAGE.matches(name)) return null
        val appInfo = info.applicationInfo ?: return null
        val rawLabel = appInfo.loadLabel(pm)?.toString()?.trim().orEmpty()
        val label = rawLabel.ifBlank { name }.take(150)
        val versionName = info.versionName?.trim().orEmpty().take(64)
        val versionCode = if (Build.VERSION.SDK_INT >= 28) {
            info.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            info.versionCode.toLong()
        }
        if (versionCode < 0) return null
        return InstalledAppRecord(name, label, versionName, versionCode)
    }

    private fun installedPackages(pm: PackageManager): List<PackageInfo> {
        return if (Build.VERSION.SDK_INT >= 33) {
            pm.getInstalledPackages(PackageManager.PackageInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION")
            pm.getInstalledPackages(0)
        }
    }

    private fun launcherPackages(pm: PackageManager): Set<String> {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val activities = if (Build.VERSION.SDK_INT >= 33) {
            pm.queryIntentActivities(intent, PackageManager.ResolveInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION")
            pm.queryIntentActivities(intent, 0)
        }
        return activities.mapNotNull { it.activityInfo?.packageName }.toSet()
    }

    private val PACKAGE = Regex("^(?:[A-Za-z_][A-Za-z0-9_]*)(?:\\.[A-Za-z_][A-Za-z0-9_]*)+$")
}
