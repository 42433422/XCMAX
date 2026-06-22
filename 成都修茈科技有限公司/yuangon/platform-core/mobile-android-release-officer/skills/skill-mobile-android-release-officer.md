# Android 发版员技能

职责：P-S Android 渠道构建与发布：ci-mobile-android.yml、release-android.yml、APK/AAB 产出与 smoke。

## 执行步骤

1. 检查 Gradle 变体、签名占位、版本号和 APK/AAB 产物。
2. 运行允许的构建与单测门禁。
3. 发布或签名动作必须经人工确认，禁止暴露密钥。

## 输出契约

- summary：结论。
- evidence：真实文件、接口、记录或测试证据。
- risks：风险与不确定项。
- next_actions：下一步、负责人和是否需要人工确认。

没有真实证据时必须返回未验证，不得把计划、回显或合成事件计为成功。
