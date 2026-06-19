# 移动端消息系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让老板在手机端收到 AI 员工/IM/审批的推送通知(含国内 JPush),和 AI 员工有持久化会话历史,离线再上线 AI 对话历史自动补拉,IM WebSocket 稳定(心跳+重连)。

**Architecture:** 不重构现有 IM 基础设施(已就绪),只补 5 个缺口:(1) ChatCacheEntity 加 session_id 实现按会话持久化 AI 历史;(2) ImWebSocketClient 加心跳 ping + 指数退避重连;(3) 新建 JPushReceiver 打通国内推送接收;(4) 后端 ConversationService.save_message 在 assistant 消息时触发 notify_user + sync/pull 加 ai_changes 字段;(5) Android MobileSyncRepository 处理 ai_changes 写入 Room。

**Tech Stack:** Kotlin + Jetpack Compose + Room + OkHttp WebSocket + JPush SDK 5.6.0 + FCM + Python FastAPI + SQLAlchemy + pytest

**Spec:** [2026-06-20-mobile-messaging-system-design.md](file:///Users/a4243342/Desktop/XCMAX/specs/2026-06-20-mobile-messaging-system-design.md)

---

## 文件结构

### Android 端 (修改/新建)

| 文件 | 职责 | 操作 |
|------|------|------|
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/db/XcagiDatabase.kt` | Room 数据库:ChatCacheEntity 加 session_id + Migration 3→4 + DAO 加 observeBySession | 修改 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImWebSocketClient.kt` | WS 客户端:加心跳 ping + 指数退避重连 | 修改 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoff.kt` | 纯函数:重连退避延迟计算(可单测) | 新建 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/PushMessageHandler.kt` | 公共推送消息处理:解析+写 Room+弹通知(供 FCM/JPush 复用) | 新建 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/XcagiMessagingService.kt` | FCM 推送:改用 PushMessageHandler | 修改 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/JPushReceiver.kt` | JPush 推送接收:改用 PushMessageHandler | 新建 |
| `FHD/mobile-android/app/src/main/AndroidManifest.xml` | 注册 JPushReceiver | 修改 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt` | streamChat/loadCachedChat 按 session_id 读写 | 修改 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt` | loadChatCache 按 session_id 加载 | 修改 |
| `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/sync/MobileSyncRepository.kt` | pullAndCache 处理 ai_changes | 修改 |
| `FHD/mobile-android/app/src/test/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoffTest.kt` | 重连退避单测 | 新建 |

### 后端 (修改/新建)

| 文件 | 职责 | 操作 |
|------|------|------|
| `FHD/app/services/conversation_service.py` | save_message 在 assistant 消息时触发 notify_user | 修改 |
| `FHD/app/services/mobile_push.py` | notify_user 确保 data 带 message_id | 修改 |
| `FHD/app/fastapi_routes/mobile_api_extensions.py` | mobile_sync_pull 加 ai_changes 字段 | 修改 |
| `FHD/tests/test_services/test_conversation_service_push.py` | ConversationService 推送测试 | 新建 |
| `FHD/tests/test_routes/test_mobile_sync_ai_changes.py` | sync/pull ai_changes 测试 | 新建 |

---

## Phase 1:AI 对话持久化改造

### Task 1.1: ChatCacheEntity 加 session_id + Migration 3→4

**Files:**
- Modify: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/db/XcagiDatabase.kt`

- [ ] **Step 1: 修改 ChatCacheEntity 加 session_id 字段**

在 `XcagiDatabase.kt` 中,将 ChatCacheEntity 改为:

```kotlin
@Entity(tableName = "chat_cache")
data class ChatCacheEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val session_id: String = "default",
    val role: String,
    val text: String,
    val ts: Long = System.currentTimeMillis(),
)
```

- [ ] **Step 2: ChatCacheDao 加 observeBySession 和 clearSession**

将 ChatCacheDao 改为:

```kotlin
@Dao
interface ChatCacheDao {
    @Query("SELECT * FROM chat_cache ORDER BY id ASC LIMIT 200")
    suspend fun all(): List<ChatCacheEntity>

    @Query("SELECT * FROM chat_cache WHERE session_id = :sessionId ORDER BY id ASC LIMIT 200")
    fun observeBySession(sessionId: String): Flow<List<ChatCacheEntity>>

    @Query("SELECT * FROM chat_cache WHERE session_id = :sessionId ORDER BY id ASC LIMIT 200")
    suspend fun getBySession(sessionId: String): List<ChatCacheEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(row: ChatCacheEntity)

    @Query("DELETE FROM chat_cache")
    suspend fun clear()

    @Query("DELETE FROM chat_cache WHERE session_id = :sessionId")
    suspend fun clearSession(sessionId: String)
}
```

- [ ] **Step 3: 数据库 version 3→4 + 加 Migration**

将 `@Database` 注解和类改为:

```kotlin
@Database(
    entities = [
        ChatCacheEntity::class,
        ApprovalCacheEntity::class,
        ShipmentCacheEntity::class,
        ImMessageCacheEntity::class,
        ImReadStateEntity::class,
    ],
    version = 4,
    exportSchema = false,
)
abstract class XcagiDatabase : RoomDatabase() {
    abstract fun chatDao(): ChatCacheDao
    abstract fun approvalDao(): ApprovalCacheDao
    abstract fun shipmentDao(): ShipmentCacheDao
    abstract fun imMessageDao(): ImMessageCacheDao
    abstract fun imReadStateDao(): ImReadStateDao

    companion object {
        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    "ALTER TABLE chat_cache ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'"
                )
            }
        }
    }
}
```

需要在文件头部加 import:

```kotlin
import androidx.room.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
```

- [ ] **Step 4: 找到 XcagiDatabase 的构建处,注册 Migration**

搜索 `Room.databaseBuilder` 找到数据库构建位置:

Run: `grep -rn "databaseBuilder" FHD/mobile-android/app/src/main/java/`

在找到的 builder 处加 `.addMigrations(XcagiDatabase.MIGRATION_3_4)`。例如:

```kotlin
Room.databaseBuilder(context, XcagiDatabase::class.java, "xcagi.db")
    .addMigrations(XcagiDatabase.MIGRATION_3_4)
    .fallbackToDestructiveMigration()
    .build()
