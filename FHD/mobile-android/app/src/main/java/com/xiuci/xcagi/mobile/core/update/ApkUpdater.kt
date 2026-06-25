package com.xiuci.xcagi.mobile.core.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * 应用内自更新：把整包 APK 流式下载到应用私有目录，再经 FileProvider 拉起系统安装器。
 *
 * 与旧实现（跳浏览器下载整包、用户自己找文件点安装）相比，用户全程不离开 App。
 * 仍是「整包替换」而非热修复——不引入 Tinker/Sophix，避免合规与稳定性风险。
 */
object ApkUpdater {
    private const val SUBDIR = "updates"
    private const val APK_NAME = "xcagi-update.apk"

    private val client by lazy {
        OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(120, TimeUnit.SECONDS)
                .build()
    }

    private fun authority(context: Context): String = "${context.packageName}.fileprovider"

    /** 下载目标：应用私有 external 目录，FileProvider 可共享，App 卸载时随之清理。 */
    private fun targetFile(context: Context): File {
        val dir = File(context.getExternalFilesDir(null), SUBDIR).apply { mkdirs() }
        return File(dir, APK_NAME)
    }

    /**
     * 流式下载 APK，按字节进度回调 [onProgress]（0..100）。
     * 协程取消时抛 [CancellationException]；其它失败包装进 [Result.failure]。
     */
    suspend fun download(
            context: Context,
            url: String,
            onProgress: (Int) -> Unit,
    ): Result<File> =
            withContext(Dispatchers.IO) {
                val target = targetFile(context)
                try {
                    if (target.exists()) target.delete()
                    val request = Request.Builder().url(url).build()
                    client.newCall(request).execute().use { resp ->
                        if (!resp.isSuccessful) error("HTTP ${resp.code}")
                        val body = resp.body ?: error("响应为空")
                        val total = body.contentLength()
                        var downloaded = 0L
                        var lastPct = -1
                        body.byteStream().use { input ->
                            target.outputStream().use { output ->
                                val buf = ByteArray(16 * 1024)
                                while (true) {
                                    ensureActive() // 支持取消：每读一块前检查协程是否仍活跃
                                    val read = input.read(buf)
                                    if (read < 0) break
                                    output.write(buf, 0, read)
                                    downloaded += read
                                    if (total > 0) {
                                        val pct =
                                                ((downloaded * 100) / total).toInt().coerceIn(0, 100)
                                        if (pct != lastPct) {
                                            lastPct = pct
                                            onProgress(pct)
                                        }
                                    }
                                }
                                output.flush()
                            }
                        }
                    }
                    if (!target.exists() || target.length() == 0L) error("下载文件无效")
                    Result.success(target)
                } catch (ce: CancellationException) {
                    runCatching { target.delete() }
                    throw ce
                } catch (e: Exception) {
                    runCatching { target.delete() } // 清理半成品，避免误装
                    Result.failure(e)
                }
            }

    /** Android 8+ 安装未知来源应用需用户单独授权。 */
    fun canInstall(context: Context): Boolean =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
                    context.packageManager.canRequestPackageInstalls()

    /** 跳转系统设置页，让用户为本应用开启「安装未知应用」权限。 */
    fun requestInstallPermission(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val intent =
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                            .setData(Uri.parse("package:${context.packageName}"))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            runCatching { context.startActivity(intent) }
        }
    }

    /** 经 FileProvider 拉起系统安装器安装已下载的 APK。 */
    fun install(context: Context, file: File) {
        val uri = FileProvider.getUriForFile(context, authority(context), file)
        val intent =
                Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/vnd.android.package-archive")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                }
        context.startActivity(intent)
    }
}
