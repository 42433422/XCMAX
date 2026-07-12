# W-02 Win11 真机验收（DevFleet / Para · 2026-07-12）

> **通道**：DevFleet `devfleet_run_remote_command`（日志标题走排比 Para）  
> **设备**：`5fdd29c4-9140-48fa-a28b-ab5db375201f` · Win32 · ROG Zephyrus G16  
> **OS**：Windows 11 **家庭中文版** · Build **26200** · AMD64  
> **包**：CDN `XCAGI-Enterprise-Setup-10.0.0-x64.exe` · size **213823976** · `buildSha=3f00c87b…`  
> **安装目录**：`%LOCALAPPDATA%\\Programs\\XCAGI\\`  
> **证据根**：`FHD/docs/evidence/e2e/w02-win11-para-20260712/`  
> **录屏**：`rec/w02-acceptance.gif` — **运动门禁 PASS（v4 自动走查录屏）**  
> **截图**：`shots/k{00..04}.jpg`

## 网络 / 远程桌面备注

- CDN：须 `curl.exe --ssl-no-revoke`（`CRYPT_E_REVOCATION_OFFLINE`）
- **Windows App / RDP 不可用**：本机为 Home，`fDenyTSConnections=1`，3389 未监听
- **ToDesk** 两边已装；人工已连上设备码 `432435835` 后，Agent 自动边驱边录

## 验收矩阵（Win11 列）

| # | 用例 | 结果 | 说明 |
|---|------|------|------|
| 1.1 | 下载安装包 | **PASS** | `latest.yml` + setup.exe |
| 1.2–1.4 | 静默安装 | **PASS** | `/S` · `INSTALL_EXIT=0` |
| 1.7 | SmartScreen | **PARTIAL** | 静默未弹 |
| 2.1–2.2 | 启动 / health | **PASS** | `status=ok` · 17500 LISTENING |
| 2.4 | SKU | **PASS** | enterprise |
| 3.1 | 登录 | **PASS** | API 企业演示账号 |
| 3.3 | ERP API | **PASS** | orders/materials 200 |
| 录屏 | 动态证据 | **PASS（运动门禁）** | v4：unique=26 · motion=16/99 |

## 结论

**命令冒烟 PASS。**  
**录屏运动门禁 PASS（v4）**：ToDesk 已连的交互桌面上，Agent 自动置前 XCAGI、Edge 翻页 `/login|/erp|/orders|/materials`、SendKeys，同时 GDI 抓 100 帧。  
**诚实边界**：仍是自动化驱动 + GDI 合成，不是人手全程点完的产品签字片；但相对 v3（纯 MoveWindow）更接近真实 UI 变化。Home 版无法用 Windows App/RDP。

## 录屏复核

门禁：`unique≥15` 且 `motion_transitions≥15`。

| 版本 | 方法 | 唯一帧 | 运动跃迁 | 结论 |
|------|------|--------|----------|------|
| v1–v2 | 置前/盲点 | 7–12 | &lt;15 | FAIL |
| v3 | MoveWindow 强制运动 | 43 | 25 | PASS（通道证明） |
| **v4** | **ToDesk 在线 + Edge/XCAGI 自动走查** | **26** | **16/99** | **PASS** |

## 媒体索引

见 `w02-win11-para-20260712/05-media-index.txt`。GIF/zip gitignore；`shots/` 可入库。
