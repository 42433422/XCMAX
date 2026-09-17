# 2026-09-17 Mac 真机验收轮次 · 最终报告

对象：已安装 `/Applications/XCAGI.app` = **1.0.0.4**（gitSha `280225ac77ce0b5f66470d2d7a11ad2844cdad67`，owner root:wheel，
Developer ID Application: jialong Li `G26WSH472M`，notarized，`spctl` accepted）

口径：每条结论只认**本轮**在**本机**实跑产生的证据。历史 PASS 一律不计入本轮 PASS。
未修改任何测试标准；未以代码存在 / CI PASS / health=200 替代实机验收。
Gate 状态仅用 PASS / FAIL / RUNNING / NOT RUN。

---

## 1. 逐 Gate 结果

| Gate | 本轮状态 | 本轮证据 | 说明 |
|---|---|---|---|
| G0 基线（已装包身份） | **PASS** | `round-20260917-g0-baseline.json` | health=`1.0.0.4`/`280225ac7`/healthy；`/api/mods`=**62**（与 1.0.0.3 基线一致）；`/api/employees` 200；`/api/platform-shell/capabilities` 200（attendance-industry 在 protected 列表）；`/api/mods/attendance-industry` 200（v1.0.1） |
| G8 应用内检查更新 | **FAIL** | `round-20260917-g8-g9-result.json`、`round-20260917-g8-update-check.png`、`round-20260917-feed-latest-mac.yml` | 真实 GUI 路径「系统设置 → 关于 → 检查更新」已点击；UI 仅回「已开始检查更新，如有新版本将提示下载。」，无新版本提示；`updater-events.jsonl` 检查前后无新增 `update_available` 行 |
| G9 一键安装 / 自动退出 / ShipIt / 自动重启 | **NOT RUN** | `round-20260917-g8-g9-result.json` | G8 未产生可安装对象 → 无「安装更新」可点，无自动退出可观察 |
| G10 升级前后数据保留 | **NOT RUN**（严格判定） | `round-20260917-g10-post-ota-digest.json`、`round-20260917-g10-digest-compare.txt` | 本轮 digest 与 1.0.0.4 首启历史基线逐项一致：db 字节 0 变、users 6→6、templates 18→20、uploads 163→165、mods 1257→1257，**无丢失**；但本轮无真实升级动作，pre 侧为历史证据，故不给 PASS |
| G11 业务链复测（登录→上传模板→发货单生成→xlsx 下载回读） | **PASS** | `round-20260917-g11-g7-retest.json`、`round-20260917-g11-artifact-digest.json`、`round-20260917-g11-logged-in-window.png` | login 200 → auth_me 200 → 模板上传 200（`db:21`）→ 发货单生成 200（`发货单_26-0900001A_20260917_010152.xlsx`，run_id `run_56c0162b244748fa86db9b3c9f187f1f`，agent_status=completed）→ xlsx 下载 200 / 5192B / PK 魔数 / SHA256 `9b1eae31bf34c55daf646e69d0a63892c9c46ba54ab1458a25bc0573c21c80fb`；产物已落盘供重启后比对 |
| G12 重启后复验 | **PASS** | `round-20260917-g12-post-reboot.json` 及同名前缀 6 件 | 整机重启已发生（`kern.boottime` = `Thu Sep 17 01:31:51`）；登录后应用自动恢复，布防任务 01:37:34 跑完全链；详见 §8 |

---

## 2. 第一个真实断点

**Gate：G8 / G9 — 应用内不存在可安装的更新对象。**

证明链（均为本轮实测）：

1. feed `https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml` → 200，`productVersion: 1.0.0.4`，`buildSha: 280225ac77ce0b5f66470d2d7a11ad2844cdad67`。
2. 本机 `/Applications/XCAGI.app/Contents/Resources/build-info.json` → `gitSha` = 同值，`version` = 1.0.0.4。
3. `desktop/updater.ts` `installSameVersionRebuildHook()`：`remoteSha === localSha` → `isUpdateAvailable = false`（同版本构建绝不再提示自更新）。
4. `https://xiu-ci.com/xcagi-v1.0.0.5/manifest.json` → **404**；`https://xiu-ci.com/xcagi-v1.0.0.5/enterprise/` → **404**。
5. 应用内「检查更新」实点后仅返回「已开始检查更新，如有新版本将提示下载。」，无任何更新提示。

