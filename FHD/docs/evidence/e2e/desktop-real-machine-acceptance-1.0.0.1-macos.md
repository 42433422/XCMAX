# XCAGI 桌面端真实机验收证据 — 1.0.0.1 — macOS

> 按模板 [desktop-acceptance-template.md](../templates/desktop-acceptance-template.md) 填写；
> 协议判据见 [desktop-real-machine-acceptance-protocol.md](../desktop-real-machine-acceptance-protocol.md)。
> 执行方式：引导脚本 `FHD/scripts/package/acceptance-macos.sh` 自动执行步骤一/二的可自动化部分，
> OTA/回滚按协议为人工步骤（见第 4/5 节结果与原因）。

---

## 1. 基本信息

| 字段 | 值 |
|------|-----|
| 验收版本（四段产品版本） | `1.0.0.1` |
| 构建身份 gitSha（build-info.json） | `0df6e1a075dd40abdbdbacca222ac4680ac3e0d0` |
| 平台 / 架构 | `macos` + `arm64`（Apple Silicon） |
| 机器型号 | `Mac16,10`（24GB / 25769803776 bytes） |
| OS 版本 | `macOS 26.3 (25D125)`，Gatekeeper assessments enabled |
| 内存 / 可用磁盘 | 24GB / （验收时 ≥100GB 可用） |
| 执行人 | Agent（Trae 自动化执行，代码评审兜底） |
| 执行日期 | 2026-09-01 |
| 安装方式 | 验收脚本（`acceptance-macos.sh --version 1.0.0.1 --skip-launch`；hdiutil 挂载 + ditto 拷贝） |
| 安装目录 | `/tmp/xcagi-acceptance-app/XCAGI.app`（见下方说明） |
| 总体结论 | **PARTIAL** — 安装+签名+身份校验 PASS；冷启动 SKIP（现有实例冲突）；OTA SKIP（无升级目标）；回滚 PARTIAL（自动化佐证） |

> **安装目录说明**：脚本默认安装到 `~/Applications/acceptance/`；本轮执行环境为 Trae 沙箱，
> 对 `~/Applications/` 下文件写入被系统沙箱策略拦截（`Operation not permitted`），
> 故使用脚本 `--dest /tmp/xcagi-acceptance-app` 改为临时目录安装。
> 真实人机环境下默认路径可用（`mkdir ~/Applications/acceptance` 已验证可建目录）。
> 该临时安装未触碰 `/Applications/XCAGI.app`（本机现有安装，保持原样）。

---

## 2. 安装

| 字段 | 值 |
|------|-----|
| 安装包文件名 | `XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg` |
| 下载 URL | `https://xiu-ci.com/xcagi-v1.0.0.1/enterprise/XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg` |
| 文件大小（字节） | `292930436`（实测 `stat`；脚本显示 288M） |
| 实测 SHA256 | `a36a92cdc052df226f3c5b0ff442c40868596eeb534bdaa6bd4c02c9296f043b` |
| manifest 期望 SHA256 | **manifest 无该版本条目**：`https://xiu-ci.com/xcagi-v1.0.0.1/manifest.json` 返回 404；`https://xiu-ci.com/releases/stable/manifest.json` 存在但 `version=1.0.0.0`（其条目为 1.0.0.0 的 dmg，不作为本版本基准） |
| 与 manifest 比对结果 | **PARTIAL** — 无线上基准；SHA256 在两轮独立脚本运行中实测值完全一致（下载完整性交叉验证） |
| 版本身份交叉佐证 | dmg 内 `build-info.json.gitSha = 0df6e1a0…` 与 OTA 通道 `releases/stable/enterprise/latest-mac.yml` 的 `buildSha = 0df6e1a0…` **完全一致** ✔ |
| 签名校验结果 | `codesign -dv`：`Authority=Developer ID Application: jialong Li (G26WSH472M)`、`TeamIdentifier=G26WSH472M`、`Identifier=com.xcagi.desktop.enterprise`；`codesign --verify --deep --strict` **PASS**（签名完整）；`spctl -a -vv -t execute` → **`accepted`，`source=Notarized Developer ID`** ✔ |
| 安装结果 | **PASS** — `hdiutil attach -nobrowse -readonly` 挂载 `/Volumes/XCAGI-Enterprise` → `ditto` 拷贝 `.app` → `hdiutil detach` 卸载成功 |
| 安装后版本核对 | Info.plist `CFBundleShortVersionString=1.0.0.1`；`build-info.json`：`{"schema_version":1,"gitSha":"0df6e1a075dd40abdbdbacca222ac4680ac3e0d0","version":"1.0.0.1","builtAt":"2026-08-27T23:47:55.396Z"}`；`product-sku.json`：`{"sku":"enterprise","schema_version":1}` |
| 系统拦截弹窗 | 无（未走 GUI 双击；Gatekeeper 判定以 `spctl accepted` + Notarized Developer ID 佐证） |
| **本步结论** | **PASS**（SHA256 校验为 PARTIAL：线上 manifest 未发布 1.0.0.1 条目，属发布流程缺陷，见第 6 节 D-01） |

