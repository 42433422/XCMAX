# XCAGI 移动客户端（Flutter · 对外仅 Android）

> **状态（2026-07-14）**：**对外发版仅 Android**，工程主线为 `FHD/mobile-flutter-poc/`（Flutter）。  
> **已归档**：原生 `mobile-ios` / `mobile-harmony` → [`archive/mobile/`](../../../archive/mobile/README.md)。  
> **归档中**：`FHD/mobile-android/`（Kotlin）仅作迁移参照。

> **SSOT**：[`mobile_tri_platform_ssot.md`](../mobile_tri_platform_ssot.md) · OpenAPI [`contracts/openapi.json`](../../contracts/openapi.json)

## 路径与职责

| 路径 | 状态 | 说明 |
|------|------|------|
| `FHD/mobile-flutter-poc/` | **主线** | 对外 Android APK；新功能、UX、发版只在此 |
| `FHD/mobile-android/` | **归档中** | Kotlin 参照；仅 P0 安全/构建修复 |
| `archive/mobile/mobile-ios/` | **已归档** | 原 SwiftUI；禁止新增产品流程 |
| `archive/mobile/mobile-harmony/` | **已归档** | 原 ArkTS；禁止新增产品流程 |
| `FHD/mobile-ios/` · `FHD/mobile-harmony/` | **指针 README** | 仅指向 archive，避免旧链接误导 |

## 本地开发

```bash
cd FHD/mobile-flutter-poc
flutter pub get
flutter test
flutter run
```

## 后端契约

- 移动 API：`/api/mobile/v1/*`（`mobile_api.py` + `mobile_api_extensions.py`）
- 禁止新增 `/api/flutter/*` 或手写与 OpenAPI 漂移的 DTO
- 设计 token：[`config/mobile_design_tokens.json`](../../config/mobile_design_tokens.json)

## 迁移规则

1. **新页面 / 路由 / 状态 / 错误文案** → 只改 Flutter。
2. 行为对齐：可读 `mobile-android` 已验证路径；**以 OpenAPI + FastAPI 为准**。
3. 产品验收：[`guides/PRODUCT_POLISH_CHECKLIST.md`](PRODUCT_POLISH_CHECKLIST.md) 以 `mobile-flutter-poc/lib/` 为准。

## 发版

- **对外：仅 Android APK**（`flutter build apk`）。
- 打包脚本：`FHD/scripts/mobile/stage-release-packages.sh`（默认 `--android-only`）。
- 根仓 CI：`fhd-ci-mobile-flutter.yml` / `fhd-release-android.yml` / `android-build.yml`。
- 改 workflow 后：`python scripts/dev/publish_ci_workflows_to_root.py`。

## 相关文档

- 归档原生 Android：[`MOBILE_ANDROID.md`](MOBILE_ANDROID.md)（历史）
- 账号与端权限：[`account_system_ssot.md`](../account_system_ssot.md) §0
- 产品线：[`specs/product-lines-3-plus-2.md`](../../../specs/product-lines-3-plus-2.md)
