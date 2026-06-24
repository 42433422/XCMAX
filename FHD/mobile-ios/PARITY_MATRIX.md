# iOS 端 ↔ 安卓端 功能对标矩阵

记录 `mobile-ios`(SwiftUI)对标 `mobile-android`(Kotlin/Compose)/ `mobile-harmony`(ArkTS)的逐项状态。

**验证口径**
- ✅ 已落地:SwiftUI 视图 + MVVM + 真实 API 客户端均已实现,逻辑层 `swiftc` 类型检查通过。
- 📱 待真机验证:代码已落地,但真机行为(逐字流/WebSocket 实时/相机/识别/推送/生物识别)需在 iOS 设备验证。
- 🧱 占位(诚实声明):依赖原生设备框架,本轮以可编译占位呈现,分阶段补齐(见下「仍待办」)。

后端端点见 `app/fastapi_routes/mobile_api_extensions.py`(挂在 `/api/mobile/v1`);契约与安卓/鸿蒙三端同源。

## 页面 / 功能

| 功能 | 安卓 | 鸿蒙 | iOS(本轮) | 数据源 / 说明 | 验证 |
|---|---|---|---|---|---|
| 登录(管理端/企业端) | ✅ | ✅ | ✅ | `auth/login` | ✅ |
| 桌面绑定码 | ✅ | ✅ | ✅ | `pairing/exchange` → 切换基址 | ✅ |
| 登录态持久化 + 自动登录 | ✅ | ✅ | ✅ | `SessionStore`(Keychain + UserDefaults) | ✅ |
| 合规同意(首启门) | ✅ | ✅ | ✅ | `SessionStore.legalConsented` | ✅ |
| 会话列表 / 固定联系人 | ✅ | ✅ | ✅ | `contacts/fixed` | ✅ |
| **SSE 流式对话(逐字)** | ✅ | ✅ | ✅ | `SSEChatClient` → `/api/ai/chat/stream`,失败回退 `api/ai/chat` | 📱 |
| 通讯录 / 员工档案 | ✅ | ✅ | ✅ | `mods` → workflow_employees | ✅ |
| 审批(列表/详情/通过驳回) | ✅ | ✅ | ✅ | `approval/requests` (+`/approve`/`/reject`) | ✅ |
| 专属客服聊天 | ✅ | ✅ | ✅ | `cs/info`/`cs/messages`/`cs/chat` | ✅ |
| **AI 交流圈(朋友圈)** | ✅ | ✅ | ✅ | `circle/posts`(点赞/评论,乐观更新) | 📱 |
| **AI 群聊** | ✅ | ✅ | ✅ | `ai-groups`(列表/建群/发消息/已读) | 📱 |
| 企业模块-客户 | ✅ | ✅ | ✅ | `customers` | ✅ |
| 企业模块-发货 | ✅ | ✅ | ✅ | `shipments` | ✅ |
| 企业模块-服务桥工单 | ✅ | ✅ | ✅ | `service-bridge/requests` | ✅ |
| 账户钱包(我的页) | ✅ | ✅ | ✅ | `wallet/balance` | ✅ |
| 设置(主题/生物识别持久化) | ✅ | ✅ | ✅ | `SessionStore.savePreferences` | ✅ |
| **生物识别解锁** | ✅ | ✅ | ✅ | `BiometricGate`(LocalAuthentication) | 📱 |
| **网络监测 + 离线横幅** | ✅ | ✅ | ✅ | `NetworkMonitor`(NWPathMonitor) | ✅ |
| **IM 实时(WebSocket)客户端** | ✅ | ✅ | ✅(基础设施) | `IMWebSocketClient`(退避重连+心跳);会话 UI 占位 | 📱🧱 |
| **真二维码扫描** | ✅ | ✅ | 🧱 占位 | 待接 `AVCaptureMetadataOutput` | 🧱 |
| **真 OCR 文字识别** | ✅ | ✅ | 🧱 占位 | 待接 Vision `VNRecognizeTextRequest` + PhotosUI | 🧱 |
| **推送 token 注册** | ✅ | ✅ | 🧱 占位 | `APIClient.registerDevice` 已就绪;待接 APNs 取 token | 🧱 |
| 通知中心 | ✅ | ✅ | 🧱 占位 | 待接 UNUserNotificationCenter | 🧱 |
| MOD 市场承载页(WebView) | ✅ | ⚠️ 占位 | 🧱 占位 | 列表用 `mods`;详情待接 WKWebView | 🧱 |

## 仍待办(诚实声明)

1. **真机验证(📱)**:SSE 逐字、群聊收发、生物识别解锁需在 iOS 设备/模拟器验证交互。
2. **设备能力(🧱)**——按优先级分阶段补齐:
   - 扫码:`AVFoundation` `AVCaptureMetadataOutput`
   - OCR:`Vision` + `PhotosUI`(选图识别)
   - 推送:APNs(`UNUserNotificationCenter` 取 device token → 已有 `/devices/register`)
   - IM 会话 UI:`IMWebSocketClient` 客户端已就绪,缺会话页与历史拉取的接线
   - MOD 详情:`WKWebView` 注入登录态
3. **签名 / 上架**:`project.yml` 的 `DEVELOPMENT_TEAM` 需真机/分发时填写;App 图标当前为占位(`AppIcon` 无图)。
4. **个人版 SKU**:当前单 target = 企业版;个人版(MODstore 基址 + 手机验证码注册)作为后续 scheme/配置。

## 与安卓的架构对应

| 安卓(Kotlin) | iOS(Swift) |
|---|---|
| Retrofit + OkHttp + AuthInterceptor | `APIClient`(URLSession) |
| `SseChatClient.kt` | `SSEChatClient.swift` |
| `core/im/ImWebSocketClient.kt` | `IMWebSocketClient.swift` |
| Room + DataStore(SessionStore) | Keychain + UserDefaults(`SessionStore.swift`) |
| Hilt + MVVM + StateFlow | `@StateObject`/`@EnvironmentObject` + `@MainActor` ObservableObject |
| Jetpack Compose | SwiftUI |
| `ApiEndpoints.kt` / `ApiModels.kt` | `APIEndpoints.swift` / `APIModels.swift` |
