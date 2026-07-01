# XCAGI 桌面客户端 · 干净构建链（v10）

替代自 v7 起损坏的 FHD 桌面打包链：在干净仓 `xcagi-modstore` 内，用标准 `electron-builder` 出**真·可安装** v10 安装包。

- 精简客户端：Electron 外壳加载 XCAGI 工作台 Web 面（`XCAGI_DESKTOP_URL`，默认 `https://xiu-ci.com/market/`）。
- 版本恒 `10.0.0`（全产品线 v10 锁）。
- 产物名对齐下载 SSOT：`XCAGI-Personal-Setup-10.0.0-x64.exe`。
- 桌面壳内点击安装包下载时走原生保存对话框，默认保存到用户 Downloads，不写安装目录或应用目录。
- Windows 安装包为用户级安装（`asInvoker` + `allowElevation=false`），避免下载后安装时误触发管理员权限路径。

## 本地构建
```bash
cd desktop-shell
npm install
npm run dist:win      # 产物在 desktop-shell/dist/
```

## 签名构建

正式 Windows 发布使用 Azure Artifact Signing。先设置：

```text
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_TRUSTED_SIGNING_ENDPOINT
AZURE_TRUSTED_SIGNING_ACCOUNT
AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE
```

可选设置 `XCAGI_WINDOWS_PUBLISHER_NAME`，默认 `成都修茈科技有限公司`；如果 Azure 证书 Subject 使用英文/拼音法定名，用证书 Subject 里的公司名。

然后构建：

```bash
XCAGI_PRODUCT_SKU=personal XCAGI_REQUIRE_WINDOWS_SIGNING=1 npm run dist:win
XCAGI_PRODUCT_SKU=enterprise XCAGI_REQUIRE_WINDOWS_SIGNING=1 npm run dist:win
```

## CI 构建
`.github/workflows/build-desktop.yml`（`workflow_dispatch`，windows-latest）→ 产物上传为 artifact `xcagi-desktop-win`。
构建成功后由运维下载并经部署密钥 SSH 上传到服务器 `/var/www/update/releases/stable/personal/` 并刷新 `latest.yml`。

## 后续
原生能力（本地 Python 后端、ASR/TTS、离线 SKU）可逐步迁移到本链，替换 web-wrapper 主进程逻辑；mac/android target 在同 workflow 增加矩阵即可。
