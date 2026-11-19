package com.xiuci.xcagi.mobile

import android.Manifest
import android.app.DownloadManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.provider.Settings
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.app.ActivityCompat
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
import androidx.core.content.pm.PackageInfoCompat
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.BufferedInputStream
import java.io.File
import java.security.KeyStore
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlin.concurrent.thread
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject

private const val SessionFileName = "xcagi_session.json"
private const val LegacySessionDataStorePath = "datastore/xcagi_session_enterprise.preferences_pb"
private const val LegacySessionMigrationMarkerName = "xcagi_session_legacy_migrated"
private const val RecordAudioPermissionRequestCode = 4242
private const val CameraPermissionRequestCode = 4243
private val UpdateInProgress = AtomicBoolean()

class MainActivity : FlutterFragmentActivity() {
    private var deepLinkChannel: MethodChannel? = null
    private var pendingDeepLinkRoute: String? = null
    private var pendingRecordAudioPermissionResult: MethodChannel.Result? = null
    private var pendingCameraPermissionResult: MethodChannel.Result? = null
    private val legacySessionDataStore: DataStore<Preferences> by lazy {
        PreferenceDataStoreFactory.create(
            produceFile = { File(filesDir, LegacySessionDataStorePath) },
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        pendingDeepLinkRoute = parseDeepLinkRoute(intent)
        super.onCreate(savedInstanceState)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xcagi/workspace_files")
            .setMethodCallHandler { call, result ->
                if (call.method != "share") {
                    result.notImplemented()
                } else {
                    try {
                        val file = File(call.argument<String>("path") ?: "").canonicalFile
                        val root = File(cacheDir, "workspace_exports").canonicalFile
                        require(file.isFile && file.path.startsWith(root.path + File.separator))
                        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
                        val mime = when (file.extension.lowercase()) {
                            "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            "pdf" -> "application/pdf"
                            else -> "application/octet-stream"
                        }
                        val intent = Intent(Intent.ACTION_SEND).apply {
                            type = mime
                            putExtra(Intent.EXTRA_STREAM, uri)
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            clipData = android.content.ClipData.newRawUri(file.name, uri)
                        }
                        startActivity(Intent.createChooser(intent, "保存或分享文件"))
                        result.success(null)
                    } catch (error: Exception) {
                        result.error("file_export", "无法打开文件分享，请重试", null)
                    }
                }
            }
        deepLinkChannel =
            MethodChannel(
                flutterEngine.dartExecutor.binaryMessenger,
                "xcagi/deep_link",
            ).also { channel ->
                channel.setMethodCallHandler { call, result ->
                    when (call.method) {
                        "getInitialRoute" -> {
                            val route = pendingDeepLinkRoute ?: parseDeepLinkRoute(intent)
                            pendingDeepLinkRoute = null
                            result.success(route)
                        }
                        else -> result.notImplemented()
                    }
                }
            }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/biometric",
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "canAuthenticate" -> result.success(canAuthenticate())
                "authenticate" -> promptBiometric(result)
                "finishApp" -> {
                    finish()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/credential_cipher",
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "encrypt" -> {
                    val plain = call.argument<String>("plain").orEmpty()
                    result.success(CredentialCipher.encrypt(plain))
                }
                "decrypt" -> {
                    val stored = call.argument<String>("stored").orEmpty()
                    result.success(CredentialCipher.decrypt(stored))
                }
                else -> result.notImplemented()
            }
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/update_installer",
        ).setMethodCallHandler { call, result ->
            if (call.method != "startPackageUpdate") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val downloadUrl = call.argument<String>("downloadUrl").orEmpty()
            val targetVersionCode = call.argument<Number>("targetVersionCode")?.toLong() ?: 0L
            startPackageUpdate(downloadUrl, targetVersionCode, result)
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/background_work",
        ).setMethodCallHandler { call, result ->
            if (call.method != "reconcile") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val autoSync = call.argument<Boolean>("autoSync") ?: true
            val autoLanProbe = call.argument<Boolean>("autoLanProbe") ?: false
            val state = XcagiBackgroundWork.reconcile(this, autoSync, autoLanProbe)
            result.success(state)
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/session_store",
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "sessionFilePath" -> {
                    result.success(resolveSessionFile().absolutePath)
                }
                else -> result.notImplemented()
            }
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/permissions",
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "ensureRecordAudio" -> ensureRecordAudioPermission(result)
                "checkCamera" -> result.success(isCameraPermissionGranted())
                "ensureCamera" -> ensureCameraPermission(result)
                else -> result.notImplemented()
            }
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "xcagi/content_uri",
        ).setMethodCallHandler { call, result ->
            if (call.method != "readBytes") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val uriText = call.argument<String>("uri").orEmpty()
            thread(name = "xcagi-content-uri-reader") {
                try {
                    val bytes = readContentUriBytes(uriText)
                    runOnUiThread { result.success(bytes) }
                } catch (error: Throwable) {
                    runOnUiThread {
                        result.error(
                            "CONTENT_URI_READ_FAILED",
                            error.message ?: "无法读取头像内容 URI",
                            null,
                        )
                    }
                }
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val granted = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        when (requestCode) {
            RecordAudioPermissionRequestCode -> {
                pendingRecordAudioPermissionResult?.success(granted)
                pendingRecordAudioPermissionResult = null
            }
            CameraPermissionRequestCode -> {
                pendingCameraPermissionResult?.success(granted)
                pendingCameraPermissionResult = null
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val route = parseDeepLinkRoute(intent) ?: return
        val channel = deepLinkChannel
        if (channel == null) {
            pendingDeepLinkRoute = route
        } else {
            channel.invokeMethod("onRoute", route)
        }
    }

    private fun parseDeepLinkRoute(intent: Intent?): String? {
        val route = intent?.getStringExtra("deep_link_route")?.trim().orEmpty()
        if (route.isNotBlank()) return route
        val data: Uri = intent?.data ?: return null
        return when {
            data.scheme == "xcagi" -> {
                val host = data.host.orEmpty()
                val path = data.path.orEmpty()
                val base =
                    when {
                        path.isNotBlank() -> "$host$path"
                        host.isNotBlank() -> host
                        else -> ""
                    }
                val query = data.encodedQuery?.trim().orEmpty()
                when {
                    base.isBlank() -> null
                    query.isNullOrBlank() -> base
                    else -> "$base?$query"
                }
            }
            data.host?.contains("xiu-ci.com") == true -> data.path ?: "chat"
            else -> null
        }
    }

    private fun canAuthenticate(): Boolean {
        val code =
            BiometricManager.from(this).canAuthenticate(
                BiometricManager.Authenticators.BIOMETRIC_STRONG or
                    BiometricManager.Authenticators.DEVICE_CREDENTIAL,
            )
        return code == BiometricManager.BIOMETRIC_SUCCESS
    }

    private fun promptBiometric(result: MethodChannel.Result) {
        val executor = ContextCompat.getMainExecutor(this)
        var completed = false
        val prompt =
            BiometricPrompt(
                this,
                executor,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(
                        authenticationResult: BiometricPrompt.AuthenticationResult,
                    ) {
                        if (completed) return
                        completed = true
                        result.success(true)
                    }

                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                        if (completed) return
                        completed = true
                        result.success(false)
                    }
                },
            )
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder()
                .setTitle("解锁 XCAGI")
                .setSubtitle("验证指纹或设备密码")
                .setAllowedAuthenticators(
                    BiometricManager.Authenticators.BIOMETRIC_STRONG or
                        BiometricManager.Authenticators.DEVICE_CREDENTIAL,
                )
                .build(),
        )
    }

    private fun isCameraPermissionGranted(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED

    private fun ensureCameraPermission(result: MethodChannel.Result) {
        if (isCameraPermissionGranted()) {
            result.success(true)
            return
        }
        if (pendingCameraPermissionResult != null) {
            result.error(
                "PERMISSION_REQUEST_IN_PROGRESS",
                "相机权限请求正在进行",
                null,
            )
            return
        }
        pendingCameraPermissionResult = result
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.CAMERA),
            CameraPermissionRequestCode,
        )
    }

    private fun ensureRecordAudioPermission(result: MethodChannel.Result) {
        val alreadyGranted =
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        if (alreadyGranted) {
            result.success(true)
            return
        }
        if (pendingRecordAudioPermissionResult != null) {
            result.error(
                "PERMISSION_REQUEST_IN_PROGRESS",
                "录音权限请求正在进行",
                null,
            )
            return
        }
        pendingRecordAudioPermissionResult = result
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.RECORD_AUDIO),
            RecordAudioPermissionRequestCode,
        )
    }

    private fun readContentUriBytes(uriText: String): ByteArray {
        require(uriText.isNotBlank()) { "内容 URI 为空" }
        val uri = Uri.parse(uriText)
        require(uri.scheme == "content") { "仅支持 content:// 头像 URI" }
        val input = contentResolver.openInputStream(uri)
            ?: throw IllegalArgumentException("无法打开头像 URI")
        return input.use { stream -> BufferedInputStream(stream).readBytes() }
    }

    private fun resolveSessionFile(): File {
        val file = File(filesDir, SessionFileName)
        migrateLegacyAndroidSessionIfNeeded(file)
        return file
    }

    private fun migrateLegacyAndroidSessionIfNeeded(sessionFile: File) {
        val legacyFile = File(filesDir, LegacySessionDataStorePath)
        val markerFile = File(filesDir, LegacySessionMigrationMarkerName)
        if (!legacyFile.exists() || markerFile.exists()) return

        runCatching {
            val prefs = runBlocking { legacySessionDataStore.data.first() }
            val legacy = prefs.toFlutterSessionJson()
            if (legacy.length() == 0) return

            val merged = readSessionJson(sessionFile)
            legacy.keys().forEach { key -> merged.put(key, legacy.get(key)) }
            sessionFile.parentFile?.mkdirs()
            sessionFile.writeText(merged.toString(), Charsets.UTF_8)
            markerFile.writeText("migrated:$LegacySessionDataStorePath", Charsets.UTF_8)
        }
    }

    private fun readSessionJson(file: File): JSONObject {
        if (!file.exists()) return JSONObject()
        return runCatching {
            val text = file.readText(Charsets.UTF_8)
            if (text.trim().isBlank()) JSONObject() else JSONObject(text)
        }.getOrDefault(JSONObject())
    }

    private fun Preferences.toFlutterSessionJson(): JSONObject {
        val json = JSONObject()

        putString(json, "fhd_host")
        putString(json, "fhd_access_token", "access_token")
        putString(json, "fhd_refresh_token", "refresh_token")
        putString(json, "fhd_session_id", "session_id")
        putString(json, "fhd_username", "username")
        putString(json, "market_token", "market_access_token")
        putString(json, "market_refresh_token", "market_refresh_token")
        putString(json, "server_mode")
        putString(json, "account_kind")
        putString(json, "fcm_token")
        putString(json, "last_sync_at")
        putString(json, "legal_accepted_version")
        putString(json, "theme_mode")
        putString(json, "saved_username")
        putString(json, "saved_password")
        putString(json, "avatar_uri", "local_avatar_source")
        putString(json, "relay_desktop_id")
        putString(json, "relay_base_url")
        putString(json, "local_base_url")
        putString(json, "relay_session_token")
        putString(json, "relay_account_id")
        putString(json, "relay_tenant_id")
        putString(json, "relay_paired_at")
        putString(json, "wallet_balance_json")
        putInt(json, "user_id")
        putInt(json, "sync_cursor")
        putBool(json, "auto_lan_probe")
        putBool(json, "auto_sync")
        putBool(json, "biometric_enabled")
        putBool(json, "remember_password")
        putBool(json, "auto_login")

        val setupComplete = this[booleanPreferencesKey("setup_complete")]
        if (setupComplete != null || json.optString("fhd_host").isNotBlank()) {
            json.put("setup_complete", setupComplete == true || json.optString("fhd_host").isNotBlank())
        }

        val inflight = this[stringPreferencesKey("inflight_relay_tasks")]?.trim().orEmpty()
        if (inflight.isNotBlank()) {
            runCatching { JSONObject(inflight) }
                .getOrNull()
                ?.takeIf { it.length() > 0 }
                ?.let { json.put("inflight_relay_tasks", it) }
        }

        return json
    }

    private fun Preferences.putString(json: JSONObject, sourceKey: String, targetKey: String = sourceKey) {
        val value = this[stringPreferencesKey(sourceKey)]?.trim().orEmpty()
        if (value.isNotBlank()) json.put(targetKey, value)
    }

    private fun Preferences.putInt(json: JSONObject, sourceKey: String, targetKey: String = sourceKey) {
        val value = this[intPreferencesKey(sourceKey)] ?: return
        if (value > 0) json.put(targetKey, value)
    }

    private fun Preferences.putBool(json: JSONObject, sourceKey: String, targetKey: String = sourceKey) {
        val value = this[booleanPreferencesKey(sourceKey)] ?: return
        json.put(targetKey, value)
    }

    private fun startPackageUpdate(
        downloadUrl: String,
        targetVersionCode: Long,
        result: MethodChannel.Result,
    ) {
        val uri = Uri.parse(downloadUrl.trim())
        val installed = packageManager.getPackageInfo(packageName, 0)
        if (uri.scheme != "https" || uri.host.isNullOrBlank() ||
            !uri.userInfo.isNullOrEmpty() ||
            !uri.path.orEmpty().endsWith(".apk", ignoreCase = true) ||
            targetVersionCode <= PackageInfoCompat.getLongVersionCode(installed)
        ) {
            result.error("invalid_update", "安装包地址或目标版本无效", null)
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !packageManager.canRequestPackageInstalls()
        ) {
            startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")),
            )
            result.success("请授权安装未知应用后再点击去更新")
            return
        }

        if (!UpdateInProgress.compareAndSet(false, true)) {
            result.error("update_in_progress", "正在下载安装包", null)
            return
        }
        thread(name = "xcagi-apk-update") {
            val downloaded = runCatching { downloadUpdateApk(uri, targetVersionCode) }
            runOnUiThread {
                UpdateInProgress.set(false)
                downloaded.mapCatching { apk ->
                    try {
                        check(!isFinishing && !isDestroyed) { "更新界面已关闭，请重试" }
                        openInstaller(apk)
                    } catch (error: Exception) {
                        apk.delete()
                        throw error
                    }
                }.fold(
                    onSuccess = { result.success("系统安装器已打开，请确认安装") },
                    onFailure = { result.error("update_failed", it.message ?: "安装包更新失败", null) },
                )
            }
        }
    }

    private fun downloadUpdateApk(uri: Uri, targetVersionCode: Long): File {
        val manager = requireNotNull(getSystemService(DownloadManager::class.java)) {
            "系统下载服务不可用"
        }
        val pending = getSharedPreferences("xcagi_package_update", MODE_PRIVATE)
        val pendingId = pending.getLong("id", -1L)
        val id =
            if (pendingId >= 0 && pending.getString("url", null) == uri.toString() &&
                pending.getLong("version", 0L) == targetVersionCode
            ) {
                pendingId
            } else {
                if (pendingId >= 0) manager.remove(pendingId)
                manager.enqueue(
                    DownloadManager.Request(uri)
                        .setTitle("XCAGI")
                        .setMimeType("application/vnd.android.package-archive")
                        .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE),
                )
            }
        try {
            check(pending.edit().putLong("id", id).putString("url", uri.toString())
                .putLong("version", targetVersionCode).commit()
            ) { "无法保存更新任务" }
            awaitDownload(manager, id)
            val dir = File(cacheDir, "updates").also { it.mkdirs() }
            val cutoff = System.currentTimeMillis() - 24L * 60 * 60 * 1000
            dir.listFiles()?.filter { it.lastModified() < cutoff }?.forEach { it.delete() }
            val apk = File.createTempFile("XCAGI-", ".apk", dir)
            try {
                val descriptor = manager.openDownloadedFile(id)
                ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { input ->
                    apk.outputStream().use { output -> input.copyTo(output) }
                }
                val archive = requireNotNull(packageManager.getPackageArchiveInfo(apk.path, 0)) {
                    "下载文件不是有效的 Android 安装包"
                }
                require(archive.packageName == packageName &&
                    PackageInfoCompat.getLongVersionCode(archive) == targetVersionCode
                ) { "安装包与当前应用或目标版本不一致" }
                return apk
            } catch (error: Exception) {
                apk.delete()
                throw error
            }
        } finally {
            try {
                manager.remove(id)
            } finally {
                pending.edit().clear().commit()
            }
        }
    }

    private fun awaitDownload(manager: DownloadManager, id: Long) {
        val query = DownloadManager.Query().setFilterById(id)
        val deadline = SystemClock.elapsedRealtime() + 10 * 60_000
        while (SystemClock.elapsedRealtime() < deadline) {
            manager.query(query).use { cursor ->
                check(cursor != null && cursor.moveToFirst()) { "下载任务已取消" }
                when (cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))) {
                    DownloadManager.STATUS_SUCCESSFUL -> return
                    DownloadManager.STATUS_FAILED -> {
                        val reason = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
                        error("下载安装包失败（$reason）")
                    }
                }
            }
            Thread.sleep(500)
        }
        error("下载安装包超时")
    }

    private fun openInstaller(apk: File) {
        val uri = FileProvider.getUriForFile(this, "$packageName.update.fileprovider", apk)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(intent)
    }
}

