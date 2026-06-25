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
| **IM 实时(WebSocket)** | ✅ | ✅ | ✅ | `ImMessengerView`:REST 历史/发送(`/api/im/...`)+ `IMWebSocketClient` 实时接收 | 📱 |
| **真二维码扫描** | ✅ | ✅ | ✅ | `QRScannerView`(AVFoundation `AVCaptureMetadataOutput`),结果可作绑定码 | 📱 |
| **真 OCR 文字识别** | ✅ | ✅ | ✅ | `OcrView`:PhotosUI 选图 + Vision `VNRecognizeTextRequest` + 复制 | 📱 |
| **推送 token 注册** | ✅ | ✅ | ✅ | `AppDelegate`/`PushManager` 取 APNs token → `/devices/register` | ⚙️📱 需推送证书 |
| 通知中心 | ✅ | ✅ | ✅ | `NotificationListView`(UNUserNotificationCenter,前台/点击入库) | 📱 |
| MOD 市场承载页(WebView) | ✅ | ⚠️ 占位 | ✅ | `MarketListView`(`/mods`)→ `ModWebView`(WKWebView 注入登录态) | 📱 |

## 仍待办(诚实声明)

1. **真机验证(📱)**:所有设备相关能力已写完并通过类型/语法检查,但交互需在 iOS 真机/模拟器验证:SSE 逐字、群聊/IM 收发、扫码取景、OCR 识别、生物识别、WebView 登录态注入。
2. **推送 APNs 密钥(⚙️)**:`aps-environment` 权限 + `remote-notification` 后台模式 + Push capability 已在工程内预置(`XCAGIMobile.entitlements`);**端到端仍需在 Apple Developer 配置 APNs 密钥/证书**并用真实 Team 签名。未配置时 `didFailToRegister` 静默忽略、不阻断 App。
3. **签名 / 上架**:`project.yml` 的 `DEVELOPMENT_TEAM` 通过 `IOS_TEAM_ID` 在归档脚本/CI 注入;App 图标由 `scripts/generate-app-icon.sh` 生成 1024 PNG;App Store Connect 上传仍需真实证书、provisioning profile 与 API Key。

### 已闭合(累计)
- ✅ **WebView 登录态注入对齐 Android**:`ModWebView` 精确镜像 `WebViewTokenScript.kt` —— 市场页(`xiu-ci.com`)注入 `localStorage.modstore_token` 不加 Authorization;局域网 FHD(http+内网)注入 `session_id` cookie + Bearer 头;并发 `window.__XCAGI_CLIENT__='ios'` / `xcagi-client-ready` 事件。
- ✅ **个人版兼容 SKU**:`project.yml` 保留 `XCAGIMobilePersonal` target/scheme(`com.xiuci.xcagi.mobile.personal`,定义 `PERSONAL` 编译条件 → `AppConfig.sku=.personal` → MODstore 基址);当前产品线口径下仅作冻结兼容,不作为 iOS 当前上架主线。
- ✅ **推送能力工程预置**:entitlements + 后台模式 + project.yml 接线已就位(差 Apple 侧密钥)。
- ✅ **注册页**(对标 Android `RegisterScreen`):`RegisterView`(用户名/密码/邮箱 → FHD `api/auth/register`),登录页可进入。
- ✅ **服务桥工单回复**(对标 Android `BridgeScreen`):服务桥列表项可回复 —— `service-bridge/requests/{id}/respond`(PUT,状态 resolved/processing/closed)。
- ✅ **固定伙伴名片**(对标 Android `FixedPartnerProfileScreen`):`FixedPartnerProfileView`(头像/简介/能力标签/交流圈标签 + 发消息/查看交流圈),小C/客服/Codex/Claude 四类规格;消息列表行**左滑「名片」**进入(保留点按即对话)。
- ℹ️ **Branded(`BrandedScreens`)非独立屏**:即安卓的登录/连接/鉴权 UI + 条款隐私链接,已由 `LoginView` + `LegalConsentView` + 设置法务链接覆盖,非缺失。

至此安卓 20 个实质 mobile 屏 + 名片页全部对齐;无"故意省略"项。

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
