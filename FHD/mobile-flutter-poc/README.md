# XCAGI Flutter 统一移动端

XCAGI unified mobile implementation：一套 Flutter 代码同时交付 Android 与 iOS，
替代原生 `mobile-android` / `mobile-ios` 成为移动端唯一主实现（Flutter proof of concept
已收敛为主线，SSOT 见 [`FHD/docs/mobile_tri_platform_ssot.md`](../docs/mobile_tri_platform_ssot.md)）。

操作规则见 [`ANDROID_FIRST_UNIFICATION.md`](ANDROID_FIRST_UNIFICATION.md)：
`mobile-android` 是行为、路由命名、头像身份、布局常量与 API 契约的**对齐参照基线**（已冻结）；
Flutter 主线收敛移动产品线，不做第四套移动视觉分叉。

刻意复制 Android 移动 SSOT 概念而不是发明 Flutter-only 规则：

- `PinnedIds`
- `ConversationType`
- `AppAvatarFallback`
- `MessageAvatarLayout`
- `chatAvatarFallback`
- `aiGroupAvatarFallback`
- Codex / Cursor / Claude / Trae 超级员工工具路由

## 双 SKU 构建（与原生 mobile-android 完全一致）

| SKU | applicationId | 应用名 | 构建命令 |
|---|---|---|---|
| personal | `com.xiuci.xcagi.mobile.personal` | XCAGI 个人版 | `flutter build apk --flavor personal --dart-define=XCAGI_PRODUCT_SKU=personal` |
| enterprise | `com.xiuci.xcagi.mobile.enterprise` | XCAGI 企业版 | `flutter build apk --flavor enterprise --dart-define=XCAGI_PRODUCT_SKU=enterprise` |

- 版本锚点全线 v10 锁定：`pubspec.yaml` = `10.0.0+10`，禁止单端 bump。
- Dart 构建 SKU 走 `XCAGI_PRODUCT_SKU` dart-define（缺省 enterprise）；运行时可被
  `GET /api/app/config` 的 `sku` 远程覆盖（与原生 `ProductSkuConfig` 同策略）。
- 同一套代码在 Android 上报 `X-XCAGI-Client: android`、在 iOS 上报 `X-XCAGI-Client: ios`。

## 覆盖流程

- 会话列表、1:1 聊天（SSE 流式）、AI 员工通讯录、员工档案、员工任务中心（Phase-D 提问回答）。
- AI 群聊、AI 交流圈、专属客服 + 管理端客服收件箱、IM（`api/mobile/v1/im/*`）。
- 登录（密码/验证码）、法务同意、行业引导、扫码配对/中继、审批、企业模块、服务桥。
- 钱包/支付、市场目录、Mod WebView（token 注入）、设置、通知、OCR、语音输入、APK 自更新。

头像规则刻意从严：固定联系人永远使用内置固定资产；员工 URL 仅用于非固定 AI 员工；
所有头像裁剪后以 `BoxFit.cover` 渲染。

## Parity 门禁（对齐 Android 的自动化防漂移）

`flutter test` 内含直读 `../mobile-android` 源码的 parity 测试：

- `mobile_api_parity_test.dart`：`ApiEndpoints.kt` 端点表、`FhdApi.kt` 全部 Retrofit HTTP 面（105 对 method+path）、`Topology.kt`、Gradle BuildConfig 默认值、`AuthInterceptor` 公开路径与 token 选择。
- `android_manifest_parity_test.dart`：Manifest 元数据、双 SKU productFlavors、launcher 图标字节一致。
- `theme_parity_test.dart` / `home_shell_parity_test.dart` / `duty_roster_ssot_test.dart` 等：token、Tab、值班编制。

## 本地工具链

```bash
cd FHD/mobile-flutter-poc
flutter pub get
flutter test
flutter run --flavor enterprise --dart-define=XCAGI_PRODUCT_SKU=enterprise
```

保持 Android-first 对齐：行为有分歧时，先复制 `mobile-android` 逻辑，再谈样式偏好。
