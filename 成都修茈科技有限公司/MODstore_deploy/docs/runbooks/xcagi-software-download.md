# XCAGI 工作台「软件下载」公网交付

## 页面行为（`SoftwareDownloadView.vue`）

- 构建时注入 `VITE_XCAGI_DOWNLOAD_VERSION`（默认 `8.1.0`）、`VITE_XCAGI_DOWNLOAD_BASE_URL`。
- 下载页为 **个人版 / 企业版** 两卡；点击 Windows / macOS / Android：通过隐藏 `<a download>` 跳转到  
  `{BASE}/{personal|enterprise}/{XCAGI-*-Setup|*-mac-x64.dmg|*-Android-*.apk}`。
- 仅 SKU 非法时才会 `alert`，不会出现「敬请期待」占位。
- **Android APK** 不在该 Vue 页直链；由内部分发或应用商店提供，产物路径见主仓 `FHD/docs/guides/MOBILE_ANDROID_STORE_COMPLIANCE.md`（`release/packages-v*/personal|enterprise/`）。

## 服务器 / COS 路径（与前端 `VITE_XCAGI_DOWNLOAD_BASE_URL` 一致）

COS 桶 `xiuci-website-1374207682`（成都）对象前缀：

```
xcagi-v8.1.0/{personal,enterprise}/XCAGI-*-Setup-8.1.0-x64.exe
xcagi-v8.1.0/{personal,enterprise}/XCAGI-{Personal|Enterprise}-8.1.0-mac-x64.dmg
xcagi-v8.1.0/{personal,enterprise}/XCAGI-{Personal|Enterprise}-8.1.0-mac-arm64.dmg
```

下载页会按访客 Mac 架构（Apple Silicon / Intel）自动选择对应 `.dmg`；测试可用 `?macArch=arm64` 或 `?macArch=x64`。

公网下载基址（market 构建注入）：

```
https://xiu-ci.com/xcagi-v8.1.0
```

nginx（`xiu-ci.com`）将 `/xcagi-v8.1.0/` alias 到本机安装包目录（与 COS 目录结构一致，CDN 接入前由 CVM 出文件）：

```
/var/www/update/releases/stable/{personal,enterprise}/
```

旧路径 `/releases/stable/offline/` 仅作历史只读，**勿再上传**新版本。旧路径 `/releases/stable/` 根下其它结构仍可用时按现网为准。

## 公网检测命令

```bash
# 域名 DNS 未切到本机时，HTTPS 会失败或 403（旧 IP）
curl -sI https://update.xcagi.com/releases/stable/personal/XCAGI-Personal-Setup-8.1.0-x64.exe
curl -sI https://update.xcagi.com/releases/stable/enterprise/XCAGI-Enterprise-Setup-8.1.0-x64.exe

# 本机文件（Host 或 IP 直链，HTTP）
curl -sI -H "Host: update.xcagi.com" http://119.27.178.147/releases/stable/personal/XCAGI-Personal-Setup-8.1.0-x64.exe
curl -sI -H "Host: update.xcagi.com" http://119.27.178.147/releases/stable/enterprise/XCAGI-Enterprise-Setup-8.1.0-x64.exe

# 临时 HTTPS（xiu-ci.com 同机 alias，已配置）
curl -sI https://xiu-ci.com/releases/stable/personal/XCAGI-Personal-Setup-8.1.0-x64.exe
curl -sI https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-Setup-8.1.0-x64.exe
```

## 下载慢（~100 KB/s、654MB 需 1～2 小时）

根因：`dl.xiu-ci.com` 若仍 **A 记录到 CVM**，走单机出站带宽（常 1～3 Mbps）。  
**解决办法**：安装包上传 COS + `dl.xiu-ci.com` 改 **CDN CNAME**，见 [`deploy/docs/runbooks/xcagi-download-cdn.md`](../../deploy/docs/runbooks/xcagi-download-cdn.md) 与脚本 `deploy/scripts/sync-xcagi-releases-to-cos.sh`。

## 推荐运维顺序

1. **DNS**：`update.xcagi.com` A 记录 → `119.27.178.147`（勿指向欠费/旧机 `170.33.12.185`）。
2. **HTTPS（update 子域）**：`certbot certonly --nginx -d update.xcagi.com` 或扩展现有 `xiu-ci.com` 配置后 `nginx -t && systemctl reload nginx`。
3. **前端**：生产 `.env` 设 `VITE_XCAGI_DOWNLOAD_VERSION=8.1.0`、`VITE_XCAGI_DOWNLOAD_BASE_URL=https://update.xcagi.com/releases/stable`（或继续用 `https://xiu-ci.com/releases/stable` 作过渡）。
4. **重建 market**（见下）。

发版全流程见主仓 `FHD/docs/guides/RELEASE_TWO_SKUS.md`。

## 重建 market

在 `MODstore_deploy` 目录：

```bash
# Docker
docker compose --profile app build market
docker compose --profile app up -d market

# 或本地
cd market && npm ci && npm run build
```

构建参数来自根目录 `.env` 的 `VITE_XCAGI_*`（`docker-compose.yml` 已传 `build.args`）。

## 勿与 MODstore /market/ 部署混用

| 变更类型 | 只动 | 部署后检查 |
|----------|------|------------|
| COS / 安装包加速 | `/var/www/update/`、`deploy/nginx/snippets/xcagi-cos-alias.inc.conf` | `curl -sI https://xiu-ci.com/xcagi-v8.1.0/personal/...` 与 `.../enterprise/...` |
| MODstore 工作台 | `MODstore_deploy/market/dist`、`deploy/nginx/snippets/market-static.inc.conf` | `bash deploy/scripts/post-deploy-check.sh` + 浏览器只开 `https://xiu-ci.com/market/` |

**禁止**：将官网根目录 `index.html`（含 `site-header`、`./main.js`）复制到 `market/dist/`。  
**禁止**：在 `^~ /market/assets/` 上对 `alias` 使用 `try_files` 回退到 `index.html`（缺失 chunk 会返回 HTML，触发 `Unexpected token '<'`）。

Nginx 片段同步（CVM）：

```bash
bash /root/成都修茈科技有限公司/deploy/scripts/sync-nginx-xiu-ci-snippets.sh
```

每次改 Nginx / 部署 market / 调整 COS alias 后：

```bash
bash /root/成都修茈科技有限公司/deploy/scripts/post-deploy-check.sh
```

检查项摘要：

- `market/dist/index.html` 含 `index-t4QjOg3z.js`，不含 `site-header`
- `curl -sI` 本机：`/main.js`、`/market/assets/index-*.js` 为 `application/javascript`
- `/var/www/update/releases/stable/personal/` 与 `.../enterprise/` 安装包存在
- `systemctl is-active modstore`

## market lazy chunk 404（EdgeOne Pages 返回 HTML）

若 `/market/assets/*.js` 的 `Server: edgeone-pages` 且 body 为 `<!DOCTYPE html>`，见 [`deploy/docs/runbooks/dns-edgeone-to-cvm.md`](../../deploy/docs/runbooks/dns-edgeone-to-cvm.md)：解绑 Pages / 改 DNS / 或上传完整 `market/dist` 到 Pages 的 `market/` 目录。
