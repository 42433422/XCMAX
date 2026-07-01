# XCAGI Windows 代码签名发布流程

XCAGI Windows 安装包使用 `desktop-shell` 的 Electron Builder 配置构建。默认本地构建允许未签名；正式发布必须设置 `XCAGI_REQUIRE_WINDOWS_SIGNING=1` 并通过 Azure Artifact Signing 签名。

Windows 安装包固定为用户级安装：`win.requestedExecutionLevel=asInvoker`，`nsis.perMachine=false`，`nsis.allowElevation=false`。下载后不应要求管理员权限；若出现 “未知发布者” 或 SmartScreen 风险提示，优先检查 Authenticode 签名，而不是改回管理员安装。

## Azure 侧准备

1. 完成 Azure Trusted Signing 账号的企业身份验证。
2. 创建 Code Signing Account 和 Certificate Profile。
3. 创建可供 GitHub Actions 使用的 App Registration / service principal。
4. 给该 service principal 授权访问对应的 Code Signing Account / Certificate Profile。

## GitHub Actions 必填 Secrets

```text
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_TRUSTED_SIGNING_ENDPOINT
AZURE_TRUSTED_SIGNING_ACCOUNT
AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE
```

## GitHub Actions 可选 Variable

```text
XCAGI_WINDOWS_PUBLISHER_NAME
```

`XCAGI_WINDOWS_PUBLISHER_NAME` 默认是 `成都修茈科技有限公司`。如果 Azure 证书 Subject 使用英文/拼音法定名，把这个值改成证书 Subject 里实际出现的公司名，并同步配置到 GitHub Actions Repository variable。

## 构建

```powershell
cd 成都修茈科技有限公司/MODstore_deploy/desktop-shell
npm ci
$env:XCAGI_REQUIRE_WINDOWS_SIGNING = "1"
$env:XCAGI_PRODUCT_SKU = "personal"
npm run dist:win
```

## 验签

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-windows-signature.ps1 `
  -Path dist/XCAGI-Personal-Setup-10.0.0-x64.exe
```

验签必须显示 `Status=Valid`，签名主体必须包含 `XCAGI_WINDOWS_PUBLISHER_NAME`。

## 桌面壳内下载

`desktop-shell` 的 preload 暴露 `window.xcagiDesktop.downloadFile({ url, filename })`。软件下载页在 Electron 内点击 Windows / macOS 安装包时会调用该桥，由主进程弹系统保存对话框，默认保存到用户 Downloads，避免渲染页直接写文件或误写安装目录。浏览器环境仍使用隐藏 `<a download>`。

## 上传前检查

确认文件、blockmap、latest.yml 同批生成并上传到：

```text
/var/www/update/releases/stable/personal/
/var/www/update/releases/stable/enterprise/
```

上传后至少检查：

```bash
curl -I https://xiu-ci.com/xcagi-v10.0.0/personal/XCAGI-Personal-Setup-10.0.0-x64.exe
curl -r 0-0 -I https://xiu-ci.com/xcagi-v10.0.0/personal/XCAGI-Personal-Setup-10.0.0-x64.exe
```
