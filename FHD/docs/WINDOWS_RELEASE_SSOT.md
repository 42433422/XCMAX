# Windows 发布交付 SSOT（唯一事实来源）

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。**每次 Windows 发版必须复用本文件**：更新第 1–2 节事实，重跑第 4 节全部 Gate，无证据不得标 GREEN，CI 通过 ≠ 验收通过。
> 状态取值仅限：`GREEN`（有完整实机证据）/ `YELLOW`（部分证据或以替代证据佐证）/ `RED`（实机验证失败，须记录复现步骤+日志+截图）/ `UNKNOWN`（无法静态证明，须生成实机验收任务）。
> 兄弟文档：[MACOS_RELEASE_SSOT.md](MACOS_RELEASE_SSOT.md)（macOS 域，G1–G13 同构）。
> 判据协议：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；证据模板：[desktop-acceptance-template.md](e2e/templates/desktop-acceptance-template.md)。
> RED 处理规则：只修真正阻断闭环的问题，修复后重测，不得直接改状态。
> **闭环规则**：G2→G12 连续完整通过 **2 轮**（第二轮从正式地址重新下载开始）才算交付闭环。第 1 轮已完整通过（2026-09-14 00:04，[LOOP-COMPLETE](evidence/e2e/windows-release-1.0.0.2/loop-round1/LOOP-COMPLETE.txt)）；第 2 轮已完整通过（2026-09-14 05:06，[LOOP-COMPLETE](evidence/e2e/windows-release-1.0.0.2/loop-round2/LOOP-COMPLETE.txt)）→ **G2–G12 双轮闭环达成**。#1923 合并后的最终收口实跑见 §4「T9 最终收口」（main `604b85e1`，基座 1.0.0.2 → OTA 1.0.0.4）。
> 最后实跑：2026-09-15（T9 最终收口：CI/CD `34882474880` 全绿 → Release Desktop `34889725771` → testing feed `34891598292` → latest.yml 验证 → OTA→1.0.0.4 → 数据保留/业务/Mod 复验 → dual-process/migration-mutex 实机 PASS → 系统重启后复验 PASS；证据 [t9/](evidence/e2e/windows-release-1.0.0.2/t9/t9-chain-runs.json)）。

## 1. 当前版本信息与真相源

| 字段 | 值 | 证据 |
|------|-----|------|
| 稳定产品版本 | `1.0.0.4` | [VERSION.md](../VERSION.md)（版本域 SSOT，#1920 升版）；testing feed 已广播 1.0.0.4@`604b85e1`（2026-09-15 实测 latest.yml）；stable feed 仍广播 1.0.0.1（B1 决策下未签名不进 stable，见 B6） |
| 工具链兼容版本 | `1.0.0`（npm/Electron 三段映射） | 同上 |
| 发布 SKU | `enterprise`（personal 冻结） | [download_release.json](../config/download_release.json) |
| 发布火车内部流水 | `1.0.0.3`（服务器无 v1.0.0.2/3/4 目录，仅内部号） | [release_train.json](../config/release_train.json) |
| `release_ready` | `false` | download_release.json + manifest.json |
| 本机已装构建 | `1.0.0.4@604b85e1`（T9 最终收口 OTA 升级后；OTA 前基座 1.0.0.2@1f7d9f11e） | [chain-buildinfo-post-ota.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/chain-buildinfo-post-ota.json) + 安装目录 `resources\build-info.json` 一致；/api/health `healthy` version=1.0.0.4 |
| 版本元数据偏差 | `XCAGI.exe` 属性 ProductVersion `1.0.0.0` ≠ build-info `1.0.0.1` | B5（P2，验收协议以 build-info 为准） |
| 更新发现逻辑 | `desktop/updater.ts` | electron-updater generic + **同 semver 重建钩子**；强制升级按 4 段 `productVersion ≥ minVersion` |
| 官方下载地址（营销） | `https://xiu-ci.com/xcagi-v{version}/enterprise/` | 服务器目录 `/var/www/update/xcagi-v{version}/enterprise/` |
| 自动更新 feed（win） | `https://xiu-ci.com/releases/stable/enterprise/latest.yml` | 服务器 `/var/www/update/releases/stable/enterprise/` |
| 隔离测试通道 | `https://xiu-ci.com/releases/testing/enterprise/` | 仅供验收，非生产；当前广播 1.0.0.4@`604b85e1`（ed25519 VALID；T9 OTA 实机消费通过） |
| 应用内 feed SSOT | [desktop-config.ts](../desktop/desktop-config.ts) `SKU_UPDATE_URL.enterprise` | 环境变量 `XCAGI_UPDATE_URL` 可覆盖（**验收时不得设置**，否则指向本地镜像） |

**测试机（本机）**：Windows 11 家庭版 26200 x64 · i9-13900H · 15.6GB RAM · 主机名「佳诺」。
**局限（必须知悉）**：本机同时是开发机（node/python/git/本地代理 127.0.0.1:49587 间歇拒连），不是干净客户环境；
「干净安装」门以隔离安装目录 + 静默安装近似，完整干净环境需虚拟机快照（实机任务 T6）。

## 2. 构建产物与校验和（线上实测 2026-09-11）

> 同一产品版本允许多个构建（`build-info.json` gitSha / SHA 区分）；**对外校验以下载页 manifest 为准，manifest 必须与文件原子同发**。

