# Runbook：iOS 发版员

1. 在 `FHD/mobile-flutter-poc/` 运行 `flutter pub get`、`flutter test` 和无签名 iOS 构建。
2. 核对 `ios/Runner` 的 Bundle ID、entitlements、版本号和 AppIcon。
3. 证书与 profile 统一由 `fastlane match` 管理，禁止另建仓内证书脚本或提交密钥。
4. 通过 `release-ios.yml` 构建 IPA 并上传 TestFlight；只有明确授权时才提交 App Review。
5. 保留 archive/IPA、Bundle ID、版本/构建号、profile、证书摘要和上传日志证据。

缺少 `APPLE_TEAM_ID`、match 仓库、证书/profile 或 App Store Connect API Key 时应停止发布，
明确报告缺口。不得回退到独立 SwiftUI 产品工程。
