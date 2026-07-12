# M-01 本机 macOS 真机验收（2026-07-12）

> **机器**：Mac16,10 · arm64 · macOS 26.3 (25D125) · 24GB · Gatekeeper assessments enabled  
> **包**：CDN `https://xiu-ci.com/releases/stable/enterprise/XCAGI-10.0.0-mac-arm64.dmg`  
> **buildSha**：`3f00c87b…` · `version=10.0.0` · Developer ID + notarization stapled  
> **证据根**：`FHD/docs/evidence/e2e/m01-mac-local-20260712/`  
> **录屏**：`rec/m01-acceptance.mov`（约 180s / 67MB，不入库）  
> **截图**：`shots/01–05-*.png`

## 验收矩阵（macOS 列）

| # | 用例 | 结果 | 证据 |
|---|------|------|------|
| 1.1 | 下载安装包 | **PASS** | `01-download.txt` / `01-sha512.txt` size+sha512 与 yml 一致 |
| 1.2 | 打开 DMG | **PASS** | `02-attach.txt` · `shots/02-dmg-mounted.png` |
| 1.3 | 安装到 Applications | **PASS** | `ditto` → `/Applications/XCAGI.app`（adhoc 旧包已备份为 `.bak-m01-20260712`） |
| 1.4 | 安装完成 | **PASS** | Dock/进程可见；`05-process-exists.txt=true` |
| 1.5 | 临时卷卸载 | **PASS** | `hdiutil detach` 成功 |
| 1.6 | Gatekeeper | **PASS** | `02-spctl.txt` / `02-spctl-execute.txt` → `accepted` · `Notarized Developer ID` · stapler OK |
| 2.1 | 启动 | **PASS** | `health_ready_sec=10`（≤60s） |
| 2.2 | health | **PASS** | `03-health.json` status=healthy · version=10.0.0 · neuro.running=true |
| 2.3 | 前端窗口 | **PASS** | `shots/03-launched.png` / `04-ui-focused.png`；进程 XCAGI 存在 |
| 2.4 | SKU | **PASS** | `product_sku=enterprise` · `03-product-sku.json` |
| 2.5 | 端口 17500 | **PASS** | `xcagi-bac` LISTEN 17500 |
| 2.6 | 麦克风权限 | **SKIP** | 本轮未触达 TCC 弹窗 |
| 2.7 | 托盘 | **PARTIAL** | 进程在；未单独断言菜单项 |
| 3.1 | 登录 | **PASS** | `xcagi-enterprise-demo` / `Demo@2026` + `account_kind=enterprise`；admin 入口亦通 |
| 3.2 | AI 对话 | **PARTIAL** | 常见 `/api/chat` 405；若干 AI 路径 403；需 UI 内对话补测 |
| 3.3 | ERP API | **PASS** | `/api/orders` `/api/materials` 200（cookie/token 会话） |
| 3.4 | 文件上传 | **SKIP** | 未跑 UI 上传 |
| 3.5 | 语音 | **SKIP** | 依赖 2.6 |
| 3.6 | 诊断包 | **PASS** | `05-support-bundle.zip` HTTP 200 · 61893 bytes（session cookie） |
| 3.7–3.9 | 窗口/长跑/锁屏 | **SKIP** | 短冒烟未覆盖 |
| 3.10 | 移动配对 | **PARTIAL** | `/api/auth/qr/issue` 404（可能路径变更）；未联手机 |
| 4.1/4.4 | 更新 feed + Ed25519 | **PASS** | 公网 `latest-mac.yml` HTTP 200 · `04-ed25519.txt=PASS` |
| 4.2–4.3/4.5–4.8 | 发现新版本/回滚 | **SKIP** | 当前已是线上同版本，无更高版本可升；回滚未故意破坏 |
| 5.x | 卸载 | **SKIP** | 保留本机已装公证包供继续用；adhoc 备份仍在 |

## 结论

**M-01 本机 macOS（arm64）技术冒烟：可签字为「安装+启动+Gatekeeper+交付状态+登录+ERP API+诊断包+更新验签」PASS。**

未勾满清单中的长跑/回滚/语音/真机扫码等项 → 记 **PARTIAL 技术签**，不阻塞「本机 mac 发布面可用」，但整表「全部 ✅」仍需补测 + Win10/Win11。

## 媒体索引

见 `05-media-index.txt`。大文件（`.mov` / `.dmg` / `.zip`）已 gitignore，不提交仓库。
