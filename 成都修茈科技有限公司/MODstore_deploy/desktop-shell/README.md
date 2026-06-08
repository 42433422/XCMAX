# XCAGI 桌面客户端 · 干净构建链（v10）

替代自 v7 起损坏的 FHD 桌面打包链：在干净仓 `xcagi-modstore` 内，用标准 `electron-builder` 出**真·可安装** v10 安装包。

- 精简客户端：Electron 外壳加载 XCAGI 工作台 Web 面（`XCAGI_DESKTOP_URL`，默认 `https://xiu-ci.com/market/`）。
- 版本恒 `10.0.0`（全产品线 v10 锁）。
- 产物名对齐下载 SSOT：`XCAGI-Personal-Setup-10.0.0-x64.exe`。

## 本地构建
```bash
cd desktop-shell
npm install
npm run dist:win      # 产物在 desktop-shell/dist/
```

## CI 构建
`.github/workflows/build-desktop.yml`（`workflow_dispatch`，windows-latest）→ 产物上传为 artifact `xcagi-desktop-win`。
构建成功后由运维下载并经部署密钥 SSH 上传到服务器 `/var/www/update/releases/stable/personal/` 并刷新 `latest.yml`。

## 后续
原生能力（本地 Python 后端、ASR/TTS、离线 SKU）可逐步迁移到本链，替换 web-wrapper 主进程逻辑；mac/android target 在同 workflow 增加矩阵即可。
