# Flutter Android 渠道指南

本文是 Flutter Android 渠道构建、签名和发布的 SSOT。

Android 与 iOS 共用 [`FHD/mobile-flutter-poc/`](../../mobile-flutter-poc/) 的 Flutter 业务代码。
`android/` 目录只承担 Flutter Runner、Manifest、平台通道、签名和打包，不是独立产品实现。

当前交付等级：**实验骨架·非签约级**。自动化测试和构建通过不能替代真机二维码/深链、
真实审批流、推送与正式签名安装证据；这些证据全部闭环后才能提升对外等级。

## 本地验证

```bash
cd FHD/mobile-flutter-poc
flutter pub get
flutter test
flutter build apk --debug
```

调试 APK 位于 `build/app/outputs/flutter-apk/app-debug.apk`。

## 正式发布

正式 APK/AAB 统一由 `FHD/.github/workflows/release-android.yml` 构建。签名材料仅通过
GitHub Actions Secrets 注入：

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

流水线会拒绝缺失签名、debug 证书、Bundle ID 或版本不一致的产物。发布后必须保留
workflow 日志、APK/AAB、签名证书摘要和真实安装启动证据。

## 边界

- 唯一移动实现：`FHD/mobile-flutter-poc/lib/`
- Android Runner：`FHD/mobile-flutter-poc/android/`
- 统一 CI：`FHD/.github/workflows/ci-mobile-flutter.yml`
- Android 发布：`FHD/.github/workflows/release-android.yml`
- 禁止恢复独立 Kotlin 产品工程或重复 Android CI。
