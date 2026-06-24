# 修茈企业 iOS App(`mobile-ios`)

原生 **SwiftUI + MVVM** 客户端,对标 `mobile-android`(Kotlin/Compose)与 `mobile-harmony`(ArkTS)。
共享同一套移动 API 契约 `api/mobile/v1/*`(见 `app/fastapi_routes/mobile_api_extensions.py`)。

> 范围:**全量对标安卓**。核心流程(登录/配对、SSE 流式对话、会话、通讯录、审批、客服、AI 交流圈、AI 群聊、企业模块、设置)
> + 设备相关能力(二维码扫描、OCR、APNs 推送、IM 实时收发、MOD WebView)均已用真实原生框架实现,逐项状态见 `PARITY_MATRIX.md`。
> 仍需在 Xcode/真机做交互验证(摄像头/识别/推送/WebSocket 实时);推送端到端需开启 Push Notifications capability + APNs 配置。

## 技术栈

- SwiftUI(iOS 16+)、async/await、`URLSession`
- **零第三方依赖**:仅 SwiftUI / Foundation / Network / Security / LocalAuthentication
- 三种传输全部原生实现:
  - REST:`Networking/APIClient.swift`(统一信封解包 + Bearer + snake_case 解码)
  - SSE 逐字流:`Networking/SSEChatClient.swift`(`URLSession.bytes` → 有序 `AsyncThrowingStream`)
  - IM 实时:`Networking/IMWebSocketClient.swift`(`URLSessionWebSocketTask` + 指数退避重连 + 心跳)
- 令牌存 **Keychain**(`Persistence/KeychainHelper.swift`),比安卓端明文 DataStore 更稳妥

## 构建(需装有 Xcode 的 Mac)

工程由 `project.yml` 声明式生成(`.xcodeproj` 不入库)。

```bash
brew install xcodegen          # 一次性
cd FHD/mobile-ios
xcodegen generate              # 生成 XCAGIMobile.xcodeproj
open XCAGIMobile.xcodeproj
# 两个 scheme(对标 Android flavor):
#   XCAGIMobile         → 企业版(com.xiuci.xcagi.mobile.enterprise)
#   XCAGIMobilePersonal → 个人版(com.xiuci.xcagi.mobile.personal,PERSONAL 编译条件 → MODstore 基址)
# 选 scheme → Cmd+R 跑模拟器;真机需在 project.yml 填 DEVELOPMENT_TEAM
```

**推送**:工程已预置 Push 能力(`Resources/XCAGIMobile.entitlements` 的 `aps-environment` + Info.plist `remote-notification` 后台模式)。
端到端取 token 仍需在 Apple Developer 配置 APNs 密钥并用真实 Team 签名;只跑模拟器或暂不接推送时,可移除 `project.yml` 的 `CODE_SIGN_ENTITLEMENTS` 行以免签名要求。

命令行构建(可选):

```bash
xcodegen generate
xcodebuild -project XCAGIMobile.xcodeproj -scheme XCAGIMobile \
  -destination 'platform=iOS Simulator,name=iPhone 15' build
```

## 发版与签名(CI)

两条流水线(源在 `FHD/.github/workflows/`,根 `.github/workflows/` 为镜像):

| workflow | 触发 | 作用 | 需要 secret |
|---|---|---|---|
| `ci-mobile-ios` | push/PR 命中 `mobile-ios/**` | `xcodegen` + `xcodebuild` **免签编译验证**(模拟器目标) | 无 |
| `release-ios`(Release iOS Enterprise) | 手动 `workflow_dispatch` | 签名 `archive` → 导出 `.ipa`(可选 TestFlight 上传);**未配 secret 时降级为未签名归档** | 见下 |

发版所需 GitHub secrets(仓库 Settings → Secrets and variables → Actions):

| secret | 来源 | 必填 |
|---|---|---|
| `IOS_DIST_CERT_P12_BASE64` | 分发证书 `.p12` → `base64 -i dist.p12 \| pbcopy` | 是 |
| `IOS_DIST_CERT_PASSWORD` | 导出 `.p12` 时设的密码 | 是 |
| `IOS_PROVISION_PROFILE_BASE64` | 描述文件 `.mobileprovision` → `base64 -i app.mobileprovision \| pbcopy` | 是 |
| `IOS_TEAM_ID` | Apple Developer → Membership 的 10 位 Team ID | 是 |
| `IOS_KEYCHAIN_PASSWORD` | 任意临时口令(留空则随机) | 否 |
| `APP_STORE_CONNECT_API_KEY_ID` / `_ISSUER_ID` / `_KEY_BASE64` | App Store Connect API Key(`.p8` base64),仅 `upload_testflight=true` 用 | 否 |

> 配齐前 4 个 secret 后,Actions 里手动跑 **Release iOS Enterprise** 即产出 `.ipa` 工件;勾 `upload_testflight` 且配好 API Key 则直推 TestFlight。本地手动导出见 `ExportOptions.example.plist`。
> ⚠️ 当前 `Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png` 是**占位图标**,上架前用正式品牌图标替换(脚本:`scripts/gen_placeholder_appicon.py`)。

## 后端基址

- 企业版默认 `https://xiu-ci.com/fhd-api`(`Config/AppConfig.swift`)
- 桌面端「绑定码」走 `pairing/exchange`,下发局域网主机基址(默认端口 17500)并持久化
- `Info.plist` 已开 `NSAllowsLocalNetworking`,便于内网/桌面联调

## 目录

```
XCAGIMobile/
  App/            入口 + 根路由 + 偏好/网络注入
  Config/         AppConfig(基址/SKU/公司)
  Networking/     APIEndpoints / APIModels / APIClient / SSEChatClient / IMWebSocketClient
  Persistence/    Keychain + SessionStore(对标鸿蒙 LocalStore)
  State/          SessionManager(登录/配对/登出/客户端工厂)/ NetworkMonitor / BiometricGate
  DesignSystem/   Theme + 复用组件
  Features/       Auth / Shell / Conversations / Chat / Contacts / Approvals /
                  CustomerService / Circle / AiGroups / Enterprise / Discover /
                  Profile / Settings / Placeholders
  Resources/      Info.plist + Assets.xcassets
```

## 本地已验证

本机无 Xcode,无法整体编译,但已用 `swiftc` 对照 **macOS SDK** 做了:

- **逻辑层全量类型检查通过**(Networking / Persistence / State 等不依赖 SwiftUI 的文件,`swiftc -typecheck` exit 0)——这些用的是 Foundation/Network/Security/Combine/LocalAuthentication,与 iOS 同源。
- **全部 Swift 文件零语法错误**(`swiftc -parse`)。
- 视图层仅余「iOS 专有 API 在 macOS 不存在」一类预期噪声(如 `navigationBarTitleDisplayMode`、`UIColor.systemGroupedBackground`),在 iOS SDK 下均为合法用法。

真机/模拟器编译与交互验证请在 Xcode 侧完成。
