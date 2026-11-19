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
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy NO_PROXY=127.0.0.1,localhost flutter test --no-pub
flutter run
```

## 策略摘要

- 固定联系人 / 员工头像 / 超级员工路由：见 [`FLUTTER_UNIFICATION.md`](FLUTTER_UNIFICATION.md)
- 设计 token：`FHD/config/mobile_design_tokens.json`。业务工作台复用 [Flutter Material 3.44.7](https://github.com/flutter/flutter/tree/3.44.7/packages/flutter/lib/src/material)（BSD-3-Clause）的列表、表单与动效组件。
- 错误文案：`lib/src/policy/mobile_error_policy.dart`（`mobileProductErrorMessage`）

## 已覆盖流程（节选）

- 登录、配对、会话持久化、LAN ↔ 云中继路由
- 消息列表、聊天 SSE、通讯录、AI 群、超级员工 Codex/Cursor/Claude/Trae
- IM WebSocket、员工任务中心、设备注册

详见 [`FLUTTER_UNIFICATION.md`](FLUTTER_UNIFICATION.md)。

> 本目录是移动端产品主线；签名安装、双端真机与升级验收状态以发布记录为准，源码或测试通过不等于已交付。
> 测试命令仅在测试子进程中绕过代理，避免本机回环调试连接被代理拦截；不修改系统代理。

离线聊天与待发队列按服务端、账号隔离。旧版未标注归属的 JSON/SQLite 缓存保留在设备上，不自动展示、迁入或重放到当前账号。
