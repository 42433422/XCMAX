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
bash scripts/generate-app-icon.sh
xcodegen generate              # 生成 XCAGIMobile.xcodeproj
open XCAGIMobile.xcodeproj
# 两个 scheme(对标 Android flavor):
#   XCAGIMobile         → 企业版(com.xiuci.xcagi.mobile.enterprise)
#   XCAGIMobilePersonal → 个人版(com.xiuci.xcagi.mobile.personal,PERSONAL 编译条件 → MODstore 基址)
# 选 scheme → Cmd+R 跑模拟器;真机/归档需传入 Apple Team ID
```

**App Icon**:`scripts/generate-app-icon.sh` 从 `Brand/xiu-ci-logo.png` 生成 App Store 需要的 1024x1024、无透明 `AppIcon-1024.png`。

**推送**:工程已预置 Push 能力(`Resources/XCAGIMobile.entitlements` 的 `aps-environment` + Info.plist `remote-notification` 后台模式)。
`aps-environment` 由 Xcode build setting 注入:Debug 为 `development`,Release 为 `production`。
端到端取 token 仍需在 Apple Developer 配置 APNs 密钥并用真实 Team 签名;只跑模拟器或暂不接推送时,可移除 `project.yml` 的 `CODE_SIGN_ENTITLEMENTS` 行以免签名要求。

命令行构建(可选):

```bash
bash scripts/ci-build-ios.sh
```

## TestFlight / App Store 归档

本地归档需要 Apple Developer 账号、有效 Team ID、App Store Distribution 证书和 provisioning profile。账号密钥不入库,通过环境变量注入:

```bash
cd FHD/mobile-ios
IOS_TEAM_ID=ABCDE12345 \
IOS_SCHEME=XCAGIMobile \
IOS_MARKETING_VERSION=10.0.0 \
IOS_BUILD_NUMBER=1 \
bash scripts/archive-ios.sh --export
```

上传 App Store Connect 需要 API Key:

```bash
IOS_UPLOAD_APP_STORE_CONNECT=1 \
APP_STORE_CONNECT_API_KEY_ID=... \
APP_STORE_CONNECT_API_ISSUER_ID=... \
APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64=... \
IOS_TEAM_ID=ABCDE12345 \
bash scripts/archive-ios.sh --export
```

GitHub Actions 入口: `FHD/.github/workflows/release-ios.yml`。默认只跑模拟器编译;手动勾选 `export_ipa` 时才读取 signing secrets 并导出 IPA。

需要配置的 GitHub Secrets:

- `IOS_TEAM_ID`
- `IOS_CERTIFICATE_P12_BASE64`
- `IOS_CERTIFICATE_PASSWORD`
- `IOS_PROVISION_PROFILE_BASE64`
- `IOS_KEYCHAIN_PASSWORD`
- `APP_STORE_CONNECT_API_KEY_ID`
- `APP_STORE_CONNECT_API_ISSUER_ID`
- `APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64`

`XCAGIMobile` 与 `XCAGIMobilePersonal` 是两个 Bundle ID,如果两个都要上架,需要在 Apple Developer / App Store Connect 分别注册并各自准备 provisioning profile。

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

## 本地验证口径

- `scripts/ci-build-ios.sh`:生成 AppIcon、生成 `.xcodeproj`,并对企业版/个人版两个 scheme 跑 iOS Simulator build。
- `scripts/archive-ios.sh`:生成 AppIcon、生成 `.xcodeproj`,执行 device archive,可选导出 IPA 和上传 App Store Connect。
- 真机交互仍需人工验证:扫码、OCR、APNs 推送、WebSocket/SSE、WebView 登录态。