```

- [ ] **Step 5: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 6: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/db/XcagiDatabase.kt
git commit -m "feat(mobile): ChatCacheEntity 加 session_id + Migration 3→4

- ChatCacheEntity 新增 session_id 字段(默认 'default' 向后兼容)
- ChatCacheDao 加 observeBySession/getBySession/clearSession
- 数据库 version 3→4 + Migration(ALTER TABLE ADD COLUMN)
- 为按会话持久化 AI 对话历史做准备"
```

---

### Task 1.2: XcagiRepository streamChat 写 session_id

**Files:**
- Modify: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt:956-1021`

- [ ] **Step 1: 修改 streamChat 方法签名加 sessionId 参数**

将 `streamChat` 方法改为接收 `sessionId: String = "default"`:

```kotlin
suspend fun streamChat(
    message: String,
    conversationId: String? = null,
    sessionId: String = "default",
    onToken: (String) -> Unit,
    onDone: (String) -> Unit,
    onError: (String) -> Unit,
) {
    syncRouterFromStore()
    db.chatDao().insert(ChatCacheEntity(session_id = sessionId, role = "user", text = message))
    val acc = StringBuilder()

    if (conversationId == PinnedIds.CODEX) {
        streamCodexSuperEmployeeChat(
            message = message,
            onToken = { t ->
                acc.append(t)
                onToken(t)
            },
            onDone = onDone,
            onError = onError,
        )
        val finalText = acc.toString()
        if (finalText.isNotBlank()) {
            db.chatDao().insert(ChatCacheEntity(session_id = sessionId, role = "assistant", text = finalText))
        }
        return
    }

    val useCloud = !isPcReachable()
    if (useCloud) {
        val relayId = sessionStore.relayDesktopId()
        if (relayId.isNotBlank()) {
            streamRelayCodexTask(
                relayId = relayId,
                message = message,
                onToken = { t ->
                    acc.append(t)
                    onToken(t)
                },
                onDone = onDone,
                onError = onError,
            )
            return
        }
        preferCloudIfLanUnreachable()
    }
    sseChat.streamChat(
        message,
        authHeader(),
        userId(),
        useCloud = useCloud,
        onToken = { t ->
            acc.append(t)
            onToken(t)
        },
        onDone = { full ->
            val text = full.ifBlank { acc.toString() }
            onDone(text)
        },
        onError = onError,
    )
    val finalText = acc.toString()
    if (finalText.isNotBlank()) {
        db.chatDao().insert(ChatCacheEntity(session_id = sessionId, role = "assistant", text = finalText))
    }
}
```

- [ ] **Step 2: 修改 streamChatCloud 同样传递 sessionId**

```kotlin
suspend fun streamChatCloud(
    message: String,
    conversationId: String? = null,
    sessionId: String = "default",
    onToken: (String) -> Unit,
    onDone: (String) -> Unit,
    onError: (String) -> Unit,
) {
    streamChat(message, conversationId, sessionId, onToken, onDone, onError)
}
```

- [ ] **Step 3: 修改 loadCachedChat 加 sessionId 参数**

```kotlin
suspend fun loadCachedChat(sessionId: String = "default"): List<Pair<String, String>> =
    db.chatDao().getBySession(sessionId).map { it.role to it.text }
```

- [ ] **Step 4: 新增 loadCachedChatFlow 返回 Flow 供观察**

在 `loadCachedChat` 下方加:

```kotlin
fun observeCachedChat(sessionId: String = "default"): Flow<List<Pair<String, String>>> =
    db.chatDao().observeBySession(sessionId).map { rows -> rows.map { it.role to it.text } }
```

需要在文件头部加 import:

```kotlin
import kotlinx.coroutines.flow.map
```

- [ ] **Step 5: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 6: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt
git commit -m "feat(mobile): streamChat/loadCachedChat 按 session_id 读写

- streamChat 加 sessionId 参数,写 Room 带 session_id
- loadCachedChat 加 sessionId 参数,按 session 加载
- 新增 observeCachedChat 返回 Flow 供 UI 观察"
```

---

### Task 1.3: AppViewModel sendChat/loadChatCache 传 session_id

**Files:**
- Modify: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt:1093-1199`

- [ ] **Step 1: 修改 loadChatCache 按 session_id 加载**

将 `loadChatCache` 方法改为:

```kotlin
fun loadChatCache(conversationId: String? = null) =
        viewModelScope.launch {
            if (conversationId == PinnedIds.CODEX) {
                repo.loadCodexSuperEmployeeMessages()
                        .onSuccess { _chatMessages.value = it }
                        .onFailure {
                            snack("超级员工-Codex 历史加载失败", true)
                            _chatMessages.value = emptyList()
                        }
                return@launch
            }
            val sessionId = conversationId ?: "default"
            _chatMessages.value = repo.loadCachedChat(sessionId)
        }
