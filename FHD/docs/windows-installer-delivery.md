# Windows 安装包正式交付流程

统一入口为 `Release Desktop`（根工作流 `fhd-release-desktop.yml`）。

- 单独交付 Windows 安装包：设置 `windows_installer_only=true`、产品版本及完整 `release_sha`。该模式自行构建前后端，不需要 macOS 凭据或跨平台前端 run ID。
- Windows 签名配置齐全时自动签名；五项配置全部缺失时允许生成明确标注 `unsigned` 的安装包。部分配置、签名服务失败、证书不可信、文件被篡改仍阻断，绝不静默降级。
- 保留打包资源安全检查、安装后 SHA/版本/SKU 校验、启动冒烟、卸载保留数据检查。通过后才输出 EXE、SHA-256 和 `delivery-receipt.json`，在工作流 Artifacts 下载；有效期 30 天，应归档后交付客户。
- 未签名文件名带 `-unsigned.exe`，回执明确提示未知发布者/安全提示风险。不要指导客户关闭系统安全防护。
- 单独交付不发布 `latest.yml`，不覆盖全体客户的自动更新指针，不将 CI runner 冒烟等同真实客户 Win10/Win11 验收。
- 统一 Windows/macOS 稳定自动更新仍用原模式，签名、安全扫描及跨端验收要求不变；缺少扫描/共享前端输入会失败，不会绕过门禁。

签名配置：Actions Secrets `ES_USERNAME`、`ES_PASSWORD`、`CREDENTIAL_ID`、`ES_TOTP_SECRET`，Actions Variable `XCAGI_WINDOWS_PUBLISHER_NAME`。
