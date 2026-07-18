# Runbook：Android 发版员

1. 在 `FHD/mobile-flutter-poc/` 运行 `flutter pub get`、`flutter test`、`flutter build apk`。
2. 核对 `android/app/build.gradle.kts` 的 Bundle ID、版本和 release signing。
3. 通过 `ci-mobile-flutter.yml` 验证统一代码，通过 `release-android.yml` 产出签名 APK/AAB。
4. 在真实设备或模拟器验证安装、启动、登录、深链和平台通道。
5. 发布前保留 APK/AAB、签名证书摘要、版本号和 workflow 日志证据。

故障时不得回退到独立 Kotlin 产品工程；应在 Flutter 业务代码或 Flutter Android Runner
中修复。密钥缺失或签名不一致时停止发布并请求人工补齐。