结论：**1.0.0.4 今日无法取得 MAC FULL CHAIN PASS**。G9 的「一键安装 → 应用自动退出（#1930 isQuitting 修复）→ ShipIt 替换 → 自动重启」必须在 **1.0.0.4 → 1.0.0.5** 的 OTA 中才能被真正复测——
自动退出修复位于触发方（发起安装的那个版本）代码中，1.0.0.3 触发方不含该修复。这是**缺发布对象**，不是本机缺陷。

---

## 3. 第一次「已重启」声明的核对（历史记录，已由 01:31:51 的真实重启取代）

用户口头告知「已重启」。本轮用系统权威来源独立核对，结论为**未发生重启**：

| 证据 | 值 |
|---|---|
| `sysctl -n kern.boottime` | `Mon Sep 14 13:57:35 2026`（与重启前同一值） |
| `uptime` | `up 2 days, 11:23` |
| `last reboot`（最新一条） | `一 9月 14 13:57` |
| `last shutdown` | 自 9/14 13:57 后无记录 |
| 应用进程 | pid **3027** 仍在，`lstart = 二 9月/15 15:18:03 2026`（重启前同一进程） |
| 布防任务 | `onboot-10004.log` **不存在** → `RunAtLoad` 从未触发 |

当时据此判 G12 = **NOT RUN**，不以口头声明替代实机证据。
**后续更新：2026-09-17 01:31:51 本机完成真实整机重启（`kern.boottime` = `Thu Sep 17 01:31:51`），G12 已按 §8 重新判定为 PASS。本节保留为过程记录，说明判据「口头声明 ≠ 实机证据」的执行方式。**

---

## 4. 布防（用户真正重启后即可自动完成 G12）

- `~/Library/LaunchAgents/com.xcagi.t6-postreboot.plist`（`RunAtLoad=true`，仍在位）
- 运行链：`/Users/Shared/xcagi-t6-tools/t6-onboot.sh` → `macos-release-1.0.0.4/t6-post-reboot-verify.sh`
  （health → data digest → G7 全链 → `/api/mods` `/api/employees`）
- 租户凭据：`/Users/Shared/xcagi-t6-tools/.t6-creds`（chmod 600）
- 轮询窗口：48 × 15s ≈ 12 分钟等待后端 healthy
- 前置条件：登录后 `/Applications/XCAGI.app` 必须在窗口内启动。系统登录项中**没有** XCAGI；
  `TALLogoutSavesState=1`（重启时选「重新打开窗口」可自动恢复）。
- 该链路已在本轮以隔离目录 **dry-run 全链跑通**（临时目录已清理）。

---

## 5. 异常项定性（均非产品缺陷，避免误判）

- `templates_list.probe_present=false`：脚本把列表响应截断到 400 字符，探针落在窗口之外；
  直接查 `/api/templates` 原文**包含** `G7重测探针` → 脚本度量假象。
- `customer_ensure` 400：返回「客户名称已存在」（customer id=26）→ 幂等，不影响出单。
- `auth_me.user=null`：HTTP 200，仅取值字段名不匹配。
- `xcagi.db` 中 `rows.customers=0` 但 API 有 1 个客户：该客户存放于 `mod:xcagi-erp-domain-bridge` 的 Mod 库，非主库表。

---

## 6. 下一已知风险

**1.0.0.4 → 1.0.0.5 OTA 是否需要再次人工授权：UNKNOWN。**
上一轮证据称「ShipIt helper 授权后常驻、后续 OTA 免密全自动」。本轮独立核对当前系统：
`/Library/PrivilegedHelperTools` 与 `/Library/LaunchDaemons` 均无 xcagi / electron / ShipIt 条目，
`~/Library/LaunchAgents` 亦无 Squirrel/ShipIt 项，仅 app bundle 内存在 `Squirrel.framework`。
→ 该「常驻免密」说法本轮**无法证实**，下一次 OTA 仍需现场观察是否弹出 SecurityAgent / 管理员授权。

