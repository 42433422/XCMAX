# XCAGI 移动客户端（Flutter 主线）

> **2026-07-18**：本目录是唯一移动端实现与交付主线。独立 Kotlin、SwiftUI、HarmonyOS 产品工程已删除。
>
> 文档：[`docs/guides/MOBILE_FLUTTER.md`](../docs/guides/MOBILE_FLUTTER.md) · SSOT：[`docs/mobile_tri_platform_ssot.md`](../docs/mobile_tri_platform_ssot.md)

Android、iOS 和 HarmonyOS 候选构建共用 `lib/` 和 `/api/mobile/v1/*` 契约。
`android/`、`ios/` 和 `ohos/` 承载 Runner 和各自的平台通道。

## 本地命令

```bash
cd FHD/mobile-flutter-poc
flutter pub get
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy NO_PROXY=127.0.0.1,localhost flutter test --no-pub
flutter run
```

## HarmonyOS 候选构建

鸿蒙 Runner 复用 CPF-Flutter `3.44.9+ohos-1.0.0-beta` 的 Stage 模板，锁定提交 `744cbb4f08e577787774c04033cc19a9d318d0d2`。SDK 与引擎使用 BSD-3-Clause，模板许可随 `ohos/` 保留。需要 DevEco Command Line Tools `26.0.0.851`、HarmonyOS SDK 26.0.0、JDK 21 和 SQLite 源码生成依赖 Tcl、make。最低运行版本为 HarmonyOS `5.0.5(17)`。[CPF-Flutter](https://gitcode.com/CPF-Flutter/flutter_flutter/tree/3.44.9%2Bohos-1.0.0-beta) · [DevEco 命令行工具](https://developer.huawei.com/consumer/cn/download/command-line-tools-for-hmos)

鸿蒙端复用 `path_provider_ohos 2.2.1`、`shared_preferences_ohos 2.2.0`（BSD-3-Clause），`file_selector_ohos 0.5.0+2`、`url_launcher_ohos 6.3.0`（Apache-2.0），以及 `webview_flutter_harmonyos 4.14.1`、`image_picker_harmonyos 1.2.4`、`package_info_plus_harmonyos 0.0.1`（BSD-3-Clause）和 `flutter_tts_ohos 4.2.5`（MIT）。扫码和凭证分别使用系统 Scan Kit 和 HUKS。离线聊天继续使用 Drift 和 SQLite，鸿蒙构建用 NDK 生成目标架构的 SQLite 库。[CPF 插件](https://gitcode.com/CPF-Flutter/flutter_packages) · [Harmony Flutter Packages](https://github.com/Wayaer/harmony_flutter_packages)

用 CI 中的配置初始化 Flutter OHOS 与 DevEco 环境后，在本目录构建 ARM64 无签名候选包。

```bash
python3 scripts/build_harmony_hap.py \
  --flutter "$FLUTTER_ROOT/bin/flutter" \
  --native-sdk "$DEVECO_SDK_HOME/default/openharmony/native" \
  --output build/xcagi-harmonyos-arm64-unsigned.hap
```

构建同时输出 SHA-256 校验文件。签名、安装和鸿蒙真机验收按发布记录核对。

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