---

## 3. 冷启动

| 字段 | 值 |
|------|-----|
| 启动方式 | **SKIP** |
| 启动耗时 | 未测（见 SKIP 原因） |
| 主窗口截图路径 | 无（启动步骤跳过，无截图） |
| 后端健康检查结果 | 未测（17500 端口被现有实例占用，见下） |
| 17500 端口监听进程 | 验收前即为现有实例的 `xcagi-bac`（PID 56592，`/Applications/XCAGI.app/Contents/Resources/backend/xcagi-backend`） |
| 前端渲染完整性 | 未测 |
| **本步结论** | **SKIP + 原因** |

**SKIP 原因（如实记录）**：执行时本机已有正在使用的 XCAGI 实例（`/Applications/XCAGI.app`，主进程 PID 56548）：

1. 桌面壳启用单实例锁（`FHD/desktop/main.ts:67` `app.requestSingleInstanceLock()`）——第二实例会立即退出，无法完成冷启动链路；
2. 本地后端端口 17500 已被现有实例监听（`lsof` 实测），新实例健康检查会命中既有后端，计时无效；
3. userData 目录（`~/Library/Application Support/XCAGI/`）为共享数据目录，强行测试有干扰用户现有安装与数据的风险（任务红线：不动用户现有 XCAGI 安装）。

**替代证据（代码评审 + CI 冒烟）**：
- 真实启动链路：`FHD/desktop/e2e/desktop.e2e.spec.ts`（bootstrap → spawn 后端 → `/api/ping` 就绪探测 → splash → loadURL 主界面 → preload IPC）；
- 更新观察期启动链路：`FHD/desktop/e2e/update-rollback.e2e.spec.ts`（预置 rollback-marker → 观察期启动加载主界面）；
- 历史真机启动实测：本机同型号曾实测 `health_ready_sec=10`（见 [m01-mac-local-acceptance-2026-07-12.md](./m01-mac-local-acceptance-2026-07-12.md) 用例 2.1）。

---

## 4. OTA（在线自动更新）

| 字段 | 值 |
|------|-----|
| 更新源 URL（macOS） | `https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml` |
| latest-mac.yml 中 productVersion（目标版本） | `1.0.0.1` |
| 升级前版本号 | —（未执行） |
| 升级后版本号 | —（未执行） |
| Ed25519 签名校验 | 通道元数据含 `signature: ed25519:Zx6zZJAHjYqp9SLO…`（验签字段存在且非空；应用内验签动作未触达） |
| 观察期表现 | 未触达 |
| updater-events.jsonl 摘录 | 未收集（未执行 OTA） |
| **本步结论** | **SKIP + 原因：当前已是线上最新版本** — `latest-mac.yml` `productVersion=1.0.0.1` 与验收目标一致，无更高版本可升（协议 4.4 允许的如实标注场景） |

**通道可达性检查（本轮实测，协议 4.4 最低要求）**：
- `latest-mac.yml` HTTP 200，`version: 1.0.0`、`productVersion: 1.0.0.1`、`buildSha: 0df6e1a0…`、工件 `XCAGI-Enterprise-1.0.0.1-mac-arm64.zip`（size 256619660）、`minVersion: 1.0.0`、`stagingPercentage: 100`；
- 最近一次 OTA 闭环证据：[`desktop-ota-closed-loop-20260724/`](./desktop-ota-closed-loop-20260724/)。

---

## 5. 回滚

| 字段 | 值 |
|------|-----|
| 验证方式 | 替代证据（未在真实机注入坏更新） |
| 回滚前版本号 | —（未注入坏更新） |
| 回滚后版本号 | —（未注入坏更新） |
| rollback-applied.json 内容 | 未生成（未触发回滚；`~/Library/Application Support/XCAGI/rollback-applied.json` 不存在） |
| 回滚后健康状态 | 现有实例 health 正常运行中（非本轮验收对象） |
| 用户数据保留 | 未验证（未执行降级安装） |
| 界面提示截图 | 无 |
| **本步结论** | **PARTIAL** — 真实机未注入坏更新（避免破坏本机现有安装与数据）；回滚机制以自动化证据佐证：`FHD/desktop/rollback.test.ts`（prepareRollback / commitRollback / triggerRollback / rollback-applied.json 全链路单测）+ `FHD/desktop/e2e/update-rollback.e2e.spec.ts`（真实 Electron 链路：预置 marker → 观察期 → 5 秒稳定性窗口 → commitRollback 删除 marker） |

