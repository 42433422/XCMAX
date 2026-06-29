package com.xiuci.xcagi.mobile.core.network

import com.google.gson.Gson
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.BufferedReader
import java.io.InputStreamReader
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SseChatClient @Inject constructor(
    private val okHttp: OkHttpClient,
    private val serverRouter: ServerRouter,
) {
    private val gson = Gson()

    suspend fun streamChat(
        message: String,
        bearer: String,
        userId: Int,
        useCloud: Boolean = false,
        recentMessages: List<Map<String, String>> = emptyList(),
        industry: String? = null,
        refreshBearer: (suspend () -> String)? = null,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) = withContext(Dispatchers.IO) {
        val url = "${serverRouter.fhdBaseUrl()}api/ai/chat/stream"
        // 构造与桌面端一致的请求体：message + context.recent_messages + user_id + source + mode
        val bodyMap = mutableMapOf<String, Any>(
            "message" to message,
            "source" to "pro",
            "mode" to "professional",
        )
        if (userId > 0) bodyMap["user_id"] = userId.toString()
        // 上下文：最近6条对话 + 行业（与桌面端 useChatRequest.ts 一致）
        val contextMap = mutableMapOf<String, Any>()
        if (recentMessages.isNotEmpty()) {
            contextMap["recent_messages"] = recentMessages
        }
        if (!industry.isNullOrBlank()) {
            contextMap["industry"] = industry
        }
        if (contextMap.isNotEmpty()) {
            bodyMap["context"] = contextMap
        }
        val bodyJson = gson.toJson(bodyMap)
        fun buildRequest(currentBearer: String): Request {
            val reqBuilder = Request.Builder()
                .url(url)
                .post(bodyJson.toRequestBody("application/json".toMediaType()))
                .header("Accept", "text/event-stream")
                .header("X-XCAGI-Client", "android")
            if (currentBearer.isNotBlank()) {
                reqBuilder.header("Authorization", currentBearer)
            }
            if (userId > 0) {
                reqBuilder.header("X-User-ID", userId.toString())
            }
            return reqBuilder.build()
        }

        // 重试机制：后端 LLM 上游存在间歇性 SSL 握手超时（_ssl.c:999），
        // 桌面端有重试因此能恢复，移动端原本单次失败即放弃。
        // 仅在连接建立失败（HTTP 错误或网络异常）时重试，
        // 一旦开始接收 SSE token 流则不再重试（避免重复输出）。
        val maxAttempts = 3
        var lastError: String? = null
        var currentBearer = bearer
        for (attempt in 1..maxAttempts) {
            // 用于标记是否已开始流式接收；若已开始则失败不可重试。
            var streamingStarted = false
            try {
                val req = buildRequest(currentBearer)
                okHttp.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        lastError = if (useCloud) "远程对话 HTTP ${resp.code}" else "HTTP ${resp.code}"
                        if (resp.code in setOf(401, 403) && refreshBearer != null && attempt < maxAttempts) {
                            refreshBearer().takeIf { it.isNotBlank() }?.let { currentBearer = it }
                            delay(300L)
                            return@use
                        }
                        // 5xx 错误可能是后端 LLM 上游瞬时故障，可重试；4xx 不重试。
                        if (resp.code in 500..599 && attempt < maxAttempts) {
                            delay(800L * attempt)
                            return@use
                        }
                        onError(lastError)
                        return@withContext
                    }
                    val reader = BufferedReader(InputStreamReader(resp.body!!.byteStream()))
                    val buf = StringBuilder()
                    var line: String?
                    while (reader.readLine().also { line = it } != null) {
                        val l = line!!.trim()
                        if (!l.startsWith("data:")) continue
                        val payload = l.removePrefix("data:").trim()
                        if (payload.isBlank() || payload == "[DONE]") continue
                        try {
                            val json = JsonParser.parseString(payload).asJsonObject
                            val eventType = json.get("type")?.asString
                            if (!eventType.isNullOrBlank()) {
                                when (eventType) {
                                    "token" -> {
                                        streamingStarted = true
                                        val t = json.get("text")?.asString ?: ""
                                        if (t.isNotEmpty()) {
                                            buf.append(t)
                                            onToken(t)
                                        }
                                    }
                                    "done" -> {
                                        val result = json.get("result")
                                        val finalText = when {
                                            result == null -> buf.toString()
                                            result.isJsonObject -> result.asJsonObject.get("response")?.asString ?: buf.toString()
                                            else -> result.asString
                                        }
                                        onDone(finalText.ifBlank { buf.toString() })
                                        return@withContext
                                    }
                                    "error" -> {
                                        val errMsg = json.get("message")?.asString ?: "stream error"
                                        // 后端 LLM 上游瞬时错误（如 SSL 握手超时）可重试；
                                        // 但若已开始输出 token 则不重试（避免内容断裂）。
                                        if (!streamingStarted && attempt < maxAttempts && isRetryableUpstreamError(errMsg)) {
                                            lastError = errMsg
                                            delay(800L * attempt)
                                            return@use
                                        }
                                        onError(errMsg)
                                        return@withContext
                                    }
                                }
                            } else if (useCloud) {
                                streamingStarted = true
                                json.get("error")?.asString?.takeIf { it.isNotBlank() }?.let {
                                    onError(it)
                                    return@withContext
                                }
                                val t = json.get("text")?.asString ?: ""
                                if (t.isNotEmpty()) {
                                    buf.append(t)
                                    onToken(t)
                                }
                                if (json.get("done")?.asBoolean == true) {
                                    onDone(buf.toString().ifBlank { "（无回复）" })
                                    return@withContext
                                }
                            }
                        } catch (_: Exception) {
                        }
                    }
                    onDone(buf.toString().ifBlank { "（无回复）" })
                    return@withContext
                }
            } catch (e: Exception) {
                val errMsg = e.message ?: "连接失败"
                lastError = errMsg
                // 网络异常（连接超时/SSL 握手失败）可重试
                if (attempt < maxAttempts) {
                    delay(800L * attempt)
                    continue
                }
                onError(errMsg)
                return@withContext
            }
        }
        // 所有重试均失败
        val finalErr = lastError ?: "连接失败"
        onError(finalErr)
    }

    /**
     * 判断后端 LLM 上游错误是否值得重试。
     * 典型可重试场景：SSL 握手超时（_ssl.c:999）、上游超时、502/504。
     */
    private fun isRetryableUpstreamError(msg: String): Boolean {
        val lower = msg.lowercase()
        return lower.contains("_ssl.c") ||
            lower.contains("handshake") ||
            lower.contains("timeout") ||
            lower.contains("timed out") ||
            lower.contains("upstream") ||
            lower.contains("502") ||
            lower.contains("504") ||
            lower.contains("上游")
    }

    /**
     * 员工 chat 流式接口（手机端）。
     *
     * POST /api/mobile/v1/employees/{employeeId}/chat/stream
     * 后端同步跑员工 agent loop，然后把结果按句号 chunk emit 成 SSE token 流（伪流式）。
     *
     * 注意：员工 chat 不做重试 —— 后端 agent loop 有副作用（可能改文件、跑测试、调接口），
     * 重试会重复执行员工任务。失败即报错给用户。
     */
    suspend fun streamEmployeeChat(
        message: String,
        employeeId: String,
        modId: String,
        conversationId: String,
        bearer: String,
        userId: Int,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) = withContext(Dispatchers.IO) {
        val url = "${serverRouter.fhdBaseUrl()}api/mobile/v1/employees/$employeeId/chat/stream"
        val bodyMap = mapOf(
            "message" to message,
            "conversation_id" to conversationId,
            "mod_id" to modId,
            "employee_id" to employeeId,
        )
        val bodyJson = gson.toJson(bodyMap)
        val reqBuilder = Request.Builder()
            .url(url)
            .post(bodyJson.toRequestBody("application/json".toMediaType()))
            .header("Accept", "text/event-stream")
            .header("X-XCAGI-Client", "android")
        if (bearer.isNotBlank()) {
            reqBuilder.header("Authorization", bearer)
        }
        if (userId > 0) {
            reqBuilder.header("X-User-ID", userId.toString())
        }
        val req = reqBuilder.build()

        val buf = StringBuilder()
        try {
            okHttp.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    onError("员工对话 HTTP ${resp.code}")
                    return@withContext
                }
                val reader = BufferedReader(InputStreamReader(resp.body!!.byteStream()))
                var line: String?
                while (reader.readLine().also { line = it } != null) {
                    val l = line!!.trim()
                    if (!l.startsWith("data:")) continue
                    val payload = l.removePrefix("data:").trim()
                    if (payload.isBlank() || payload == "[DONE]") continue
                    try {
                        val json = JsonParser.parseString(payload).asJsonObject
                        val eventType = json.get("type")?.asString
                        when (eventType) {
                            "token" -> {
                                val t = json.get("text")?.asString ?: ""
                                if (t.isNotEmpty()) {
                                    buf.append(t)
                                    onToken(t)
                                }
                            }
                            "done" -> {
                                val result = json.get("result")
                                val finalText = when {
                                    result == null -> buf.toString()
                                    result.isJsonObject -> result.asJsonObject.get("response")?.asString ?: buf.toString()
                                    else -> result.asString
                                }
                                onDone(finalText.ifBlank { buf.toString() })
                                return@withContext
                            }
                            "error" -> {
                                val errMsg = json.get("message")?.asString ?: "员工对话流错误"
                                onError(errMsg)
                                return@withContext
                            }
                        }
                    } catch (_: Exception) {
                    }
                }
                onDone(buf.toString().ifBlank { "（员工未回复）" })
            }
        } catch (e: Exception) {
            onError(e.message ?: "员工对话连接失败")
        }
    }
}
