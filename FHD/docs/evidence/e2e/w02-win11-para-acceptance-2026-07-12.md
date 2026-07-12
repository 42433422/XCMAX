# W-02 Win11 真机验收（DevFleet / Para · 2026-07-12）

> **通道**：DevFleet `devfleet_run_remote_command`（日志标题走排比 Para）  
> **设备**：`5fdd29c4-9140-48fa-a28b-ab5db375201f` · Win32 · ROG Zephyrus G16  
> **OS**：Windows 11 · Build **26200** · AMD64 · 15.6GB RAM  
> **包**：CDN `XCAGI-Enterprise-Setup-10.0.0-x64.exe` · size **213823976** · `buildSha=3f00c87b…`  
> **安装目录**：`%LOCALAPPDATA%\\Programs\\XCAGI\\`  
> **证据根**：`FHD/docs/evidence/e2e/w02-win11-para-20260712/`  
> **录屏**：`rec/w02-acceptance.gif` — **FAIL / 不可签字**（画面几乎静止；见下方「录屏复核」）  
> **截图**：`shots/` 仅作定格参考，**不替代**动态验收录屏

## 网络备注

- 默认 `Invoke-WebRequest` / `curl` 因 **CRYPT_E_REVOCATION_OFFLINE** 失败  
- 改用 `curl.exe --ssl-no-revoke` 后 CDN 下载成功（TCP 443 到 `xiu-ci.com`/`119.27.178.147` 本就通）

## 验收矩阵（Win11 列）

| # | 用例 | 结果 | 说明 |
|---|------|------|------|
| 1.1 | 下载安装包 | **PASS** | `latest.yml` + setup.exe；`SIZE_OK=True` |
| 1.2–1.4 | 静默安装 | **PASS** | `Start-Process setup.exe /S` · `INSTALL_EXIT=0` |
| 1.7 | SmartScreen | **PARTIAL** | 静默安装未弹出；未人工双击观察 |
| 2.1–2.2 | 启动 / health | **PASS** | 重装后 `REHEALTH=healthy v=10.0.0`（约 4 轮轮询，&lt;60s） |
| 2.4 | SKU | **PASS** | `product-sku.json` → enterprise |
| 2.5 | 端口 17500 | **PASS** | LISTENING |
| 3.1 | 登录 | **PASS** | `xcagi-enterprise-demo` + `account_kind=enterprise` |
| 3.3 | ERP API | **PASS** | `/api/orders` `/api/materials` 200 |
| deliverable | 交付状态 | **PASS** | `deliverable=true` · `blockers=0` · mods=13（安装前冒烟） |
| 4.4 | Ed25519 feed | **PASS** | 公网 `latest.yml` 含 `signature: ed25519:`（本机 Mac 公钥可验；Win 侧已拉取 yml） |
| 3.8/4.7/5.x | 长跑/回滚/卸载 | **SKIP** | 短冒烟未覆盖 |

## 结论

**命令冒烟（安装/health/登录/ERP）PASS；录屏证据 FAIL，不能当 UI 真机走查签字。**  
DevFleet 仅 1 台 Windows，**无独立 Win10** → W-01 仍空。

## 录屏复核（2026-07-12 晚）

| 版本 | 帧数 | 唯一帧 | 有运动帧跃迁 | 结论 |
|------|------|--------|--------------|------|
| v1 置前窗口 | 45 | 7 | 7/44（median diff=0） | **FAIL** 定格 |
| v2 点击/打字 | 62 | 12 | 6/61（median diff=0） | **FAIL** 仍几乎不动 |

根因：Para 远程会话里 GDI 能抓到桌面，但自动化点击未造成可持续的 UI 变化；把「有 gif 文件」当成「录屏过关」是错误结论。  
**下一步**：须在可见交互下重录（浏览器翻页 / 真机人工走查），运动门禁建议：唯一帧 ≥15 且运动跃迁 ≥15。

## 命令 ID（Para 日志）

- `773fb627-…` 机器画像  
- `d64494b9-…` 已装包启动冒烟  
- `4329b721-…` CDN `--ssl-no-revoke` 下载 + 静默安装 + 复验 health  
- `16853a60-…` / `ac7db585-…` GDI 桌面帧录屏（v2 置前 XCAGI）

## 媒体索引

见 `w02-win11-para-20260712/05-media-index.txt`。大文件（`.gif` / `.mp4` / `.zip`）已 gitignore，不提交仓库。
