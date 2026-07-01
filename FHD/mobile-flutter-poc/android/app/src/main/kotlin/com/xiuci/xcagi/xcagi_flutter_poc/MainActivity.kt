package com.xiuci.xcagi.mobile

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
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
import java.io.DataInputStream
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlin.concurrent.thread
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject

private const val DeltaFormatCopyDataV1 = "xcagi-copy-data-v1"
private const val SessionFileName = "xcagi_session.json"
private const val LegacySessionDataStorePath = "datastore/xcagi_session_enterprise.preferences_pb"
private const val LegacySessionMigrationMarkerName = "xcagi_session_legacy_migrated"

private data class PackageDeltaSpec(
    val available: Boolean,
    val format: String,
    val patchUrl: String,
    val baseVersionCode: Int,
    val targetVersionCode: Int,
    val patchSha256: String,
    val baseApkSha256: String,
    val targetApkSha256: String,
) {
    fun canUseFor(currentVersionCode: Int): Boolean =
        available &&
            format == DeltaFormatCopyDataV1 &&
            patchUrl.isNotBlank() &&
            baseVersionCode == currentVersionCode &&
            targetVersionCode > currentVersionCode
}

class MainActivity : FlutterFragmentActivity() {
    private var deepLinkChannel: MethodChannel? = null
    private var pendingDeepLinkRoute: String? = null
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
            val versionName = call.argument<String>("versionName").orEmpty()
            val currentVersionCode = call.argument<Int>("currentVersionCode") ?: 0
            @Suppress("UNCHECKED_CAST")
            val delta = call.argument<Map<String, Any?>>("delta").orEmpty()
            startPackageUpdate(downloadUrl, versionName, currentVersionCode, delta, result)
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
            data.scheme == "xcagi" -> data.host.orEmpty().let { host ->
                data.path?.let { path -> "$host$path" } ?: host
            }.ifBlank { null }
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
        versionName: String,
        currentVersionCode: Int,
        delta: Map<String, Any?>,
        result: MethodChannel.Result,
    ) {
        val safeUri =
            runCatching { validateApkUrl(downloadUrl) }
                .getOrElse {
                    result.error("invalid_url", it.message ?: "安装包下载地址无效", null)
                    return
                }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !packageManager.canRequestPackageInstalls()
        ) {
            val settingsIntent =
                Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:$packageName"),
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(settingsIntent)
            result.success("请授权安装未知应用后再点击去更新")
            return
        }

        val deltaSpec = parseDeltaSpec(delta)
        thread(name = "xcagi-apk-update") {
            runCatching {
                val apk = downloadUpdateApk(safeUri, versionName, deltaSpec, currentVersionCode)
                runOnUiThread {
                    openInstaller(apk)
                    result.success("系统安装器已打开，请确认安装")
                }
            }.onFailure {
                runOnUiThread {
                    result.error("update_failed", it.message ?: "安装包更新失败", null)
                }
            }
        }
    }

    private fun validateApkUrl(raw: String): Uri {
        require(raw.isNotBlank()) { "安装包下载地址为空" }
        val uri = Uri.parse(raw.trim())
        val scheme = uri.scheme?.lowercase().orEmpty()
        require(scheme == "https" || scheme == "http") { "安装包下载地址必须是 http(s)" }
        require(!uri.host.isNullOrBlank()) { "安装包下载地址缺少域名" }
        require(uri.path.orEmpty().lowercase().endsWith(".apk")) { "更新地址不是 APK 安装包" }
        return uri
    }

    private fun validatePatchUrl(raw: String): Uri {
        require(raw.isNotBlank()) { "增量包下载地址为空" }
        val uri = Uri.parse(raw.trim())
        val scheme = uri.scheme?.lowercase().orEmpty()
        require(scheme == "https" || scheme == "http") { "增量包下载地址必须是 http(s)" }
        require(!uri.host.isNullOrBlank()) { "增量包下载地址缺少域名" }
        return uri
    }

    private fun parseDeltaSpec(raw: Map<String, Any?>): PackageDeltaSpec? {
        if (!raw.readBool("available")) return null
        return PackageDeltaSpec(
            available = true,
            format = raw.readString("format"),
            patchUrl = raw.readString("patch_url"),
            baseVersionCode = raw.readInt("base_version_code"),
            targetVersionCode = raw.readInt("target_version_code"),
            patchSha256 = raw.readString("patch_sha256"),
            baseApkSha256 = raw.readString("base_apk_sha256"),
            targetApkSha256 = raw.readString("target_apk_sha256"),
        )
    }

    private fun downloadUpdateApk(
        uri: Uri,
        versionName: String,
        deltaSpec: PackageDeltaSpec?,
        currentVersionCode: Int,
    ): File {
        if (deltaSpec != null && deltaSpec.canUseFor(currentVersionCode)) {
            return runCatching { downloadAndApplyDelta(deltaSpec, versionName) }
                .getOrElse { downloadApk(uri, versionName) }
        }
        return downloadApk(uri, versionName)
    }

    private fun downloadAndApplyDelta(deltaSpec: PackageDeltaSpec, versionName: String): File {
        val patchUri = validatePatchUrl(deltaSpec.patchUrl)
        val dir = File(cacheDir, "updates").also { it.mkdirs() }
        val patchFile = File(dir, deltaFileName(versionName))
        val sourceApk = File(applicationInfo.sourceDir)
        val target = File(dir, apkFileName(versionName))
        val targetTmp = File(dir, "${target.name}.delta.tmp")

        verifyExpectedSha(sourceApk, deltaSpec.baseApkSha256, "当前安装包与增量包不匹配")
        downloadToFile(patchUri, patchFile)
        verifyExpectedSha(patchFile, deltaSpec.patchSha256, "增量包校验失败")

        if (targetTmp.exists()) targetTmp.delete()
        applyDelta(sourceApk, patchFile, targetTmp)
        verifyExpectedSha(targetTmp, deltaSpec.targetApkSha256, "合成安装包校验失败")

        if (target.exists()) target.delete()
        if (!targetTmp.renameTo(target)) {
            targetTmp.copyTo(target, overwrite = true)
            targetTmp.delete()
        }
        cleanOldUpdateFiles(dir, target)
        return target
    }

    private fun downloadApk(uri: Uri, versionName: String): File {
        val dir = File(cacheDir, "updates").also { it.mkdirs() }
        val target = File(dir, apkFileName(versionName))
        val tmp = File(dir, "${target.name}.tmp")
        if (target.exists()) target.delete()
        if (tmp.exists()) tmp.delete()

        downloadToFile(uri, tmp)
        if (tmp.length() <= 0L) {
            tmp.delete()
            throw IllegalStateException("下载安装包失败：文件为空")
        }
        if (!tmp.renameTo(target)) {
            tmp.copyTo(target, overwrite = true)
            tmp.delete()
        }
        cleanOldUpdateFiles(dir, target)
        return target
    }

    private fun downloadToFile(uri: Uri, target: File) {
        val parent = target.parentFile ?: throw IllegalStateException("保存目录无效")
        val tmp = File(parent, "${target.name}.download")
        if (target.exists()) target.delete()
        if (tmp.exists()) tmp.delete()
        val connection = (URL(uri.toString()).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 5 * 60_000
            instanceFollowRedirects = true
        }
        try {
            val code = connection.responseCode
            if (code !in 200..299) {
                throw IllegalStateException("下载更新文件失败：HTTP $code")
            }
            connection.inputStream.use { input ->
                FileOutputStream(tmp).use { output ->
                    input.copyTo(output)
                }
            }
            if (tmp.length() <= 0L) {
                throw IllegalStateException("下载更新文件失败：文件为空")
            }
            if (!tmp.renameTo(target)) {
                tmp.copyTo(target, overwrite = true)
                tmp.delete()
            }
        } finally {
            connection.disconnect()
            if (tmp.exists()) tmp.delete()
        }
    }

    private fun openInstaller(apk: File) {
        val uri =
            FileProvider.getUriForFile(
                this,
                "$packageName.update.fileprovider",
                apk,
            )
        val intent =
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
    }

    private fun apkFileName(versionName: String): String {
        val clean =
            versionName
                .trim()
                .replace(Regex("[^A-Za-z0-9._-]"), "_")
                .take(80)
                .ifBlank { "latest" }
        return "XCAGI-Android-$clean.apk"
    }

    private fun deltaFileName(versionName: String): String =
        apkFileName(versionName).removeSuffix(".apk") + ".xcapkdiff"

    private fun cleanOldUpdateFiles(dir: File, keep: File) {
        dir.listFiles()
            ?.filter { it != keep && (it.extension == "apk" || it.extension == "xcapkdiff") }
            ?.forEach { it.delete() }
    }

    private fun verifyExpectedSha(file: File, expected: String, error: String) {
        val cleanExpected = expected.trim()
        if (cleanExpected.isEmpty()) return
        require(sha256(file).equals(cleanExpected, ignoreCase = true)) { error }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    private fun applyDelta(oldApk: File, patchFile: File, outputApk: File) {
        val magicBytes = "XCAGIDLT1".toByteArray(Charsets.US_ASCII)
        DataInputStream(BufferedInputStream(patchFile.inputStream())).use { patch ->
            val magic = ByteArray(magicBytes.size)
            patch.readFully(magic)
            require(magic.contentEquals(magicBytes)) { "增量包格式不匹配" }

            RandomAccessFile(oldApk, "r").use { old ->
                outputApk.outputStream().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    loop@ while (true) {
                        when (val command = patch.readByte()) {
                            0.toByte() -> {
                                val offset = patch.readLong()
                                val length = patch.readInt()
                                require(offset >= 0L && length >= 0) { "增量包 COPY 段无效" }
                                copyOldRange(old, offset, length, output, buffer)
                            }
                            1.toByte() -> {
                                val length = patch.readInt()
                                require(length >= 0) { "增量包 DATA 段无效" }
                                copyPatchData(patch, length, output, buffer)
                            }
                            2.toByte() -> break@loop
                            else -> throw IllegalStateException("增量包命令无效：$command")
                        }
                    }
                }
            }
        }
    }

    private fun copyOldRange(
        old: RandomAccessFile,
        offset: Long,
        length: Int,
        output: OutputStream,
        buffer: ByteArray,
    ) {
        old.seek(offset)
        var remaining = length
        while (remaining > 0) {
            val read = old.read(buffer, 0, minOf(buffer.size, remaining))
            if (read <= 0) throw IllegalStateException("读取旧安装包失败")
            output.write(buffer, 0, read)
            remaining -= read
        }
    }

    private fun copyPatchData(
        patch: DataInputStream,
        length: Int,
        output: OutputStream,
        buffer: ByteArray,
    ) {
        var remaining = length
        while (remaining > 0) {
            val read = minOf(buffer.size, remaining)
            patch.readFully(buffer, 0, read)
            output.write(buffer, 0, read)
            remaining -= read
        }
    }

    private fun Map<String, Any?>.readString(key: String): String =
        this[key]?.toString().orEmpty()

    private fun Map<String, Any?>.readInt(key: String): Int =
        when (val value = this[key]) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull() ?: 0
            else -> 0
        }

private fun Map<String, Any?>.readBool(key: String): Boolean =
        when (val value = this[key]) {
            is Boolean -> value
            is Number -> value.toInt() != 0
            is String -> value.equals("true", ignoreCase = true) || value == "1"
            else -> false
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
