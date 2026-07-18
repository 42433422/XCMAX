# 移动统一 SSOT（Flutter / OpenAPI / FastAPI 主线）

> 本文件是 XCAGI 移动端统一前端、前后端契约、后端业务归属、设计 token 与端侧性能监控的唯一真相源。新方向是：Flutter 统一移动前端，OpenAPI 统一前后端契约，FastAPI 统一后端业务。
> 最后更新：2026-07-18

## 0. 结论

- **Flutter 统一前端（唯一交付主线）**：新移动页面、路由、状态、组件、缓存和移动端业务流程 **只** 落到 `FHD/mobile-flutter`。
- **Android / iOS 均从 Flutter 发版**：统一 CI 验证两端；Android 产出 APK/AAB，iOS 通过 TestFlight / App Store Connect 发布。
- **独立原生工程已删除**：Kotlin、SwiftUI、HarmonyOS 产品实现及重复 CI 已退出活跃仓库；历史仅可从 Git 取证。
- **OpenAPI 统一前后端契约**：`FHD/contracts/openapi.json` 是移动端与 FastAPI 后端之间的机器可读契约。Flutter 的 DTO/API client 应从 OpenAPI 或经裁剪的 mobile contract 派生，不允许手写一套与 OpenAPI 漂移的字段口径。
- **FastAPI 统一后端业务**：账号、权限、员工系统、聊天、SSE/WebSocket、支付、审批、同步、移动 relay、行业选择和数据写入都归 FastAPI 服务端实现；Flutter 只承载交互、展示、本地缓存和必要的端侧适配。
- **KMM 暂停作为主线**：Flutter 已解决 Android 前端交付问题，不再规划 `mobile-shared` KMM 作为默认方向。
- **设计 token 统一**：`FHD/config/mobile_design_tokens.json` 是移动 token 的机器可读口径；Flutter 是唯一消费主线。
- **性能监控统一指标名**：Flutter Android/iOS 复用本文第 6 节指标名。

## 1. 权威入口

| 范围 | 主线 / SSOT | 派生或对标 |
|---|---|---|
| 移动前端主实现 | `FHD/mobile-flutter` | **唯一交付主线**；Android+iOS |
| Android Runner | `FHD/mobile-flutter/android` | Manifest、平台通道、签名、APK/AAB |
| iOS Runner | `FHD/mobile-flutter/ios` | entitlements、平台通道、签名、IPA |
| 入口文档 | [`guides/MOBILE_FLUTTER.md`](guides/MOBILE_FLUTTER.md) | 日常开发与发版说明 |
| 前后端契约 | `FHD/contracts/openapi.json` | Flutter `lib/src/api/*` |
| 后端业务实现 | `FHD/app/fastapi_routes/mobile_api.py`、`FHD/app/fastapi_routes/mobile_api_extensions.py` 与 `/api/mobile/v1/*` | OpenAPI 导出、移动端 API client |
| 设计 token | `FHD/config/mobile_design_tokens.json` | Flutter `lib/src/theme/*` |
| 端侧性能指标 | 本文第 6 节指标名 | Flutter 埋点 |

## 2. Flutter 前端边界

Flutter 主线负责：

- 页面、导航、Shell、主题、组件、表单、列表、聊天气泡、头像渲染。
- 登录、配对、会话、通讯录、AI 群、客服、审批、钱包、设置等移动端交互流程。
- Dart API client、DTO、repository、轻量本地缓存、端侧错误展示。
- 端侧平台适配入口：扫码、OCR、推送、生物识别、WebView token 注入、深链。

Flutter 不负责：

- 权限判定、会员等级、员工系统执行、支付状态、审批流推进、聊天持久化、任务调度、数据最终写入。
- 自定义一套绕过 OpenAPI 的后端字段、错误码或路由命名。
- 在 Android/iOS Runner 内重复业务逻辑，或另起独立产品实现。

## 3. OpenAPI 契约边界

`FHD/contracts/openapi.json` 是移动端与后端之间的契约层。变更规则：

1. 后端新增或修改移动接口，必须先让 FastAPI 路由进入 OpenAPI，并通过 OpenAPI 一致性检查。
2. Flutter DTO/API client 从 OpenAPI 派生；手写模型只能作为临时过渡，必须在同次或后续明确任务中回收。
3. 移动接口路径继续归 `/api/mobile/v1/*`，不要为 Flutter 另开一套 `/api/flutter/*`。
4. 新字段必须保持向后兼容：老客户端可忽略，新客户端可解析，删除字段必须先做迁移窗口。