---

## 7. 附加检查：进程级冷启动复验（**明确不等价于 G12，不计入 FULL CHAIN PASS**）

2026-09-17 01:21 因「是否可不重启整机、只重启进程」的提问而执行的独立检查。

先说为什么不能替代 G12：G12 判据是「**重启 Mac 后**」复验，要覆盖进程重启无法触及的三层——
(a) OS 级冷启动路径（launchd 登录项、应用自启、TCC 权限重评估、网络栈重建）；
(b) 真实关机/开机周期下的 SQLite 落盘完整性（WAL 检查点与恢复路径）；
(c) 不可伪造的重启锚点（`kern.boottime`/`uptime`），否则证据无法区分「真做过」与「没做过」。
用进程重启去替 G12 = 修改测试标准，故不做。

本轮实跑结果（**PASS，但归类为独立检查**）：

| 步骤 | 结果 |
|---|---|
| 优雅停止 | `SIGTERM` pid 3027 → 4 秒退出，后端 `HTTP 000`（连接被拒），进程全清 |
| 冷启动 | `open -a /Applications/XCAGI.app` → 新 pid **80518**（后端 80547），**5 秒**内 healthy |
| 重启锚点 | `kern.boottime` = `Mon Sep 14 13:57:35 2026` **未变** → 确为进程重启，非整机重启 |
| health | 200，`1.0.0.4`，`280225ac77ce`，`status=healthy`，`degradedReasons=[]` |
| SQLite 冷启动完整性 | `PRAGMA quick_check` → **ok**（只读连接直测） |
| 数据保留 | db 字节 / uploads / templates / mods / models / rows.templates / rows.users **delta 全部为 0**，无丢失 |
| G7 业务链（冷启动后） | 登录 200 → 上传 200（`db:23`）→ 发货单生成 200（`发货单_26-0900001A_20260917_012225.xlsx`，run_id `run_4db28a984c6f4eedb7d14c69b1e02e33`，agent_status=completed）→ 下载 200 / 5194B / PK 魔数 / SHA256 `3b19554d…` |
| Mod / AI 员工 | `/api/mods` 200（`{success,data:[…]}` = **62** 项，与 G0 基线一致）；`/api/employees` 200 |
| 启动日志扫描 | `quick_check\|corrupt\|recover\|integrity` 命中 0 条（无恢复/损坏痕迹） |

结论：**进程级冷启动 PASS**；`counts_as_G12 = NO`，`counts_as_FULL_CHAIN_PASS = NO`。
机读结果：`round-20260917-process-restart-coldstart.json`；原始日志与产物在
`/Users/Shared/xcagi-t6-tools/process-restart-20260917/`（含 `process-restart-verify.log`、`db-quick-check.txt`、
`pre/post-restart-digest.json`、`g7-retest-after-process-restart.json`）。

---

## 8. G12 重启后复验：**PASS**（整机重启已发生）

**重启锚点（不可伪造）**：`kern.boottime` = `Thu Sep 17 01:31:51 2026 (sec=1789579911)`，上一轮为 `Mon Sep 14 13:57:35` → 确为整机重启。

**应用自动恢复**：应用 pid 691 `01:36:51` 启动、后端 pid 1067 `01:37:06` 启动；布防任务 `01:37:16` 开始，
`01:37:31` 首次轮询即 healthy → 登录后应用自动恢复，无需人工启动。布防于 `01:37:34` 完成并自清理 plist + creds。

