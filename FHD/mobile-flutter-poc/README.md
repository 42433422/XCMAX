# XCAGI 移动客户端（Flutter 主线）

> **2026-07-18**：本目录是唯一移动端实现与交付主线。独立 Kotlin、SwiftUI、HarmonyOS 产品工程已删除。
>
> 文档：[`docs/guides/MOBILE_FLUTTER.md`](../docs/guides/MOBILE_FLUTTER.md) · SSOT：[`docs/mobile_tri_platform_ssot.md`](../docs/mobile_tri_platform_ssot.md)

Android + iOS 单代码库，对接 `/api/mobile/v1/*` 与 OpenAPI 契约。`lib/` 是唯一业务实现，
`android/` 与 `ios/` 只负责 Runner、平台通道、签名和商店发布。

## 本地命令

```bash
cd FHD/mobile-flutter-poc
flutter pub get
flutter test
flutter run
```

## 策略摘要

- 固定联系人 / 员工头像 / 超级员工路由：见 [`FLUTTER_UNIFICATION.md`](FLUTTER_UNIFICATION.md)
- 设计 token：`FHD/config/mobile_design_tokens.json`
- 错误文案：`lib/src/policy/mobile_error_policy.dart`（`mobileProductErrorMessage`）

## 已覆盖流程（节选）

- 登录、配对、会话持久化、LAN ↔ 云中继路由
- 消息列表、聊天 SSE、通讯录、AI 群、超级员工 Codex/Cursor/Claude/Trae
- IM WebSocket、员工任务中心、设备注册

详见 [`FLUTTER_UNIFICATION.md`](FLUTTER_UNIFICATION.md)。