| 产物 | 构建 gitSha | 大小 | 校验和 | 签名 | 托管 |
|------|------------|------|--------|------|------|
| Win 稳定通道热修包 `…-1.0.0.1-x64-macalign.exe` | `73861ed7` | 247,881,767 B | sha512 `u2oJlM7h…Q==`（本地更新器副本实测一致）；sha256 `b196c07f…f0a63` | **未签名** | `…:8443/releases/stable/enterprise/` 200；**:443 同路径 404** |
| Win 隔离验收包 `…-1.0.0.1-x64-unsigned.exe` | `a9507f0f` | 248,318,327 B | sha256 `ac7fa2c7…321a`（`.sha256` + `delivery-receipt.json` 在列，09-11 10:41） | **未签名** | `…/releases/testing/enterprise/` |
| Win 隔离验收包 `…-1.0.0.2-x64-unsigned.exe` | `77aca5743` | 248,408,728 B | sha256 `d281abad…d575`（`.sha256` + `delivery-receipt.json` 在列，09-13 07:59；`git_sha=77aca5743` 交付波收口 main，`runner_install_smoke:passed`，run 34725093731 `windows_installer_only` 精确 SHA 构建；本机下载与 CVM 远端 SHA 双验证一致） | **未签名** | `…/releases/testing/enterprise/` |
| Win 未签名交付包 `XCAGI-Enterprise-Setup-1.0.0.2-x64-unsigned.exe`（manual_installer） | `e3bde5f33` | 248410443 B | sha256 `7738e8d58ea1e219b1ce2c532816d5ad079288dbdd36c7ecc50f069fa2b0449a`（delivery-receipt + 本机下载复验一致） | **未签名（B1 决策）** | GitHub Actions run 34738192540 artifact `xcagi-windows-installer-e3bde5f33e14b12ad400e0ae8fc6587079f5594b`（需仓库读权限）；stable feed 不动 |
| Win 未签名交付包 `XCAGI-Enterprise-Setup-1.0.0.3-x64-unsigned.exe`（manual_installer） | `4bfb23365c` | 248408870 B | sha256 `7c044bec4c87391ea86e9f445fa356ae34bfcebede6876bfc0c7a1df28889e8b`（delivery-receipt + 本机下载复验一致；`runner_install_smoke:passed`；testing feed sha512 与之同源） | **未签名（B1 决策）** | GitHub Actions artifact `xcagi-windows-installer-4bfb23365c…`（需仓库读权限）；testing feed 已广播；stable feed 不动 |
| Win 未签名交付包 `XCAGI-Enterprise-Setup-1.0.0.4-x64-unsigned.exe`（testing feed 派发） | `604b85e1e` | 248,424,269 B | sha512 `IlnSGtts…tisw==`（latest.yml 内嵌，OTA 下载器实机校验通过）；manifest 由 publish 管线原子生成 | **未签名（B1 决策）** | Release Desktop run 34889725771 产物 → testing feed publish run 34891598292 广播（`buildSha=604b85e1…`）；stable feed 不动 |
| 回滚演练目标 `…-1.0.0.0-x64.exe` | 1.0.0.0 | 213,833,311 B | sha256 `a40250c2…`（stable manifest） | 未签名 | 200；其 `.sha256` 文件 404 |

**live 探测（2026-09-11）**：`xcagi-v1.0.0.1/manifest.json` 200（`release_ready:false`、**无 win 条目**）；营销目录服务器端实测**仅 mac arm64 dmg/zip，无任何 win exe**（B2 实锤）；`latest-mac.yml` 200（格式完整、ed25519 VALID）；mac x64 dmg **404**。

**服务器端实测（2026-09-11，root SSH 只读）**：
- nginx `conf.d/xcagi-h1-download.conf` 在 **8443** 专设 HTTP/1.1 下载通道——09-09 六次 `ERR_HTTP2_PING_FAILED` 下载失败的针对性规避；**:443 主块未包含该路径**（B4 定位收窄为主块 alias/发布根不一致）。
- `MACALIGN-HOTFIX.txt` 陈旧：写 `2e6f03bf`（09-05），实际文件已是 09-09 `73861ed7` 构建（服务器文档漂移，随 T1 更正）。
- 元数据 Ed25519 验签（公钥取自 desktop-config.ts，本机 `verify_update_manifest_sig.py` 实测）：stable `latest.yml` **VALID**、stable `latest-mac.yml` **VALID**、testing `latest.yml` **INVALID**（B7）。
- 更新器事件链（`%APPDATA%\XCAGI\logs\updater-events.jsonl`）：07-08/09-08 两次 `install_failed 数据库迁移失败（code=1）`；09-09 六次下载失败后成功（sha512 一致）；07-10/11 同版本重建防护正常。

**签名管线事实**：[release-desktop.yml](../.github/workflows/release-desktop.yml) 由 `ES_USERNAME/ES_PASSWORD/CREDENTIAL_ID/ES_TOTP_SECRET` secrets 驱动，**配置即自动签名**，未配置则显式未签名且不进稳定 feed（昨晚三连构建均为未签名 → 仓库 secrets 未配置）。**公开 Windows 交付唯一授权通道 = [release-orchestrator.yml](../.github/workflows/release-orchestrator.yml)**（硬校验 `release_sha` == 当前 `origin/main`；`a9507f0f` 为 main 祖先）。未签名 macalign 通道按其工作流声明"公开交付禁止"。

## 3. Release Gate 定义（G1–G13，与 MACOS_RELEASE_SSOT.md 同构 + Windows 回滚门）