private object CredentialCipher {
    private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
    private const val KEY_ALIAS = "xcagi_credential_key"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val IV_LENGTH = 12
    private const val TAG_BITS = 128
    private const val PREFIX = "enc:v1:"

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        (keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let {
            return it.secretKey
        }
        val generator =
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    fun encrypt(plain: String): String {
        if (plain.isEmpty()) return ""
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey())
            val iv = cipher.iv
            val cipherText = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
            val packed = ByteArray(iv.size + cipherText.size)
            System.arraycopy(iv, 0, packed, 0, iv.size)
            System.arraycopy(cipherText, 0, packed, iv.size, cipherText.size)
            PREFIX + Base64.encodeToString(packed, Base64.NO_WRAP)
        } catch (_: Exception) {
            plain
        }
    }

    fun decrypt(stored: String): String {
        if (stored.isEmpty()) return ""
        if (!stored.startsWith(PREFIX)) return stored
        return try {
            val packed = Base64.decode(stored.removePrefix(PREFIX), Base64.NO_WRAP)
            val iv = packed.copyOfRange(0, IV_LENGTH)
            val cipherText = packed.copyOfRange(IV_LENGTH, packed.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(TAG_BITS, iv))
            String(cipher.doFinal(cipherText), Charsets.UTF_8)
        } catch (_: Exception) {
            ""
        }
    }
}