---

## 6. 缺陷与异常记录

| # | 步骤 | 严重度 | 描述 | 证据 | 状态 |
|---|------|--------|------|------|------|
| D-01 | 安装 | **P1（发布流程）** | 1.0.0.1 的公开 manifest 未发布：`https://xiu-ci.com/xcagi-v1.0.0.1/manifest.json` 返回 404，`releases/stable/manifest.json` 与 `download-release.json` 仍锁定 `version=1.0.0.0`（git_sha 656db7b7…）。latest*.yml 已更新到 1.0.0.1 但 manifest 未同步，官网下载页的 SHA256 校验基准缺失，验收只能以实测值留痕。疑似 `fhd-release-desktop.yml` 的 manifest 发布/`fix-mac-update-feed.yml` 只完成了 OTA 侧更新。 | 本文件第 2 节；`curl` 404 实测 | 待修 |
| D-02 | 安装 | P2 | 同一产品版本 1.0.0.1 存在两个构建批次：本机 `/Applications/XCAGI.app` 的 `gitSha=383c7b1393edf39df7b0c71cd1612edc8238e2f6`（builtAt 2026-08-27T04:06:19Z）与公开 dmg/`latest-mac.yml` 的 `gitSha=0df6e1a075dd40abdbdbacca222ac4680ac3e0d0`（builtAt 2026-08-27T23:47:55Z）。两者均自称 1.0.0.1，制品身份可用 gitSha 区分，但"同版本多批次并存"需在发布记录中登记以避免验收对象混淆。 | 本文件第 2 节 build-info 交叉数据 | 待登记 |
| D-03 | OTA | P2 | Windows stable 更新通道（`latest.yml`）仍为 `productVersion=1.0.0.0`（buildSha 656db7b7…，2026-07-13），未随 macOS 一起推进到 1.0.0.1——跨平台同版本 parity（D1-1 门禁关注点）当前不满足，Win10/Win11 验收将因无 1.0.0.1 Windows 工件而无法开展。 | `curl latest.yml` 实测 | 待修 |

（本轮无 P0。）

---

## 7. 证据文件清单

| 类型 | 路径 / 内容 |
|------|------|
| 下载文件 SHA256（两轮一致） | `a36a92cdc052df226f3c5b0ff442c40868596eeb534bdaa6bd4c02c9296f043b  XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg`（`shasum -a 256` 实测，文件 292930436 bytes） |
| codesign / spctl 输出 | 见第 2 节原文（`Developer ID Application: jialong Li (G26WSH472M)`；`accepted` + `Notarized Developer ID`） |
| build-info.json（dmg 内） | `{"schema_version":1,"gitSha":"0df6e1a075dd40abdbdbacca222ac4680ac3e0d0","version":"1.0.0.1","builtAt":"2026-08-27T23:47:55.396Z"}` |
| product-sku.json（dmg 内） | `{"sku":"enterprise","schema_version":1}` |
| latest-mac.yml（OTA 通道快照） | `productVersion: 1.0.0.1` / `buildSha: 0df6e1a0…` / `signature: ed25519:Zx6zZJAHjYqp9SLO…` / 工件 `XCAGI-Enterprise-1.0.0.1-mac-arm64.zip`（256619660 bytes）/ releaseDate 2026-08-27T23:55:27Z |
| 主窗口截图 | 无（冷启动 SKIP，见第 3 节；不建空 assets 占位） |
| 引导脚本原始输出 | 本轮执行留痕见对话记录；脚本可幂等重跑：`bash FHD/scripts/package/acceptance-macos.sh --version 1.0.0.1` |

---

## 8. 结论与签名

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 执行人 | Agent（Trae 自动化） | 2026-09-01 | （机器留痕） |
| 测试负责人复核 | 待人工复核 | | |

**最终结论**：

- [ ] **PASS** — 全部通过
- [ ] **FAIL** — 存在 FAIL 项
- [x] **PARTIAL** — 安装+签名+制品身份 PASS（SHA256 无线上基准记 PARTIAL）；冷启动 SKIP（现有实例冲突，附代码评审+CI 冒烟替代证据）；OTA SKIP（无升级目标，通道可达性 PASS）；回滚 PARTIAL（自动化佐证）。
  **允许技术签字**，但该版本 mac 真机验收的冷启动与 OTA 待下一次真实发布窗口在干净验收机上补测；
  Windows 侧因 D-03（无 1.0.0.1 Windows 工件）暂无法开展。

