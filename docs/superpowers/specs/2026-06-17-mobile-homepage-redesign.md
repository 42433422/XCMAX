# 手机端首页重构设计：AI 微信模式

> **日期**：2026-06-17
> **状态**：待审核
> **范围**：Android 原生 App 首页 + 导航重构
> **产品定位**：AI 微信——看起来像微信，聊的全是 AI

---

## 一、产品定位（核心认知）

### 1.1 不是 IM 通讯软件，是 AI 聊天工具

| 维度 | 传统微信/钉钉 | XCMAX 手机端 |
|------|-------------|------------|
| 聊天对象 | 真人 | **AI 为主** |
| 核心价值 | 人与人沟通 | **人与 AI 协作** |
| 消息来源 | 对方真人发送 | **AI 响应 / 任务执行结果** |
| 会话类型 | 联系人聊天 | **AI Agent / 任务会话 / 客服** |

### 1.2 两个核心入口

| 入口 | 名称 | 对接对象 | 内容本质 |
|------|------|---------|---------|
| 固定项 1 | **专属客服** | 企业版桌面端软件客服通道 | 可能是 AI 客服，也可能是人工客服（由桌面端决定） |
| 固定项 2 | **小C助理** | 后端 AI Agent（现有 ChatScreen） | AI 多轮对话 + 工具调用 |

### 1.3 用户心智模型

```
打开 App → "这是我的 AI 工作台，像微信一样好用"
  ↓
看到会话列表 → "我和谁聊过、聊了什么"
  ↓
点「小C助理」→ "问 AI 任何问题"
  ↓
点「专属客服」→ "找企业客服解决问题"
  ↓
其他会话 → "之前的 AI 任务记录"
```

---

## 二、现状分析

### 2.1 当前首页（ChatScreen.kt）

**文件**：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt`（793 行）

**当前形态**：
- 打开 App → 直接进入**单一聊天界面**
- 顶部标题「智能对话」+ 右上角「+」（进入 AI 员工列表）
- 中间：消息气泡列表（空状态显示 Logo + 模式切换 + 快捷建议）
- 底部：输入栏（语音 + 输入框 + 发送 + 更多）
- 功能标签行：深度思考 / 智能搜索

**问题**：
1. 没有"会话列表"概念——用户无法看到历史对话
2. AI 能力入口太深（需要先进入聊天界面才能切换模式）
3. 不像"常用工具"——更像"一个聊天窗口"
4. 企业版没有专属客服入口

### 2.2 现有导航结构

**文件**：`XcagiNavHost.kt`

```
4 Tab 底栏：
  Tab 1: CHAT    → "对话"   → ChatScreen（单一聊天界面）
  Tab 2: WORK    → "生态"   → 工作台/审批/ERP 入口
  Tab 3: DISCOVER → "发现"   → Mod 市场/扫码/工作台 WebView
  Tab 4: PROFILE → "我的"   → 设置页
