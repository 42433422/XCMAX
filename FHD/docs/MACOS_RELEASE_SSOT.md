# macOS 发布交付 SSOT（唯一事实来源）

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「macos-release」域。**每次 macOS 发版必须复用本文件**：更新第 1–5 节事实，重跑第 6 节全部 Gate，无证据不得标 GREEN，CI 通过 ≠ 验收通过。
> 状态仅限：`GREEN`（完整真机证据）/ `YELLOW`（部分或替代证据）/ `RED`（真机验证失败，记录复现+日志+截图，只修真阻断项，修完重测，禁止直接改状态）/ `UNKNOWN`（无法静态证明，生成实机任务）。判据协议与证据模板见 [e2e/desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)。

## 1. 当前版本信息

| 字段 | 值 | 证据 |
|------|-----|------|
| 稳定产品版本 | `1.0.0.5` | [VERSION.md](../VERSION.md)（版本域 SSOT；PR #1972 `54325894c` 合入，2026-09-18） |
| 工具链兼容版本 | `1.0.0`（npm/Electron/Apple 三段映射；已知显示差异见 §9-0 Runbook 口径） | 同上 |
| 发布 SKU | `enterprise`（personal 冻结） | [download_release.json](../config/download_release.json) |
| 发布产物 gitSha | `54325894cc6e3fc2becfcbc98697a099310d9420` | latest-mac.yml `buildSha` + 真机已装包 build-info `gitSha` + DMG 内 build-info 三向一致（2026-09-18 实测，§6 G1/G3） |
| manifest git_sha | `54325894cc6e3fc2becfcbc98697a099310d9420`（与构建 SHA 一致，公网复验 2026-09-18） | [manifest.json](https://xiu-ci.com/xcagi-v1.0.0.5/manifest.json) `generated_at=2026-09-18T09:57:25Z`（该 manifest `release_ready=false`，为发布脚本显式契约） |
| 构建时间 | build-info builtAt `2026-09-18T07:39:47.185Z` | 官方包 build-info.json（真机已装包 + DMG 内文件双向锚定一致） |
| 安全扫描对 | `passed=true`，锚定 `54325894c`，blockers 为空 | [scan-pair-verify.json](evidence/e2e/macos-release-1.0.0.5/scan-pair-verify.json)（2026-09-18 复核） |
| release_train 内部流水 | `product_version=1.0.0.5`（=VERSION.md 锚定）；`current=1.0.0.5`（下载中心已切换） | [release_train.json](../config/release_train.json) |
| `release_ready` | `false`（发布脚本 [publish-macos-download-center.sh](../scripts/package/publish-macos-download-center.sh#L68) **显式要求** `release_ready=false`；`download_release.json` `version_lock`/`download_version` 已切 `1.0.0.5`，OTA feed 广播 `productVersion=1.0.0.5` 且真机完成 OTA → 见 §7-13） | download_release.json + [manifest.json](https://xiu-ci.com/xcagi-v1.0.0.5/manifest.json) |

## 2. 构建产物（线上实测）

| 产物 | URL | 大小（字节） | 指纹 |
|------|-----|------------|------|
| DMG（arm64，官方下载） | `https://xiu-ci.com/xcagi-v1.0.0.5/enterprise/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg` | **298,366,428** | SHA256 `6d127de45f58d86ebfb015b4216be8064bf70321e112bde6da35a2cf92ea0464`（manifest 条目 + 公网回下载实体复算 + HTTP HEAD `content-length` 三证一致；2026-09-18） |
| ZIP（arm64，OTA 载荷） | `https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-1.0.0.5-mac-arm64.zip` | 264,715,517 | SHA256 `5d51fbcbe27b8abe211ca51f8cb80c979d13d4c50c7fdb2901d485fe6f32786d`（**应用内 updater 实际下载实体哈希**）；SHA512 `5yCehH+8DS1kyUmX4yG7uTgbqSuHoSdcZHvs2IFE6Vy6qGOQdZSYJYwuGMMHXh6/kfvvB4+JMn5cyz1+KaXENQ==`（latest-mac.yml，与缓存实体一致；ed25519 签名 `x3rUKDehqd6hMqyOTRt4WWo0pzqkEmJRrbrn8P/oj2YSILekcDiKsXHMx4W7bAmzRBzenXq6lpGao+MdG6jFAw==` 在案） |

**1.0.0.5 交付说明（2026-09-18）**：PR #1972 合入 `54325894c` 后由 [publish-macos-download-center.sh](../scripts/package/publish-macos-download-center.sh) 发布；该脚本**硬断言** `release_ready=false`（L68）并校验远端 DMG sha256 与公网 `content-length`/`latest-mac.yml` 逐字节一致。`download_release.json` 的 `version_lock`/`download_version` 已切 `1.0.0.5`，下载中心与 OTA feed 同版本对齐——**1.0.0.4 的发布面错配（下载中心 1.0.0.3 / feed 1.0.0.4）已消除**。真机闭环见 §6（G3/G8/G9/G10/G11/G12 全 PASS）。

**历史**：1.0.0.3（`4bfb23365c`，release run [34773838698](https://github.com/42433422/XCMAX/actions/runs/34773838698) 构建+签名+公证+扫描对 `passed=true`，2026-09-13）已完成真机全链闭环，其 DMG `288549712a63…`/305,748,094B、ZIP `c2f7c6982519…`/264,518,917B 仍由下载中心提供（`download_version=1.0.0.3`）。1.0.0.2（`6eda2203d`）已发布并完成真机闭环（CVM 恢复处置见 [ota-release-cvm-recovery-20260913.md](evidence/e2e/macos-release-1.0.0.2/ota-release-cvm-recovery-20260913.md)）；其 G7 正式包 bundle 写回归在 1.0.0.3 修复并重测（§6-G7、§7-11）。

## 3. 构建环境

| 字段 | 值 |
|------|-----|
| 构建 CI | GitHub Actions `macos-latest`，workflow [release-desktop-mac-ota.yml](../.github/workflows/release-desktop-mac-ota.yml)（`macos-ota` job） |
| 构建脚本 | `scripts/package/build-installer.sh <version> enterprise`（版本动态读 VERSION.md） |
| 代码签名 | Developer ID Application（Team `G26WSH472M`），证书 `CSC_LINK` secret；hardened runtime；时间戳 `timestamp.apple.com/ts01` |
| 公证 | `build/notarize.cjs`（afterSign），App Store Connect API（`APP_STORE_CONNECT_API_*` secrets） |
| 更新元数据签名 | Ed25519（`XCAGI_UPDATE_ED25519_PRIVATE_KEY`，`scripts/dev/sign_update_metadata.py`），公钥内置于 [desktop-config.ts](../desktop/desktop-config.ts) |
| 发布脚本 | [publish-macos-download-center.sh](../scripts/package/publish-macos-download-center.sh)（DMG 双目录落盘 + 远端 SHA256 核验 + manifest 生成 + latest-mac.yml 验签断言） |

## 4. 下载与更新服务

| 项 | 地址 |
|----|------|
| 官方下载页（版本化） | `https://xiu-ci.com/xcagi-v<version>/enterprise/` |
| 官方 manifest | `https://xiu-ci.com/xcagi-v<version>/manifest.json`（历史兜底 `/releases/stable/manifest.json`） |
| 自动更新 feed（mac） | `https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml` |
| 自动更新 feed（win） | `https://xiu-ci.com/releases/stable/enterprise/latest.yml` |
| 服务器 | nginx 本机直供：`/xcagi-v{version}/` → `/var/www/update/releases/stable/`；dl.xiu-ci.com(COS) 备用待启用 |
| 应用内 feed URL SSOT | [desktop-config.ts](../desktop/desktop-config.ts) `SKU_UPDATE_URL.enterprise` |

## 5. 测试机（当前实跑）

| 字段 | 值 |
|------|-----|
| 机型 / 芯片 | Mac mini (Mac16,10) / Apple M4 (arm64) |
| OS | macOS 26.3 (25D125) |
| 内存 / 可用磁盘 | 24 GB / 70 GB |
| 序列号 | LK7W1TVPX1 |
| 环境性质 | ⚠ **非干净环境**：开发机（有 Xcode/Python/仓库），userData `~/Library/Application Support/XCAGI/` 已有 ~11GB 历史数据与多份旧安装副本；**且与主安装 `/Applications/XCAGI.app`（同 1.0.0.1）共享同一 userData**（含 2026-09-07 同步的 mods 与 986MB 生产库）——G6 attendance 回归即此环境污染与版本错配共同暴露，见 §7-7 |

## 6. Release Gate 状态（2026-09-18 实跑 1.0.0.5 @ `54325894c`；证据目录 [evidence/e2e/macos-release-1.0.0.5/](evidence/e2e/macos-release-1.0.0.5/)）

> **当前结论（2026-09-17 1.0.0.4 真机全链复跑后）：G9 RED 阻断「零干预 OTA」，其余 Gate 全链真机证据齐备。** ① **发布面未闭环**：构建 run [34856380264](https://github.com/42433422/XCMAX/actions/runs/34856380264) **cancelled**、manifest/`download_release.json` 均 `release_ready=false` 且下载中心未切 1.0.0.4（§1、§7-13）。② **OTA 链**：真机 1.0.0.3 应用内发现 1.0.0.4（G8 GREEN）→ 点击「下载更新 → 更新并重新加载」→ ShipIt「Detected this as an install request」→ **181s 无进展（等应用退出）** → 外部干预后 `Installation completed successfully`（G9 子项：入口 PASS / **自动退出 FAIL** / 替换 PASS / **自动重启 FAIL**）→ 数据保留 16 项 15 SAME（G10 PASS）→ 登录/上传/出单 200（G11 PASS）→ **真实整机重启（`kern.boottime` 1789579911→1789626349）后冷启动** health 1.0.0.4/healthy + `PRAGMA quick_check=ok` + mods 62 + 业务出单（G12 PASS）。历史 RED（G7 bundle 写回归）已在 1.0.0.3 修复并重测转 GREEN（§7-11）。

| # | Gate | 状态 | 现有证据 | 缺失证据 | 阻断 | 对应 PR | 下一步 |
|---|------|------|---------|---------|------|---------|--------|
| G1 | 构建（产物+身份） | YELLOW | **1.0.0.5 身份三证齐备（2026-09-18）**：DMG 内 / 已装包 / feed 的 `gitSha=54325894cc6e3fc2becfcbc98697a099310d9420`+`version=1.0.0.5`+`releaseId` 三向一致；`codesign`+`spctl`+`stapler` 全过（§6-G3）；公网 DMG/manifest/feed 复验 200 且 sha256 一致（§2）；**安全扫描对** [35316330641](https://github.com/42433422/XCMAX/actions/runs/35316330641)+[35319093843](https://github.com/42433422/XCMAX/actions/runs/35319093843) 双 success、间隔 36min（≥30min）、均锚定 `54325894c`（[scan-pair-verify.json](evidence/e2e/macos-release-1.0.0.5/scan-pair-verify.json) `passed=true`）；CodeQL main tip `54325894c` success（[35315724549](https://github.com/42433422/XCMAX/actions/runs/35315724549)） | **发布 run [35319932712](https://github.com/42433422/XCMAX/actions/runs/35319932712) cancelled**（2026-09-18T07:32:45Z 起）——产物/feed/manifest 在取消前已落盘（feed releaseDate 07:48:07Z、manifest 09:57:25Z），但 run 内 `verify_security_scan_pair.py` 未执行；`release_ready=false`（发布脚本 [L68](../scripts/package/publish-macos-download-center.sh#L68) 显式契约）。**较 1.0.0.4 改进**：`version_lock`/`download_version` 已切 `1.0.0.5`，下载中心与 feed 版本对齐 | 阻断「正式发布闭环」，不阻断产物可用性 | #1972 | 重跑 release run 走完 run 内门禁（§7-13） |
| G2 | 干净环境安装 | YELLOW | 验收脚本真实下载→SHA256→挂载→安装全链 PASS（历史版本实证）；真机 OTA 安装机制可用（G9） | 非干净机（dev 机+存量数据）；未在全新用户/VM 验证 | 无 | #1870 | 实机任务 T1：干净环境（新账户或 VM）重跑 |
| G3 | macOS 安全项 | GREEN | **1.0.0.5 DMG 原件挂载复核（2026-09-18，[round-20260918-g3-dmg-verify-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g3-dmg-verify-10005.json)）**：`hdiutil verify` **checksum VALID**；DMG 内 `codesign --verify --deep --strict` valid / satisfies Designated Requirement（`com.xcagi.desktop.enterprise`，Team `G26WSH472M`，`Developer ID Application: jialong Li`）；`spctl --assess` **accepted / Notarized Developer ID**；`stapler validate` **worked**；DMG 内 build-info `gitSha=54325894c`/`1.0.0.5`/`builtAt=2026-09-18T07:39:47.185Z`。**陌生客户路径复证**：公网回下载 DMG 298,366,428B 复算 sha256 一致 → `ditto` 装到 `/Applications` → 装后签名同上（[first-install-from-dmg-10005.json](evidence/e2e/macos-release-1.0.0.5/first-install-from-dmg-10005.json)） | — | 无 | — | 下版沿用本目录脚本 |
| G4 | 首次启动 | YELLOW | **1.0.0.4 冷启动实测（2026-09-17 14:26，真实整机重启后）**：health 200 `version=1.0.0.4`/`gitSha=280225ac77ce`、runtime healthy、`PRAGMA quick_check=ok`（[round-20260917-ota2-g12-post-reboot.json](evidence/e2e/macos-release-1.0.0.4/round-20260917-ota2-g12-post-reboot.json)） | 首启 degraded（登录前 LLM_UNAVAILABLE）为预期态（§7-4）；未在干净环境首次启动 | 无 | — | T1 干净环境冷启动 |
| G5 | 登录绑定 | GREEN | **1.0.0.4 真机登录态（2026-09-17）**：API `auth/login` 200 `success=true`（[postinstall-retest](evidence/e2e/macos-release-1.0.0.4/round-20260917-ota2-postinstall-g7-retest.json)）；1.0.0.3 UI 双证（主窗口登录态截图 + 渲染进程认证请求全 200）见 [g5-login-ui-10003.json](evidence/e2e/macos-release-1.0.0.3/g5-login-ui-10003.json) | 1.0.0.4 UI 登录态截图未重拍（本轮以 API 会话 + G11 业务链实证） | 无 | — | 下版补 UI 截图 |
| G6 | Mod / AI 员工加载 | GREEN | **1.0.0.4 实测（2026-09-17）**：`/api/mods` 200 返回 62 mod（attendance-industry v1.0.1 在列）；`/api/employees` 200 catalog；platform shell capabilities 200 `edition=full`（[round-20260917-g0-baseline.json](evidence/e2e/macos-release-1.0.0.4/round-20260917-g0-baseline.json)、[g6-post-ota-10004.json](evidence/e2e/macos-release-1.0.0.4/g6-post-ota-10004.json)） | 干净首装 seed 版 mod 行为随 T1 | 无 | f37372e97 | T1 |
| G7 | 真实业务任务 | GREEN | **1.0.0.4 全链实测两次（2026-09-17 03:16 与 ShipIt 装成后 05:21）**：`POST /api/templates/upload` 200（db:25/db:26）→ 客户查重 400（已存在=数据存活）→ `POST /api/shipment/generate` 200「发货单生成成功」→ xlsx 下载回读 5195B / PK 魔数 / sha256 `f5a0eb248a44…` 与 `99d404a690df…`（[g11-retest](evidence/e2e/macos-release-1.0.0.4/round-20260917-ota2-g11-g7-retest.json)、[postinstall-retest](evidence/e2e/macos-release-1.0.0.4/round-20260917-ota2-postinstall-g7-retest.json)）。历史 RED（1.0.0.2 bundle 写回归）复现+修复记录见 §7-11 | — | 无 | #1922 | — |
| G8 | 更新发现 | GREEN | **1.0.0.4 本轮新证据（2026-09-17 03:21）**：1.0.0.3 应用内检查更新 → `update_available` 事件（19:21:01.305Z，diff 基准 106 行）+ 左下角状态行「可更新 1.0.0.4」角标截图（CDP 渲染视图）；远端 `buildSha=280225ac` ≠ 本机 `4bfb23365c`，未命中同版本抑制分支；缓存包 sha512 == feed sha512（[round-20260917-ota2-g8-discovery.json](evidence/e2e/macos-release-1.0.0.4/round-20260917-ota2-g8-discovery.json)） | — | 无 | #583 | — |
| G9 | 更新安装 | GREEN | **1.0.0.4→1.0.0.5 真机安装链（2026-09-18，[round-20260918-g9-install-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g9-install-10005.json)）**：CDP 真实点击「更新并重新加载」19:09:16 → `install_start` 11:09:26.125Z → 旧主进程 71300 **19:09:32 自行退出（无外部干预、无 SecurityAgent 弹窗）** → ShipIt「Detected this as an install request」19:09:30 /「Beginning installation」/「Installation completed successfully」19:09:32.176 →「Launching new ShipIt … with instructions to launch file:///Applications/XCAGI.app/」→「Successfully launched application」19:09:33.861 → 新主进程 90904 于 19:09:33 启动。**全程约 21 秒零干预**（入口 PASS / 自动退出 PASS / 替换 PASS / 自动重启 PASS）；`ShipItState.plist launchAfterInstallation` 由 `false` → `true`（§7-14 复测通过）。OTA 下载实体 sha256 `5d51fbcb…`/264,715,517B 与官方 ZIP 逐字节一致（[round-20260918-g9-download-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g9-download-10005.json)） | — | 无 | #1930 + §7-14 | — |
| G10 | 数据保留（升级后） | GREEN | **1.0.0.4→1.0.0.5 OTA 前后 digest 比对 + 重启后复算（2026-09-18，[round-20260918-g10-data-retention-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g10-data-retention-10005.json)、[g12](evidence/e2e/macos-release-1.0.0.5/round-20260918-g12-post-reboot-verify-10005.json)）**：8 项口径 `lost=[]`，唯一变化为 DB 正常增长（987,504,640→987,750,400B）；升级前创建的客户行「G11重测客户(勿删)」在 1.0.0.5 上仍判「客户名称已存在」；`PRAGMA quick_check=ok`。历史 1.0.0.2/1.0.0.3/1.0.0.4 三次覆盖/OTA 升级全 PASS | — | 无 | #1870 | — |
| G11 | 更新后重新执行业务 | GREEN | **ShipIt 装成 1.0.0.5 后业务复跑（2026-09-18，[round-20260918-g11-business-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g11-business-10005.json)）**：应用内真实会话复用 200 `SUNBIRD`（user_id=5、permission_count=15、`has_shipment_edit=true`）→ 模板上传 200 → 客户查重命中（数据存活）→ `POST /api/shipment/generate` 200「发货单生成成功」→ xlsx 回读 5199B / PK 魔数 / sha256 复算。**全新安装实例上同链复跑亦 PASS**（[post-fresh-install](evidence/e2e/macos-release-1.0.0.5/round-20260918-g11-business-post-fresh-install-10005.json)）；**重启后 AI 自动复跑亦 PASS**（G12 证据内 `business_retest`） | — | 无 | — | — |
| G12 | 重启 Mac 后核心功能复验 | GREEN | **1.0.0.5 真实整机重启实测（2026-09-18 冷启动，[round-20260918-g12-post-reboot-verify-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g12-post-reboot-verify-10005.json)）**：`kern.boottime` 1789626349→1789731306（Thu 09-17 14:25:49 → Fri 09-18 19:35:06）三证；布防 LaunchAgent 于 21:22:17 自动触发、PASS 后自清理——health 200 `version=1.0.0.5`/`gitSha=54325894cc6e`、`PRAGMA quick_check=ok`、数据 `lost=[]`、mods 15/15 `load_mismatch=false`、会话 200 `SUNBIRD`、业务复跑出单（`发货单_26-0900001A_20260918_212223.xlsx`/5199B/PK 魔数）。**诚实口径**：应用由用户手动打开（产品「开机自启」未启用），不记作产品自动启动 | — | 无 | 本 PR | — |
| G13 | 回滚/恢复 | GREEN | **实机降级演练 PASS（2026-09-12）**：1.0.0.2 候选包 → 1.0.0.1 正式包覆盖安装成功——codesign+spctl accepted、冷启动 0.2s、health PASS、业务数据零丢失。证据 [g13-rollback-20260912.zip](evidence/e2e/macos-release-1.0.0.1/g13-rollback-20260912.zip)、[data-retention](evidence/e2e/macos-release-1.0.0.1/g13-rollback-data-retention.json) | 路径 A（坏更新观察期自动回滚）实机证据 | 无 | — | 路径 A 留待专用验收机（非阻断） |

## 7. 已知偏差与缺陷

1. **~~manifest 与实际产物不符（G1 RED）~~ 已修复（2026-09-11）**：09-04 构建 run 取消导致 manifest 生成步骤未执行，线上 manifest 停在 09-02（#1685、DMG 条目 290,432,409B/`7ab4fdc1…`）与服务器实际 DMG（293,401,820B/`c39bed60…`）不符。修复：在构建 SHA 上建临时分支触发 `Publish macOS Download Center Metadata`（[run 34577330930](https://github.com/42433422/XCMAX/actions/runs/34577330930) 全绿），manifest 重生成后与实测一致，重测 G1 转 GREEN。教训：OTA run 取消会留下"feed 已更新、manifest 未生成"的漂移；发版 Runbook 第 2 步后必须核验 manifest `generated_at` 与构建 SHA。
2. **`/Applications/XCAGI.app` spctl 报 `a sealed resource is missing or invalid`**：本地副本被改或本地构建签名不完整；与发布产物无关（以验收实例对新鲜 DMG 的 spctl 结果为准，见 G3 GREEN）。
3. x64 dmg 在 download_release.json 声明但 manifest 无条目（§2）。
4. **首启 `status=degraded`（LLM_RUNTIME_UNAVAILABLE）为登录前预期态，非缺陷**：`app/runtime_integrity.py` `neuro_degraded_reasons()` 在无任何已配置 LLM provider 时上报该原因；provider 配置来自登录后的 modstore 会话/API key（`registry.resolve()`），干净机器登录前必然为 false；前端 [runtimeHealthPresentation.js](../frontend/src/components/sidebar/runtimeHealthPresentation.js) 对此有专用文案（"部分 AI 能力未就绪…在设置的模型服务中确认"）。登录绑定后复测应转绿（并入 T2）。
5. **本机代理拦截 127.0.0.1 致健康检查假阴性（测试环境坑，已修复工具）**：系统代理把 `curl http://127.0.0.1:17500` 路由到代理返回 502；`acceptance-macos.sh` 健康检查已加 `--noproxy '*'`（2026-09-11）。人工复核命令务必带 `--noproxy '*'`；CI/干净机无代理不受影响。
6. 仓库根 `release/VERSION`（=0.0.1）为 legacy 暂存目录，不在 version 域锚点内；版本域锚点 `FHD/release/VERSION`=1.0.0.2 已验证同步（`verify_version_anchors.py` OK，2026-09-13）。
7. **G6 缺陷（1.0.0.1）：attendance-industry mod HTTP 路由注册失败**：userData 同步版 mod（2026-09-07）import `app.mod_sdk.customer_features`，该模块由 main f37372e97 引入、晚于构建提交 99854233，bundle 缺失 → 每次启动 `Failed to register routes for attendance-industry`，`/attendance/*`（capabilities/policy/rules/convert-upload/download）全部不可用；bundle 自带 seed 版 mod 为旧版不受影响（干净首装待 T1 验证）。修复已在 main（f37372e97），1.0.0.1 不含。证据 [g6-attendance-route-regression.txt](evidence/e2e/macos-release-1.0.0.1/g6-attendance-route-regression.txt)。
8. **G7 阻断（1.0.0.1）：发货单模板导入链路断裂**：shipped 后端缺 `template_create.py` 路由（main b97073acc 引入，晚于构建提交）→ 前端 `templates/upload|analyze|create` 全部 405；`/api/excel/template/save` 要求源文件预置于 base_dir（无 UI 途径）；bundle 无 legacy 兜底模板 → `shipment/generate` 恒 TEMPLATE_NOT_FOUND。**1.0.0.1 用户无法完成发运单真实业务**。修复已在 main（b97073acc），1.0.0.1 不含。证据 [g7-template-import-broken.txt](evidence/e2e/macos-release-1.0.0.1/g7-template-import-broken.txt)。**2026-09-12 根因修正定性**：1.0.0.2 候选包（含 b97073acc+f37372e97）重测 upload 仍 405——`upload|analyze` 此前仅存在于 env 门禁 legacy_gap（`app/legacy/routes/legacy_gap.py`，需 `XCAGI_REGISTER_LEGACY_ROUTES=1` 才挂载，且自述已被 xcagi_compat 取代），xcagi_compat 实际只承接 create → 迁移留洞。修复：`template_api.py` 默认挂载 upload/analyze/progress（登录+租户隔离与 create 同套鉴权）+ 默认 app openapi 回归测试（`test_default_factory_registers_template_upload_and_analyze`）。
9. **本地构建环境三坑（2026-09-12 实录，供复现候选包）**：① 本机 Node 20.18 < desktop engines 要求的 22.12，`@electron/get` 5.x 为 ESM-only，`npm rebuild electron` 在 Node 20 下必失败——需 Node ≥22.12（本机用官方 tarball 解至 /tmp 临时供 PATH）；② `build-installer.sh` 在 `set -euo pipefail` 下 `xattr -cr desktop/node_modules/electron/dist` 于目录缺失时退出码 1 直接杀死脚本（且 electron postinstall 未跑过时 dist 必缺失）——需先 `npm rebuild electron` 成功再构建；③ 本地 shell 若带 `CI` 环境变量，`notarize.cjs` 按 CI 严格模式在无公证密钥时硬失败——本地构建需 `env -u CI`。产物为 Developer ID 签名+时间戳但**未公证**（spctl rejected），仅可作验收候选，不得冒充发布产物。
10. **~~build-info.json `version` 字段与产品版本不同源~~（1.0.0.2 已对齐）**：1.0.0.1 健康检查的 `version` 读 Python 包版本，落后产品号；1.0.0.2 官方包 build-info `version=1.0.0.2` 已与产品版本一致。验收采证口径仍以 releaseId+gitSha 对齐为准。
11. **G7 正式包新断点（1.0.0.2，6eda2203d）：模板上传分析写入签名 bundle 内 `_internal/` 报 Permission denied**：`analyzer.py` `_analyze_template_with_upload_inner` 把上传 Excel 存到 `os.path.dirname(os.path.dirname(__file__)) / uploads/templates`——源码态解析为 `app/uploads/templates`，但打包态 `__file__` 位于 `XCAGI.app/Contents/Resources/backend/_internal/app/...`（签名 bundle 内只读），写入报 `Permission denied`；此前候选包 v2（9a4a06bc4）登录态 upload 200 是因为该候选包经 `XCAGI_DATA_DIR`/未公证等环境差异未命中 bundle 只读路径，T4 OTA 后正式包实测暴露。修复（#1922）：改用 `get_upload_dir()`（打包感知：源码态落仓库、打包态落 `~/Library/Application Support/XCAGI/uploads/templates`），与路由策略文件重定向（#1905）同一原则。证据 [g7-retest-post-ota.txt](evidence/e2e/macos-release-1.0.0.2/g7-retest-post-ota.txt)、[g7-retest-login-prefix.txt](evidence/e2e/macos-release-1.0.0.2/g7-retest-login-prefix.txt)。**已于 1.0.0.3 修复并真机重测转 GREEN（§6-G7）。教训：候选包（未公证、环境特异）验证结果不能外推为正式包结论，正式包上线后必须重跑核心业务链。**
12. **G9 应用内一键安装缺陷（1.0.0.2→1.0.0.3 实机复现）：点击「安装更新」后应用不退出、ShipIt 无限等待**：`installUpdate → autoUpdater.quitAndInstall(false, true)` 走 Squirrel `[NSApp terminate]` 路径，该路径**不触发 `before-quit`**，`app.isQuitting` 仍为 false 时主窗口 close 处理（window-manager.ts）`event.preventDefault()+hide()` 拦截退出，terminate 被取消 → 应用存活、ShipIt 检测到 install request 后无限等待（ShipIt_stderr.log 14755 行「Detected this as an install request」无后续直至手动退出）。复现：真机 1.0.0.2 → 应用内更新 1.0.0.3 → 下载完成 → 点击安装 → 应用不退出；时间线见 [t4-ota-10003.log](evidence/e2e/macos-release-1.0.0.3/t4-ota-10003.log)。本次发布以「手动退出应用」（用户可完成操作）完成安装闭环（G9 YELLOW 定级依据）；修复 PR [#1930](https://github.com/42433422/XCMAX/pull/1930)：`desktop-install-update.ts` 在 `quitAndInstall` 前预置 `app.isQuitting = true`（含回归测试），**下版 OTA 复测应用内一键安装无需手动退出后方可转 GREEN（任务 T9）**。
13. **~~1.0.0.4 发布面未闭环~~ 已在 1.0.0.5 消除（2026-09-18）**：1.0.0.4 曾出现「下载中心仍发 1.0.0.3 DMG、OTA feed 已广播 1.0.0.4」的版本错位（`version_lock`/`download_version` 未同步）。1.0.0.5 已按发布脚本契约同步至 `1.0.0.5`，下载中心与 feed 同版本对齐（§1/§2）。**残留同类风险**：发布 run [35319932712](https://github.com/42433422/XCMAX/actions/runs/35319932712) 仍为 cancelled，run 内 `verify_security_scan_pair.py` 未执行；扫描对本身已独立通过（§6-G1）。
14. **~~G9 自动重启缺陷~~ 已修复并复测转 GREEN（2026-09-18）**：1.0.0.3→1.0.0.4 首次暴露「ShipIt 替换完成但不重启」（`ShipItState.plist launchAfterInstallation=false`）。1.0.0.4→1.0.0.5 专项复测：点击后 **21 秒内**完成 自动退出 → 替换 → 自动重启，`launchAfterInstallation` 观测为 `true`，ShipIt 全程日志齐备（Detected → Beginning → completed → Launching → Successfully launched）。证据 [round-20260918-g9-install-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g9-install-10005.json)。
15. **OTA 未覆盖 SecurityAgent 管理员授权分支（保真度声明，2026-09-17）**：本轮夹具 `/Applications/XCAGI.app` 属主为 `a4243342:staff`（由降级 DMG `ditto` 复制而来），`/Applications` 为 `root:admin drwxrwxr-x` 且用户属 `admin` 组 → ShipIt 判定 `isAdminRightsRequired=false`，**不触发管理员授权弹窗**。真实客户以 admin 身份把 app 拖入 `/Applications` 时属主为 `root:wheel`，可能走授权弹窗分支；**该分支本轮未覆盖**，需在专用验收机补测（见 §8-T10）。声明见 [round-20260917-ota2-g9-preflight.txt](evidence/e2e/macos-release-1.0.0.4/round-20260917-ota2-g9-preflight.txt)。
16. **~~B6：OTA 替换后旧 backend 进程残留~~ 本轮未复现（2026-09-18）**：1.0.0.3→1.0.0.4 曾观测旧 backend 占 17500 致 health 短暂报旧版本。1.0.0.4→1.0.0.5 本轮：旧主进程 71300 随安装自行退出、新进程 90904 启动，health 立即为 `1.0.0.5`/`54325894cc6e`（G12 重启后复算仍一致），**未观测到残留**。保留观察项：若再现，按原建议「启动时比对 bundle 版本 > 运行中 backend 版本则强杀重启」处理。

## 8. 实机验收任务（UNKNOWN 项 → 待执行）

| ID | 任务 | Gate | 环境 |
|----|------|------|------|
| T1 | 全新 macOS 用户账户（或干净 VM）跑 `acceptance-macos.sh`，验证无开发依赖 | G2/G4 | 干净机 |
| T2 | ~~真机登录绑定，截图+日志~~ **已完成（2026-09-14）**：1.0.0.3 原生主窗口登录态截图（[t2-logged-in-main-window-1.0.0.3.png](evidence/e2e/macos-release-1.0.0.3/t2-logged-in-main-window-1.0.0.3.png)）+ 渲染进程认证请求全 200（[g5-login-ui-10003.json](evidence/e2e/macos-release-1.0.0.3/g5-login-ui-10003.json)）+ API 登录 200（g6 探针）；G5 转 GREEN | G5 | 任意真机 |
| T3 | ~~真机完成 1 单真实业务~~ **已完成（2026-09-12 登录态全链）**：upload 200 入库 → generate 200 出单（发货单_26-0900001A_20260912_200002.xlsx，record_id=1）；证据 g7-full-chain-success-20260912.json | G7 | 任意真机 |
| T4 | ~~旧版真机→检查更新→下载→安装→复验~~ **已完成两次真机全链**：① 2026-09-13 1.0.0.1→1.0.0.2（G8/G9 GREEN、G10 PASS）；② 2026-09-14 1.0.0.2→1.0.0.3（G8 GREEN、G9 YELLOW—退出拦截缺陷手动退出配合、G10 PASS、G11 业务复跑出单）；证据 [t4-ota-10003.log](evidence/e2e/macos-release-1.0.0.3/t4-ota-10003.log)、g8/g9/g10 证据 JSON | G8/G9/G10/G11 | 真机 |
| T5 | ~~跨版本覆盖升级数据保留~~ **已完成（2026-09-14 OTA 路径）**：1.0.0.2→1.0.0.3 digest 比对全保留（G10-④/⑤） | G10 | 真机 |
| T6 | ~~重启 Mac 后复验~~ **已完成（2026-09-14 14:04）**：真实重启后 health 1.0.0.3→登录/上传/出单全链 200→mods/employees 200→数据基线零丢失（G12 GREEN）。教训：该机 /private/tmp 重启即清，复验脚本必须存证据目录（本 PR 已入库）+ `/Users/Shared/xcagi-t6-tools/` 备份 | G12 | 真机 |
| T7 | ~~下版本发后重测 G6/G7~~ **已完成（1.0.0.3 实机重测 2026-09-14）**：G6——mods 200（62 个）+ attendance-industry v1.0.1 路由注册修复生效（capabilities 200，[g6-post-ota-10003.json](evidence/e2e/macos-release-1.0.0.3/g6-post-ota-10003.json)）；G7——upload 200 入库 + generate 200 出单（[g7-retest-10003.json](evidence/e2e/macos-release-1.0.0.3/g7-retest-10003.json)） | G6/G7 | 真机（1.0.0.3） |
| T8 | ~~回滚/恢复演练~~ **已完成（2026-09-12 路径 B 降级）**：1.0.0.2→1.0.0.1 覆盖安装 PASS（签名 accepted、数据零丢失、health PASS），证据 g13-rollback-20260912.*；路径 A（坏更新观察期自动回滚）留待专用验收机 | G13 | 真机 |
| T9 | ~~1.0.0.4→1.0.0.5 OTA 专项复测（G9 由 RED 转 GREEN 的唯一路径）~~ **已完成（2026-09-18）**：① 自动退出 PASS（无外部干预）；② ShipIt 自动替换 PASS；③ 自动重启 PASS——三项全过，G9 转 GREEN（§6-G9）。证据 [round-20260918-g9-install-10005.json](evidence/e2e/macos-release-1.0.0.5/round-20260918-g9-install-10005.json) | G9 | 真机（1.0.0.5 feed） |
| T10 | SecurityAgent 管理员授权分支补测：以 `root:wheel` 属主装 app（真实客户拖入 `/Applications` 路径）触发 ShipIt `isAdminRightsRequired=true`，验证授权弹窗与安装结果（§7-15） | G9 | 专用验收机（或临时改属主） |
| T11 | ~~发布面闭环~~ **1.0.0.5 已达成版本对齐（2026-09-18）**：`version_lock`/`download_version` 与 feed 同为 `1.0.0.5`，错位消除（§7-13）。**残留**：发布 run cancelled → `release_ready=false` 仍为脚本契约，run 内门禁未执行（§6-G1） | G1 | CI + 公网复验 |

## 9. 发版复用 Runbook（每次 macOS 发版照此执行）

0. **版本口径提醒（2026-09-14 收口审计定稿）**：运行期版本判定**以 health 端点 + build-info（version/releaseId/gitSha 三锚定）为准**（口径见 §7-10）；其余显示值为映射，出现不一致先改锚点再发布，不改 health 口径。已知显示差异：① npm/Electron/Dart pub/Apple MARKETING_VERSION 三段 `1.0.0` 为工具链映射（VERSION.md 已声明等价关系）；② mobile `profileVersionText` 硬编码 `(12)` 与实际 `versionCode=10`/pubspec `1.0.0+10` 不同步（锚点校验不覆盖 build number，显示以 `versionName` 四段为准，(12) 待下版同步）。
1. `VERSION.md` 升版 → `version_sync.py --apply` + `verify_version_anchors.py`；
2. CI `release-desktop-mac-ota` 构建+签名+公证+发布 → `publish-macos-download-center` 更新下载中心/manifest/feed（发版 Runbook 第 2 步后必须核验 manifest `generated_at` 与构建 SHA，防"feed 已更新、manifest 未生成"漂移，见 §7-1）；
3. 真机跑 `bash FHD/scripts/package/acceptance-macos.sh --version <v>`（下载→SHA256→签名→安装→冷启动→健康检查）；跨版本数据保留走 `--overwrite-upgrade`（T5）；
4. 有新版本时真机走完整 OTA 链（G8→G12），按协议 4.1–4.2 判定；
5. 证据按版本入 `FHD/docs/evidence/e2e/macos-release-<版本>/`（截图/日志/JSON 与脚本），Gate 结论回填本文件 §6，不另建验收记录文档；发版前回归两个历史 RED：`POST /api/templates/upload` 非 405（G7，见 §7-8）；启动日志无 attendance 路由注册 ERROR（G6，见 §7-7）；
6. 回填本文件 §1–§6；全部 Gate 无 RED 且 G1–G4 GREEN、G5–G13 无 UNKNOWN 遗留方可宣布闭环；
7. RED：只修阻断项→重测→重写状态，禁止直接改状态。