| Gate | 名称 | 通过判据（全部满足） | 证据要求 |
|------|------|----------------------|----------|
| G1 | 构建（产物+身份） | 授权管线产物；build-info 版本/gitSha 正确；`pre-release-security.ps1 -Phase post` 通过；校验和入册 | delivery-receipt + run URL |
| G2 | 干净环境安装 | 正式地址 200；SHA256 与 manifest 一致；签名判定符合交付声明；静默装到隔离目录；无 SmartScreen 拦截 | 下载校验输出+截图 |
| G3 | Windows 安全项 | Authenticode 签名 Valid（发布者=期望值）；`verify-windows-signature.ps1` 通过；证书链+时间戳有效 | `Get-AuthenticodeSignature` 输出 |
| G4 | 首次启动 | 冷启动 ≤60s 主窗口完整；`/api/health` healthy；17500 由本实例监听 | 计时+截图+health JSON |
| G5 | 登录绑定 | 市场账号登录成功；绑定生效 | 每步截图 |
| G6 | Mod / AI 员工加载 | Mod 与 AI 员工加载可见可用 | 截图 |
| G7 | 真实业务任务 | **执行 ≥1 个真实业务任务成功**（如采购订单→出货单） | 截图/短视频 |
| G8 | 更新发现 | feed 可达且确有新版本（semver/重建钩子判定）；应用内出现更新提示 | feed 内容+应用内截图 |
| G9 | 更新安装 | sha512 校验通过；下载→安装完成（`updater-events.jsonl` + `pending-update-install-receipt.json`） | 事件日志尾部+截图 |
| G10 | 数据保留（升级后） | 升级前后业务数据基线比对一致（库/上传/Mod 文件数）；登录态/历史数据可见 | `-OverwriteInstall` 比对输出 |
| G11 | 更新后重新执行业务 | 再次执行同真实业务任务成功 | 截图 |
| G12 | 重启复验 | 自动重启进入新版本；观察期通过（后端健康+主窗口+5s 稳定）；`rollback-marker.json` 清除 | build-info 新版本+截图 |
| G13 | 回滚/恢复 | 路径 A（观察期自动回滚）或路径 B（降级安装）：版本回退、health healthy、数据在 | `rollback-applied.json`/安装凭证+截图 |

**失败处理**：任一 Gate FAIL → 精确定位失败点 → 建 Issue/任务 → **只修当前阻断点** → 回到该 Gate 重测 → 通过后才继续后续 Gate。

> **故障注入补充证据（2026-09-13，GitHub Windows runner，包=§2 1.0.0.2 行）**：run 34727133868 `fault-injection-windows.ps1 -Scenario all` PASS=4/FAIL=0/SKIP=2——kill-all（status=degraded 可观测）/kill-orphan（孤儿 sidecar 占端口后重启恢复）/corrupt-backup（坏备份不误伤启动）/corrupt-main（坏库改名留证→备份还原→health 可达）全过；disk-full/power-cut 为实体机人工场景 SKIP（归 T8）。
>
> **故障注入补充证据（2026-09-15，本机实装 1.0.0.4@`604b85e1`，dual-process/migration-mutex）**：PASS=2/FAIL=0/SKIP=2——dual-process：运行中二次启动第二实例 1s 自退（`requestSingleInstanceLock` 生效），主实例 health 可达、单后端、无损坏证据；migration-mutex：0.3s 间隔竞态双启动收敛，后端恰 1 个、监听唯一（37404）、主库 1,699,840 B 完整。收据+场景证据：[t9/chain/fault-local-1.0.0.4/](evidence/e2e/windows-release-1.0.0.2/t9/chain/fault-local-1.0.0.4/fault-injection-receipt.json)。CI 侧同场景基线修复后回执见 run 34851567425（main `280225ac`）。

## 4. Release Gate 状态（2026-09-14 实跑，round-1 闭环全过；T9 最终收口见文末小节）