```

- [ ] **Step 2: 修改 sendChat 传 sessionId**

将 `sendChat` 方法签名和内部调用改为:

```kotlin
fun sendChat(text: String, conversationId: String? = null) {
    chatJob?.cancel()
    _chatAction.value = null
    _chatMessages.value = _chatMessages.value + ("user" to text) + ("assistant" to "")
    _streaming.value = true
    var acc = ""
    val sessionId = conversationId ?: "default"
    chatJob =
            viewModelScope.launch {
                    if (repo.hasNativeFhdAuth()) {
                        // 有本地 FHD 认证，走局域网
                        repo.streamChat(
                                text,
                                conversationId,
                                sessionId,
                                onToken = { t ->
                                    acc += t
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) + ("assistant" to acc)
                                },
                                onDone = { full ->
                                    _streaming.value = false
                                    val reply = full.ifBlank { acc }
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) + ("assistant" to reply)
                                    inferChatAction(text, reply)
                                },
                                onError = { e ->
                                    _streaming.value = false
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) +
                                                        ("assistant" to productErrorMessage(
                                                                e,
                                                                "对话暂不可用，请稍后重试",
                                                        ))
                                },
                        )
                    } else {
                        // 无本地认证，走云端 API
                        repo.streamChatCloud(
                                text,
                                conversationId,
                                sessionId,
                                onToken = { t ->
                                    acc += t
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) + ("assistant" to acc)
                                },
                                onDone = { full ->
                                    _streaming.value = false
                                    val reply = full.ifBlank { acc }
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) + ("assistant" to reply)
                                    inferChatAction(text, reply)
                                },
                                onError = { e ->
                                    _streaming.value = false
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) +
                                                    ("assistant" to productErrorMessage(
                                                                e,
                                                                "当前离线同步不可用，请连接电脑或稍后重试。",
                                                        ))
                                },
                        )
                    }
                }
}
```

- [ ] **Step 3: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt
git commit -m "feat(mobile): AppViewModel sendChat/loadChatCache 传 session_id

- loadChatCache 按 conversationId 推导 sessionId 加载历史
- sendChat 传 sessionId 给 repo.streamChat
- 不同会话的 AI 对话历史互不干扰"
```

---

## Phase 2:ImWebSocketClient 心跳 + 重连

### Task 2.1: 新建 ReconnectBackoff 纯函数 + 单测

**Files:**
- Create: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoff.kt`
- Test: `FHD/mobile-android/app/src/test/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoffTest.kt`

- [ ] **Step 1: 写失败的单测**

创建 `FHD/mobile-android/app/src/test/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoffTest.kt`:

```kotlin
package com.xiuci.xcagi.mobile.core.im

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReconnectBackoffTest {
    @Test
    fun firstAttemptReturnsBaseDelay() {
        assertEquals(5000L, ReconnectBackoff.delayForAttempt(0))
    }

    @Test
    fun secondAttemptDoublesDelay() {
        assertEquals(10_000L, ReconnectBackoff.delayForAttempt(1))
    }

    @Test
    fun thirdAttemptQuadruplesDelay() {
        assertEquals(20_000L, ReconnectBackoff.delayForAttempt(2))
    }

    @Test
    fun delayCappedAtFiveMinutes() {
        assertEquals(300_000L, ReconnectBackoff.delayForAttempt(10))
        assertEquals(300_000L, ReconnectBackoff.delayForAttempt(100))
    }

    @Test
    fun allDelaysArePositive() {
        for (i in 0..20) {
            assertTrue("attempt $i", ReconnectBackoff.delayForAttempt(i) > 0)
        }
    }
}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD/mobile-android && ./gradlew test --tests "com.xiuci.xcagi.mobile.core.im.ReconnectBackoffTest" 2>&1 | tail -20`
Expected: FAIL with "Unresolved reference: ReconnectBackoff"

- [ ] **Step 3: 实现 ReconnectBackoff**

创建 `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoff.kt`:

```kotlin
package com.xiuci.xcagi.mobile.core.im

import kotlin.math.min

/**
 * WebSocket 重连指数退避延迟计算。
 *
 * 基础延迟 5s，每次翻倍，上限 5 分钟。
 * - attempt 0 → 5s
 * - attempt 1 → 10s
 * - attempt 2 → 20s
 * - attempt 6+ → 300s (5min cap)
 */
object ReconnectBackoff {
    private const val BASE_DELAY_MS = 5_000L
    private const val MAX_DELAY_MS = 300_000L

