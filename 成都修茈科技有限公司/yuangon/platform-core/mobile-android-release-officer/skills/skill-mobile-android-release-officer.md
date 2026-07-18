# Android 发版员技能

1. 检查 Flutter 测试、Android Runner、Bundle ID、版本与签名配置。
2. 运行统一 Flutter CI 与 `release-android.yml` 的等价本地门禁。
3. 核对 APK/AAB 签名、版本和真实安装启动结果。
4. 输出结论、证据、风险和下一步；没有真实证据时标记为未验证。

禁止恢复独立 Kotlin 产品实现，禁止暴露签名密钥。