---

## 9. 复检记录（2026-09-09，脚本 `acceptance-macos.sh --version 1.0.0.1 --skip-launch` 重跑）

> 原第 1–8 节为 2026-09-01 快照，保持原文不改；本节为增量复检。

### 9.1 制品完整性：P0 复现并升级

同一 URL `https://xiu-ci.com/xcagi-v1.0.0.1/enterprise/XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg` 的字节内容在三次独立观测中互不相同：

| 观测时间 | 字节数 | SHA256（前 16 位） | 来源 |
|---|---|---|---|
| 2026-09-01（第 2 节） | 292,930,436 | `a36a92cdc052df22` | 脚本实测（两轮一致） |
| 当前 manifest 记录 | 290,432,409 | `7ab4fdc1de1974e6` | `xcagi-v1.0.0.1/manifest.json` |
| 2026-09-09（本次） | 293,401,820 | `c39bed60b92ce32d` | 脚本实测 → **SHA256 不一致，验收按 fail-closed 中止** |

结论：**下载 manifest 与线上实际制品脱节**——manifest 声称的 sha256 既不等于 9/1 实测值，也不等于今日实测值。脚本的门禁行为正确（发现不一致即停止），但暴露发布流程缺陷：制品被替换后 manifest 未同步再生。

### 9.2 制品身份漂移：D-02 恶化

同一产品版本 `1.0.0.1` 现观测到 **5 个不同构建 gitSha** 并存：

| gitSha | 身份载体 | 与 main 关系 |
|---|---|---|
| `0df6e1a0…` | 9/1 dmg 内 build-info + 当时 latest-mac.yml | 9/1 快照，已被后续构建覆盖 |
| `2e6f03bf…` | 当前下载 manifest `git_sha` 字段 | main 祖先（compare 状态 ahead） |
| `99854233…` | 当前 dmg 内 build-info + 当前 latest-mac.yml `buildSha` | main 祖先（ahead） |
| `1532f843…` | 本机 `/Applications/XCAGI.app` build-info | **diverged（已不在 main 历史）** |
| `383c7b13…` | 9/1 本机安装记录（第 6 节 D-02） | 历史批次 |

### 9.3 通道一致性：OTA feed 与制品一致（PASS）

- `latest-mac.yml`：`productVersion=1.0.0.1`、`buildSha=99854233…`、含 `signature: ed25519:7AX0…`（非空）；
- 实际 dmg 内 build-info `gitSha=99854233…` —— **OTA 通道与线上制品身份一致**；
- dmg 内 app：`codesign --verify --deep --strict` **PASS**；`spctl -a -t execute` → **accepted / source=Notarized Developer ID / Developer ID Application: jialong Li (G26WSH472M)**。

### 9.4 本机安装状态（新增异常）

`/Applications/XCAGI.app`（1.0.0.1 / build 1532f843）`codesign --verify --deep --strict` **FAIL**：`a sealed resource is missing or invalid`——本机安装副本在签名后被开发过程改动，不能作为发布制品验收对象；发布 dmg 本身校验通过（9.3）。

### 9.5 缺陷状态更新

| # | 状态变化 |
|---|---|
| D-01 | **部分修复**：`xcagi-v1.0.0.1/manifest.json` 已发布（不再 404），但 `git_sha/sha256` 与实际制品不符（9.1） |
| D-02 | **恶化**：同版本并存构建 2→5 个（9.2） |
| D-03 | **未修复**：`releases/stable/enterprise/latest.yml`（Windows）仍为 `productVersion=1.0.0.0 / buildSha=656db7b7…`（2026-07-13），Windows 真机验收仍被阻塞 |

### 9.6 收敛路径（R03 结论）

**当前"优化提交 / 主线 / 安装运行"三者不一致，R03 不能判 PASS。** 唯一收敛方式：PR#1826 合并后，以冻结的 main SHA 走一次完整 `Release Orchestrator`（security-preflight 双扫描 → verify-version-anchors → 单一构建批次），同批再生 OTA feed、下载 manifest 与 dmg/zip 制品，使所有身份载体绑定同一 `git_sha`；随后 Mac 端重跑本脚本（冷启动需先退出本机现有实例）+ Windows 端补 D-03 工件后验收。

---

*证据生成：2026-09-01；复检追加：2026-09-09（脚本 `acceptance-macos.sh` 重跑 + 通道/制品交叉取证）。*