    fun delayForAttempt(attempt: Int): Long {
        val safeAttempt = attempt.coerceAtLeast(0).coerceAtMost(6)
        val delay = BASE_DELAY_MS * (1L shl safeAttempt)
        return min(delay, MAX_DELAY_MS)
    }
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD/mobile-android && ./gradlew test --tests "com.xiuci.xcagi.mobile.core.im.ReconnectBackoffTest" 2>&1 | tail -20`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoff.kt
git add app/src/test/java/com/xiuci/xcagi/mobile/core/im/ReconnectBackoffTest.kt
git commit -m "feat(mobile): ReconnectBackoff 指数退避计算 + 单测

- 基础延迟 5s，每次翻倍，上限 5min
- 纯函数可单测，5 个测试全通过
- 供 ImWebSocketClient 重连使用"
```

---

### Task 2.2: ImWebSocketClient 加心跳 + 重连

**Files:**
- Modify: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImWebSocketClient.kt`

- [ ] **Step 1: 加心跳 + 重连逻辑**

将整个 `ImWebSocketClient.kt` 替换为:

```kotlin
package com.xiuci.xcagi.mobile.core.im

import com.xiuci.xcagi.mobile.core.network.ServerRouter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton

/**
 * IM V0 WebSocket（/ws/im?session_id=）— 以会话 ID 鉴权，避免客户端自报 user_id 带来的安全风险。
 *
 * 含心跳 ping（30s）+ 断线指数退避重连（5s→10s→...→5min cap）。
 */
@Singleton
class ImWebSocketClient @Inject constructor(
    private val okHttp: OkHttpClient,
    private val serverRouter: ServerRouter,
) {
    private var socket: WebSocket? = null
    private val _events = MutableSharedFlow<JSONObject>(extraBufferCapacity = 32)
    val events: SharedFlow<JSONObject> = _events.asSharedFlow()

    @Volatile
    var connected: Boolean = false
        private set

    private var currentSessionId: String = ""
    private var reconnectAttempts: Int = 0
    private var heartbeatJob: Job? = null
    private var reconnectJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    @Synchronized
    fun connect(sessionId: String) {
        if (sessionId.isBlank()) return
        currentSessionId = sessionId
        disconnectSocket()
        cancelReconnect()
        doConnect(sessionId)
    }

    private fun doConnect(sessionId: String) {
        val url = serverRouter.fhdImWebSocketUrl(sessionId)
        val request = Request.Builder().url(url).build()
        socket = okHttp.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
                    reconnectAttempts = 0
                    startHeartbeat()
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { JSONObject(text) }.onSuccess { _events.tryEmit(it) }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    connected = false
                    stopHeartbeat()
                    scheduleReconnect()
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    connected = false
                    stopHeartbeat()
                    scheduleReconnect()
                }
            },
        )
    }

    private fun startHeartbeat() {
        stopHeartbeat()
        heartbeatJob = scope.launch {
            while (connected) {
                delay(30_000)
                if (connected) {
                    socket?.send("""{"type":"ping"}""")
                }
            }
        }
    }

    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
    }

    private fun scheduleReconnect() {
        if (currentSessionId.isBlank()) return
        cancelReconnect()
        val delayMs = ReconnectBackoff.delayForAttempt(reconnectAttempts)
        reconnectAttempts++
        reconnectJob = scope.launch {
            delay(delayMs)
            if (currentSessionId.isNotBlank()) {
                doConnect(currentSessionId)
            }
        }
    }

    private fun cancelReconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
    }

    private fun disconnectSocket() {
        stopHeartbeat()
        socket?.close(1000, "client_close")
        socket = null
        connected = false
    }

    @Synchronized
    fun disconnect() {
        currentSessionId = ""
        cancelReconnect()
        disconnectSocket()
    }

    companion object {
        fun parseEvent(json: JSONObject): ImWsEvent? = when (json.optString("type")) {
            "im.message", "message" -> parseMessage(json)
            "im.read", "read" -> parseRead(json)
            else -> null
        }

        private fun parseMessage(json: JSONObject): ImWsEvent.Message? {
            val conversationId = json.optInt("conversation_id", 0)
            val msg = json.optJSONObject("message")
            val messageId = when {
                msg != null -> msg.optLong("id", 0L)
                else -> json.optLong("message_id", 0L)
            }
            if (conversationId <= 0 || messageId <= 0L) return null
            val senderUserId = when {
                msg != null -> msg.optInt("sender_user_id", 0)
                else -> json.optInt("sender_user_id", 0)
            }
            val body = when {
                msg != null -> msg.optString("body", "")
                else -> json.optString("body", "")
            }
            val createdAtMs = when {
                msg != null -> ImRepository.parseTimestampMs(msg.opt("created_at"))
                else -> ImRepository.parseTimestampMs(json.opt("created_at"))
            } ?: System.currentTimeMillis()
            return ImWsEvent.Message(
                conversationId = conversationId,
                messageId = messageId,
                senderUserId = senderUserId,
                body = body,
                createdAtMs = createdAtMs,
                updatedAtMs = System.currentTimeMillis(),
            )
        }

        private fun parseRead(json: JSONObject): ImWsEvent.Read? {
            val conversationId = json.optInt("conversation_id", 0)
            val lastRead = json.optLong("last_read_message_id", 0L)
                .takeIf { it > 0L }
                ?: json.optLong("last_message_id", 0L)
            if (conversationId <= 0 || lastRead <= 0L) return null
            return ImWsEvent.Read(
                conversationId = conversationId,
                lastReadMessageId = lastRead,
                updatedAtMs = System.currentTimeMillis(),
            )
        }
    }
}
```

- [ ] **Step 2: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: 运行已有测试确保无回归**

Run: `cd FHD/mobile-android && ./gradlew test 2>&1 | tail -20`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImWebSocketClient.kt
git commit -m "feat(mobile): ImWebSocketClient 加心跳 ping + 指数退避重连

- 心跳:每 30s 发 {\"type\":\"ping\"}，onOpen 时启动，onClose/onFailure 时停止
- 重连:onFailure/onClosed 触发 scheduleReconnect，指数退避 5s→10s→...→5min
- onOpen 时重置 reconnectAttempts = 0
- disconnect() 清除 currentSessionId 防止重连
- 使用 @Synchronized 保护 connect/disconnect 线程安全"
```

---

## Phase 3:打通 JPush 接收

### Task 3.1: 新建 PushMessageHandler 公共处理方法

**Files:**
- Create: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/PushMessageHandler.kt`

- [ ] **Step 1: 创建 PushMessageHandler**

创建 `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/PushMessageHandler.kt`:

```kotlin
package com.xiuci.xcagi.mobile.core.push

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.xiuci.xcagi.mobile.MainActivity
import com.xiuci.xcagi.mobile.R
import org.json.JSONObject

/**
 * 推送消息公共处理器：FCM 和 JPush 共用。
 *
 * 职责：
 * - 解析推送 data（title/body/route/channel/message_id/session_id/source）
 * - 弹通知（点击 deep link 跳转）
 *
 * 注意：写 Room 预览由 MobileSyncWorker 在收到推送后触发 sync/pull 完成，
 * 这里只负责弹通知，不直接写 Room（避免在推送接收线程做 DB IO）。
 */
object PushMessageHandler {

    data class PushPayload(
        val title: String,
        val body: String,
        val route: String,
        val channel: String,
        val messageId: String?,
        val sessionId: String?,
        val source: String?,
    )

    fun parse(
        title: String?,
        body: String?,
        route: String?,
        channel: String?,
        messageId: String?,
        sessionId: String?,
        source: String?,
    ): PushPayload {
        return PushPayload(
            title = title?.takeIf { it.isNotBlank() } ?: "XCAGI",
            body = body ?: "",
            route = route?.takeIf { it.isNotBlank() } ?: "xcagi://chat",
            channel = channel?.takeIf { it.isNotBlank() } ?: NotificationChannels.CHAT,
            messageId = messageId,
            sessionId = sessionId,
            source = source,
        )
    }

