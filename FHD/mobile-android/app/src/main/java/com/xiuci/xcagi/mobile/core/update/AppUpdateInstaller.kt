package com.xiuci.xcagi.mobile.core.update

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

sealed class PackageUpdateResult {
    data class InstallerOpened(val apkPath: String) : PackageUpdateResult()
    object InstallPermissionRequired : PackageUpdateResult()
}

data class PackageDeltaSpec(
        val format: String,
        val patchUrl: String,
        val baseVersionCode: Int,
        val targetVersionCode: Int,
        val patchSha256: String = "",
        val baseApkSha256: String = "",
        val targetApkSha256: String = "",
) {
    fun canUseFor(currentVersionCode: Int): Boolean =
            format == ApkUpdatePolicy.DELTA_FORMAT_COPY_DATA_V1 &&
                    patchUrl.isNotBlank() &&
                    baseVersionCode == currentVersionCode &&
                    targetVersionCode > currentVersionCode
}

internal object ApkUpdatePolicy {
    const val DELTA_FORMAT_COPY_DATA_V1 = "xcagi-copy-data-v1"

    fun validateDownloadUrl(rawUrl: String): String {
        val url = rawUrl.trim()
        require(url.isNotBlank()) { "安装包下载地址为空" }
        val uri =
                runCatching { URI(url) }
                        .getOrElse { throw IllegalArgumentException("安装包下载地址无效") }
        val scheme = uri.scheme?.lowercase().orEmpty()
        require(scheme == "https" || scheme == "http") { "安装包下载地址必须是 http(s)" }
        require(!uri.host.isNullOrBlank()) { "安装包下载地址缺少域名" }
        require((uri.path ?: "").lowercase().endsWith(".apk")) { "更新地址不是 APK 安装包" }
        return uri.toString()
    }

    fun validatePatchUrl(rawUrl: String): String {
        val url = rawUrl.trim()
        require(url.isNotBlank()) { "增量包下载地址为空" }
        val uri =
                runCatching { URI(url) }
                        .getOrElse { throw IllegalArgumentException("增量包下载地址无效") }
        val scheme = uri.scheme?.lowercase().orEmpty()
        require(scheme == "https" || scheme == "http") { "增量包下载地址必须是 http(s)" }
        require(!uri.host.isNullOrBlank()) { "增量包下载地址缺少域名" }
        return uri.toString()
    }

    fun apkFileName(versionName: String): String {
        val clean =
                versionName
                        .trim()
                        .replace(Regex("[^A-Za-z0-9._-]"), "_")
                        .take(80)
                        .ifBlank { "latest" }
        return "XCAGI-Android-$clean.apk"
    }

    fun deltaFileName(versionName: String): String =
            apkFileName(versionName).removeSuffix(".apk") + ".xcapkdiff"
}

internal object XcagiDeltaPatch {
    private val MAGIC = "XCAGIDLT1".toByteArray(Charsets.US_ASCII)
    private const val CMD_COPY: Byte = 0
    private const val CMD_DATA: Byte = 1
    private const val CMD_END: Byte = 2