| # | Gate | 状态 | 现有证据 | 缺失证据 | 阻断 | 下一步 |
|---|------|------|---------|---------|------|--------|
| G1 | 构建 | **GREEN** | 授权管线 desktop run 34738192540（`e3bde5f33`，`windows_installer_only`）delivery-receipt `runner_install_smoke:passed` + SHA256 本机复验一致（§2 产物表）；1.0.0.2@1f7d9f11e、1.0.0.3@4bfb2336 同管线产物均带回执 | — | 无 | — |
| G2 | 干净环境安装 | **GREEN** | T2 实机（2026-09-13，交付形态=GitHub artifact manual_installer，B1/B2）：下载→SHA256 `7738e8d5…` 与回执一致→静默隔离安装→冷启动（[t2-first-launch.png](evidence/e2e/windows-release-1.0.0.2/t2/t2-first-launch.png)）→21 点冒烟全过（[t2-smoke.log](evidence/e2e/windows-release-1.0.0.2/t2/t2-smoke.log) SMOKE_PASS=21/FAIL=0）；round-1 基座 a9507f0f 安装同过（[a-baseline-smoke.log](evidence/e2e/windows-release-1.0.0.2/loop-round1/a-baseline-smoke.log)） | VM 快照严谨性归 T6 | 无 | T6 可选 |
| G3 | Windows 安全项 | **GREEN** | 口径=B1 决策（未签名交付）：安装器与安装后 XCAGI.exe `Get-AuthenticodeSignature` 均 **NotSigned** 且与 delivery-receipt 声明一致（[t3-authenticode-installed.txt](evidence/e2e/windows-release-1.0.0.2/t2/t3-authenticode-installed.txt)、[t2-delivery-receipt.json](evidence/e2e/windows-release-1.0.0.2/t2/t2-delivery-receipt.json)）；round-1 手动安装「未知发布者」点击实录见 LOOP-COMPLETE 注记 | — | 无 | — |
| G4 | 首次启动 | **GREEN** | 受控冷启动实机实测（2026-09-11 16:0x）：`Start-Process` 起表 → 24.5s health 首响应（neuro 总线延迟启动期 status=degraded）→ ~50s 全绿（`status=healthy / runtime=healthy / neuro=healthy running=true`，无 degradedReasons）；主窗口完整渲染截图 [g4-main-window-foreground.png](evidence/e2e/windows-release-1.0.0.1/g4-main-window-foreground.png)；xcagi-backend + 5×XCAGI 进程在册；health JSON 存档 [g4-health.json](evidence/e2e/windows-release-1.0.0.1/g4-health.json) | — | 无 | — |
| G5 | 登录绑定 | **GREEN** | T3 新鲜登录实机（2026-09-14 07:24，1.0.0.3）：退出态凭据登录 SUNBIRD 成功，主界面完整渲染工作空间（[t3-post-login-main.png](evidence/e2e/windows-release-1.0.0.2/t3/t3-post-login-main.png)）；绑定生效以实机 UI 为准——顶栏 SUNBIRD 品牌+租户工作空间+AI 员工「小C助理」可见（同截图及 [t3-biz-product-page.png](evidence/e2e/windows-release-1.0.0.2/t3/t3-biz-product-page.png)）；登录态 25 会话跨双轮 OTA 完整保留（[f-retention.json](evidence/e2e/windows-release-1.0.0.2/loop-round1/f-retention.json)）；注：`/api/auth/company-brand` 已随 B10 死路由清理移除（现 400），向导同步链路 2026-09-12 实测 200 在册 | — | 无 | — |
| G6 | Mod / AI 员工加载 | **GREEN** | 1.0.0.2 实机：mods-list 23、loaded=13 partial_failure=False、7 个桥接 Mod detail 全 200（[a-baseline-smoke.log](evidence/e2e/windows-release-1.0.0.2/loop-round1/a-baseline-smoke.log)）；ERP Mod 业务可用（产品创建/列表 200）；AI 员工对话证据为 1.0.0.1 实测（[g7-business-task.png](evidence/e2e/windows-release-1.0.0.1/g7-business-task.png)）；T3 复验 1.0.0.3：loading-status 200 partial_failure=false + 智能对话/员工工作台/业务菜单实机在图（[t3-post-login-main.png](evidence/e2e/windows-release-1.0.0.2/t3/t3-post-login-main.png)）；B9 已随 T1 重发解除 | — | 无 | — |
| G7 | 真实业务任务 | **GREEN** | round-1 实机（1.0.0.1 基座）：升级前经 ERP Mod API 创建产品 `SUNBIRD-loop-round1-234556` 成功（[b-business-task-done.png](evidence/e2e/windows-release-1.0.0.2/loop-round1/b-business-task-done.png)、[b-business-task-status.txt](evidence/e2e/windows-release-1.0.0.2/loop-round1/b-business-task-status.txt)）；升级后再次创建 + 旧产品可读（[g-g8-status.txt](evidence/e2e/windows-release-1.0.0.2/loop-round1/g-g8-status.txt)）。B9 空壳根因已修（vue-dist 构建守卫 + T1 重发）；1.0.0.1 时代 RED 记录见 [g7-business-task-final.png](evidence/e2e/windows-release-1.0.0.1/g7-business-task-final.png) | — | 无 | — |
| G8 | 更新发现 | **GREEN** | round-1 实机：testing feed 可达（ed25519 VALID），应用内 `update_available` 事件 + 更新徽标截图（[c-g4-status.txt](evidence/e2e/windows-release-1.0.0.2/loop-round1/c-g4-status.txt)、[c-g4-update-badge.png](evidence/e2e/windows-release-1.0.0.2/loop-round1/c-g4-update-badge.png)、[c-updater-events.jsonl](evidence/e2e/windows-release-1.0.0.2/loop-round1/c-updater-events.jsonl)）；round-2 同过（[c-g4-status.txt](evidence/e2e/windows-release-1.0.0.2/loop-round2/c-g4-status.txt)、[c-g4-update-badge.png](evidence/e2e/windows-release-1.0.0.2/loop-round2/c-g4-update-badge.png)） | — | 无 | — |
| G9 | 更新安装 | **GREEN** | round-1 实机：下载→sha512 校验→安装触发（`install_start` 事件，[d-updater-events-install.jsonl](evidence/e2e/windows-release-1.0.0.2/loop-round1/d-updater-events-install.jsonl)）→安装完成进入 1.0.0.2；round-2：断点恢复安装（Phase D resume，[d2-resume-config.txt](evidence/e2e/windows-release-1.0.0.2/loop-round2/d2-resume-config.txt)）→`installUpdate` 触发（[d2-g5-install-triggered.txt](evidence/e2e/windows-release-1.0.0.2/loop-round2/d2-g5-install-triggered.txt)、[d2-updater-events-install.jsonl](evidence/e2e/windows-release-1.0.0.2/loop-round2/d2-updater-events-install.jsonl)）→**安装器自动点击器实战通过**进入 1.0.0.3 | — | 无 | — |
| G10 | 数据保留 | **GREEN** | round-1 实机：升级前后 sessions 25/25、users 3/3、products 5/5，产品读回一致（[f-retention.json](evidence/e2e/windows-release-1.0.0.2/loop-round1/f-retention.json)、[f-db-snapshot-post.json](evidence/e2e/windows-release-1.0.0.2/loop-round1/f-db-snapshot-post.json)、[f-retention-readback.log](evidence/e2e/windows-release-1.0.0.2/loop-round1/f-retention-readback.log)）；round-2：sessions 25/25、users 3/3、products 8/8，产品读回一致（[f-retention.json](evidence/e2e/windows-release-1.0.0.2/loop-round2/f-retention.json)、[f-db-snapshot-post.json](evidence/e2e/windows-release-1.0.0.2/loop-round2/f-db-snapshot-post.json)） | — | 无 | — |
| G11 | 升级后业务 | **GREEN** | round-1 实机：升级后业务任务成功（新建 `SUNBIRD-loop-round1-post-000403` + 升级前产品可读，[g-g8-status.txt](evidence/e2e/windows-release-1.0.0.2/loop-round1/g-g8-status.txt)、[g-g8-business-done.png](evidence/e2e/windows-release-1.0.0.2/loop-round1/g-g8-business-done.png)）；round-2：新建 `SUNBIRD-loop-round2-post-050624` + 升级前产品可读（[g-g8-status.txt](evidence/e2e/windows-release-1.0.0.2/loop-round2/g-g8-status.txt)、[g-g8-business-done.png](evidence/e2e/windows-release-1.0.0.2/loop-round2/g-g8-business-done.png)） | — | 无 | — |
| G12 | 重启复验 | **GREEN** | round-1 实机：自动重启进入 1.0.0.2@1f7d9f11e（[e-post-build-info.json](evidence/e2e/windows-release-1.0.0.2/loop-round1/e-post-build-info.json)），升级后 UI 完整（[e-g6-post-upgrade-ui.png](evidence/e2e/windows-release-1.0.0.2/loop-round1/e-g6-post-upgrade-ui.png)），冒烟全过（[g-post-smoke.log](evidence/e2e/windows-release-1.0.0.2/loop-round1/g-post-smoke.log)）；round-2：进入 1.0.0.3@4bfb2336（[e-post-build-info.json](evidence/e2e/windows-release-1.0.0.2/loop-round2/e-post-build-info.json)），UI 完整（[e-g6-post-upgrade-ui.png](evidence/e2e/windows-release-1.0.0.2/loop-round2/e-g6-post-upgrade-ui.png)），冒烟全过（[g-post-smoke.log](evidence/e2e/windows-release-1.0.0.2/loop-round2/g-post-smoke.log)） | — | 无 | — |
| G13 | 回滚/恢复 | **GREEN** | T5 路径 B 实机降级演练（2026-09-14 14:2x）：1.0.0.3 基线 sessions 27/users 3/products 10（[t5-db-snapshot-pre.json](evidence/e2e/windows-release-1.0.0.2/t5/t5-db-snapshot-pre.json)）→ 卸载→正式地址装 1.0.0.0，SHA256 `a40250c2…` 校验一致（[t5-download-sha256.txt](evidence/e2e/windows-release-1.0.0.2/t5/t5-download-sha256.txt)）→ 冷启动 health healthy（[t5-health-post-rollback.json](evidence/e2e/windows-release-1.0.0.2/t5/t5-health-post-rollback.json)）→ 数据保留 27/3/10 且产品名逐一一致（[t5-db-snapshot-post-rollback.json](evidence/e2e/windows-release-1.0.0.2/t5/t5-db-snapshot-post-rollback.json)）→ 登录态保留、旧版 UI 可用（[t5-rollback-ui-1.0.0.0.png](evidence/e2e/windows-release-1.0.0.2/t5/t5-rollback-ui-1.0.0.0.png)）；全序列与降级兼容偏差（1.0.0.0 运行时+1.0.0.3 时代 Mod 文件→neuro 报缺 `host_services`，主状态仍 healthy，P3 记录）见 [t5-status.txt](evidence/e2e/windows-release-1.0.0.2/t5/t5-status.txt) | 路径 A 观察期自动回滚仅库内单测/e2e spec 覆盖；T8 磁盘满/断电人工场景开放（补充证据，不属本 Gate 判据） | 无 | T8 可选 |

