# XCAGI 商店桌面壳（历史兼容，不用于稳定版发布）

此目录保留 AI 员工商店 Web 壳兼容代码，但不再承担 XCAGI 稳定版安装包构建或发布。企业桌面稳定版的唯一发布入口是根仓 `Release Desktop`（源文件：`FHD/.github/workflows/release-desktop.yml`，发布文件：`.github/workflows/fhd-release-desktop.yml`）。

- 精简客户端：Electron 外壳加载 XCAGI 工作台 Web 面（`XCAGI_DESKTOP_URL`，默认 `https://xiu-ci.com/market/`）。
- 对外稳定产品版本为 `1.0.0.1`，Electron 工具链包版本为 `1.0.0`。
- 本地构建产物仅用于兼容性调试，不得上传到 `/releases/stable/`。
- 桌面壳内点击安装包下载时走原生保存对话框，默认保存到用户 Downloads，不写安装目录或应用目录。
- Windows 安装包为用户级安装（`asInvoker` + `allowElevation=false`），避免下载后安装时误触发管理员权限路径。

## 本地构建
```bash
cd desktop-shell
npm install
npm run dist:win      # 产物在 desktop-shell/dist/
```

## 正式发布

不得在本目录新增或恢复 `build-desktop.yml`。正式 Windows 签名、macOS 公证、企业版制品上传、统一 manifest 和下载验真必须由 `Release Desktop` 一次完成；个人版按 `specs/product-lines-3-plus-2.md` 保持冻结。

## 后续
如需恢复此壳的产品化或个人版发布，必须先修改产品线 SSOT 并重新评审发布边界。
