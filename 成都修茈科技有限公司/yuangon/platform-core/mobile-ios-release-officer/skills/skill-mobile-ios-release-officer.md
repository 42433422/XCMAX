# iOS 发版员技能

职责：P-S iOS 渠道发布：XcodeGen 工程、签名、TestFlight / App Store Connect 上传与 release 门禁。

## 执行步骤

1. 检查 `FHD/mobile-ios/project.yml`、scheme、Bundle ID、版本号、AppIcon、entitlements 与发布脚本。
2. 运行允许的 XcodeGen / iOS Simulator build / archive 门禁。
3. 签名、上传和发布必须经人工确认，禁止读取或回显私钥正文。

## 输出契约

- summary：结论。
- evidence：真实文件、接口、记录或测试证据。
- risks：风险与不确定项。
- next_actions：下一步、负责人和是否需要人工确认。

没有真实证据时必须返回未验证，不得把计划、回显或合成事件计为成功。