    fun showNotification(context: Context, payload: PushPayload) {
        NotificationChannels.ensure(context)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, android.Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("deep_link_route", payload.route)
        }
        val pending = PendingIntent.getActivity(
            context,
            payload.route.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, payload.channel)
            .setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle(payload.title)
            .setContentText(payload.body)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(payload.route.hashCode(), notification)
        } catch (_: SecurityException) {
            /* 用户拒绝通知权限时不拖垮推送回调 */
        }
    }
}
```

- [ ] **Step 2: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/push/PushMessageHandler.kt
git commit -m "feat(mobile): PushMessageHandler 公共推送处理方法

- 解析 title/body/route/channel/message_id/session_id/source
- 弹通知（点击 deep link 跳转 MainActivity）
- 供 FCM XcagiMessagingService 和 JPush JPushReceiver 复用
- 不直接写 Room，由 MobileSyncWorker sync/pull 补数据"
```

---

### Task 3.2: XcagiMessagingService 改用 PushMessageHandler

**Files:**
- Modify: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/XcagiMessagingService.kt`

- [ ] **Step 1: 简化 onMessageReceived 改用 PushMessageHandler**

将 `XcagiMessagingService.kt` 替换为:

```kotlin
package com.xiuci.xcagi.mobile.core.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class XcagiMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        PushTokenHolder.fcmToken = token
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val payload = PushMessageHandler.parse(
            title = message.notification?.title ?: message.data["title"],
            body = message.notification?.body ?: message.data["body"],
            route = message.data["route"],
            channel = message.data["channel"],
            messageId = message.data["message_id"],
            sessionId = message.data["session_id"],
            source = message.data["source"],
        )
        PushMessageHandler.showNotification(this, payload)
    }
}

object PushTokenHolder {
    @Volatile var fcmToken: String = ""
    @Volatile var jpushRegistrationId: String = ""
}
```

- [ ] **Step 2: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/push/XcagiMessagingService.kt
git commit -m "refactor(mobile): XcagiMessagingService 改用 PushMessageHandler

- 移除内联通知构建逻辑，改用 PushMessageHandler.parse + showNotification
- 提取 message_id/session_id/source 供后续去重和路由使用"
```

---

### Task 3.3: 新建 JPushReceiver + Manifest 注册

**Files:**
- Create: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/JPushReceiver.kt`
- Modify: `FHD/mobile-android/app/src/main/AndroidManifest.xml`

- [ ] **Step 1: 创建 JPushReceiver**

创建 `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/push/JPushReceiver.kt`:

```kotlin
package com.xiuci.xcagi.mobile.core.push

import android.content.Context
import cn.jpush.android.api.CmdMessage
import cn.jpush.android.api.CustomMessage
import cn.jpush.android.api.JPushMessageService
import cn.jpush.android.api.NotificationMessage
import org.json.JSONObject

/**
 * JPush 消息接收服务（国内推送通道）。
 *
 * JPush SDK 5.x 使用 JPushMessageService 而非 BroadcastReceiver。
 * onMessage 处理自定义消息（不显示在通知栏，需自行弹通知）。
 * onNotifyMessageOpened 处理通知点击。
 *
 * 注册在 AndroidManifest.xml 中，intent-filter 为 cn.jpush.android.intent.RECEIVE_MESSAGE。
 */
class JPushReceiver : JPushMessageService() {

    override fun onMessage(context: Context, customMessage: CustomMessage) {
        // customMessage.content 是后端 send_jpush 中 message.msg_content
        // customMessage.extra 是后端 send_jpush 中 message.extras
        val extras = customMessage.extra
        val payload = if (extras != null) {
            runCatching { JSONObject(extras) }.getOrElse { JSONObject() }
        } else {
            JSONObject()
        }
        val parsed = PushMessageHandler.parse(
            title = payload.optString("title").ifBlank { customMessage.title },
            body = payload.optString("body").ifBlank { customMessage.content },
            route = payload.optString("route", "xcagi://chat"),
            channel = payload.optString("channel", NotificationChannels.CHAT),
            messageId = payload.optString("message_id").ifBlank { null },
            sessionId = payload.optString("session_id").ifBlank { null },
            source = payload.optString("source").ifBlank { null },
        )
        PushMessageHandler.showNotification(context, parsed)
    }

    override fun onNotifyMessageOpened(context: Context, message: NotificationMessage) {
        // JPush 通知点击：交给 MainActivity 的 intent-filter 处理 deep link
        // 这里不做额外处理，JPush SDK 会自动打开应用
    }

    override fun onCommandResult(context: Context, cmdMessage: CmdMessage) {
        // JPush 注册成功后 PushRegistrar 会拿到 registrationId
        // 这里不需要额外处理
    }
}
```

- [ ] **Step 2: AndroidManifest.xml 注册 JPushReceiver**

在 `AndroidManifest.xml` 的 `<application>` 标签内,在 `XcagiMessagingService` 的 `<service>` 之后加:

```xml
        <service
            android:name=".core.push.JPushReceiver"
            android:enabled="true"
            android:exported="false">
            <intent-filter>
                <action android:name="cn.jpush.android.intent.RECEIVE_MESSAGE" />
                <category android:name="${applicationId}" />
            </intent-filter>
        </service>
```

- [ ] **Step 3: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/push/JPushReceiver.kt
git add app/src/main/AndroidManifest.xml
git commit -m "feat(mobile): 新建 JPushReceiver 打通国内推送接收

- JPushReceiver 继承 JPushMessageService（SDK 5.x 方式）
- onMessage 解析 customMessage.extra JSON，复用 PushMessageHandler
- AndroidManifest 注册 RECEIVE_MESSAGE intent-filter
- 至此 FCM(海外) + JPush(国内) 双通道推送接收打通"
```

---

## Phase 4:后端 AI 推送 + sync ai_changes

### Task 4.1: ConversationService.save_message 在 assistant 消息时触发推送

**Files:**
- Modify: `FHD/app/services/conversation_service.py:40-110`
- Test: `FHD/tests/test_services/test_conversation_service_push.py`

- [ ] **Step 1: 写失败的单测**

创建 `FHD/tests/test_services/test_conversation_service_push.py`:

