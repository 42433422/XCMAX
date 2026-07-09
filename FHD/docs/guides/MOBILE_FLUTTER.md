# XCAGI 移动客户端（Flutter 主线）

> **状态（2026-07-07）**：**Flutter 为唯一移动交付主线**（`FHD/mobile-flutter-poc`）。  
> **归档中**：`FHD/mobile-android/`（Kotlin）、`FHD/mobile-ios/`（SwiftUI）仅保留兼容构建与行为参照，**禁止新增产品流程**。

> **SSOT**：[`mobile_tri_platform_ssot.md`](../mobile_tri_platform_ssot.md) · OpenAPI [`contracts/openapi.json`](../../contracts/openapi.json)

## 路径与职责

| 路径 | 状态 | 说明 |
|------|------|------|
| `FHD/mobile-flutter-poc/` | **主线** | Android + iOS 统一 UI；新功能、UX 修复、发版优先在此 |
| `FHD/mobile-android/` | **归档中** | 迁移参照；仅 P0 安全/构建修复，不做新 Tab/新流程 |
| `FHD/mobile-ios/` | **归档中** | 同上；TestFlight 维护可选，默认不再扩功能 |
| `FHD/mobile-harmony/` | **冻结** | 参照 [`mobile_tri_platform_ssot.md`](../mobile_tri_platform_ssot.md) |

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
2. Android/iOS 原生仅当 Flutter 缺平台能力（推送、相机、Keychain 等）时补 **platform channel**，不在原生层复制业务 UI。
3. 行为对齐：归档期内可读 `mobile-android` 已验证路径；**以 OpenAPI + FastAPI 为准**，不以原生旧实现为长期 SSOT。
4. 产品验收：[`guides/PRODUCT_POLISH_CHECKLIST.md`](PRODUCT_POLISH_CHECKLIST.md) 移动端落点以 `mobile-flutter-poc/lib/` 为准。

## 发版

- **Android APK / iOS IPA**：由 Flutter 工程产出（`flutter build apk` / `flutter build ipa`）。
- 根仓 CI：`fhd-release-android.yml` / `fhd-release-ios.yml` 在 Flutter 发版链就绪前仍可能指向归档原生目录；切换发版 SSOT 须同 PR 更新 workflow 与 [`VERSION.md`](../../VERSION.md) 锚点说明。

## 相关文档

- 归档原生 Android：[`MOBILE_ANDROID.md`](MOBILE_ANDROID.md)（历史）
- 账号与端权限：[`account_system_ssot.md`](../account_system_ssot.md) §0
- 产品线：[`specs/product-lines-3-plus-2.md`](../../../specs/product-lines-3-plus-2.md)
