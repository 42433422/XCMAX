# 1.0.0.4 真机闭环执行清单（主干 HEAD 重跑，逐 Gate 留证）

> 前提：扫描对 A/B 零漏洞锚定 release_sha → release-desktop-mac-ota 构建发布 → feed 广播 1.0.0.4。
> 口径：运行期版本判定以 health + build-info（version/releaseId/gitSha）为准。
> 状态标记：[ ] 未执行 / [x] 已执行含证据 / [BLOCKED] 等待外部条件。
> 本轮口径：**每个 Gate 只用本轮新证据**；历史证据单独标注，不折算 PASS。

## 前置
- [x] G1 安装包下载：官方产物 SHA256/ZIP 与 manifest 双通道 MATCH（DMG `cf01c076…` / ZIP `5514e649…`）→ `round-20260917-g0-baseline.json`、归档 `/Users/Shared/xcagi-archives/20260917-ota-10004-artifact/`
- [ ] G2 覆盖安装：**未走** `acceptance-macos.sh`；本轮改用「DMG 装 1.0.0.3 → 应用内真实 OTA 升 1.0.0.4」夹具路径，降级安装痕迹见 `round-20260917-ota2-verification.json`
- [x] 冷启动 + health：version=1.0.0.4 + gitSha=280225ac77ce0b5f66470d2d7a11ad2844cdad67 → `round-20260917-g0-baseline.json`、`round-20260917-g12-health.json`

## 业务链（G7 全链）
- [x] G7 全链 PASS（本轮两次：OTA 前 01:01、升级态 03:16）→ `round-20260917-g11-g7-retest.json`、`round-20260917-ota2-g11-g7-retest.json`
- [x] steps：login 200 / templates_upload 200（template db:25）/ shipment_generate 200（`发货单_26-0900001A_20260917_031605.xlsx`，agent_status=completed）/ file_download 200（5195B，PK 魔数，SHA256 `f5a0eb24…`）
  - 既有非缺陷项：`auth_me.user=null`、`customer_ensure 400`（重复客户名）、`templates_list.probe_present=false`（脚本截断响应）
- [x] 截图：`round-20260917-g11-logged-in-window.png`

## Mod / AI 员工（G6）
- [x] GET /api/mods → 200，数量 62 与 1.0.0.3 基线一致 → `round-20260917-g0-baseline.json`
- [x] GET /api/employees → 200（catalog + 5 个 split mod 条目齐全）
- [x] capabilities 路由更正并实测：`/api/platform-shell/capabilities` 200（edition=full）；`/api/diagnostics/capabilities` 200，但 `rasa.status=degraded / available=false`（非 required 组件，health 整体仍 healthy）→ 记为 **YELLOW 观察项**
  - 注：`/api/attendance/capabilities` 与 `/api/mods/attendance-industry/capabilities` 均 404（路由不存在，前一轮清单条目路径有误）

## OTA（G8-G11，核心：G9 自动退出=T9 复测）
- [x] G8 应用内检查更新发现 1.0.0.4（本轮新事件 `update_available` @ 2026-09-16T19:21:01.305Z + 角标可见）→ `round-20260917-ota2-g8-discovery.json`、`round-20260917-ota2-g8-chip-visible.png`
  - 角标定位：`button.desktop-update-chip` 文案「可更新 1.0.0.4」，锚点坐标 (90,714) 100×22，位于左下角状态行
