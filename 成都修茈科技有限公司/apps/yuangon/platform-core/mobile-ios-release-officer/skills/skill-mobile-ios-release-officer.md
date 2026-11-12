# iOS 发版员技能

1. 检查 Flutter iOS Runner、Bundle ID、entitlements、版本、AppIcon 和无签名构建。
2. 核对 `fastlane/Matchfile`、`Fastfile`、match 仓库与 App Store Connect API Key 配置。
3. 通过 `release-ios.yml` 产出 IPA 并上传 TestFlight；只有明确授权才提交审核。
4. 输出真实 archive/IPA、profile、证书摘要、版本号和上传日志证据。

禁止恢复独立 SwiftUI 产品实现，禁止暴露证书和密钥。