```

### 2.3 已有基础设施（可复用）

| 组件 | 文件 | 说明 |
|------|------|------|
| IM 消息缓存 | `ImRepository.kt` | Room 本地存储 + WebSocket 监听 |
| IM 数据模型 | `ImMessageCacheEntity` / `ImReadStateEntity` | conversation_id / message_id / body / sender |
| SSE 聊天客户端 | `SseChatClient.kt` | 流式 AI 对话（云端 + 局域网） |
| AI 员工列表 | `AiEmployeeListScreen.kt`（ChatScreen.kt 第 666 行） | 已有微信风格列表 UI 可参考 |
| 微信风格组件 | `WeChatBubble` / `WeChatStyleInputBar` / `WeCell` / `WeTopBar` | 气泡/输入栏/单元格/顶栏已就绪 |
| SKU 配置 | `ProductSkuConfig.kt` | `showsEnterpriseNav` 判断企业版 |
| Retrofit API | `FhdApi.kt` | 30+ 移动端接口定义 |

---

## 三、设计方案

### 3.1 新首页布局（ConversationListScreen）

```
┌──────────────────────────────────────┐
│  消息                    🔍搜索  ➕  │  ← WeTopBar（标题+搜索+加号）
├──────────────────────────────────────┤
│                                      │
│  ═══ 固定联系人（置顶区）═══          │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ 👤  🔵 专属客服          在线  │  │  ← 仅 enterprise SKU 显示
│  │     您好，我是您的专属客服…      │  │
│  │                        10:30  │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ 🤖  🟢 小C助理         AI在线 │  │  ← 始终显示
│  │     有什么可以帮您？            │  │
│  │                         刚刚  │  │
│  └────────────────────────────────┘  │
│                                      │
│  ═══ 最近聊天 ═══                     │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ 📦  发货单处理           [文件] │  │  ← AI 任务会话
│  │     [AI] 已生成标签打印任务      │  │
│  │                          昨天  │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ 📋  审批通知                   │  │  ← 系统通知类会话
│  │     张三提交了发货审批申请       │  │
│  │                        6月15日 │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ 🏷️  标签打印                   │  │  ← AI 工具会话
│  │     [AI] 模板 A 已应用          │  │
│  │                        6月14日 │  │
│  └────────────────────────────────┘  │
│                                      │
├──────────────────────────────────────┤
│  💬消息   📋工作台   🔍发现   👤我的  │  ← WeBottomNavBar（4 Tab）
└──────────────────────────────────────┘
```

### 3.2 数据模型

#### 3.2.1 会话列表项（ConversationItem）

```kotlin
/**
 * 会话列表中的单个条目。
 * 来源三部分：(A) 固定联系人 (B) AI 任务/工具会话 (C) 系统通知。
 */
data class ConversationItem(
    // ── 身份 ──
    val id: String,                  // 唯一 ID："pinned:cs" / "pinned:assistant" / "conv:{uuid}"
    val type: ConversationType,     // 见下文枚举

    // ── 显示 ──
    val title: String,              // 显示名称：「专属客服」「小C助理」「发货单处理」
    val subtitle: String,           // 最后一条消息预览 / 状态描述
    val timestamp: Long,            // 最后消息时间戳（epoch millis）

    // ── 头像 ──
    val avatarType: AvatarType,     // ICON / LETTER / URL
    val avatarIcon: Int? = null,    // R.drawable.* （系统图标：客服/AI）
    val avatarLetter: Char? = null,// 首字（普通会话用）
    val avatarColor: Color? = null, // 首字头像底色
    val avatarUrl: String? = null,  // 远程头像 URL（未来扩展）

    // ── 状态 ──
    val unreadCount: Int = 0,       // 未读数（红点角标）
    val isOnline: Boolean = false,  // 在线状态（仅专属客服有效）
    val isPinned: Boolean = false,  // 是否置顶（固定联系人为 true）

    // ── 徽标 ──
    val badgeText: String? = null,  // 右侧徽标文本：「在线」「AI在线」「[文件]」「[图片]」
    val badgeColor: Color? = null,  // 徽标颜色
)

enum class ConversationType {
    PINNED_CS,          // 固定：专属客服（仅 enterprise）
    PINNED_ASSISTANT,   // 固定：小C助理
    AI_TASK,            // AI 任务会话（发货单/标签/采购等）
    SYSTEM_NOTIFICATION, // 系统通知（审批/同步等）
}

enum class AvatarType { ICON, LETTER, URL }
```

#### 3.2.2 会话列表数据源优先级

```
1. 固定联系人（硬编码，不依赖网络）：
   ├── 专属客服：showsEnterpriseNav == true 时显示
   └── 小C助理：始终显示

2. AI 会话历史（本地 Room DB：im_message 表聚合）：
   ├── 按 conversation_id 分组
   ├── 取每组最后一条消息作为 subtitle
   ├── 取 max(created_at) 作为 timestamp
   └── 未读数 = 总消息数 - im_read_state.last_read_message_id 之后的消息数