## 4. FastAPI 后端业务边界

FastAPI 是移动后端业务主线。所有需要可信执行或持久化的逻辑都在服务端完成：

- 账号、注册、登录、session、权限、订阅/会员、企业/个人 SKU。
- 员工系统、超级员工消息、AI 群、交流圈、客服、审批、通知。
- SSE/WebSocket、移动 relay、同步、冲突处理、支付、钱包、行业 onboarding。
- 数据库读写、审计、限流、错误包络、OpenAPI schema 导出。

Flutter 只能缓存和展示服务端状态。出现端侧与服务端冲突时，以 FastAPI 返回和数据库事实为准。

### 准入门槛

- Flutter：`cd FHD/mobile-flutter && flutter pub get && flutter test`
- OpenAPI：`cd FHD && python scripts/dev/export_openapi.py --output contracts/openapi.json && python scripts/tools/check_openapi_consistency.py`
- FastAPI mobile：`cd FHD && python -m pytest tests/test_routes/test_mobile_api_extensions_cov.py`
- SSOT：`cd FHD && python scripts/dev/ssot_cli.py check mobile-tri-platform`

## 5. 设计 Token

`mobile_design_tokens.json` 必须覆盖四类 token：

- `colors`：品牌色、功能色、聊天气泡、交流圈、浅深色中性色。
- `spacing`：4px 栅格，Flutter 使用同数值 logical pixels。
- `radius`：Flutter 使用统一圆角等级。
- `typography`：Flutter 是唯一移动端消费实现。

变更规则：

1. 先改 `mobile_design_tokens.json`。
2. 同次提交同步 Flutter `lib/src/theme/*`。
3. 禁止在 Flutter 新增未登记的品牌色、间距、字号常量；确需平台差异时，在 token JSON 的 `platform_overrides` 登记。

## 6. 性能监控

统一指标名：

| 指标 | 含义 | 平台入口 |
|---|---|---|
| `mobile.app.cold_start` | 首屏可交互耗时 | Flutter 启动埋点 |
| `mobile.auth.login` | 登录请求到状态落地耗时 | Flutter 登录流程 |
| `mobile.api.latency` | 普通 API 请求耗时 | Flutter API client |
| `mobile.sse.first_token` | SSE 首 token 耗时 | Flutter SSE client |
| `mobile.websocket.reconnect` | IM WebSocket 重连耗时/次数 | Flutter IM client |
| `mobile.screen.render` | 关键页面首帧/渲染耗时 | Flutter route/screen lifecycle |
| `mobile.crash.nonfatal` | 非致命异常 | Firebase/MetricKit/HiLog 或 AGC |

平台要求：

- Flutter：新增埋点必须使用上表指标名，具体 SDK/插件可替换但事件名不得漂移。
- 后端：端侧批量上报接口另立任务，未落地前不阻断端侧本地指标采集。

## 7. KMM 例外规则

KMM 不再是移动统一默认路线。满足以下全部条件时，才允许提出 KMM 例外：

1. 逻辑是端侧纯逻辑，不依赖 UI、相机、推送、生物识别、WebView、Keychain/DataStore/Preferences 等平台 SDK。
2. 同一逻辑必须被 Flutter 与第三方 SDK 至少两类消费者长期复用。
3. 用 Dart package、OpenAPI 生成、FastAPI 服务端下沉都不能更简单地解决。
4. 方案明确 platform channel、构建、CI、发布和调试成本，并有退出策略。

未满足上述条件时，不得新增 `mobile-shared` KMM 试点。

## 8. 漂移处理

出现以下任一情况即视为移动统一 SSOT 漂移：

- 新移动能力绕过 Flutter 主线，在 Runner 或新原生工程内新增产品流程。
- Flutter API model 与 `FHD/contracts/openapi.json` 字段、路径、错误包络不一致。
- 可信业务逻辑落在 Flutter 端，导致服务端无法审计、复算或持久化。
- Flutter 新增颜色、间距、字号，但 `mobile_design_tokens.json` 没有登记。
- 性能事件命名绕过第 6 节指标表。
- 未经第 7 节例外评审新增 KMM 共享层。