- [x] **G9 点击「安装更新」→ 应用自动退出（不手动退出）→ ShipIt 自动替换 → 自动重启** → **判定 FAIL**（子项：入口 PASS / 自动退出 FAIL / ShipIt 替换 PASS / 自动重启 FAIL），详见 `round-20260917-ota2-g9-install-chain.json`
  - 本轮第一次尝试：**FAIL**，安装由人工解压缓存 zip 覆盖完成，无 `install_start`、无 ShipIt 会 话 → `round-20260917-ota2-verification.json`（含三路反证）
  - 已知结构性事实（**本轮已双证**）：1.0.0.3 触发包 `installUpdate()` **缺** `app.isQuitting = true`（反编译 `/Applications/XCAGI.app/.../app.asar` 实测），1.0.0.4 产物**含**两处该赋值（反编译 `_prev-10004-app/.../app.asar` 实测）；修复提交 `732233aca (#1930)` / `3d872b32e (#1920)`。故「自动退出」子项在 1.0.0.3 触发侧必然失败，完整验证只能由 **1.0.0.4 → 1.0.0.5** 的下一次 OTA 完成 → `round-20260917-ota2-verification.json` 的 `g9_autoquit_root_cause`
  - 本轮第二次尝试（**真实按钮路径，已执行**）：由 computer_use OS 级合成点击完成（**非人手点击，已在证据中标注**）「可更新 1.0.0.4」→「下载更新」→「更新并重新加载」
    - 时间线（UTC）：`21:14:49.960 download_start` → `21:14:50.273 update_downloaded`（命中缓存）→ `21:15:28.089` **`install_start`** → `21:15:33.561 ShipIt[4502] Detected this as an install request` → `21:15:35Z` 时间线首见 shipit_pid=4502
    - **自动退出 FAIL**：`install_start` 后应用存活 ≥181s（21:15:28→21:18:29），ShipIt 4502 期间**无任何日志输出** = 卡在等应用退出 → `round-20260917-ota2-g9-stuck-state.txt`
    - **ShipIt 替换 PASS**：外部 SIGKILL 应用后，`21:18:32.675 Installation completed successfully`；替换后产物与官方产物**逐字节一致**（app.asar `875ca9a25415beee…`、主可执行 `e63f5f58d937d169…`，spctl accepted / Notarized Developer ID G26WSH472M）
    - **自动重启 FAIL（新独立缺陷）**：`ShipItState.plist`（写于 21:15，早于外部干预，不受混淆）`launchAfterInstallation=false`，ShipIt 日志无任何 Launching 行 → 应用未自行回来，由我手动 `open` 恢复。应用层可控点**未定位到**（不臆测），需 1.0.0.4→1.0.0.5 复验
    - 混淆声明：`SIGKILL` 与 `open` 均为外部干预，已如实标注；「自动退出」结论的窗口内无外部干预
  - 点击前 preflight（本轮实测，含保真度声明）→ `round-20260917-ota2-g9-preflight.txt`：缓存 1.0.0.4 zip sha512 与 feed 一致、`isAdminRightsRequired=false`（本轮**不覆盖** SecurityAgent 授权分支，因夹具 app 属主为 a4243342:staff）、磁盘 98Gi 可用、ShipIt 缓存自 9月15 15:09 起未再运行
- [x] G9 证据（本轮已全部产出）：`round-20260917-ota2-postinstall-{updater-events-AFTER.jsonl,events-delta.txt,traces.txt,health.json,digest.json,g7-retest.json}` + `round-20260917-ota2-g9-{chain-timeline.jsonl,preflight.txt,stuck-state.txt,install-chain.json}`
  - events delta 关键三行：`21:14:49.960 download_start` / `21:14:50.273 update_downloaded` / `21:15:28.089 install_start`（本轮新事件，非历史）
- [x] G10 升级前后数据基线比对：**本轮 postinstall digest vs pre-ota2-10003 digest：16 项 15 SAME，唯一 DIFF = `backups.latest` 文件名（安装时新生成自动备份，`backups.files` 计数不变 → 轮转，非数据丢失）** → `round-20260917-ota2-postinstall-digest.json`、`round-20260917-ota2-g9-install-chain.json`
  - 早前 OTA 前的基线比对（1.0.0.3 降级路径）：DB 987402240B、WAL、uploads 169、templates 23 等逐项一致，唯一 delta = Mods 代码树 −18（归因包内 Mod 刷新忽略 `__pycache__/*.pyc` 且旧目录归档）→ `round-20260917-ota2-verification.json`；本轮该项已不再出现（mods.files SAME）
- [x] G11 更新后重跑 G7 业务链：`round-20260917-ota2-postinstall-g7-retest.json` → login 200 / templates_upload 200 / shipment_generate 200（`发货单_26-0900001A_20260917_052123.xlsx`, agent_status=completed）/ file_download 200（5195B, xlsx_magic=true, sha256 `99d404a6…`）；旧数据可读 → `round-20260917-ota2-g11-g7-retest.json`