| 复验项 | 结果 |
|---|---|
| health | 200，`1.0.0.4`，`280225ac77ce`，`status=healthy`，`degradedReasons=[]`，`runtime.status=healthy` |
| SQLite 冷启动完整性 | `PRAGMA quick_check` → **ok**（只读直测），`journal_mode=wal` |
| 数据保留 | **无丢失**。正向 delta：db +233,472B、uploads +2、templates +2、mods.files +2、backups +1、rows.templates +2、rows.users 0、models 0、routing_policies 0 |
| 唯一负向 delta | `xcagi.db.wal.bytes` 2,537,952 → **0**：干净关机时的 WAL checkpoint（内容已并入主库），**非数据丢失** |
| G7 业务链（重启后） | 登录 200 → 上传 200（`db:24`）→ 发货单生成 200（`发货单_26-0900001A_20260917_013734.xlsx`，run_id `run_e807d1ee1a4144829d6faa279e246ad1`，completed）→ 下载 200 / 5194B / PK 魔数 / SHA256 `7b6b1d8d08…` |
| Mod / AI 员工 | `/api/mods` 200，**62** 项；`/api/employees` 200 |
| 死 worktree 清理 | `git worktree prune -v` 移除 xcmax-p1920 / -1937 / -closure / -p1923 / -fi-fix；`worktree list` 现仅剩主仓库 |

**诚实口径**：pre 基线采集于 01:12，而 01:22 我方进程级冷启动测试额外写入 1 模板 + 1 发货单，
故 uploads / templates / mods.files 的 +2 属我方测试写入，不构成"漂移"证据。

**本轮新发现（非 G12 失败项，需后续确认）**：本次冷启动生成了 **2 份全量备份**
`backups/xcagi-unknown-20260916173730.db`（987,402,240B）与 `xcagi-unknown-20260916173738.db`（987,439,104B），
文件名时间戳为 UTC（= 北京时间 01:37:30 / 01:37:38，恰为启动时刻），与 09-16 的 `xcagi-unknown-*` 同型。
**单次冷启动约占 2GB**；`reason=unknown` 的触发源（启动即备份 / 迁移前备份）待确认。

---

## 9. 本轮最终判定

| 项 | 判定 |
|---|---|
| G0 基线 | PASS |
| G8 检查更新 | **FAIL** |
| G9 安装更新（含自动退出） | **NOT RUN** |
| G10 升级前后数据保留 | **NOT RUN**（无真实升级动作） |
| G11 业务链 | PASS |
| G12 重启后复验 | **PASS** |
| **1.0.0.4 MAC FULL CHAIN PASS** | **未达成（FAIL）** |
| **第一个真实断点** | **G8/G9：应用内不存在可安装的更新对象（需 1.0.0.5）** |

未修改任何测试标准；未以历史证据、代码存在、CI 通过或 health=200 替代实机验收；
每一次"未发生/未执行"均如实判 NOT RUN。

---

## 10. 本轮证据索引（均在 `FHD/docs/evidence/e2e/macos-release-1.0.0.4/`）

```
round-20260917-gate-status.json                  逐 Gate 状态 + 断点证明链 + 风险 + 完整性声明
round-20260917-g0-baseline.json                  G0 基线
round-20260917-feed-latest-mac.yml               更新 feed 原始快照
round-20260917-g8-g9-result.json                 G8/G9 结论与判定依据
round-20260917-g8-update-check.png               「检查更新」实点截图
round-20260917-updater-events-BEFORE.jsonl       检查更新前 updater 事件快照
round-20260917-g10-post-ota-digest.json          G10 本轮 digest
round-20260917-g10-digest-compare.txt            G10 双基线逐项比对
round-20260917-g11-g7-retest.json                G11 业务链全步骤结果
round-20260917-g11-artifact-digest.json          G11 产物下载回读指纹
round-20260917-g11-artifact-发货单_26-0900001A_20260917_010152.xlsx   G11 产物本体
round-20260917-g11-logged-in-window.png          登录态截图
round-20260917-g12-pre-reboot-digest.json        G12 重启前数据基线
round-20260917-g12-pre-reboot-state.json         G12 重启前状态与布防记录
round-20260917-g12-post-reboot.json              G12 判定与全部证据锚点（PASS）
round-20260917-g12-post-reboot-verify.log        G12 复验原始日志（布防自动执行）
round-20260917-g12-post-reboot-digest.json       G12 重启后数据摘要
round-20260917-g12-health.json                   G12 重启后 health 全文
round-20260917-g12-g7-retest.json                G12 重启后 G7 业务链
round-20260917-g12-onboot.log                    布防任务原始日志（含自清理记录）
round-20260917-process-restart-coldstart.json    进程级冷启动独立检查（不等价 G12）
round-20260917-tmp-rescue-archive.json          重启前 /tmp 资产抢救归档与三重核验
round-20260917-FINAL-REPORT.md                   本文件
```

