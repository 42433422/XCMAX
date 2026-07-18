# XCAGI 移动客户端（Flutter Android+iOS）

本文是 Flutter 移动端日常开发与统一交付入口的 SSOT。

`FHD/mobile-flutter/` 是唯一移动端实现与交付主线。独立 Kotlin、SwiftUI、HarmonyOS
产品工程和重复 Android CI 已删除；历史只能从 Git 取证。

## 目录边界

| 路径 | 职责 |
|---|---|
| `lib/` | Android/iOS 共用业务、UI、状态、API client |
| `android/` | Flutter Runner、Manifest、平台通道、签名 |
| `ios/` | Flutter Runner、entitlements、平台通道、签名 |
| `fastlane/` | match、TestFlight、App Store 发布 |

## 本地验证

```bash
cd FHD/mobile-flutter
flutter pub get
flutter test
flutter build apk --debug
flutter build ios --debug --no-codesign
```

后端契约统一使用 `/api/mobile/v1/*` 与 `FHD/contracts/openapi.json`，设计 token 使用
`FHD/config/mobile_design_tokens.json`。

## CI 与发版

- 统一 CI：`fhd-ci-mobile-flutter.yml`（Flutter test + Android APK + iOS no-codesign build）
- Android：`fhd-release-android.yml`
- iOS/TestFlight/App Store：`fhd-release-ios.yml`
- 修改实现源后运行：`python scripts/dev/publish_ci_workflows_to_root.py`

禁止恢复独立原生产品工程、重复 Android CI，或把业务逻辑放进平台 Runner。
