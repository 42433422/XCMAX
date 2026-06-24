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
# 选 XCAGIMobile scheme → Cmd+R 跑模拟器;真机需在 project.yml 填 DEVELOPMENT_TEAM
```

命令行构建(可选):

```bash
xcodegen generate
xcodebuild -project XCAGIMobile.xcodeproj -scheme XCAGIMobile \
  -destination 'platform=iOS Simulator,name=iPhone 15' build
```

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