```python
"""测试 ConversationService.save_message 在 assistant 消息时触发推送。"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def svc():
    from app.services.conversation_service import ConversationService
    return ConversationService()


def _mock_db_with_session(user_id=42, conversation_id=99):
    """构造 mock db，db.refresh 会把 id 写入传入的 conversation 对象。"""
    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_session.user_id = user_id
    mock_db.query.return_value.filter.return_value.first.return_value = mock_session
    mock_db.flush.return_value = None
    mock_db.commit.return_value = None

    def _refresh(obj):
        obj.id = conversation_id
    mock_db.refresh.side_effect = _refresh
    return mock_db


class TestSaveMessagePush:
    def test_assistant_message_triggers_notify_user(self, svc):
        """assistant 消息保存后应触发 notify_user 推送。"""
        mock_db = _mock_db_with_session(user_id=42, conversation_id=99)
        with patch("app.services.conversation_service.get_db") as mock_get_db, \
             patch("app.services.conversation_service.notify_user") as mock_notify:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            svc.save_message(
                session_id="sess-123",
                user_id="42",
                role="assistant",
                content="您好，订单已处理",
            )

        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs.kwargs["user_id"] == 42
        assert "订单已处理" in call_kwargs.kwargs["body"]
        assert call_kwargs.kwargs["data"]["source"] == "ai"
        assert call_kwargs.kwargs["data"]["session_id"] == "sess-123"
        assert call_kwargs.kwargs["data"]["message_id"] == "99"

    def test_user_message_does_not_trigger_notify_user(self, svc):
        """user 消息保存后不应触发推送。"""
        mock_db = _mock_db_with_session(user_id=42, conversation_id=100)
        with patch("app.services.conversation_service.get_db") as mock_get_db, \
             patch("app.services.conversation_service.notify_user") as mock_notify:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            svc.save_message(
                session_id="sess-123",
                user_id="42",
                role="user",
                content="帮我查订单",
            )

        mock_notify.assert_not_called()

    def test_notify_user_failure_does_not_break_save(self, svc):
        """notify_user 失败不应中断消息保存。"""
        mock_db = _mock_db_with_session(user_id=42, conversation_id=101)
        with patch("app.services.conversation_service.get_db") as mock_get_db, \
             patch("app.services.conversation_service.notify_user", side_effect=Exception("push fail")):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            # 不应抛异常
            result = svc.save_message(
                session_id="sess-123",
                user_id="42",
                role="assistant",
                content="测试推送失败不影响保存",
            )
            assert result == 101
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_services/test_conversation_service_push.py -v 2>&1 | tail -30`
Expected: FAIL with "Cannot import notify_user" or "AttributeError"

- [ ] **Step 3: 修改 ConversationService.save_message 加推送**

在 `FHD/app/services/conversation_service.py` 文件头部 import 区加(在 `from app.utils.operational_errors import RECOVERABLE_ERRORS` 之后):

```python
from app.services.mobile_push import notify_user
```

注意:`logging` 和 `logger` 已在文件中存在(第 7 行 `import logging`、第 17 行 `logger = logging.getLogger(__name__)`),无需重复添加。

将 `save_message` 方法改为(在 `db.commit()` 之后、`return conversation.id` 之前加推送逻辑):

```python
    def save_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        intent: str = "",
        metadata: str = "",
    ) -> int:
        """
        保存对话消息

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            role: 角色（user/assistant）
            content: 消息内容
            intent: 意图
            metadata: 元数据

        Returns:
            消息 ID
        """
        with get_db() as db:
            try:
                # 更新或创建会话（必须先创建会话，因为消息有外键依赖）
                session = (
                    db.query(AIConversationSession)
                    .filter(AIConversationSession.session_id == session_id)
                    .first()
                )

                normalized_user_id = self._normalize_user_id(user_id)

                if session:
                    session.message_count += 1
                    session.last_message_at = datetime.now()
                else:
                    session = AIConversationSession(
                        session_id=session_id,
                        user_id=normalized_user_id,
                        message_count=1,
                        last_message_at=datetime.now(),
                        created_at=datetime.now(),
                    )
                    db.add(session)
                db.flush()

                # 保存消息
                conversation = AIConversation(
                    session_id=session_id,
                    user_id=str(user_id) if user_id is not None else None,
                    role=role,
                    content=content,
                    intent=intent,
                    conversation_metadata=metadata,
                    created_at=datetime.now(),
                )
                db.add(conversation)

                db.commit()
                db.refresh(conversation)
                message_id = conversation.id
                target_user_id = normalized_user_id or session.user_id
            except Exception:
                db.rollback()
                raise

        # assistant 消息推送给用户（AI 员工回复 / 主动消息）
        if role == "assistant" and target_user_id:
            try:
                notify_user(
                    user_id=int(target_user_id),
                    title="AI 助手",
                    body=content[:120],
                    data={
                        "message_id": str(message_id),
                        "session_id": session_id,
                        "source": "ai",
                        "route": f"xcagi://chat?session={session_id}",
                        "channel": "xcagi_chat",
                    },
                )
            except Exception as exc:
                logger.warning("conversation push notify failed: %s", exc)

        return message_id
```

注意:需要确认 `save_message` 原方法末尾的 `return` 语句。原方法在 commit 后有 `db.refresh(conversation)` 和 `return conversation.id`。上面的代码已包含。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_services/test_conversation_service_push.py -v 2>&1 | tail -30`
Expected: PASS (3 tests)

- [ ] **Step 5: 运行已有 conversation 测试确保无回归**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/ -k "conversation" -v 2>&1 | tail -30`
Expected: All conversation tests PASS

- [ ] **Step 6: Commit**

```bash
cd FHD
git add app/services/conversation_service.py tests/test_services/test_conversation_service_push.py
git commit -m "feat(backend): ConversationService assistant 消息触发 notify_user 推送

- save_message 在 role=assistant 时调用 notify_user
- 推送 data 含 message_id/session_id/source/route/channel
- notify_user 失败不影响消息保存（catch + warning）
- 3 个单测：assistant 触发推送、user 不触发、推送失败不中断保存"
```

