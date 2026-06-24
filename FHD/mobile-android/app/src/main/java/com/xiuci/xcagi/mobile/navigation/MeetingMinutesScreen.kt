package com.xiuci.xcagi.mobile.navigation

import android.Manifest
import android.media.MediaRecorder
import android.os.Build
import android.webkit.WebView
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.xiuci.xcagi.mobile.ui.AppViewModel
import java.io.File

/**
 * 会议纪要屏：录音转写 / 粘贴原文 → 一键生成三级纪要（剧本式 → 架构图式 → 说人话）。
 * 三级与后端 SSOT 同源；L2 架构图用 WebView 渲染 Mermaid。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MeetingMinutesScreen(vm: AppViewModel, onBack: () -> Unit) {
    val context = LocalContext.current

    val levels by vm.meetingLevels.collectAsState()
    val result by vm.meetingResult.collectAsState()
    val generating by vm.meetingGenerating.collectAsState()
    val transcribing by vm.meetingTranscribing.collectAsState()
    val meetingError by vm.meetingError.collectAsState()

    var transcript by remember { mutableStateOf("") }
    var activeTab by remember { mutableIntStateOf(0) }
    var recording by remember { mutableStateOf(false) }

    val recorderHolder = remember { mutableStateOf<MediaRecorder?>(null) }
    val recordFile = remember { mutableStateOf<File?>(null) }

    fun startRecording() {
        val file = File(context.cacheDir, "meeting_${System.currentTimeMillis()}.m4a")
        val rec = newMediaRecorder(context)
        try {
            rec.setAudioSource(MediaRecorder.AudioSource.MIC)
            rec.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            rec.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            rec.setOutputFile(file.absolutePath)
            rec.prepare()
            rec.start()
            recorderHolder.value = rec
            recordFile.value = file
            recording = true
        } catch (e: Exception) {
            try {
                rec.release()
            } catch (_: Exception) {
            }
            recording = false
        }
    }

    fun stopRecordingAndTranscribe() {
        val rec = recorderHolder.value ?: return
        try {
            rec.stop()
        } catch (_: Exception) {
        }
        try {
            rec.release()
        } catch (_: Exception) {
        }
        recorderHolder.value = null
        recording = false
        val file = recordFile.value
        if (file != null && file.exists() && file.length() > 0) {
            val bytes = file.readBytes()
            vm.transcribeMeeting(bytes, "audio/mp4") { text ->
                transcript = if (transcript.isBlank()) text else "${transcript.trimEnd()}\n$text"
            }
        }
    }

    val micPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> if (granted) startRecording() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("会议纪要") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Button(
                    enabled = !generating && !transcribing,
                    onClick = {
                        if (recording) {
                            stopRecordingAndTranscribe()
                        } else {
                            micPermission.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    },
                ) {
                    Text(if (recording) "停止录音" else "开始录音")
                }
                if (transcribing) Text("转写中…")
                else if (meetingError.isNotBlank()) Text(meetingError)
            }

            OutlinedTextField(
                value = transcript,
                onValueChange = { transcript = it },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 12.dp),
                label = { Text("会议转写原文（可粘贴或录音自动填入）") },
                minLines = 4,
                maxLines = 8,
            )

            Button(
                enabled = transcript.isNotBlank() && !generating && !transcribing,
                onClick = { vm.generateMeetingMinutes(transcript) },
                modifier = Modifier.padding(top = 12.dp),
            ) {
                Text(if (generating) "生成中…" else "一键生成三级纪要")
            }

            val status = result?.status
            if (status == "degraded") {
                Text("⚠️ AI 暂不可用，已保存原文，稍后可重试", modifier = Modifier.padding(top = 8.dp))
            } else if (status == "failed") {
                Text("生成失败：${result?.error_message ?: "未知错误"}", modifier = Modifier.padding(top = 8.dp))
            }

            TabRow(selectedTabIndex = activeTab, modifier = Modifier.padding(top = 12.dp)) {
                levels.forEachIndexed { idx, lvl ->
                    Tab(
                        selected = activeTab == idx,
                        onClick = { activeTab = idx },
                        text = { Text(lvl.short ?: lvl.label) },
                    )
                }
            }

            val content = when (levels.getOrNull(activeTab)?.id) {
                "level1_script" -> result?.level1_script
                "level2_architecture" -> result?.level2_architecture
                "level3_plain" -> result?.level3_plain
                else -> null
            }.orEmpty()

            val isMermaid = levels.getOrNull(activeTab)?.render == "mermaid"

            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = 12.dp)
                    .verticalScroll(rememberScrollState()),
            ) {
                when {
                    content.isBlank() -> Text(
                        if (result != null) "该层暂无内容" else "生成后这里显示：剧本式实录 → 架构图式总结 → 说人话",
                    )
                    isMermaid -> MermaidWebView(content, Modifier.fillMaxWidth())
                    else -> SelectionContainer { Text(content) }
                }
            }
        }
    }
}

@Suppress("DEPRECATION")
private fun newMediaRecorder(context: android.content.Context): MediaRecorder =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(context) else MediaRecorder()

/** 用 WebView + Mermaid 渲染 L2 架构图（含 ```mermaid 代码块 + 提纲）。 */
@Composable
private fun MermaidWebView(markdown: String, modifier: Modifier = Modifier) {
    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
            }
        },
        update = { web -> web.loadDataWithBaseURL(null, buildMermaidHtml(markdown), "text/html", "utf-8", null) },
    )
}

private fun buildMermaidHtml(markdown: String): String {
    val esc = markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    // 把 ```mermaid ... ``` 提为 <pre class="mermaid">，其余作为纯文本 <pre>。
    val regex = Regex("```mermaid\\s*([\\s\\S]*?)```", RegexOption.IGNORE_CASE)
    val body = StringBuilder()
    var last = 0
    for (m in regex.findAll(esc)) {
        if (m.range.first > last) body.append("<pre class=\"txt\">").append(esc.substring(last, m.range.first)).append("</pre>")
        body.append("<pre class=\"mermaid\">").append(m.groupValues[1].trim()).append("</pre>")
        last = m.range.last + 1
    }
    if (last < esc.length) body.append("<pre class=\"txt\">").append(esc.substring(last)).append("</pre>")
    return """
        <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{background:#1b1c1f;color:#e8e8ea;font-family:sans-serif;padding:8px;margin:0}
        pre.txt{white-space:pre-wrap;word-break:break-word}.mermaid{background:transparent}</style>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
        </head><body>$body
        <script>try{mermaid.initialize({startOnLoad:true,theme:'dark',securityLevel:'loose'});}catch(e){}</script>
        </body></html>
    """.trimIndent()
}
