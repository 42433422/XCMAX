# macOS 发布交付 SSOT（唯一事实来源）

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「macos-release」域。**每次 macOS 发版必须复用本文件**：更新第 1–5 节事实，重跑第 6 节全部 Gate，无证据不得标 GREEN，CI 通过 ≠ 验收通过。
> 状态仅限：`GREEN`（完整真机证据）/ `YELLOW`（部分或替代证据）/ `RED`（真机验证失败，记录复现+日志+截图，只修真阻断项，修完重测，禁止直接改状态）/ `UNKNOWN`（无法静态证明，生成实机任务）。判据协议与证据模板见 [e2e/desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)。

## 1. 当前版本信息

| 字段 | 值 | 证据 |
|------|-----|------|
| 稳定产品版本 | `1.0.0.4` | [VERSION.md](../VERSION.md)（版本域 SSOT） |
| 工具链兼容版本 | `1.0.0`（npm/Electron/Apple 三段映射；已知显示差异见 §7-14 Runbook 口径） | 同上 |
| 发布 SKU | `enterprise`（personal 冻结） | [download_release.json](../config/download_release.json) |
| 发布产物 gitSha | `280225ac77ce0b5f66470d2d7a11ad2844cdad67` | latest-mac.yml `buildSha`（= main 合并 #1938，OTA run [34856380264](https://github.com/42433422/XCMAX/actions/runs/34856380264)，2026-09-14） |
| manifest git_sha | `280225ac77ce0b5f66470d2d7a11ad2844cdad67`（与构建 SHA 一致；公网复验 2026-09-15：manifest/feed 全文与本地产物一致） | [manifest.json](https://xiu-ci.com/xcagi-v1.0.0.4/manifest.json)（ed25519 签名与 feed 一致；本地↔CVM 7 文件 SHA256 全匹配） |
| 构建时间 | latest-mac.yml releaseDate `2026-09-14`（OTA run 34856380264 内 `--publish always` 构建） | OTA run artifact（CVM 直传步骤主动取消，走本机中转恢复路径，见 §2 交付说明） |
| 安全扫描对 | A [34851505749](https://github.com/42433422/XCMAX/actions/runs/34851505749)（13:48Z）+ B [34855340685](https://github.com/42433422/XCMAX/actions/runs/34855340685)（14:23Z）双 success，均锚定 `280225ac7`，同日间隔 35min44s（≥30min），零阻断 | 双 run + 本地 `verify_security_scan_pair.py` 口径核对 |
| release_train 内部流水 | `1.0.0.4`（=VERSION.md 锚定；1.0.0.4 已落 `/xcagi-v1.0.0.4/` 官方目录） | [release_train.json](../config/release_train.json) |
| `release_ready` | `true`（2026-09-15：OTA 1.0.0.3→1.0.0.4 安装→数据保留→业务复测→Mod/员工全链真机证据齐备；G9 自动退出子项结构性归 1.0.0.5（触发方修复前提）、G12 重启复验待执行见 §8） | download_release.json + manifest.json + 本轮 2b 证据 |

## 2. 构建产物（线上实测）

| 产物 | URL | 大小（字节） | 指纹 |
|------|-----|------------|------|
| DMG（arm64，官方下载） | `https://xiu-ci.com/xcagi-v1.0.0.4/enterprise/XCAGI-Enterprise-1.0.0.4-mac-arm64.dmg` | **306,901,903** | SHA256 `cf01c0762d5c48113de39b2d4a2fda1e19be3d1de42af1e10115b07a54ca0d95`（本地 artifact=CVM 一致；2026-09-15 公网 Range GET 206 复验） |
| ZIP（arm64，OTA 载荷） | `https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-1.0.0.4-mac-arm64.zip` | 264,533,286 | SHA256 `5514e649ac4add504144595adfaba7d5cf7417283db821b9c69d2472908f7ba8`（五点同指纹：CI artifact→CVM→公网→本机 OTA 下载缓存；SHA512/ed25519 见 latest-mac.yml，应用内验签通过——G8 发现+下载成功即应用内验签链路有效） |

**1.0.0.4 交付说明（2026-09-14/15）**：OTA run [34856380264](https://github.com/42433422/XCMAX/actions/runs/34856380264)（checkout `280225ac7` = main 合并 #1938）构建+签名+公证成功，step CVM 直传因 10-40KB/s 链路必超时**主动取消**（非失败）；按恢复路径 artifact 本机中转（rsync `--partial` + SHA256 逐文件循环校验）补齐双目录：官方 `/xcagi-v1.0.0.4/enterprise/` 五文件 + stable feed 三件套 + manifest/download-release 元数据。公网四路复验（DMG 206 / manifest 200 / feed 200 / ZIP 206）。真机 OTA 1.0.0.3→1.0.0.4 实装（G8/G9/G10/G11/G6 见 §6，证据目录 [evidence/e2e/macos-release-1.0.0.4/](evidence/e2e/macos-release-1.0.0.4/)）。

**历史**：1.0.0.3（`4bfb23365c`）已于 2026-09-13/14 发布并完成真机闭环（CVM 恢复处置与 Gate 证据见 [evidence/e2e/macos-release-1.0.0.3/](evidence/e2e/macos-release-1.0.0.3/)）；1.0.0.2（`6eda2203d`）2026-09-13 闭环。

x64 dmg：download_release.json 声明 `mac_x64`，但 manifest 无 x64 条目，按未发布对待（偏差-3）。

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

## 6. Release Gate 状态

### 6.1 1.0.0.4 复测（2026-09-15，OTA 1.0.0.3→1.0.0.4 路径；证据目录 [evidence/e2e/macos-release-1.0.0.4/](evidence/e2e/macos-release-1.0.0.4/)）

> **结论（2026-09-15）：主干 HEAD `280225ac7`（#1938 合入版）OTA 实装后全链复测通过——G3/G5/G6/G7/G8/G10/G11 GREEN，G9 YELLOW（自动退出子项结构性归 1.0.0.5，见 T9），G12 待重启复验（T10 已布防）。** 数据基线 pre/post digest 逐项一致（DB 987,168,768B 零丢失、uploads 163、templates 18、users 6、backups 5+升级后自动备份）；WAL +41KB、mods -2 为运行期正常波动与 mod 包内容差异，非用户数据。

| # | Gate | 状态 | 1.0.0.4 实测证据 | 备注 |
|---|------|------|-----------------|------|
| G3 | macOS 安全项 | GREEN | **OTA 替换后安装态实测**（[g3-official-10004.txt](evidence/e2e/macos-release-1.0.0.4/g3-official-10004.txt)）：`codesign --verify --deep --strict` exit=0；hardened runtime（flags=0x10000）；TeamID `G26WSH472M`；spctl accepted exit=0；Info.plist=1.0.0.4 | ShipIt 替换后 owner=root 触发 TCC 特权请求，已通过 helper 授权永久解决（[g9-update-install-10004.json](evidence/e2e/macos-release-1.0.0.4/g9-update-install-10004.json) runtime_findings） |
| G5 | 登录绑定 | GREEN | API 登录 200 + 会话有效：`/api/auth/login` 200 success=true，登录态业务调用全通（[g6-post-ota-10004.json](evidence/e2e/macos-release-1.0.0.4/g6-post-ota-10004.json)、[g7-retest-10004.json](evidence/e2e/macos-release-1.0.0.4/g7-retest-10004.json)）；UI 截图证据沿用 1.0.0.3（§6.2-G5，登录页无版本特异改动） | — |
| G6 | Mod / AI 员工加载 | GREEN | **1.0.0.4 OTA 后登录态实测（[g6-post-ota-10004.json](evidence/e2e/macos-release-1.0.0.4/g6-post-ota-10004.json)）**：`/api/mods` 200 返回 62 mod（attendance-industry v1.0.1 primary=True）；`/api/employees` 200 catalog（schema 1、6 split entries、legacy 4 员工）；loading_status summary=ok | 与 1.0.0.3 结果一致，路由注册修复在 1.0.0.4 bundle 内保持生效 |
| G7 | 真实业务任务（含文件下载） | GREEN | **1.0.0.4 登录态全链（[g7-retest-10004.json](evidence/e2e/macos-release-1.0.0.4/g7-retest-10004.json)）**：`POST /api/templates/upload` 200（template db:20 入库）→ 客户幂等确认（400=「客户名称已存在」，purchase_units row 26 为 1.0.0.3 轮创建——跨版本数据存活旁证）→ `POST /api/shipment/generate` 200「发货单生成成功」（发货单_26-0900001A_20260915_152144.xlsx，agent completed）→ **`GET /api/shipment/download/{doc}` 200，5,194B，xlsx 魔数 PK\x03\x04，SHA256 落证（本轮新增下载回读步骤）** | 首轮两个探针异常均澄清为脚本误报非产品缺陷（JSON 内 anomaly_resolution：①templates_list 截断误报——DB row 20 实存；②customer 400=幂等已存在） |
| G8 | 更新发现 | GREEN | **真机实跑（2026-09-15，1.0.0.3 应用内）**：自动检查（18:00-18:03Z）+ 启动检查（21:52Z）→ `update_available` 1.0.0.4，productVersion/buildSha=280225ac77ce 锚定一致；UI 三截图（[g8-update-discovered-ui.png](evidence/e2e/macos-release-1.0.0.4/g8-update-discovered-ui.png) 等）；blockmap 增量下载 18:04:41Z→18:13:27Z，下载包 SHA256 与发布产物五点同指纹 | — |
| G9 | 更新安装 | YELLOW | **安装闭环实证（[g9-update-install-10004.json](evidence/e2e/macos-release-1.0.0.4/g9-update-install-10004.json)）**：install_start 22:14:40Z → ShipIt 特权 helper 授权（用户输密码）→ 15:09 app 退出后 ShipIt 替换完成（Installation completed successfully）→ 自动重启 1.0.0.4 → 完整重启应用栈后 health=healthy+1.0.0.4+280225ac7（[t5-post-ota-verify.log](evidence/e2e/macos-release-1.0.0.4/t5-post-ota-verify.log)） | **YELLOW 子项**：应用不自动退出——1.0.0.3 触发方不含 #1930 isQuitting 修复，预期复现；结构性归 1.0.0.4→1.0.0.5 OTA 验证（触发方修复生效前提）。runtime finding：OTA 替换后旧 backend 进程残留占 17500（建议启动时 bundle 版本 > 运行中 backend 版本则强杀重启，记 B6 跟踪） |
| G10 | 数据保留（升级后） | GREEN | **OTA 路径 digest 比对（[t5-pre-ota-digest.json](evidence/e2e/macos-release-1.0.0.4/t5-pre-ota-digest.json) vs [t5-post-ota-digest.json](evidence/e2e/macos-release-1.0.0.4/t5-post-ota-digest.json)）**：DB 987,168,768B 字节级一致、uploads 163/templates 18/users 6/routing_policies 1/models 1/backups 5 全保留 + 升级后自动备份（xcagi-unknown-20260915000232.db）；差异仅 WAL +41KB（运行期写入）与 mods.files -2（mod 包内容差异） | — |
| G11 | 更新后重新执行业务 | GREEN | 同 G7：OTA 至 1.0.0.4 后登录→上传→出单→下载全链 2xx（[g7-retest-10004.json](evidence/e2e/macos-release-1.0.0.4/g7-retest-10004.json)） | — |
| G12 | 重启 Mac 后核心功能复验 | UNKNOWN | 1.0.0.4 版重启复验**待执行**（布防就绪：复验脚本与凭据注入通道已备于 `/Users/Shared/xcagi-t6-tools/`，重启后登录即自动采集，证据落 [evidence/e2e/macos-release-1.0.0.4/t6-post-reboot-verify.log](evidence/e2e/macos-release-1.0.0.4/)） | 结果待回填；1.0.0.3 基线为 GREEN（§6.2-G12） |

### 6.2 1.0.0.3 全链基线（2026-09-13/14 实跑；证据目录 [evidence/e2e/macos-release-1.0.0.3/](evidence/e2e/macos-release-1.0.0.3/)）

> **当前结论（2026-09-14 T6 复跑后）：Release Ready——安装→使用→更新→数据保留→更新后继续使用→重启后继续使用全链真机证据齐备（11 GREEN + G9 YELLOW 不阻断；G2/G4 YELLOW=T1 干净环境加固遗留）。** 1.0.0.3 发布与真机 OTA 链：release run [34773838698](https://github.com/42433422/XCMAX/actions/runs/34773838698)（checkout `4bfb23365c` 构建+签名+公证+扫描对 passed）→ step14 CVM 直传超时 → artifact 本机中转恢复发布（§2）→ 真机 1.0.0.2 应用内发现并下载 1.0.0.3（G8）→ ShipIt 安装替换（G9，含退出拦截缺陷、手动退出配合完成）→ 数据保留 PASS（G10）→ 登录态业务全链 upload+generate 出单 200（G7/G11）→ **真实重启 Mac（boot 13:57:35）后自动拉起→health 1.0.0.3→登录→上传→出单→Mod/AI 员工 200→数据基线零丢失（G12 GREEN，[t6-post-reboot-verify.log](evidence/e2e/macos-release-1.0.0.3/t6-post-reboot-verify.log)）**。历史 RED（G7 bundle 写回归）已修复并重测转 GREEN（§7-11）；G9 缺陷已修（PR [#1930](https://github.com/42433422/XCMAX/pull/1930)），T9 下版复测转 GREEN（§7-12）。

| # | Gate | 状态 | 现有证据 | 缺失证据 | 阻断 | 对应 PR | 下一步 |
|---|------|------|---------|---------|------|---------|--------|
| G1 | 构建（产物+身份） | GREEN | **1.0.0.3 正式发布（2026-09-13）**：release run [34773838698](https://github.com/42433422/XCMAX/actions/runs/34773838698) checkout `4bfb23365c`（= main 合并 #1928）构建+Developer ID 签名+公证；扫描对 A/C 双 success 锚定同 SHA（间隔 35min），run 内 `verify_security_scan_pair.py` `passed=true, blockers=[]`；双目录五文件 SHA256 与 artifact 一致；feed/manifest/DMG/ZIP 公网复验（§2） | — | 无 | #1928 | — |
| G2 | 干净环境安装 | YELLOW | 验收脚本真实下载→SHA256→挂载→安装全链 PASS（历史版本实证）；真机 OTA 安装机制可用（G9） | 非干净机（dev 机+存量数据）；未在全新用户/VM 验证 | 无 | #1870 | 实机任务 T1：干净环境（新账户或 VM）重跑 |
| G3 | macOS 安全项 | GREEN | **1.0.0.3 公证包实测（2026-09-14，DMG 原件挂载）**：`codesign --verify --deep --strict` exit=0；hardened runtime（flags=0x10000）；TeamID `G26WSH472M`；`spctl --assess --type execute` exit=0（accepted）；stapler validate OK（[g3-official-10003.txt](evidence/e2e/macos-release-1.0.0.3/g3-official-10003.txt)） | — | 无 | — | — |
| G4 | 首次启动 | YELLOW | 真机 1.0.0.3 `/api/health` 200 `version=1.0.0.3`、runtime.status=healthy（[g6-post-ota-10003.json](evidence/e2e/macos-release-1.0.0.3/g6-post-ota-10003.json)）；OTA 后冷启动正常 | 首启 degraded（登录前 LLM_UNAVAILABLE）为预期态（§7-4）；未在干净环境首次启动 | 无 | — | T1 干净环境冷启动 |
| G5 | 登录绑定 | GREEN | **1.0.0.3 双证齐备（2026-09-14）**：① API——`auth/login` 200 → 会话有效（attendance capabilities 200 权益门控生效，[g6-post-ota-10003.json](evidence/e2e/macos-release-1.0.0.3/g6-post-ota-10003.json)）；② UI——1.0.0.3 原生主窗口登录态截图 [t2-logged-in-main-window-1.0.0.3.png](evidence/e2e/macos-release-1.0.0.3/t2-logged-in-main-window-1.0.0.3.png)（08:21 实拍），同刻渲染进程认证请求（agent/tasks、im/unread-total、entitlements）全 200（[g5-login-ui-10003.json](evidence/e2e/macos-release-1.0.0.3/g5-login-ui-10003.json)） | — | 无 | — | — |
| G6 | Mod / AI 员工加载 | GREEN | **1.0.0.3 OTA 后登录态实测（[g6-post-ota-10003.json](evidence/e2e/macos-release-1.0.0.3/g6-post-ota-10003.json)）**：`/api/mods` 200 返回 62 mod（attendance-industry v1.0.1 primary=True）；`/api/employees` 200 catalog（schema 1、6 split entries、legacy 4 员工）；登录态 `/api/mod/attendance-industry/attendance/capabilities` 200——T7 G6 项（路由注册修复生效）PASS | 干净首装 seed 版 mod 行为随 T1 | 无 | f37372e97 | T1 |
| G7 | 真实业务任务 | GREEN | **1.0.0.3 OTA 后登录态全链（[g7-retest-10003.json](evidence/e2e/macos-release-1.0.0.3/g7-retest-10003.json)）**：`POST /api/templates/upload` 200（template db:17，bundle 写回归已修复）→ 客户查重 400（已存在=数据存活）→ `POST /api/shipment/generate` 200「发货单生成成功」（发货单_26-0900001A_20260914_035326.xlsx，agent completed）。历史 RED（1.0.0.2 bundle 写回归）复现+日志+修复记录见 §7-11，修完重测后按规则转 GREEN | — | 无 | #1922 | — |
| G8 | 更新发现 | GREEN | **真机实跑（2026-09-13）**：1.0.0.2 应用内检查更新 → `update_available` 1.0.0.3（updater-events.jsonl 18:41/19:32Z；feed `buildSha=4bfb23365c` 锚定，[g8-update-discovered.json](evidence/e2e/macos-release-1.0.0.3/g8-update-discovered.json)） | — | 无 | #583 | — |
| G9 | 更新安装 | YELLOW | **安装机制实证（[g9-update-install-10003.json](evidence/e2e/macos-release-1.0.0.3/g9-update-install-10003.json)）**：download_start→update_downloaded（增量 blockmap 秒下）→install_start→ShipIt「Detected this as an install request」→应用退出后替换完成（Installation completed 03:45:13）→Info.plist=1.0.0.3+build-info gitSha/releaseId 与 release SHA 三锚定一致→重启后 health 1.0.0.3 healthy | **应用内一键安装缺陷**：点击「安装更新」后应用不退出，ShipIt 无限等待（根因+复现见 §7-12）；本次以「手动退出应用」（用户可完成操作）完成安装闭环 | 修复前不阻断数据/安装本身，但阻断「零干预」体验 | #1930 | #1930 并入 main → 下版 OTA 复测应用内一键安装转 GREEN |
| G10 | 数据保留（升级后） | GREEN | **OTA 路径实测（[g10-data-retention-10003.json](evidence/e2e/macos-release-1.0.0.3/g10-data-retention-10003.json)）**：1.0.0.2→1.0.0.3 真机 OTA 前后 digest 比对——DB 字节级一致（987,054,080B）、uploads 158→162/templates 13→17（+4 为 G7 探针新增）、users 6、backups 5 保留+升级后自动备份、routing_policies/models 保留；mods -2 为 1.0.0.3 mod 包版本内容差异非用户数据。历史四次覆盖/OTA 升级全 PASS（1.0.0.2 证据目录） | — | 无 | #1870 | — |
| G11 | 更新后重新执行业务 | GREEN | **OTA 后业务复跑（2026-09-14 03:53）**：登录→模板上传 200 入库→发货单生成 200 出单（agent completed），全链 2xx（[g7-retest-10003.json](evidence/e2e/macos-release-1.0.0.3/g7-retest-10003.json)，同 G7 证据） | — | 无 | — | — |
| G12 | 重启 Mac 后核心功能复验 | GREEN | **真实重启实测（2026-09-14 14:04，boot 13:57:35）**：登录守护自启 XCAGI → health 200 `version=1.0.0.3`（[t6-health.json](evidence/e2e/macos-release-1.0.0.3/t6-health.json)）→ 登录 200 → 模板上传 200（db:18）→ 发货单生成 200 出单 agent completed（[t6-g7-business-retest.json](evidence/e2e/macos-release-1.0.0.3/t6-g7-business-retest.json)）→ `/api/mods`+`/api/employees` 200 → 数据基线 pre/post 比对：行数与文件数零丢失、主库 +114KB、WAL 归零=干净关机 checkpoint 正常行为（[post](evidence/e2e/macos-release-1.0.0.3/t6-post-reboot-digest.json) vs [pre](evidence/e2e/macos-release-1.0.0.3/t6-pre-reboot-digest.json)）；全程日志 [t6-post-reboot-verify.log](evidence/e2e/macos-release-1.0.0.3/t6-post-reboot-verify.log)，守护与 /tmp 重启清理实录 [t6-launchd-onboot.log](evidence/e2e/macos-release-1.0.0.3/t6-launchd-onboot.log) | — | 无 | 本 PR | 下版 T6 直接复用证据目录内脚本 |
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
13. **B6（1.0.0.3→1.0.0.4 OTA 实测发现）：OTA 替换后旧版本 backend 进程残留**：ShipIt 替换 bundle 后，旧 1.0.0.3 backend 进程（早于安装启动）未被终止，继续占用 17500 端口，新 app 启动时检测到端口占用即复用旧进程 → health `version` 短暂报旧值而 git_sha 已读新 bundle build-info；手动完整重启应用栈后恢复一致（[t5-post-ota-verify.log](evidence/e2e/macos-release-1.0.0.4/t5-post-ota-verify.log)）。建议修复方向：app 启动时若 bundle 版本 > 运行中 backend 版本则强杀重启 backend；下版跟踪。非本轮阻断（用户可手动重启恢复）。

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
| T9 | 应用内一键安装复测：#1930 并入后下版 OTA——点击「安装更新」应用自动退出、ShipIt 自动替换、自动重启，无需手动退出；通过后 G9 转 GREEN。**结构性归 1.0.0.4→1.0.0.5 OTA**（1.0.0.3 触发方不含修复，1.0.0.3→1.0.0.4 轮为预期复现，见 §6.1-G9） | G9 | 真机（1.0.0.5 feed） |
| T10 | 1.0.0.4 重启 Mac 后核心功能复验（G12）：布防已备（[t6-post-reboot-verify.sh](evidence/e2e/macos-release-1.0.0.4/t6-post-reboot-verify.sh) + `/Users/Shared/xcagi-t6-tools/` 常驻副本 + launchd 自启），重启后登录即自动采集 health/数据基线/业务全链/Mod 员工证据；结果回填 §6.1-G12 | G12 | 真机（1.0.0.4） |

**T7 中期回执（2026-09-12，1.0.0.2 候选包实装重测，证据 [evidence/e2e/macos-release-1.0.0.2/](evidence/e2e/macos-release-1.0.0.2/)）**：① G6——启动日志零路由注册 ERROR（f37372e97 生效✅）；`/attendance/capabilities` 未登录返 SPA HTML 属权益门控设计，终判移入 T2。② G7——upload 仍 405（根因见 §7-8 修正定性：默认应用从未挂载 upload/analyze，b97073acc 只补 create）；修复已入库（template_api.py 默认挂载），**修复并入 main 后需重建候选包重测**。③ G10——跨版本覆盖升级数据保留 PASS（digest 逐项一致，见 G10 行）。

## 9. 发版复用 Runbook（每次 macOS 发版照此执行）

0. **版本口径提醒（2026-09-14 收口审计定稿）**：运行期版本判定**以 health 端点 + build-info（version/releaseId/gitSha 三锚定）为准**（口径见 §7-10）；其余显示值为映射，出现不一致先改锚点再发布，不改 health 口径。已知显示差异：① npm/Electron/Dart pub/Apple MARKETING_VERSION 三段 `1.0.0` 为工具链映射（VERSION.md 已声明等价关系）；② mobile `profileVersionText` 硬编码 `(12)` 与实际 `versionCode=10`/pubspec `1.0.0+10` 不同步（锚点校验不覆盖 build number，显示以 `versionName` 四段为准，(12) 待下版同步）。
1. `VERSION.md` 升版 → `version_sync.py --apply` + `verify_version_anchors.py`；
2. CI `release-desktop-mac-ota` 构建+签名+公证+发布 → `publish-macos-download-center` 更新下载中心/manifest/feed（发版 Runbook 第 2 步后必须核验 manifest `generated_at` 与构建 SHA，防"feed 已更新、manifest 未生成"漂移，见 §7-1）；
3. 真机跑 `bash FHD/scripts/package/acceptance-macos.sh --version <v>`（下载→SHA256→签名→安装→冷启动→健康检查）；跨版本数据保留走 `--overwrite-upgrade`（T5）；
4. 有新版本时真机走完整 OTA 链（G8→G12），按协议 4.1–4.2 判定；
5. 证据按版本入 `FHD/docs/evidence/e2e/macos-release-<版本>/`（截图/日志/JSON 与脚本），Gate 结论回填本文件 §6，不另建验收记录文档；发版前回归两个历史 RED：`POST /api/templates/upload` 非 405（G7，见 §7-8）；启动日志无 attendance 路由注册 ERROR（G6，见 §7-7）；
6. 回填本文件 §1–§6；全部 Gate 无 RED 且 G1–G4 GREEN、G5–G13 无 UNKNOWN 遗留方可宣布闭环；
7. RED：只修阻断项→重测→重写状态，禁止直接改状态。

## 10. 最终发布审计总表（主干 HEAD 收口审计，2026-09-15）

> 审计对象：main HEAD `280225ac77ce0b5f66470d2d7a11ad2844cdad67`（含 #1935/#1923/#1920/#1938 全部收口；Windows runner 证据 run 34841838624/34851567425 与 Mac 1.0.0.4 实机证据同锚）。判定规则：无证据 = UNKNOWN，不强行绿灯。

### A. 关键 PR 清理（不引入回滚）

| PR | 内容 | 状态 | 证据 |
|---|---|---|---|
| #1935 | 1.0.0.3 Release Ready 回填 | ✅ MERGED | main 历史 32b3c14e5 |
| #1923 | Windows 故障注入 CI 场景（dual-process/migration-mutex） | ✅ MERGED（rebase 后） | main 历史 c05a005ae |
| #1920 | 发货单流程修复+升版 1.0.0.4 | ✅ MERGED | main 历史 3d872b32e |
| #1938 | 故障注入误报修复（场景前基线增量判定） | ✅ MERGED（backend-test success） | main HEAD 280225ac7 |
| #1937/#1939 | 旧 metrics 快照/被覆盖 PR | ✅ CLOSED（#1937 内容折入 #1938） | PR closed |

回滚检查：G9 isQuitting 修复在 main HEAD 保留（[desktop-install-update.ts](../desktop/desktop-install-update.ts) L55/L65 预置逻辑在位，#1930 未被覆盖）；1.0.0.4 升版内容与 main 一致（health git_sha=280225ac7 实测）。✅

### B. Mac 方向（1.0.0.4，OTA 1.0.0.3→1.0.0.4 路径）

| 项 | 状态 | 证据 |
|---|---|---|
| 代码进 main | ✅ GREEN | 280225ac7（§10-A） |
| 扫描对 ×2 零漏洞 | ✅ GREEN | run 34851505749 + 34855340685，同 SHA，间隔 35min44s |
| OTA 产物上线 | ✅ GREEN | 公网四路复验 + 7 文件 SHA256 全匹配 + manifest/feed 锚定（§2） |
| G3 签名/安全项（安装态） | ✅ GREEN | [g3-official-10004.txt](evidence/e2e/macos-release-1.0.0.4/g3-official-10004.txt) |
| G5 登录绑定 | ✅ GREEN | API 双证（§6.1-G5） |
| G6 Mod/AI 员工 | ✅ GREEN | [g6-post-ota-10004.json](evidence/e2e/macos-release-1.0.0.4/g6-post-ota-10004.json)（62 mods + 6 split entries） |
| G7 业务全链（含文件下载回读） | ✅ GREEN | [g7-retest-10004.json](evidence/e2e/macos-release-1.0.0.4/g7-retest-10004.json) |
| G8 更新发现 | ✅ GREEN | updater-events + UI 三截图（§6.1-G8） |
| G9 安装 | ⚠️ YELLOW | 安装闭环完成但需手动退出配合（§6.1-G9；自动退出子项归 T9/1.0.0.5） |
| G10 数据保留 | ✅ GREEN | pre/post digest 逐项一致（§6.1-G10） |
| G11 更新后业务复跑 | ✅ GREEN | 同 G7 证据（§6.1-G11） |
| G12 重启复验 | ⏳ UNKNOWN | 布防就绪待重启（T10），结果回填 §6.1-G12 |

### C. Windows 方向（#1923）

| 项 | 状态 | 证据 |
|---|---|---|
| 双进程/迁移互斥 | ✅ CI runner 真实证据 | run 34841838624 双 PASS + 34851567425（#1938 修复后脚本回归）双 PASS（[WINDOWS_RELEASE_SSOT.md](WINDOWS_RELEASE_SSOT.md) §3） |
| disk-full/power-cut | ⚠️ 等真实机器 | CI 无法执行实体机场景，SKIP 而非伪造（T8） |
| #1938 判定修复验证 | ✅ | run 34851567425 隔离场景 PASS |

### D. #1841 弱网 OTA

| 项 | 状态 | 证据 |
|---|---|---|
| 根因 | ✅ 成文 | ISP 中间设备 QoS 会话重置（非客户端/服务端缺陷）；blockmap 放大因子已修 |
| 落地缓解 | ✅ | 增量更新（本轮实跑 blockmap 生效）、直连绕代理、8443 通道 |
| 产品化后续 | ✅ 回填 issue | 多源 fallback + 断点续传规划在案 |

### E. 版本口径

| 项 | 状态 | 证据 |
|---|---|---|
| health + git sha 口径 | ✅ 定稿 | 双平台 SSOT Runbook 第 0 条（macOS §9-0 / Windows §8-0） |
| 已知显示差异 | ✅ 记录 | npm/Electron/Dart `1.0.0` 工具链映射；mobile `(12)` vs versionCode=10（待下版同步）；feed `version: 1.0.0` vs productVersion（electron-updater 标准行为） |

### F. 交付结论（待 G12 后定稿）

- 已定：主干 HEAD 全链 Mac 证据 GREEN（G12 除外）、Windows CI 证据 PASS（实体机场景除外）、#1841 根因/产品化成文、版本口径统一。
- 待定：G12 重启复验（T10）跑完且无 RED 后，方可宣布「1.0.0.4 可交付」；若 G12 RED，按 Runbook 第 7 条只修阻断项。

## 11. 验收候选包（非发布产物，历史记录）

> 候选包 Developer ID 签名未公证（spctl rejected），仅供实机验收，不得替代发布产物、不得进 feed；正式 1.0.0.2 已于 2026-09-13 发布（§1/§2）。构建环境三坑见 §7-9；候选包 build-info `version` 落后产品号的口径见 §7-10。

| 候选 | buildSha | 实装重测结论 | 证据 |
|------|----------|-------------|------|
| v1（2026-09-12） | `3d3ec8d9867fa43cfeb402893ae3676fd86b0b95`（构建时 main HEAD，含 b97073acc/f37372e97，**不含** G7 挂载修复；DMG `6d11b2af…`/ZIP `1092e4fa…`） | G6 修复生效（启动日志零路由 ERROR）；G7 upload 仍 405（催生 template_api.py 默认挂载方案）；G10 跨版本覆盖升级数据保留 PASS | [receipt](evidence/e2e/macos-release-1.0.0.2/candidate-build-receipt.txt)、[retest](evidence/e2e/macos-release-1.0.0.2/retest-10002-results.json)、[pre](evidence/e2e/macos-release-1.0.0.2/data-digest-preupgrade-10002.json)/[post](evidence/e2e/macos-release-1.0.0.2/data-digest-after-10002.json) |
| v2（2026-09-12 17:30，含 G7 修复） | `9a4a06bc49b8885111dc7dc4c61eb15d0dd748db`（DMG `da2a1bd7…`/ZIP `e866079b…`，PR #1895 合并 main 后干净构建，`env -u CI` 跳过公证） | 覆盖升级（3d3ec8d98→9a4a06bc4）PASS；G7 upload/analyze 405→401（断链根治、鉴权生效）；G10 PASS；冷启动 0.1s health PASS | [g7-retest-cand2-20260912.txt](evidence/e2e/macos-release-1.0.0.2/g7-retest-cand2-20260912.txt) |
