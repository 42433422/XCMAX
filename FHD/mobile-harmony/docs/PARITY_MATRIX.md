# 鸿蒙端 ↔ 安卓端 功能对标矩阵

记录 `mobile-harmony`(ArkTS)对标 `mobile-android`(Kotlin/Compose)的逐项状态。

**验证口径**
- ✅ 已编译验证：本机离线 `hvigor assembleHap` 编译通过(类型检查 + 打包 HAP)。
- 📱 待真机验证：代码已落地并编译通过，但真机行为(摄像头/推送/生物识别/WebSocket 实时/系统弹窗)需在 HarmonyOS 设备上验证。
- ⚙️ 前置条件：需外部配置(如华为 AGC)才能端到端生效。

离线编译验证命令见 `BUILD_HARMONY.md`。后端端点见 `app/fastapi_routes/mobile_api_extensions.py`(挂在 `/api/mobile/v1`)。

## 页面 / 功能

| 功能 | 安卓 | 鸿蒙(本次前) | 鸿蒙(本次后) | 数据源 / 说明 | 验证 |
|---|---|---|---|---|---|
| 登录(管理端/企业端) | ✅ | ✅ | ✅ | `auth/login` | ✅ |
| 桌面绑定码 | ✅ | ✅ | ✅ | `pairing/exchange` | ✅ |
| **登录态持久化 + 自动登录** | ✅ | ❌ | ✅ 新增 | `state/LocalStore.ets`(@ohos.data.preferences) | ✅ |
| 会话列表 / 1:1 对话 | ✅ | ✅ | ✅ | `home`/`mods`/`contacts/fixed` | ✅ |
| **SSE 流式对话(逐字)** | ✅ | ❌ HTTP一次性 | ✅ 新增 | `api/SseChatClient.ets` → `/api/ai/chat/stream`，失败回退 HTTP | 📱 |
| 通讯录 / 员工档案 | ✅ | ✅ | ✅ | `buildEmployees` | ✅ |
| 值班编制(Duty Roster) | ✅ | ✅ | ✅ | `buildDutyRoster` | ✅ |
| 审批(列表/详情/通过驳回) | ✅ | ✅ | ✅ | `approval/requests` | ✅ |
| 专属客服聊天 | ✅ | ✅ | ✅ | `cs/info`/`cs/messages`/`cs/chat` | ✅ |
| **AI 交流圈(朋友圈)** | ✅ | ⚠️ mock | ✅ 接真数据 | `circle/posts`(点赞/评论) | ✅ |
| 发现页 → 交流圈入口 | ✅ | ⚠️ 无入口 | ✅ 接 overlay | — | ✅ |
| **AI 群聊(群聊)** | ✅ | ❌ 缺失 | ✅ 新增 | `ai-groups`(列表/建群/发消息/邀请成员) | 📱 |
| **企业模块-客户** | ✅ | ⚠️ mock | ✅ 接真数据 | `customers` | ✅ |
| **企业模块-发货** | ✅ | ⚠️ mock | ✅ 接真数据 | `shipments` | ✅ |
| 企业模块-审批 | ✅ | ⚠️ mock | ✅ 跳真审批入口 | → ApprovalPage | ✅ |
| 企业模块-库存/ERP/分析 | ✅ | ⚠️ mock | ✅ 诚实提示桌面端 | 移动端无 JWT 端点 | ✅ |
| **应用市场(MOD)** | ✅ | ⚠️ mock | ✅ 接真数据 | `mods` | ✅ |
| **服务桥工单** | ✅ | ⚠️ mock | ✅ 接真数据 | `service-bridge/requests` | ✅ |
| **账户钱包(原长尾)** | ✅ | ⚠️ mock | ✅ 接真数据 | `wallet/balance` | ✅ |
| **通知中心** | ✅ | ⚠️ mock 5 条 | ✅ 接真推送存储 | `NotificationManager`(无后端专用端点，来自推送/同步) | ✅ |
| 合规同意(首启门) | ✅ | ⚠️ 孤儿页 | ✅ 接入+持久化 | `LocalStore.legalConsented` | ✅ |
| 注册页 | ✅ | ⚠️ 孤儿页 | ✅ 接入导航 | 企业账号经登录/绑定下发；自助注册(modstore 手机验证码流)列为后续 | ✅ |
| **生物识别解锁** | ✅ | ⚠️ 仅开关 | ✅ 新增 | `state/BiometricGate.ets`(@ohos.userIAM.userAuth) | 📱 |
| **网络监测 + 离线横幅** | ✅ | ❌ 缺失 | ✅ 新增 | `state/NetworkMonitor.ets`(@ohos.net.connection) | 📱 |
| **IM 实时(WebSocket)** | ✅ | ⚠️ 本地append | ✅ 新增 | `api/ImWebSocketClient.ets` → `/ws/im`(重连退避+心跳，实时接收) | 📱 |
| **真二维码扫描** | ✅ | ⚠️ 模拟 | ✅ 新增 | `@kit.ScanKit` startScanForResult | 📱 |
| **真 OCR 文字识别** | ✅ | ⚠️ 模拟 | ✅ 新增 | `@kit.CoreVisionKit` + 相册选图 + 剪贴板复制 | 📱 |
| **推送 token 注册** | ✅ | ❌ 缺失 | ✅ 新增 | `state/PushService.ets`(@kit.PushKit) → `devices/register` | ⚙️📱 需 AGC |
| 设置(主题/生物识别开关持久化) | ✅ | ⚠️ 无持久化 | ✅ 持久化 | `LocalStore.savePreferences` | ✅ |
| MOD WebView 宿主 | ✅ | ⚠️ 占位 | ⚠️ 仍占位 | 需接 Web 组件(后续) | — |
| 固定伙伴名片 | ✅ | ⚠️ 静态/孤儿 | ⚠️ 未改 | 与 ContactsPage 员工档案功能重叠，低优先级后续 | — |

## 仍待办(诚实声明)

1. **真机验证(📱)**：SSE 逐字、群聊收发、IM WebSocket 实时、扫码、OCR、生物识别 —— 需在 HarmonyOS 设备/模拟器上验证交互。
2. **推送端到端(⚙️)**：PushKit `getToken` 需在华为 AGC 控制台配置应用(`agconnect-services.json`)并真机运行；当前代码 best-effort 取 token 注册，未配置时静默跳过、不阻断登录。
3. **ModWebViewPage**：仍是文本占位，需接 ArkWeb `Web` 组件并注入登录态。
4. **FixedPartnerProfilePage**：静态卡片且与通讯录员工档案重叠，未投入改造。
5. **注册自助流**：企业版以登录/绑定为主；modstore 个人账号手机验证码注册是独立子系统，未在企业端接入。
6. **权限**：已声明 INTERNET + GET_NETWORK_INFO；扫码/相册由 ScanKit/Picker 各自 ability 处理摄像头权限，宿主未额外声明 CAMERA。
