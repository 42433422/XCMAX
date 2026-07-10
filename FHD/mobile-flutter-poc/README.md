# XCAGI 移动客户端（Flutter 主线）

> **2026-07-07**：移动统一交付 **仅** 维护本目录。`../mobile-android/`、`../mobile-ios/` 进入归档，禁止新增产品流程。  
> 文档：[`docs/guides/MOBILE_FLUTTER.md`](../docs/guides/MOBILE_FLUTTER.md) · SSOT：[`docs/mobile_tri_platform_ssot.md`](../docs/mobile_tri_platform_ssot.md)

Android + iOS 单代码库，对接 `/api/mobile/v1/*` 与 OpenAPI 契约，是 XCAGI 移动端唯一生产交付主线。

迁移期行为仍可对齐已归档的 `mobile-android`（Kotlin）实现；**新功能与 UX 修复只在本仓落地**。

## 本地命令

```bash
cd FHD/mobile-flutter-poc
flutter pub get
flutter test
flutter run
```

## 策略摘要

- 固定联系人 / 员工头像 / 超级员工路由：见 [`ANDROID_FIRST_UNIFICATION.md`](ANDROID_FIRST_UNIFICATION.md)（Android 现为**参照**而非 SSOT）
- 设计 token：`FHD/config/mobile_design_tokens.json`
- 错误文案：`lib/src/policy/android_error_policy.dart`（`androidProductErrorMessage`）

## 已覆盖流程（节选）

- 登录、配对、会话持久化、LAN ↔ 云中继路由
- 消息列表、聊天 SSE、通讯录、AI 群、超级员工 Codex/Cursor/Claude/Trae
- IM WebSocket、员工任务中心、设备注册

详见 [`ANDROID_FIRST_UNIFICATION.md`](ANDROID_FIRST_UNIFICATION.md) 各 Stage。