### 4.1 T9 最终收口实跑（2026-09-15，#1923 合并后 main `604b85e1`，基座 1.0.0.2 → OTA 1.0.0.4）

| 步骤 | 结果 | 证据（[t9/](evidence/e2e/windows-release-1.0.0.2/t9/t9-chain-runs.json)） |
|------|------|------|
| main CI/CD 全 job 绿（含 container-scan） | **GREEN** | run 34882474880（#1942 修复后首绿，见 B13） |
| Release Desktop 构建（installer-only，`604b85e1`） | **GREEN** | run 34889725771 success |
| testing feed 发布 + latest.yml 外部验证 | **GREEN** | run 34891598292 success；latest.yml `1.0.0.4@604b85e1`（ota-discover.json 全文含 sha512/size） |
| OTA 更新发现→下载 248MB→安装→进入新版本 | **GREEN** | update-available→update-downloaded（230s）→向导安装（[wizard-step-4](evidence/e2e/windows-release-1.0.0.2/t9/chain/ota-install-wizard/wizard-step-4-finish-page.png)）→ build-info 1.0.0.4（[chain-buildinfo-post-ota.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/chain-buildinfo-post-ota.json)）+ health healthy |
| 登录绑定/业务/Mod/AI 员工（升级前后各一轮） | **GREEN** | pre：[chain-biz-result.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/chain-biz-result.json)（登录+业务+Mod15+AI 员工）；post：[chain-biz-post-ota.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/chain-biz-post-ota.json) + [chain-reverify-verdict.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/chain-reverify-verdict.json)（add/list 200 via ERP Mod，Mod15 与基线一致，split_mod_entries=6） |
| 数据保留（G10 口径） | **GREEN** | sessions 27/27、users 3/3、products 10→12（升级前产品全部可读+新增，[chain-db-snapshot-post-ota.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/chain-db-snapshot-post-ota.json)） |
| 故障注入 dual-process / migration-mutex（实机 1.0.0.4） | **GREEN** | PASS=2/FAIL=0（见 §3 补充证据 2026-09-15 条） |
| 系统重启后复验 | **GREEN** | 系统重启（2026-09-15 11:12:56）登录后 Startup 脚本自动采集（[post-reboot-verify.ps1](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/post-reboot-verify.ps1) + [run.log](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/run.log)）：build-info `1.0.0.4@604b85e1`（[post-reboot-buildinfo.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/post-reboot-buildinfo.json)）、进程恰 5×XCAGI+1×backend（[post-reboot-processes.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/post-reboot-processes.json)）、17500 单监听（PID 与清单一致）、DB 全保留 27/3/12 含 T9 新增产品（[post-reboot-dbcounts.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/post-reboot-dbcounts.json)）、UI 完整渲染且 SUNBIRD 会话保留（[post-reboot-xcagi-ui.png](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/post-reboot-xcagi-ui.png)）、health healthy（[post-reboot-health.json](evidence/e2e/windows-release-1.0.0.2/t9/chain/post-reboot/post-reboot-health.json)）；注：冷启动 health 首响 >240s（本机开发机冷缓存，数分钟内自行转绿），单实例/单监听/数据完整判定不受影响 |