---

### Task 4.2: mobile_sync_pull 加 ai_changes 字段

**Files:**
- Modify: `FHD/app/fastapi_routes/mobile_api_extensions.py:1816-1847`
- Test: `FHD/tests/test_routes/test_mobile_sync_ai_changes.py`

- [ ] **Step 1: 写失败的单测**

创建 `FHD/tests/test_routes/test_mobile_sync_ai_changes.py`:

```python
"""测试 mobile_sync_pull 返回 ai_changes 字段。"""
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace


@pytest.fixture
def ext_mod():
    from app.fastapi_routes import mobile_api_extensions
    return mobile_api_extensions


class TestSyncPullAiChanges:
    @pytest.mark.asyncio
    async def test_sync_pull_returns_ai_changes_field(self, ext_mod):
        """sync/pull 返回体应包含 ai_changes 字段。"""
        user = SimpleNamespace(id=1, username="admin", role="admin")
        body = ext_mod.SyncPullBody(since_cursor=0)

        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": 100}

        mock_ai_rows = [
            SimpleNamespace(
                id=1,
                session_id="sess-1",
                user_id="1",
                role="assistant",
                content="您好",
                intent="",
                conversation_metadata=None,
                created_at=None,
            ),
        ]

        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db), \
             patch("app.db.session.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_filter = MagicMock()
            mock_order = MagicMock()
            mock_limit = MagicMock()
            mock_limit.all.return_value = mock_ai_rows
            mock_order.limit.return_value = mock_limit
            mock_filter.order_by.return_value = mock_order
            mock_query.filter.return_value = mock_filter
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            result = await ext_mod.mobile_sync_pull(body=body, user=user)

        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert "ai_changes" in payload["data"]
        assert len(payload["data"]["ai_changes"]) == 1
        assert payload["data"]["ai_changes"][0]["session_id"] == "sess-1"
        assert payload["data"]["ai_changes"][0]["role"] == "assistant"
        assert payload["data"]["ai_changes"][0]["content"] == "您好"

    @pytest.mark.asyncio
    async def test_sync_pull_ai_changes_empty_when_no_messages(self, ext_mod):
        """无 AI 消息时 ai_changes 为空列表。"""
        user = SimpleNamespace(id=1, username="admin", role="admin")
        body = ext_mod.SyncPullBody(since_cursor=0)

        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": 100}

        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db), \
             patch("app.db.session.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_filter = MagicMock()
            mock_order = MagicMock()
            mock_limit = MagicMock()
            mock_limit.all.return_value = []
            mock_order.limit.return_value = mock_limit
            mock_filter.order_by.return_value = mock_order
            mock_query.filter.return_value = mock_filter
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            result = await ext_mod.mobile_sync_pull(body=body, user=user)

        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert payload["data"]["ai_changes"] == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_routes/test_mobile_sync_ai_changes.py -v 2>&1 | tail -30`
Expected: FAIL with "KeyError: 'ai_changes'" or similar

- [ ] **Step 3: 修改 mobile_sync_pull 加 ai_changes**

在 `FHD/app/fastapi_routes/mobile_api_extensions.py` 中,找到 `mobile_sync_pull` 函数(约 1816 行),在 `return format_mobile_response(...)` 之前加 ai_changes 查询。

将 `mobile_sync_pull` 函数改为:

```python
@extension_router.post("/sync/pull")
async def mobile_sync_pull(body: SyncPullBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        changes = sync_db.get_changes(since_cursor=body.since_cursor, limit=200)
        cursor = sync_db.get_status().get("local_cursor") or body.since_cursor
        if cursor:
            sync_db.update_remote_cursor(int(cursor))
        im_entity_types = {"im_message", "im_read_state"}
        im_changes = [c for c in changes if str(c.get("entity_type") or "") in im_entity_types]

        # AI 对话历史增量同步
        ai_changes = _ai_conversation_changes(user, limit=100)

        return format_mobile_response(
            data={
                "cursor": cursor,
                "changes": changes,
                "im_changes": im_changes,
                "im_change_count": len(im_changes),
                "ai_changes": ai_changes,
                "ai_change_count": len(ai_changes),
                "approvals": _approval_items(),
                "shipments": _shipment_items(),
            },
        )
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_pull: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )
```

在 `_shipment_items` 函数之后(约 1793 行后)加辅助函数:

```python
def _ai_conversation_changes(user: Any, limit: int = 100) -> list[dict[str, Any]]:
    """查询当前用户最近的 AI 对话消息，供移动端增量同步。"""
    uid = int(getattr(user, "id", 0) or 0)
    if uid <= 0:
        return []
    try:
        from app.db.models.ai import AIConversation, AIConversationSession
        from app.db.session import get_db

        with get_db() as db:
            rows = (
                db.query(AIConversation)
                .join(AIConversationSession, AIConversation.session_id == AIConversationSession.session_id)
                .filter(AIConversationSession.user_id == uid)
                .order_by(AIConversation.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "role": r.role,
                    "content": r.content,
                    "intent": r.intent or "",
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in reversed(rows)
            ]
    except OPERATIONAL_ERRORS as exc:
        logger.warning("ai_conversation_changes: %s", exc)
        return []
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_routes/test_mobile_sync_ai_changes.py -v 2>&1 | tail -30`
Expected: PASS (2 tests)

- [ ] **Step 5: 运行已有 sync 测试确保无回归**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_routes/test_mobile_api_extensions.py -v -k "sync" 2>&1 | tail -30`
Expected: All sync tests PASS

- [ ] **Step 6: Commit**

```bash
cd FHD
git add app/fastapi_routes/mobile_api_extensions.py tests/test_routes/test_mobile_sync_ai_changes.py
git commit -m "feat(backend): mobile_sync_pull 加 ai_changes 字段