3. 未来扩展：后端 `/api/mobile/v1/conversations` 接口返回的远程会话
```

### 3.3 页面路由与跳转

#### 3.3.1 新增路由常量

```kotlin
// Routes.kt 新增
const val CONVERSATION_LIST = "conversation_list"   // 首页会话列表（替代原 CHAT 作为 startDestination）
const val CS_CHAT = "cs_chat"                      // 专属客服聊天页
const val AI_CHAT = "ai_chat"                      // AI 助理聊天页（= 原 ChatScreen，带 conversationId 参数）
const val CONVERSATION_CHAT = "conversation_chat/{conversationId}"  // 普通会话聊天页
```

#### 3.3.2 点击跳转规则

| 列表项点击 | 目标页面 | 参数 | 说明 |
|-----------|---------|------|------|
| 专属客服 | `CsChatScreen` | 无 | 对接桌面端客服通道 |
| 小C助理 | `ChatScreen`（现有） | conversationId = "assistant" | 复用现有 AI 对话逻辑 |
| 普通 AI 会话 | `ChatScreen`（现有） | conversationId | 带 conversationId 的 AI 对话 |

#### 3.3.3 ChatScreen 改造（最小改动）

现有 `ChatScreen` 保持不变，仅新增可选参数：

```kotlin
@Composable
fun ChatScreen(
    vm: AppViewModel,
    onOpenMod: (String) -> Unit,
    onOpenOcr: () -> Unit = {},
    onNavigateToEmployees: () -> Unit = {},
    // === 新增参数（默认值保持向后兼容）===
    conversationId: String? = null,        // 会话 ID（null = 原来的全局聊天）
    conversationTitle: String = "智能对话", // 顶部标题（动态化）
)
```

- `conversationId == null`：行为与现在完全一致（全局聊天）
- `conversationId != null`：加载该会话的历史消息 + 在该会话上下文中发送新消息

### 3.4 专属客服对接方案

#### 3.4.1 对接目标

**企业版桌面端软件**的客服通道。基于现有代码分析：

| 组件 | 现有代码 | 用途 |
|------|---------|------|
| `EnterpriseCustomerServiceView.vue` | 前端企业外部客服视图 | Web 端客服 UI |
| `InternalCustomerServiceView.vue` | 内部客服视图 | 管理端客服 UI |
| `app/application/enterprise_login_flow.py` | 企业登录流程 | 含市场 token + 代管 |
| `app/application/impersonation_bridge.py` | Admin→Enterprise 代管桥接 | 一次性 token 中转 |

#### 3.4.2 CsChatScreen 设计（Phase 1：基础骨架 + 对接）

```kotlin
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CsChatScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val messages by vm.csMessages.collectAsState()
    val streaming by vm.csStreaming.collectAsState()
    var input by remember { mutableStateOf("") }

    Scaffold(
        topBar = {
            WeTopBar(
                title = "专属客服",
                showBack = true,
                onBack = onBack,
                trailing = {
                    // 在线状态指示器
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).background(Color.Green, CircleShape))
                        Spacer(Modifier.width(4.dp))
                        Text("在线", fontSize = 12.sp, color = Color(0xFF999999))
                    }
                },
            )
        },
        bottomBar = {
            WeChatStyleInputBar(  // 复用现有输入栏组件
                value = input,
                onValueChange = { input = it },
                placeholder = "输入消息...",
                onSend = { /* 发送到后端客服接口 */ },
                onStop = { vm.stopCsStream() },
                streaming = streaming,
            )
        },
    ) { padding ->
        // 消息列表（复用 WeChatBubble 或新建 CsBubble）
        LazyColumn(Modifier.padding(padding)) {
            items(messages) { msg ->
                CsMessageBubble(msg)  // 客服消息气泡（支持富文本/图片/文件卡片）
            }
        }
    }
}
```

#### 3.4.3 后端接口需求

**新接口**（需在后端 `mobile_api_extensions.py` 中添加）：

```
GET  /api/mobile/v1/cs/info
  → 返回当前用户的专属客服信息：
     { "cs_available": bool, "cs_name": str, "cs_avatar": str|null, "cs_online": bool }