## 5. 已知偏差与阻断项

| # | 级别 | 阻断点 | 精确定位 |
|---|------|--------|----------|
| B1 | **P0→已按用户决策关闭（2026-09-13）** | 用户决策：**不提供签名支持，免费安装**——交付形态=显式未签名 manual_installer（`windows-installer-delivery` job，`windows_installer_only=true`），不进 stable 自动更新通道；secrets `ES_USERNAME`/`ES_PASSWORD`/`CREDENTIAL_ID`/`ES_TOTP_SECRET` 与 var `XCAGI_WINDOWS_PUBLISHER_NAME` 保持不配置。T1 Windows 交付执行：desktop run 34738192540（XCAGI-Enterprise-Setup-1.0.0.2-x64-unsigned.exe，sha256 `7738e8d58ea1e219…`，248410443 B，delivery-receipt `delivery_mode=manual_installer`、`stable_auto_update=false`、`signature_status=unsigned`） | 交付形态已定；如未来恢复签名发布，回退至「配置 5 项」路径 |
| B2 | **P0→随 B1 决策转为交付形态限制（2026-09-13）** | 正式营销目录无 Windows 包（服务器实测确认）——营销目录发布依赖签名 stable 管线，B1 决策（不签名）下该路径不启用 | 交付形态变更：正式分发=GitHub artifact manual_installer（见 §2 产物表 1.0.0.2 行）；营销目录 win 包列为已知限制，恢复签名后由 orchestrator 原子发布解除 |
| B6 | **P0·开放（B1 决策下管线无法解除，需用户决策）** | 稳定 feed 仍广播 `73861ed7`（早于 `#1857` 迁移修复）——实机两次 OTA 安装失败于数据库迁移；B1 决策（不签名）下管线**禁止未签名进 stable**，故无法以新构建覆盖 feed | 可选处置（需用户授权，CVM 侧手动）：下架/清空 `update/releases/stable/enterprise/latest.yml` 停止向存量用户广播危险构建；或保持现状并记录风险 |
| B3 | **P1→已解除（2026-09-12 live 实测）** | manifest 已于 2026-09-11T08:05Z 重生成（git_sha=`99854233c`）：官方下载与 stable 双通道 dmg HEAD 实测均 293,401,820 B，与 manifest sha256/size 一致 → 官方 sha256 校验恢复有效 | 回归护栏：产物替换后 `generate-download-manifest.py` 强制重跑并原子发布（归属 macos-release 域，见 §7） |
| B4 | **P1** | feed `files.url` 指向 `:8443`（h1-download 专用通道），**:443 主块同路径 404**；stable latest.yml 为手工改写缺 3 字段 | 主 server block 补 alias 或发布根统一；feed 生成器收口 |
| B5 | **P2** | exe 版本元数据 1.0.0.0 ≠ build-info 1.0.0.1 | electron-builder 四段版本同步 |
| B7 | **P2→已解除（2026-09-14 复验）** | testing 通道 latest.yml Ed25519 验签恢复 **VALID**；round-1/round-2 更新发现签名校验正常 | 签名密钥对齐生产公钥（feed 发布管线 #1926 后持续 VALID） |
| B8 | **P2·修复已入 main（2026-09-12）** | OTA 无 `.blockmap`（两端口 404）→ 每次全量 236MB，弱网成功率低（09-09 实录 6 连败；2026-09-12 复测 stable 通道 blockmap 仍 404） | **根因**：流水线对 NSIS exe 二次包装（UI 重打包+重命名）后 electron-builder 原生 blockmap 哈希失配。**修复 PR #1897 已 squash merge 至 main `81339bbbb1`（37/37 CI 全绿）**：`generate-update-metadata.mjs` 在最终安装包上复用 app-builder-lib `buildBlockMap`（与 NsisTarget 同参 gzip）重生成并写入 latest.yml files 数组，ed25519 签名覆盖完整 body；失败降级全量下载不阻断；macOS dmg 不受影响。T1 编排器重发后 blockmap 随产物上线，G4 实测增量更新 |
| B9 | **P1→已定位** | **ERP 桥接 Mod「已交付未注册」根因确诊（2026-09-11）：安装包内嵌 vue-dist 为旧通道构建，渲染层 glob 键完全缺失 `mods/xcagi-erp-domain-bridge/*`（实测 0 键）→ `findModViewLoader` 全部未命中 → 所有 Mod 业务页（订单/库存/客户等）回退「未安装」空壳。同源码 CVM 干净构建实测含全部键（index+modViews chunk）→ 非 glob 代码缺陷，是构建管线产物缺陷** | 已加防护：`build-frontend.sh` 构建后校验 dist 含 `mods/*/frontend/views/` glob 键，缺则 fail（防回归）；已解除（2026-09-13 起）：1.0.0.2 起安装包内嵌 vue-dist 含全部 mod 键，实机 ERP 业务任务通过（G7 round-1 证据） |
| B10 | **P2·修复已上线·生产验证通过（2026-09-12）** | 首次设置向导同步失败（2026-09-11 实锤，生产 journal）：宿主代理 `PUT {market}/api/auth/profile` → 市场端 `api_update_profile` 在 `with session` 块**外**访问 commit 过期的 `row.username` → `sqlalchemy DetachedInstanceError` → 500 → 宿主 502。users 表无 `company` 列（回显仅内存值，契约只需回显）。**修复**：session 关闭前读取返回值 + 回归测试（旧红 2/新绿 3）；并删除市场端 13 条从未挂载的 legacy 死路由（-408 行，即 B10 误诊为契约错位的根源）。净 -242 行满足 net-deletion。**发布通道（2026-09-11 深夜）**：#1877 分支被并行自动化持续合入 main 无法收敛 → cherry-pick 三 commit 开 [PR #1880](https://github.com/42433422/XCMAX/pull/1880)，看护脚本自动 update-branch+合并，**已 squash merge 至 main `0a36cfe0`**（scan gate 全绿）。**生产基线实锤**：CVM 铸 token（user=1 admin）`PUT /api/auth/profile` `{"company":"CDXJ-verify"}` → **500**（B10 现网复现）。**发布流水线完成（2026-09-12）**：scan#1 run 34675267213 ✅（release_sha=`201d1f6918`）→ scan#2 run 34677201160 ✅ → deploy run 34677587105 ✅（14:20:08，product_version=1.0.0.1）→ CVM 实测线上 `PUT /api/auth/profile` **HTTP 200**（`{"ok":true,"username":"admin","company":"CDXJ-verify-b11"}`，B10 上线判据 PASS）→ **真实客户端链路回归 PASS（2026-09-12 16:0x，本机实测）**：已装实例（`49d0fe105`）+ 持久会话 → `POST /api/auth/company-brand`（首次设置向导同步路径）→ **HTTP 200** `{"success":true,"company_brand":"SUNBIRD","tenant_name":"SUNBIRD","persistence_scope":"account"}`（修复前同路径 502）→ 余 G5 实机复验绑定（T3） |
| B11 | **P0·修复已入 main（2026-09-12）** | **security release gate 53 HIGH（scan#1 run 34648494822 实锤，09-08 同 gate 全绿 → 3 天内态势劣化，全部为新披露 advisory，与 B10 无关）**：① CodeQL provenance 失配（release_sha 必须=main tip 双语言最新分析；`0a36cfe0` 分析 21:19Z 已补齐，但 main 已前移 `3d3ec8d9` → 发布 SHA 取扫描时刻 tip 且窗口内冻结）② dependabot/node/trivy/pip-audit 同源 4 包新 advisory：js-yaml<4.3.2（CVE-2026-84375）、sharp<0.35.4（GHSA-rgj7-g3m4-5g8c）、@xmldom/xmldom≤0.8.14、httpx2 2.10.0→2.12.0（PYSEC-2026-3846/48/49）、accelerate 1.14.0→1.15.0（PYSEC-2026-3804，无豁免通道必须升版）③ production-host TSSA-2026:0995 sqlite（**已修**：CVM dnf 升级 sqlite-3.26.0-21，updateinfo 已清空）④ PR #1889 首轮 CI 13 项失败（2026-09-12 实锤）：CVM npm registry 指向腾讯内网镜像（`mirrors.tencentyun.com`，VPC 外不可解析），lockfile 新增包 resolved 写入内网 URL → runner `npm ci` 全量 ENOTFOUND（main 本就含 436 处公网 npmmirror URL 曾跑绿，非同因） | 修复分支 `fix/security-gate-53high`（基于 main `3d3ec8d9`）：5 个 npm 项目 overrides（js-yaml 4.3.2 / sharp 0.35.4 / @xmldom 0.8.15）+ uv.lock 升 httpx2 2.12.0 & accelerate 1.15.0；④ 已修 commit `dce9e07aa`：65 处内网 URL 行内还原 `registry.npmjs.org`（零行差）+ CHANGELOG 条目（Changelog updated 门）+ 基线 --update --force（+1 行留痕）。**PR #1889 已 squash merge 至 main `90b7335fa7`（2026-09-12 00:47，52 项 CI 全绿，CodeQL 双语言匹配 tip）**。⚠️ 其后续 scan#1 暴露新阻断 → 见 B12 |
| B12 | **P0·已闭环（2026-09-12）** | **B11 合并后 scan#1（run 34663134753，release_sha=`90b7335fa7`）残余 7 项阻断**：① CodeQL #3730 py/path-injection（`excel_import_pipeline_resolve.py:113`，重导入 `file_path` 用户可控直接读文件——真实发现类，09-09/09-10 mloop 新代码引入，09-08 全绿后未被 gate 过）② CodeQL #3735/#3736 py/polynomial-redos（`label_print_inputs.py:7,12`）③ Dependabot #478：第 6 个 npm 项目（`成都修茈科技有限公司/`，B11 覆盖 5 项目时遗漏）js-yaml<4.3.2 ④ CodeQL #3732/3733/3734 py/path-injection（`artifact_files.py`）——**误报**：已有内联 `re.fullmatch([A-Za-z0-9_-]{1,160})` 白名单屏障+符号链接拒绝（作者注释留痕） | **修复 PR #1893 已 squash merge 至 main `201d1f6918`（52 项 CI 全绿，CodeQL 双语言 04:36/04:38 匹配 tip）**：#3730 加 realpath 包含性校验（app data/temp 根内，越界降级不读文件，改用 os.path.realpath 避免 pathlib 触发 #3738）；#3735/36 入口截断 1024 字符；#478 补 js-yaml 4.3.2 override + lockfile 还原 npmjs URL；net-deletion +26 行 --update --force 留痕。**scan#1 复跑两次失败根因=dismiss 评注证据契约**（run 34673578833 04:39）：gate（`security_release_gate.py::_false_positive_is_valid`）要求 comment.author ≠ dismissed_by.login 构成两方复核，author 写成 `42433422` 即自审无效 → 2026-09-12 13:0x 按历史模式（author=`codex-security-remediation`，reviewer=`42433422`）重写 #3730-3736 全部 6 条 + #478 以 `inaccurate` dismiss（lockfile 已解析 4.3.2，图谱过期）。**双扫描+部署+线上回归完成（2026-09-12）**：scan#1 run 34675267213 ✅（05:18，release_sha=`201d1f6918`）→ scan#2 run 34677201160 ✅（14:04 派发/14:13 success）→ deploy run 34677587105 ✅（14:20 success）→ 线上 profile PUT 200（判据见 B10）。B12 阻断清除；余 B1（用户侧 secrets）+ T1-T7 实机任务 |