- 新增 _ai_conversation_changes 查询用户 AI 对话消息
- sync/pull 返回体加 ai_changes + ai_change_count
- 按 user_id 过滤，按 id 倒序取最近 100 条
- 2 个单测：返回 ai_changes、空列表场景"
```

---

## Phase 5:Android sync 处理 ai_changes

### Task 5.1: MobileSyncRepository 处理 ai_changes 写入 Room

**Files:**
- Modify: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/sync/MobileSyncRepository.kt:63-133`

- [ ] **Step 1: 在 pullAndCache 中加 ai_changes 处理**

在 `MobileSyncRepository.kt` 的 `pullAndCache` 方法中,在 `changes.forEach { ... }` 之后、`Result.success(...)` 之前加 ai_changes 处理。

将 `pullAndCache` 方法中的 changes 处理块之后加:

```kotlin
            @Suppress("UNCHECKED_CAST")
            val aiChanges = (data["ai_changes"] as? List<Map<String, Any?>>) ?: emptyList()
            aiChanges.forEach { row ->
                val sessionId = row["session_id"]?.toString() ?: return@forEach
                val role = row["role"]?.toString() ?: return@forEach
                val content = row["content"]?.toString() ?: return@forEach
                db.chatDao().insert(
                    ChatCacheEntity(
                        session_id = sessionId,
                        role = role,
                        text = content,
                    ),
                )
            }
```

需要在文件头部加 import(如果还没有):

```kotlin
import com.xiuci.xcagi.mobile.core.db.ChatCacheEntity
```

- [ ] **Step 2: 编译验证**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
cd FHD/mobile-android
git add app/src/main/java/com/xiuci/xcagi/mobile/core/sync/MobileSyncRepository.kt
git commit -m "feat(mobile): MobileSyncRepository 处理 ai_changes 写入 Room

- pullAndCache 解析 ai_changes 列表
- 每条 ai_change 写入 chat_cache（session_id + role + content）
- 离线再上线后 AI 对话历史自动补拉到本地"
```

---

## Phase 6:集成验证

### Task 6.1: 后端全量测试无回归

**Files:**
- 无新文件,运行已有测试

- [ ] **Step 1: 运行后端全量测试**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/ -x -q 2>&1 | tail -30`
Expected: All tests PASS (无回归)

- [ ] **Step 2: 如有失败,修复后重新运行**

如果有测试失败,分析原因:
- 如果是 mock 未更新(新加了 notify_user 调用),更新对应测试的 mock
- 如果是 import 错误,检查循环依赖

- [ ] **Step 3: 运行 ruff lint + format check**

Run: `cd FHD && ruff check app/services/conversation_service.py app/fastapi_routes/mobile_api_extensions.py tests/test_services/test_conversation_service_push.py tests/test_routes/test_mobile_sync_ai_changes.py 2>&1`
Expected: All files pass

Run: `cd FHD && ruff format --check app/services/conversation_service.py app/fastapi_routes/mobile_api_extensions.py 2>&1`
Expected: All files already formatted

- [ ] **Step 4: Commit(如有修复)**

```bash
cd FHD
git add -A
git commit -m "test(backend): 修复推送改动引起的测试回归"
```

(如果无回归则跳过此步)

---

### Task 6.2: Android 全量编译 + 测试无回归

**Files:**
- 无新文件,运行已有测试

- [ ] **Step 1: 运行 Android 全量编译**

Run: `cd FHD/mobile-android && ./gradlew assembleDebug 2>&1 | tail -20`
Expected: BUILD SUCCESSFUL

- [ ] **Step 2: 运行 Android 单元测试**

Run: `cd FHD/mobile-android && ./gradlew test 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 3: 如有失败,修复后重新运行**

- [ ] **Step 4: Commit(如有修复)**

```bash
cd FHD/mobile-android
git add -A
git commit -m "test(mobile): 修复消息系统改动引起的测试回归"
```

(如果无回归则跳过此步)

---

### Task 6.3: 真机联调验证清单

**Files:**
- 无代码改动,手动验证

- [ ] **Step 1: AI 对话历史持久化验证**

1. 打开 App → AI 对话页 → 发送消息 → 收到回复
2. 退出 App → 重新打开 → 进入同一会话 → 历史消息仍在
3. 切换到另一个会话 → 历史不串

- [ ] **Step 2: WebSocket 心跳 + 重连验证**

1. 打开 App → 进入会话列表(WS 连接)
2. 等待 30s+ → 观察日志确认心跳 ping 发送
3. 关闭 WiFi → 等待 10s → 重新打开 WiFi → 观察 WS 自动重连
4. 在另一端发消息 → 手机端收到

- [ ] **Step 3: JPush 推送验证(需配置 JPUSH_APPKEY)**

1. 确认 `local.properties` 中有 `JPUSH_APPKEY`
2. 打开 App → 登录 → 确认 JPush 注册成功(看日志)
3. 后端触发 AI 员工发消息 → 手机收到推送通知
4. 点击通知 → 跳转到对应会话

- [ ] **Step 4: 离线补拉验证**

1. App 在线 → 记录当前 AI 对话
2. 杀掉 App → 后端继续产生 AI 消息(另一端触发)
3. 重新打开 App → 触发 sync/pull → AI 对话历史补全

- [ ] **Step 5: 记录验证结果**

在 commit message 或 PR 描述中记录验证结果。

---

## 完成标准

- [ ] Phase 1:ChatCacheEntity 有 session_id,不同会话历史隔离,Migration 3→4 无数据丢失
- [ ] Phase 2:WS 心跳 30s 发送,断线后指数退避重连(5s→10s→...→5min)
- [ ] Phase 3:JPushReceiver 注册成功,后端发 JPush → 手机收到通知
- [ ] Phase 4:后端 assistant 消息触发 notify_user,sync/pull 返回 ai_changes
- [ ] Phase 5:Android sync/pull 处理 ai_changes 写入 Room
- [ ] Phase 6:后端全量测试通过,Android 编译+单测通过,真机联调 4 项验证通过