---

## 11. OTA2 章节（2026-09-17 第二轮：应用内 OTA 全链 + 真实整机重启）——本节取代 §9 判定

§9 为第一轮（01:25）结论，其 G8 FAIL 的原因是「本机已装版本 == feed 广播版本」，该结构性阻塞在第二轮已解除（feed 已广播 `productVersion=1.0.0.4`、远端 `buildSha=280225ac` ≠ 本机 `4bfb23365c`）。

| Gate | 第一轮 §9 | 第二轮 | 本轮判据 |
|---|---|---|---|
| G8 更新发现 | FAIL | **PASS** | `round-20260917-ota2-g8-discovery.json`：19:21:01.305Z `update_available` 新事件 + 左下角「可更新 1.0.0.4」角标截图 |
| G9 安装更新 | NOT RUN | **FAIL（RED）** | `round-20260917-ota2-g9-install-chain.json`：入口 PASS / **自动退出 FAIL** / ShipIt 替换 PASS / **自动重启 FAIL** |
| G10 数据保留 | NOT RUN | **PASS** | 同上 `g10_verdict` + `round-20260917-ota2-postinstall-digest.json`：16 项 15 SAME（唯一 DIFF=自动备份轮转） |
| G11 业务链 | PASS | **PASS** | `round-20260917-ota2-postinstall-g7-retest.json`：发货单 `…20260917_052123.xlsx` / 5195B / sha256 `99d404a690df…` |
| G12 重启后复验 | 未执行 | **PASS** | `round-20260917-ota2-g12-post-reboot.json`：`kern.boottime` 1789579911→1789626349 + `last reboot` shutdown 14:25 双证 |

**第一个真实断点（本轮）**：G9 应用内一键安装——① 自动退出（1.0.0.3 缺 `app.isQuitting` 预置，PR #1930 已修但未随 1.0.0.4 验证）；② 自动重启（`ShipItState.plist` `launchAfterInstallation=false`，写入时刻早于任何外部干预；应用层可控点未定位，不臆测）。

**保真度与诚实口径（不得省略）**：① 本轮应用内点击由 computer_use 合成点击执行（`click_provenance` 已标注），非人手点击；② 夹具 app 属主 `a4243342:staff` → **未覆盖** SecurityAgent 管理员授权分支；③ G12 应用在 boot 后 23s 已运行（`app_launched_by_script=no`），启动来源未单独取证，**不记作产品自动启动**，「开机自启」为产品设计未启用项；④ 采样器曾误匹配携带 app 路径的 ShipIt 进程（PID 12317），已在 JSON `sampler_caveat` 更正；⑤ 部分工具缺陷当场修复并记入 `tooling_defects_found_and_fixed_mid_run`（`sysctl` 正则误吞 `usec` 致证据文件名含换行、复测产物需先 `rm` 防假 PASS、LaunchAgent 极简 PATH）。

**最终判定**：1.0.0.4「安装→使用→更新→数据保留→更新后继续使用→重启后继续使用」全链 **PASS**；「零干预」应用内一键安装（G9）**FAIL**；**1.0.0.4 MAC FULL CHAIN PASS 未达成（首断点 G9）**。另有发布面未闭环：release run [34856380264](https://github.com/42433422/XCMAX/actions/runs/34856380264) `cancelled`、manifest `release_ready=false`、下载中心仍 1.0.0.3（见 `MACOS_RELEASE_SSOT.md` §7-13/T11）。未以历史证据、代码存在、CI PASS 或 health=200 替代实机验收，未修改任何测试标准。