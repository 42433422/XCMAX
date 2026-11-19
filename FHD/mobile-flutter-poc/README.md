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
- 设计 token：`FHD/config/mobile_design_tokens.json`
- 错误文案：`lib/src/policy/mobile_error_policy.dart`（`mobileProductErrorMessage`）

## 已覆盖流程（节选）

- 登录、配对、会话持久化、LAN ↔ 云中继路由
- 消息列表、聊天 SSE、通讯录、AI 群、超级员工 Codex/Cursor/Claude/Trae
- IM WebSocket、员工任务中心、设备注册

详见 [`FLUTTER_UNIFICATION.md`](FLUTTER_UNIFICATION.md)。

> 本目录是移动端产品主线；签名安装、双端真机与升级验收状态以发布记录为准，源码或测试通过不等于已交付。
> 测试命令仅在测试子进程中绕过代理，避免本机回环调试连接被代理拦截；不修改系统代理。

离线聊天与待发队列按服务端、账号隔离。旧版未标注归属的 JSON/SQLite 缓存保留在设备上，不自动展示、迁入或重放到当前账号。

## 设备本地工作台

手机登录页与工作台可打开「本地工作台」，桌面启动、登录或侧栏可打开「本地工作区」。客户、商品和订单草稿写入本机。电脑生成五分钟内有效的局域网二维码，手机扫描后选择哪一侧作为初始数据。接收方将原有记录存入本机归档。解绑停止同步，两边继续保存本机记录。

数据通过设备间直连的加密批次交换。打开手机工作台可自动同步，也可随时手动重试。同一版本下的重复发送只入库一次，同一记录并发修改可选保留手机或电脑的版本。单条记录上限为 64 KiB，首次快照受单批次大小限制。局域网地址变化后可重新配对。订单在该工作区始终为草稿，库存、审批和已登录的企业工作区继续各自处理原有业务。

复用 [Drift 2.35.4](https://pub.dev/packages/drift/versions/2.35.4)（MIT）及 SQLite（公有领域）存储，[Dart cryptography 2.9.0](https://pub.dev/packages/cryptography/versions/2.9.0)（Apache-2.0）和现有桌面 PyCA 库实现 AES-GCM，[Uvicorn 0.52.4](https://github.com/encode/uvicorn)（BSD-3-Clause）承载独立局域网监听。桌面标准库 SQLite 构建未启用 Session Extension，业务记录与收件、发件及回执在各端同一数据库事务内维护。
