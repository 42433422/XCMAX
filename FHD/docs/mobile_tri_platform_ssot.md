# 移动三端统一 SSOT（Android 主线）

> 本文件是 XCAGI `mobile-android` / `mobile-ios` / `mobile-harmony` 的移动三端架构、共享边界、设计 token 与端侧性能监控唯一真相源。Android 是当前行为与视觉主线，iOS、鸿蒙按本文登记的派生口径对齐。
> 最后更新：2026-06-29

## 0. 结论

- **Android 为主线**：新移动能力先在 `FHD/mobile-android` 做完整行为闭环，再按 iOS `PARITY_MATRIX.md` 与鸿蒙 `docs/PARITY_MATRIX.md` 对齐。
- **KMM 可引入，但只共享网络层/模型层**：共享 DTO、端点、认证头、错误包络、分页、SSE 解析等稳定契约；不共享 UI、相机、OCR、推送、生物识别、Keychain/DataStore/Preferences、平台性能 SDK。
- **设计 token 统一**：`FHD/config/mobile_design_tokens.json` 是三端 token 的机器可读口径；当前数值来自 Android `XcagiTheme` / `XcagiTypography` / `XcagiShapes`。
- **性能监控统一指标名**：Android 继续接 Firebase Analytics/Crashlytics，iOS 接 MetricKit/os.log，鸿蒙先接本地 `PerformanceMonitor`，后续可桥到 HiAppEvent / AGC APM。

## 1. 权威入口

| 范围 | 主线 / SSOT | 派生或对标 |
|---|---|---|
| 行为与页面完整性 | `FHD/mobile-android` | `FHD/mobile-ios/PARITY_MATRIX.md`、`FHD/mobile-harmony/docs/PARITY_MATRIX.md` |
| 移动 API 契约 | `FHD/app/fastapi_routes/mobile_api_extensions.py` 与 `/api/mobile/v1/*` | Android Retrofit、iOS `Networking/*`、鸿蒙 `api/*` |
| 设计 token | `FHD/config/mobile_design_tokens.json` | Android `ui/theme/*`、iOS `DesignSystem/Theme.swift`、鸿蒙 `design/DesignTokens.ets` |
| 端侧性能指标 | 本文第 4 节指标名 | Android `XcagiAnalytics`、iOS `MobilePerformanceMonitor`、鸿蒙 `PerformanceMonitor` |

## 2. KMM 共享边界

KMM 不是全端重写。只有在下面边界内减少重复：

| 可共享 | 不共享 |
|---|---|
| API endpoints、DTO/model、auth header 策略、错误码/错误包络、分页与列表游标、SSE 行解析、通用重试/backoff 规则 | Compose/SwiftUI/ArkUI、主题渲染、导航、相机/OCR/扫码、推送 token 获取、生物识别、平台安全存储、MetricKit/Firebase/AGC 等平台 SDK |

### 引入节奏

1. **P0：契约冻结**：OpenAPI 与三端模型字段先对齐；新增字段必须能在三端解析，不要求三端立即展示。
2. **P1：`mobile-shared` KMM 试点**：只放 `network`、`models`、`auth`、`errors`、`sse` 包；Android 先消费，iOS 只在能保持 XcodeGen/CI 稳定时接入。
3. **P2：替换重复实现**：iOS/Harmony 只替换网络/模型层的重复代码；UI 层仍各端原生。

### 准入门槛

- Android：`./gradlew :app:compileEnterpriseDebugKotlin :app:testEnterpriseDebugUnitTest`
- iOS：`cd FHD/mobile-ios && xcodegen generate && ./scripts/ci-build-ios.sh`
- 鸿蒙：`bash FHD/mobile-harmony/scripts/doctor.sh && bash FHD/mobile-harmony/scripts/build-hap.sh --version 10.0.0`
- SSOT：`cd FHD && python scripts/dev/ssot_cli.py check mobile-tri-platform`

## 3. 设计 Token

`mobile_design_tokens.json` 必须覆盖四类 token：

- `colors`：品牌色、功能色、聊天气泡、交流圈、浅深色中性色。
- `spacing`：4px 栅格，Android `Spacing` 为主线。
- `radius`：Android `XcagiShapes` 为主线。
- `typography`：Android `XcagiTypography` 为主线，iOS 使用同尺寸 point，鸿蒙使用同数字 fp/vp。

变更规则：

1. 先改 `mobile_design_tokens.json` 与 Android 主题实现。
2. 同次提交同步 iOS `Theme.swift` 与鸿蒙 `DesignTokens.ets`。
3. 禁止在 iOS/鸿蒙新增未登记的品牌色、间距、字号常量；确需平台差异时，在 token JSON 的 `platform_overrides` 登记。

## 4. 性能监控

统一指标名：

| 指标 | 含义 | 平台入口 |
|---|---|---|
| `mobile.app.cold_start` | 首屏可交互耗时 | Android Firebase/custom event，iOS MetricKit/os.log，鸿蒙 `PerformanceMonitor` |
| `mobile.auth.login` | 登录请求到状态落地耗时 | 三端登录流程 |
| `mobile.api.latency` | 普通 API 请求耗时 | 三端 API client |
| `mobile.sse.first_token` | SSE 首 token 耗时 | Android/iOS/鸿蒙 SSE client |
| `mobile.websocket.reconnect` | IM WebSocket 重连耗时/次数 | 三端 IM client |
| `mobile.screen.render` | 关键页面首帧/渲染耗时 | 各端 UI 生命周期 |
| `mobile.crash.nonfatal` | 非致命异常 | Firebase/MetricKit/HiLog 或 AGC |

平台要求：

- Android：Firebase Analytics/Crashlytics 已在 Gradle 中接入，性能事件统一走 `XcagiAnalytics.logPerformanceMetric`；后续有 Firebase Performance 控制台配置后再打开插件级 trace。
- iOS：`MobilePerformanceMonitor` 订阅 MetricKit，并用 `os.Logger` 记录自定义指标；App Store/TestFlight 构建可直接收集系统性能 payload。
- 鸿蒙：`PerformanceMonitor.ets` 先提供统一指标封装；上架前桥接 HiAppEvent / AGC APM 时不得改指标名。
- 后端：端侧批量上报接口另立任务，未落地前不阻断端侧本地指标采集。

## 5. 漂移处理

出现以下任一情况即视为三端 SSOT 漂移：

- 新移动 API 只在一个端建模，另外两端没有字段兼容或对标矩阵说明。
- iOS/鸿蒙新增颜色、间距、字号，但 `mobile_design_tokens.json` 没有登记。
- 性能事件命名绕过第 4 节指标表。
- KMM 试点跨入 UI、设备能力或平台 SDK 层。