    fun apply(oldApk: File, patchFile: File, outputApk: File) {
        DataInputStream(BufferedInputStream(patchFile.inputStream())).use { patch ->
            val magic = ByteArray(MAGIC.size)
            patch.readFully(magic)
            require(magic.contentEquals(MAGIC)) { "增量包格式不匹配" }

            RandomAccessFile(oldApk, "r").use { old ->
                outputApk.outputStream().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        when (val command = patch.readByte()) {
                            CMD_COPY -> {
                                val offset = patch.readLong()
                                val length = patch.readInt()
                                require(offset >= 0L && length >= 0) { "增量包 COPY 段无效" }
                                copyOldRange(old, offset, length, output, buffer)
                            }
                            CMD_DATA -> {
                                val length = patch.readInt()
                                require(length >= 0) { "增量包 DATA 段无效" }
                                copyPatchData(patch, length, output, buffer)
                            }
                            CMD_END -> break
                            else -> throw IOException("增量包命令无效：$command")
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
            output: java.io.OutputStream,
            buffer: ByteArray,
    ) {
        old.seek(offset)
        var remaining = length
        while (remaining > 0) {
            val read = old.read(buffer, 0, minOf(buffer.size, remaining))
            if (read <= 0) throw IOException("读取旧安装包失败")
            output.write(buffer, 0, read)
            remaining -= read
        }
    }

    private fun copyPatchData(
            patch: DataInputStream,
            length: Int,
            output: java.io.OutputStream,
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
}

@Singleton
class AppUpdateInstaller
@Inject
constructor(
        @ApplicationContext private val context: Context,
        private val okHttp: OkHttpClient,
) {
    private val downloadClient: OkHttpClient =
            okHttp
                    .newBuilder()
                    .readTimeout(5, TimeUnit.MINUTES)
                    .callTimeout(10, TimeUnit.MINUTES)
                    .build()

    fun canInstallPackages(): Boolean =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
                    context.packageManager.canRequestPackageInstalls()

    fun openInstallPermissionSettings() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val intent =
                Intent(
                                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:${context.packageName}"),
                        )
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    suspend fun downloadAndOpenInstaller(
            downloadUrl: String,
            versionName: String,
            deltaSpec: PackageDeltaSpec? = null,
            currentVersionCode: Int = 0,
            onStatus: (String) -> Unit = {},
    ): PackageUpdateResult {
        val apkFile =
                if (deltaSpec != null && deltaSpec.canUseFor(currentVersionCode)) {
                    runCatching { downloadAndApplyDelta(deltaSpec, versionName, onStatus) }
                            .getOrElse {
                                onStatus("增量更新失败，切换完整安装包…")
                                downloadApk(downloadUrl, versionName) { percent ->
                                    onStatus("正在下载完整安装包… $percent%")
                                }
                            }
                } else {
                    downloadApk(downloadUrl, versionName) { percent ->
                        onStatus("正在下载完整安装包… $percent%")
                    }
                }
        return openInstaller(apkFile)
    }

    private suspend fun downloadAndApplyDelta(
            deltaSpec: PackageDeltaSpec,
            versionName: String,
            onStatus: (String) -> Unit,
    ): File =
            withContext(Dispatchers.IO) {
                val safeUrl = ApkUpdatePolicy.validatePatchUrl(deltaSpec.patchUrl)
                val targetDir = File(context.cacheDir, "updates").apply { mkdirs() }
                val patchFile = File(targetDir, ApkUpdatePolicy.deltaFileName(versionName))
                val sourceApk = File(context.applicationInfo.sourceDir)
                val targetFile = File(targetDir, ApkUpdatePolicy.apkFileName(versionName))
                val targetTmp = File(targetDir, "${targetFile.name}.delta.tmp")

                verifyExpectedSha(sourceApk, deltaSpec.baseApkSha256, "当前安装包与增量包不匹配")
                downloadToFile(safeUrl, patchFile) { percent ->
                    onStatus("正在下载增量包… $percent%")
                }
                verifyExpectedSha(patchFile, deltaSpec.patchSha256, "增量包校验失败")

                onStatus("正在合成安装包…")
                if (targetTmp.exists()) targetTmp.delete()
                XcagiDeltaPatch.apply(sourceApk, patchFile, targetTmp)

                onStatus("正在校验安装包…")
                verifyExpectedSha(targetTmp, deltaSpec.targetApkSha256, "合成安装包校验失败")
                if (targetFile.exists()) targetFile.delete()
                if (!targetTmp.renameTo(targetFile)) {
                    targetTmp.copyTo(targetFile, overwrite = true)
                    targetTmp.delete()
                }
                cleanOldApks(targetDir, targetFile)
                targetFile
            }

    private suspend fun downloadApk(
            downloadUrl: String,
            versionName: String,
            onProgress: (Int) -> Unit,
    ): File =
            withContext(Dispatchers.IO) {
                val safeUrl = ApkUpdatePolicy.validateDownloadUrl(downloadUrl)
                val targetDir = File(context.cacheDir, "updates").apply { mkdirs() }
                val targetFile = File(targetDir, ApkUpdatePolicy.apkFileName(versionName))
                val tmpFile = File(targetDir, "${targetFile.name}.tmp")
                downloadToFile(safeUrl, tmpFile, onProgress)

                if (!tmpFile.isFile || tmpFile.length() <= 0L) {
                    tmpFile.delete()
                    throw IOException("下载安装包失败：文件为空")
                }
                if (targetFile.exists()) targetFile.delete()
                if (!tmpFile.renameTo(targetFile)) {
                    tmpFile.copyTo(targetFile, overwrite = true)
                    tmpFile.delete()
                }
                onProgress(100)
                cleanOldApks(targetDir, targetFile)
                targetFile
            }

    private fun downloadToFile(
            safeUrl: String,
            targetFile: File,
            onProgress: (Int) -> Unit,
    ) {
        val tmpFile = File(targetFile.parentFile, "${targetFile.name}.download")
        if (tmpFile.exists()) tmpFile.delete()
        val request = Request.Builder().url(safeUrl).get().build()

        downloadClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("下载失败：HTTP ${response.code}")
            }
            val body = response.body ?: throw IOException("下载失败：空响应")
            tmpFile.outputStream().use { output ->
                body.byteStream().use { input ->
                    val total = body.contentLength().takeIf { it > 0L } ?: -1L
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    var copied = 0L
                    var lastPercent = -1
                    while (true) {
                        val read = input.read(buffer)
                        if (read == -1) break
                        output.write(buffer, 0, read)
                        copied += read
                        if (total > 0L) {
                            val percent = ((copied * 100L) / total).toInt().coerceIn(1, 99)
                            if (percent != lastPercent) {
                                lastPercent = percent
                                onProgress(percent)
                            }
                        }
                    }
                }
            }
        }
        if (!tmpFile.isFile || tmpFile.length() <= 0L) {
            tmpFile.delete()
            throw IOException("下载失败：文件为空")
        }
        if (targetFile.exists()) targetFile.delete()
        if (!tmpFile.renameTo(targetFile)) {
            tmpFile.copyTo(targetFile, overwrite = true)
            tmpFile.delete()
        }
        onProgress(100)
    }

    private fun verifyExpectedSha(file: File, expectedSha256: String, errorMessage: String) {
        val expected = expectedSha256.trim().lowercase()
        if (expected.isBlank()) return
        if (sha256(file) != expected) throw IOException(errorMessage)
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read == -1) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun cleanOldApks(targetDir: File, keep: File) {
        targetDir
                .listFiles { file -> file.extension.equals("apk", ignoreCase = true) && file != keep }
                ?.forEach { it.delete() }
    }

    private fun openInstaller(apkFile: File): PackageUpdateResult {
        if (!canInstallPackages()) {
            openInstallPermissionSettings()
            return PackageUpdateResult.InstallPermissionRequired
        }
        val uri =
                FileProvider.getUriForFile(
                        context,
                        "${context.packageName}.update.fileprovider",
                        apkFile,
                )
        val installIntent =
                Intent(Intent.ACTION_INSTALL_PACKAGE)
                        .setData(uri)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        .putExtra(Intent.EXTRA_NOT_UNKNOWN_SOURCE, true)
                        .putExtra(Intent.EXTRA_RETURN_RESULT, false)
        try {
            context.startActivity(installIntent)
        } catch (_: ActivityNotFoundException) {
            val viewIntent =
                    Intent(Intent.ACTION_VIEW)
                            .setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            context.startActivity(viewIntent)
        }
        return PackageUpdateResult.InstallerOpened(apkFile.absolutePath)
    }
}
