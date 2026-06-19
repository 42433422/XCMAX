# 移动端消息系统实现设计(修订版)

> **日期**:2026-06-20
> **状态**:待批准
> **范围**:FHD/mobile-android 消息推送系统真实实现(功能层,非 UI 改造)
> **前提**:前端入口和样式保留,重点是功能实际实现和完善
> **修订说明**:初版高估了工程量,实际调研发现 IM 基础设施已基本就绪,本版反映真实现状

---

## 1. 现状重新评估(关键发现)

### 1.1 Android 端已实现(比预想的好太多)

| 能力 | 状态 | 文件 |
|------|------|------|
| IM WebSocket 客户端 | ✅ 已实现 | [ImWebSocketClient.kt](file:///Users/a4243342/Desktop/XCMAX/FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImWebSocketClient.kt) 连 /ws/im,解析 im.message/im.read |
| IM 消息持久化 | ✅ 已实现 | [XcagiDatabase.kt](file:///Users/a4243342/Desktop/XCMAX/FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/db/XcagiDatabase.kt) im_message_cache + im_read_state 表 |
| IM 仓库 | ✅ 已实现 | [ImRepository.kt](file:///Users/a4243342/Desktop/XCMAX/FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImRepository.kt) observeMessages/attachWebSocketListener/applySyncMessage |
| sync/pull 增量拉取 | ✅ 已实现 | [MobileSyncRepository.kt](file:///Users/a4243342/Desktop/XCMAX/FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/sync/MobileSyncRepository.kt) 处理 im_message/im_read_state 变更 |
| WorkManager 定时同步 | ✅ 已实现 | MobileSyncWorker |
| 会话列表 UI | ✅ 已实现 | [ConversationListScreen.kt](file:///Users/a4243342/Desktop/XCMAX/FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ConversationListScreen.kt) 接入 vm.conversations,有未读计数/筛选/搜索 |
| 聊天页 UI | ✅ 已实现 | [ChatScreen.kt](file:///Users/a4243342/Desktop/XCMAX/FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt) 接入 vm.chatMessages + vm.streaming(SSE) |
| WS 收消息自动触发 sync | ✅ 已实现 | ImRepository.requestPullHint() |
| FCM 推送接收 | ✅ 已实现 | XcagiMessagingService |

### 1.2 真正的缺口(大幅缩小)

| 缺口 | 严重度 | 说明 |
|------|--------|------|
| **AI 对话持久化简陋** | 高 | ChatCacheEntity 只有 role/text/ts,没有 session_id,不能按会话存历史。vm.loadChatCache() 加载的是简陋缓存 |
| **JPush 消息接收没接** | 高 | 只有 FCM onMessageReceived,没有 JPushMessageService,国内推送收不到 |
| **ImWebSocketClient 缺心跳/重连** | 中 | onFailure 只设 connected=false,不重连;没有心跳 ping,长连接会断 |
| **后端 AI 推送缺失** | 中 | AI 员工主动发消息时不推送(只有 IM send_message 时推) |
| **后端 sync/pull 无 ai_changes** | 中 | 返回 im_changes,但没有 ai_changes,AI 对话历史不能增量同步 |
| **推送无 message_id 去重** | 低 | 推送 data 不带 message_id,可能重复 |

---

## 2. 目标

让老板:
- 收到 AI 员工/IM/审批的推送通知(含国内 JPush)
- 和 AI 员工有持久化会话历史(按 session 存,不丢)
- 离线再上线,AI 对话历史自动补拉
- IM WebSocket 稳定(心跳 + 重连)

**非目标**:
- 不做大范围 UI 改造(保留现有 ConversationListScreen/ChatScreen)
- 不做群聊/@提及/已读回执(后续迭代)
- 不做富媒体消息(后续迭代)

---

## 3. 实施方案(聚焦 5 个缺口)

### 3.1 缺口 1:AI 对话持久化改造

**问题**:ChatCacheEntity 只有 role/text/ts,不能按 session 存历史
**方案**:改造 ChatCacheEntity 加 session_id 字段,或新建 AiMessageCacheEntity

```kotlin
// 方案:改造 ChatCacheEntity(向后兼容,加 session_id)
@Entity(tableName = "chat_cache")
data class ChatCacheEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val session_id: String = "default",   // 新增:AI 会话 ID
    val role: String,                      // user/assistant
    val text: String,
    val ts: Long = System.currentTimeMillis(),
)

// DAO 加按 session 查询
@Query("SELECT * FROM chat_cache WHERE session_id = :sessionId ORDER BY id ASC LIMIT 200")
fun observeBySession(sessionId: String): Flow<List<ChatCacheEntity>>
```

**改动点**:
- XcagiDatabase.kt:ChatCacheEntity 加 session_id,version 3 → 4,加迁移
- ChatCacheDao:加 observeBySession 查询
- AppViewModel.loadChatCache(conversationId):按 session_id 加载历史
- AppViewModel 发送/接收 AI 消息时:写 Room 带 session_id

### 3.2 缺口 2:打通 JPush 消息接收

**问题**:只有 FCM,没有 JPushMessageService,国内收不到
**方案**:新建 JPushMessageService,注册到 Manifest

```kotlin
// 新建 core/push/JPushReceiver.kt
class JPushReceiver : JPushMessageService() {
    override fun onMessage(context: Context, message: CustomMessage) {
        // 解析 message.content JSON
        // 复用 XcagiMessagingService 的处理逻辑(提取公共方法)
        // 写 Room + 触发 SyncPuller + 弹通知
    }
}
```

**改动点**:
- 新建 JPushReceiver.kt
- AndroidManifest.xml 注册 JPushReceiver
- XcagiMessagingService 提取公共消息处理方法(供 JPushReceiver 复用)

### 3.3 缺口 3:ImWebSocketClient 心跳 + 重连

**问题**:无心跳,无重连,长连接会断
**方案**:加心跳 ping(30s)+ 断线重连(指数退避)

```kotlin
// ImWebSocketClient 增强:
private val heartbeatScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
private var reconnectAttempts = 0

fun connect(sessionId: String) {
    // ... 现有逻辑
    // 加心跳:每 30s 发 {"type":"ping"}
    // onFailure:重连(指数退避,1s/2s/4s/8s...最大 5min)
}

private fun startHeartbeat() {
    heartbeatScope.launch {
        while (connected) {
            delay(30_000)
            socket?.send("""{"type":"ping"}""")
        }
    }
}

private fun scheduleReconnect(sessionId: String) {
    val delay = min(5000L * (1L shl reconnectAttempts.coerceAtMost(6)), 300_000L)
    reconnectAttempts++
    heartbeatScope.launch {
        delay(delay)
        connect(sessionId)
    }
}
```

**改动点**:
- ImWebSocketClient.kt:加心跳 + 重连逻辑
- onOpen 时重置 reconnectAttempts = 0

### 3.4 缺口 4:后端 AI 推送

**问题**:AI 员工主动发消息时不推送
**方案**:在 AI 员工主动发消息的路径加 notify_user

**文件**:`app/application/conversation_app_service.py`
```python
# AI 员工主动发消息时(非流式回复):
from app.services.mobile_push import notify_user
notify_user(
    user_id=user_id,
    title=ai_employee_name,
    body=content[:120],
    data={
        "message_id": str(msg_id),
        "session_id": session_id,
        "source": "ai",
        "route": f"xcagi://chat?session={session_id}"
    }
)
```

**改动点**:
- 找到 AI 员工主动发消息的代码路径(非 /api/ai/chat/stream 流式回复)
- 加 notify_user 调用

### 3.5 缺口 5:后端 sync/pull 加 ai_changes + 推送带 message_id

**问题**:sync/pull 无 ai_changes;推送无 message_id
**方案**:

**文件 1**:`app/fastapi_routes/mobile_api_extensions.py`(sync/pull 路由)
```python
# sync/pull 返回体加 ai_changes:
{
    "changes": [...],           # 现有(含 im_message/im_read_state)
    "ai_changes": [             # 新增
        {"session_id": ..., "message_id": ..., "role": ..., "content": ..., "created_at": ...}
    ],
    "cursor": ...
}
```

**文件 2**:`app/services/mobile_push.py` + 所有调用方
```python
# 推送 data 统一带 message_id:
data["message_id"] = str(message_id)  # 供 Android 端去重
```

**改动点**:
- mobile_api_extensions.py sync/pull 加 ai_changes 字段(查 ai_conversations 表)
- mobile_push.py 所有推送 data 带 message_id
- Android MobileSyncRepository.pullAndCache() 处理 ai_changes → 写 ChatCacheEntity

---

## 4. 数据流(修订后)

### 4.1 IM 消息流(已打通,仅需补心跳/重连)

```
后端 /ws/im ──WS──► ImWebSocketClient ──► ImRepository
                                              │
                                              ├─► Room im_message_cache(去重)
                                              └─► requestPullHint() → MobileSyncWorker
                                                                     └─► MobileSyncRepository.pullAndCache()
                                                                         └─► ImRepository.applySyncMessage()

UI: ConversationListScreen ◄── vm.conversations ◄── ImRepository.observeMessages()
    ChatScreen(IM)           ◄── vm.chatMessages  ◄── ImRepository.observeMessages(conversationId)
```

### 4.2 AI 对话消息流(需改造持久化)

```
用户发消息 ──► AppViewModel.submitChat()
                 ├─► 写 Room chat_cache(session_id, role=user)  [改造点]
                 └─► SSE /api/ai/chat/stream
                       └─► 流式回复 ──► vm.streaming
                                        └─► 完成后写 Room chat_cache(session_id, role=assistant)  [改造点]
                                            └─► POST /api/ai/message/save 持久化到后端

AI 员工主动推送 ──► 后端 notify_user  [改造点]
                     └─► FCM/JPush ──► PushService
                                        ├─► 写 Room chat_cache(预览)  [改造点]
                                        └─► 弹通知 → 点开 → ChatScreen
                                                        └─► vm.loadChatCache(session_id)  [改造点]
                                                            └─► Room chat_cache WHERE session_id

离线补拉 ──► MobileSyncRepository.pullAndCache()
              └─► ai_changes  [改造点]
                  └─► 写 Room chat_cache(session_id, ...)
```

### 4.3 推送唤醒流(需打通 JPush)

```
后端 notify_user ──► FCM(海外)/ JPush(国内)
                       │                    │
                       ▼                    ▼
              XcagiMessagingService   JPushReceiver  [新建]
                       │                    │
                       └─────► 公共处理方法 ◄┘
                                  │
                                  ├─► 写 Room(预览)
                                  ├─► 触发 SyncPuller
                                  └─► 弹通知(deep link)
```

---

## 5. 工程量评估(修订后)

| 缺口 | 工作量 | 说明 |
|------|--------|------|
| AI 对话持久化改造 | 中 | ChatCacheEntity 加 session_id + 迁移 + DAO + ViewModel 改造 |
| 打通 JPush 接收 | 小 | 新建 JPushReceiver + Manifest 注册 + 提取公共方法 |
| ImWebSocketClient 心跳/重连 | 小 | 加心跳 ping + 指数退避重连 |
| 后端 AI 推送 | 小 | 找到主动发消息路径 + 加 notify_user |
| 后端 sync/pull ai_changes | 小 | sync/pull 加 ai_changes 字段 + Android 处理 |
| 推送带 message_id | 小 | mobile_push.py + 调用方加 message_id |
| 测试 | 中 | AI 持久化 + JPush + WS 重连 + 后端 AI 推送 |

**总工程量:小-中**(比初版评估的"中"降一级,因为 IM 基础设施已就绪)

---

## 6. 实施顺序

1. **Phase 1:AI 对话持久化** — ChatCacheEntity 加 session_id + 迁移 + DAO + ViewModel
2. **Phase 2:ImWebSocketClient 稳定性** — 心跳 + 重连
3. **Phase 3:打通 JPush** — JPushReceiver + Manifest + 公共方法提取
4. **Phase 4:后端改动** — AI 推送 + sync ai_changes + 推送带 message_id
5. **Phase 5:Android sync 处理 ai_changes** — MobileSyncRepository 处理 ai_changes
6. **Phase 6:测试** — 单测 + 集成 + 真机联调

---

## 7. 测试策略

### 7.1 单元测试

| 模块 | 测试内容 |
|------|---------|
| ChatCacheDao | 按 session_id 查询/去重/排序 |
| ImWebSocketClient | 心跳触发/重连指数退避/消息解析 |
| JPushReceiver | 消息解析/去重/触发 sync |
| MobileSyncRepository | ai_changes 处理/cursor 更新 |

### 7.2 集成测试

| 场景 | 验证 |
|------|------|
| AI 对话历史 | 发消息 → 写 Room → 重新打开 → 历史还在 |
| AI 推送 | 后端 notify_user → Android 收到 → Room 有预览 → 通知 |
| WS 断线重连 | 断网 → 恢复 → 自动重连 → 收消息 |
| JPush 推送 | 后端发 JPush → Android 收到 → 写 Room |
| 离线补拉 | 离线 → 后端有新 AI 消息 → 上线 sync → Room 补全 |

### 7.3 后端测试

| 场景 | 验证 |
|------|------|
| AI 推送 | AI 员工发消息 → notify_user 被调用 |
| sync/pull ai_changes | 返回体含 ai_changes |
| 推送带 message_id | data 字段含 message_id |

---

## 8. 非目标(明确不做)

- 不做大范围 UI 改造(保留现有 ConversationListScreen/ChatScreen)
- 不做群聊/@提及/已读回执(后续迭代)
- 不做富媒体消息(后续迭代)
- 不做跨进程 WebSocket 广播(后端 ImWsHub 进程内够用)
- 不做消息搜索(后续迭代)
- 不重构现有 IM 基础设施(已就绪,只补缺口)

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| ChatCacheEntity 迁移破坏现有数据 | 加 Migration(3→4),session_id 默认 "default" |
| JPush 国内配置缺失 | isJpushConfigured() 检查,缺失时静默降级到 FCM + sync |
| WS 重连风暴 | 指数退避,最大 5min,网络恢复后才重连 |
| 后端 AI 推送路径难找 | 需先调研 AI 员工主动发消息的代码路径 |
| sync/pull ai_changes 性能 | 只查用户自己的 ai_conversations,加 limit |