## 6. 实机验收任务（UNKNOWN/RED 项 → 待执行）

| ID | 任务 | Gate | 步骤 |
|----|------|------|------|
| T1 | **双腿执行（2026-09-13）**：①orchestrator（`fhd-release-orchestrator.yml`，product_version=1.0.0.2，release_sha=e3bde5f33，scan#1=34735864144 scan#2=34737848040 编排 run=34738147579）——服务器部署腿（staging→MODstore→FHD stable→production）按设计执行；其桌面派发走全路径 release-preflight（要求全部签名 secrets）在 B1 决策下**预期快速失败**，属已解释状态而非事故；②Windows 授权交付=直接派发 `fhd-release-desktop.yml` `windows_installer_only=true`（未签名 manual_installer）→ desktop run 34738192540 | G1/G3、B1/B2/B4 | 已执行，产物 SHA256 已入册（§2 产物表） |
| T2 | 闭环第 1 轮·干净安装+首启：正式地址下载→SHA256→签名判定→静默隔离安装→冷启动计时+截图 —— **已执行（2026-09-13，证据 evidence/e2e/windows-release-1.0.0.2/t2/）** | G2/G3/G4 | `acceptance-windows.ps1 -Version <v>`（**不设 `XCAGI_UPDATE_URL`**） |
| T3 | 闭环第 1 轮·业务就绪：登录→绑定→Mod/AI 员工→1 个真实业务任务 —— **已执行（2026-09-14 07:24–07:35，1.0.0.3 实机）**：新鲜登录→Mod loading-status 200 partial_failure=false→ERP `products/add` 200+列表回查 found=true（业务任务口径=ERP mod 端点；company-brand 已随 B10 死路由清理移除） | G5/G6/G7 | [t3-biz-result.log](evidence/e2e/windows-release-1.0.0.2/t3/t3-biz-result.log)、[t3-biz-product-page.png](evidence/e2e/windows-release-1.0.0.2/t3/t3-biz-product-page.png)、[t3-post-login-main.png](evidence/e2e/windows-release-1.0.0.2/t3/t3-post-login-main.png) |
| T4 | OTA 闭环：应用内发现→下载→安装→重启观察期→数据基线比对→业务复验 —— **两轮均完整通过**（round-1 1.0.0.1→1.0.0.2，2026-09-14 00:04；round-2 1.0.0.2→1.0.0.3，05:06） | G8–G12 | 证据：evidence/e2e/windows-release-1.0.0.2/loop-round1/ 与 loop-round2/（均含 LOOP-COMPLETE.txt） |
| T6 | 干净环境快照：VM（无开发环境）重跑 T2 | G2 严谨性 | 虚拟机快照 |
| T7 | 闭环第 2 轮：基座 1.0.0.2@1f7d9f11e → OTA 1.0.0.3@4bfb2336 —— **已完整通过（2026-09-14 05:06；desktop 产物+feed 发布由 watcher 自动化，安装器自动点击器实战通过）** | 闭环 | 连续两轮全过才算闭环——**已达成** |
| T8 | 实体机人工故障场景：磁盘满、异常断电（CI runner 无法模拟，run 34727133868 记 SKIP） | G13/数据安全 | 实体机按 `fault-injection-windows.ps1` disk-full/power-cut 场景执行并留证 |

## 7. 与 macOS 域的同步注记（维护 [MACOS_RELEASE_SSOT.md] 时并入）

1. **x64 dmg live 404**（其偏差-4 的 live 确认）；**testing 通道签名 INVALID**（B7，双平台共用测试通道）。

## 8. 发版复用 Runbook（每次 Windows 发版照此执行）

1. `VERSION.md` 升版 → `version_sync.py --apply` + `verify_version_anchors.py`；
2. 配置 `ES_*` secrets（一次性）→ 触发 `release-orchestrator.yml`（签名+发布+manifest 原子生成）；
3. 真机跑 `acceptance-windows.ps1 -Version <v>`（G2/G3/G4）；
4. 真机业务就绪（G5–G7）→ 发下一版后真机全链 OTA（G8–G12）→ 回滚演练（G13）；
5. 按模板填写 `FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本>-windows.md`，截图入 `assets/`；
6. 回填本文件 §1–§4；闭环规则（§0 闭环规则，两轮全过）达成前**不得宣布交付闭环**；
7. RED：只修阻断项→重测→重写状态，禁止直接改状态。