POST /api/mobile/v1/cs/messages
  → 发送消息到客服通道：
     { "body": str }
  → 返回：{ "message_id": str, "timestamp": str }

GET  /api/mobile/v1/cs/messages?since={message_id}
  → 拉取客服消息（轮询/SSE）：
     [{ "message_id", "sender": "cs|user", "body", "timestamp", "msg_type": "text|image|file|card" }]
```

**复用现有接口**：
- 设备推送注册：`POST /api/mobile/v1/devices/register`（FCM/JPush 收到客服新消息时推送）
- 同步机制：复用现有 `sync/pull` 中的 `im_changes` 字段

### 3.6 底部 Tab 调整

**仅修改 Tab 1，Tab 2/3/4 完全不变。**

| | 现在 | 改后 |
|--|------|------|
| **Tab 1 label** | 「对话」 | **「消息」** |
| Tab 1 icon | `Icons.Default.Chat` | `Icons.Default.Chat`（不变） |
| **Tab 1 内容** | ChatScreen（单一聊天界面） | **ConversationListScreen（会话列表）** |
| Tab 2 label | 「生态」 | **不改** |
| Tab 2 内容 | 工作台/审批/ERP 入口 | **不改** |
| Tab 3 label | 「发现」 | **不改** |
| Tab 3 内容 | Mod 市场/扫码/工作台 WebView | **不改** |
| Tab 4 label | 「我的」 | **不改** |
| Tab 4 内容 | 设置页 | **不改** |

**决策**：保持 `Routes.CHAT` 路由常量名不变（避免大范围引用修改），将 CHAT route 的 Composable 从 `ChatScreen` 替换为新的 `ConversationListScreen`。即 CHAT route → ConversationListScreen。Tab 2/3/4 的 route 和 composable 全部保持原样。

### 3.6 搜索功能（顶部搜索栏）

**Phase 1（本次实现）**：
- 搜索栏 UI 就绪（WeTopBar 中已有搜索 icon 占位）
- 点击搜索 icon → 展开 SearchField
- 输入关键词 → **本地过滤**会话列表（按 title / subtitle 模糊匹配）
- 不做远程搜索（后续迭代）

**Phase 2（后续）**：
- 远程搜索：`GET /api/mobile/v1/conversations/search?q=xxx`
- 搜索范围扩展到 AI 回复内容

### 3.7 加号菜单（右上角 ➕）

**Phase 1**：
- 点击 ➕ → 弹出 BottomSheet
- 选项：
  - 「发起新对话」（清空当前上下文，开始全新 AI 对话）
  - 「扫一扫」（跳转到 ScanQrScreen）

**Phase 2**：
- 「添加联系人」（邀请同事/创建群组）
- 「AI 创建会议」

---

## 四、文件变更清单

### 4.1 新建文件

| 文件 | 行数估算 | 说明 |
|------|---------|------|
| `navigation/ConversationListScreen.kt` | ~300 行 | 新首页：会话列表 Composable |
| `navigation/CsChatScreen.kt` | ~200 行 | 专属客服聊天页 |
| `model/ConversationItem.kt` | ~60 行 | 会话列表数据模型 |
| `core/cs/CsRepository.kt` | ~120 行 | 客服消息 Repository（Retrofit + Room） |

### 4.2 修改文件

| 文件 | 改动说明 |
|------|---------|
| `navigation/ChatScreen.kt` | 新增 `conversationId` / `conversationTitle` 可选参数；顶部标题动态化 |
| `navigation/XcagiNavHost.kt` | CHAT route 从 ChatScreen 改为 ConversationListScreen；Tab 1 label "对话"→"消息"；新增 CS_CHAT / CONVERSATION_CHAT composable |
| `navigation/Routes.kt` | 新增 `CS_CHAT` / `CONVERSATION_CHAT` 常量 |
| `ui/AppViewModel.kt` | 新增 csMessages / csStreaming StateFlow；新增 loadConversations() 方法 |
| `core/network/FhdApi.kt` | 新增客服相关 Retrofit 接口定义 |
| `ui/components/mobile/WeTopBar.kt` | 支持 showSearch / onSearchClick 参数 |

### 4.3 不改动的文件

| 文件 | 原因 |
|------|------|
| `SseChatClient.kt` | AI 对话流式客户端不变 |
| `ImRepository.kt` | IM 缓存层不变，ConversationListScreen 直接查询 |
| `feature/workbench/WorkbenchWebViewScreen.kt` | 工作台 WebView 不变 |
| `feature/scan/ScanQrScreen.kt` | 扫码页不变 |
| `navigation/ApprovalScreens.kt` | 审批页不变 |
| `navigation/EnterpriseScreens.kt` | ERP 页不变 |

---

## 五、实施顺序

### Phase 1（本次）：首页 UI 重构

1. **数据模型**：创建 `ConversationItem.kt`
2. **会话列表页**：创建 `ConversationListScreen.kt`
   - 固定联系人区域（小C助理 + 条件显示专属客服）
   - AI 会话历史列表（从 Room DB 聚合）
   - 微信风格 Cell 渲染（复用 WeCell）
3. **导航改造**：XcagiNavHost.kt 中 CHAT route 指向 ConversationListScreen
4. **Tab 更新**：Tab 1 label "对话"→"消息"
5. **ChatScreen 适配**：新增 conversationId 参数
6. **点击跳转**：列表项点击 → 携带正确参数跳转到 ChatScreen / CsChatScreen

### Phase 2（本次）：专属客服骨架

1. **CsChatScreen**：创建客服聊天页 UI（复用 WeChatBubble + WeChatStyleInputBar）
2. **CsRepository**：创建客服数据层（Retrofit 接口 + 内存 StateFlow）
3. **AppViewModel 扩展**：新增客服消息状态管理
4. **后端接口**：在 `mobile_api_extensions.py` 添加 `/api/mobile/v1/cs/*` 三个接口

### Phase 3（后续迭代）

- 会话持久化增强（Room migration）
- 未读计数实时同步
- 下拉刷新 / 上拉加载更多
- 搜索远程会话
- 客服消息富文本/图片/文件支持
- 长按会话操作菜单（删除/置顶/标已读）

---

## 六、技术约束与决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 会话存储 | Room 本地优先 | 已有 ImMessageCacheEntity 表；离线可用；快速 |
| 专属客服协议 | HTTP REST + FCM 推送 | 与现有移动端架构一致；不需要额外 WebSocket |
| ChatScreen 改造方式 | 向后兼容加参数 | 最小改动；不影响现有测试和路由 |
| 路由常量策略 | 保持 CHAT 名不变 | 避免修改所有引用该常量的地方 |
| 固定联系人数据 | 硬编码非网络请求 | 首屏秒开；不依赖网络；体验确定 |
| 列表排序 | 置顶优先 → timestamp 降序 | 与微信一致 |

---

## 七、验收标准

### Phase 1 验收

- [ ] 打开 App → 看到「消息」Tab 下的会话列表（不是直接进入聊天界面）
- [ ] 列表顶部显示「小C助理」固定项（绿色 AI 图标 + "有什么可以帮您？"）
- [ ] 企业版 SKU 额外显示「专属客服」固定项（个人版不显示）
- [ ] 点击「小C助手」→ 进入 AI 对话界面（行为与现在一致）
- [ ] 点击「专属客服」→ 进入客服聊天界面（骨架可用）
- [ ] AI 任务历史会话显示在固定联系人下方
- [ ] 底部 Tab 1 显示「消息」而非「对话」
- [ ] 搜索栏可输入关键词过滤列表

### Phase 2 验收

- [ ] CsChatScreen 可正常显示消息气泡（用户发 / 客服回）
- [ ] 输入框可发送文字消息到后端
- [ ] 后端 `/api/mobile/v1/cs/*` 三个接口可访问
- [ ] 客服在线状态正确显示
