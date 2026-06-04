package com.xiuci.xcagi.mobile.core.export

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import java.io.File

object AccountExportHelper {
    private val gson: Gson = GsonBuilder().setPrettyPrinting().create()

    fun writeJsonToDownloads(context: Context, data: Map<String, Any?>): Uri? {
        val json = gson.toJson(data)
        val fileName = "xcagi-account-export-${System.currentTimeMillis()}.json"
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return writeLegacyJson(context, fileName, json)
        }
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.MIME_TYPE, "application/json")
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return null
        resolver.openOutputStream(uri)?.use { it.write(json.toByteArray(Charsets.UTF_8)) }
        values.clear()
        values.put(MediaStore.Downloads.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return uri
    }

    private fun writeLegacyJson(context: Context, fileName: String, json: String): Uri? {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
        if (!dir.exists() && !dir.mkdirs()) return null
        val file = File(dir, fileName)
        file.writeText(json, Charsets.UTF_8)
        return FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            file,
        )
    }
}