## 重启复验（G12）
- [x] G12（本轮早前轮次，01:31:51 重启）：覆盖降级前那份 1.0.0.4 目录 → `round-20260917-g12-post-reboot.json`（其 `autostart_proof.note` 原文「登录后应用自动恢复，无需人工启动」属**过度声称**，本轮已更正为中性描述）
- [x] G12（**本轮收官轮次，14:25:49 重启**）：对 **ShipIt 换入的当前 1.0.0.4 安装**做整机冷启动 → **PASS**，零缺口闭合 → `round-20260917-ota2-g12-post-reboot.json`
  - boottime `1789579911 → 1789626349`（Thu Sep 17 14:25:49），`last reboot` 有 `shutdown time Thu Sep 17 14:25` → 真实整机重启
  - 冷启动后：health 200 / `1.0.0.4` / `280225ac77ce`；`PRAGMA quick_check = ok`；`/api/mods` = 62
  - 数据保留：16 项 16 可归因（`rows.templates`/`uploads.*`/`db.bytes` 增量 = 本脚本自己 G7 复测的测试副作用；`wal.bytes 1161872→0` = 干净关机 checkpoint；`backups.latest` 轮转；`mods.files +4` = 字节码缓存 glob 条目，非业务数据）
  - G7 复测全绿：`发货单_26-0900001A_20260917_142647.xlsx` / 5196B / sha256 `d2881126…`
  - 布防自清理生效（plist 与 `.g12-creds` 均已不存在）
  - 诚实口径：应用在 boot 后 23 秒已存在、早于脚本 40 秒兜底点，故 `app_launched_by_script=no`；其来源**未单独取证**（macOS 重启还原 或 用户手动打开），**不写成「产品自动启动」**（登录项为空的既有事实）；「开机自启」属产品设计项，单独记为未启用

## 回填
- [x] 本文件逐项打勾 + 证据文件名（本轮）
- [x] `MACOS_RELEASE_SSOT.md` §1/§2/§6/§7/§8 更新为 1.0.0.4 事实 + G9 判定（2026-09-17 回填完成；`ssot_cli.py check macos-release` = OK）
  - §1：版本 1.0.0.3→1.0.0.4、gitSha→`280225ac77ce…`、builtAt→`2026-09-14T14:48:06.725Z`、扫描对→34851505749/34855340685、`release_ready`→`false`
  - §2：DMG `cf01c076…`/306,901,903B、ZIP `5514e649…`/264,533,286B/SHA512 `k6NaLCXo…`
  - §6：G1→YELLOW（release run cancelled）、G9→**RED**（含复现步骤/日志/截图/#1930）、G12→GREEN（本轮整机重启）；G3/G5/G6/G7/G8/G10/G11 换本轮机证
  - §7 新增 13（发布面未闭环）/14（自动重启缺陷）/15（SecurityAgent 分支未覆盖）；§8 新增 T10/T11 并重写 T9
  - 附带净删除：移除 §2 x64 重复行、§10 验收候选包历史表、§6 T7 中期回执（本文件所在迭代净 −8 行）
- [x] 版本显示不一致清单核对（Runbook 第 0 条）**已实测**：三类口径并存且**互不矛盾**
  - 4 段产品口径（应作验收判据）：`CFBundleShortVersionString` / `CFBundleVersion` = `1.0.0.4`（1.0.0.4 产物）、`build-info.version` = `1.0.0.4`、`health.version` = `1.0.0.4`、`health.release_id` = `xcagi-1.0.0.4-280225ac77ce…` —— **四处一致**
  - 3 段 npm/Electron semver 口径（非产品版本）：`app.getVersion()` → UA `xcagi-desktop/1.0.0`、feed `version: 1.0.0`、updater 事件 `update_available.data.version = "1.0.0"` —— 这是 `readLocalProductVersion()` 注释中「Product version is four-part and comes from signed build metadata, not npm SemVer」的既有设计
  - 1.0.0.3 夹具同样一致（plist/`build-info`/`health` 均为 `1.0.0.3`，release_id `xcagi-1.0.0.3-4bfb23365c5e…`）
  - 结论：**不存在版本错配**；需在 `SSOT` 注明「看到 1.0.0 属 npm semver 口径，不是产品版本」以免误判