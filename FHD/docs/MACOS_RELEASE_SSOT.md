# macOS 发布交付 SSOT（唯一事实来源）

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「macos-release」域。**每次 macOS 发版必须复用本文件**：更新第 1–5 节事实，重跑第 6 节全部 Gate，无证据不得标 GREEN，CI 通过 ≠ 验收通过。
> 状态仅限：`GREEN`（完整真机证据）/ `YELLOW`（部分或替代证据）/ `RED`（真机验证失败，记录复现+日志+截图，只修真阻断项，修完重测，禁止直接改状态）/ `UNKNOWN`（无法静态证明，生成实机任务）。判据协议与证据模板见 [e2e/desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)。

## 1. 当前版本信息

| 字段 | 值 | 证据 |
|------|-----|------|
| 稳定产品版本 | `1.0.0.2` | [VERSION.md](../VERSION.md)（版本域 SSOT） |
| 工具链兼容版本 | `1.0.0`（npm/Electron/Apple 三段映射） | 同上 |
| 发布 SKU | `enterprise`（personal 冻结） | [download_release.json](../config/download_release.json) |
| 发布产物 gitSha | `6eda2203df27c53958b9d7af0e6db26d22b560c4` | latest-mac.yml `buildSha`（= main 合并 #1912，交付 run [34732266439](https://github.com/42433422/XCMAX/actions/runs/34732266439)，2026-09-13） |
| manifest git_sha | `6eda2203df27c53958b9d7af0e6db26d22b560c4`（与构建 SHA 一致，DMG 条目 SHA256/size 与实测一致） | [manifest.json](https://xiu-ci.com/xcagi-v1.0.0.2/manifest.json) `generated_at=2026-09-13T07:25:59Z`（step14 CVM 直传超时→本机中转后重生成，见 §2 交付说明） |
| 构建时间 | `2026-09-13T02:22:10.223Z`（feed releaseDate）/ build-info builtAt `02:13:17Z` | latest-mac.yml / 官方 DMG build-info.json |
| 安全扫描对 | A [34729999599](https://github.com/42433422/XCMAX/actions/runs/34729999599) + B [34731821526](https://github.com/42433422/XCMAX/actions/runs/34731821526) 双 success，均锚定 `6eda2203d`，间隔 35min（≥30min），run 内 `verify_security_scan_pair.py` 通过 | release run [34732266439](https://github.com/42433422/XCMAX/actions/runs/34732266439) |
| release_train 内部流水 | `1.0.0.3`（下一发版内部号；1.0.0.2 已落 `/xcagi-v1.0.0.2/` 官方目录） | [release_train.json](../config/release_train.json) |
| `release_ready` | `false`（T4/T6 真机 OTA/重启复验未完成） | download_release.json + manifest.json |

## 2. 构建产物（线上实测）

| 产物 | URL | 大小（字节） | 指纹 |
|------|-----|------------|------|
| DMG（arm64，官方下载） | `https://xiu-ci.com/xcagi-v1.0.0.2/enterprise/XCAGI-Enterprise-1.0.0.2-mac-arm64.dmg` | **307,268,181** | SHA256 `f00801b0679f6cd10af2c844c29846d2cd26acb729414f38d147aea5e77b2a28`（2026-09-13 实测；官方目录与 stable 双目录远端 SHA256 逐一核验一致，证据 [g3-official-10002.txt](evidence/e2e/macos-release-1.0.0.2/g3-official-10002.txt)） |
| ZIP（arm64，OTA 载荷） | `https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-1.0.0.2-mac-arm64.zip` | 264,517,668 | SHA512 `1ryEtv+nlqe72gUZvMK56fNjp5Ncb7MslaACYv3p43q/ifYGRwSMiZpdimmo1wCzMH6qsASQv2/NPm/TYDchUw==`（latest-mac.yml；ed25519 公钥验签 **VALID** 2026-09-13） |

**1.0.0.2 交付说明（2026-09-13）**：run 34732266439 构建+签名+公证全部成功，step14（runner→CVM 直传）因链路 10KB/s 超时失败；按恢复路径将 artifact 本机中转补齐 step14–16：双目录 5 文件 SHA256 核验、manifest 重生成（`generated_at=2026-09-13T07:25:59Z`）、公网 latest-mac.yml（buildSha `6eda2203d`）ed25519 验签 VALID、DMG/ZIP/blockmap 公网全 200。异常处置与断点续传过程见 [ota-release-cvm-recovery-20260913.md](evidence/e2e/macos-release-1.0.0.2/ota-release-cvm-recovery-20260913.md)（含并行会话误写 fa3c8832e 未验证产物的覆盖记录）。

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

## 6. Release Gate 状态（2026-09-11/12 实跑；证据目录 [evidence/e2e/macos-release-1.0.0.1/](evidence/e2e/macos-release-1.0.0.1/)：截图/SHA256/health/Mod 探针）

> **当前结论（2026-09-13）：NOT Release Ready（1.0.0.2 正式包已发布上线，剩真机 OTA/登录截图/重启复验，无代码阻断）。** 1.0.0.2 正式发布闭环已达成：release run [34732266439](https://github.com/42433422/XCMAX/actions/runs/34732266439)（checkout `6eda2203d` 构建+签名+公证+扫描对门禁通过）→ CVM 上传步骤 180min 超时 → artifact 手动恢复发布（五文件 SHA256 与 artifact 逐字节一致，官方+stable 双路径，manifest/公开 feed 复验通过，见 §2 交付说明与 [恢复证据](evidence/e2e/macos-release-1.0.0.2/ota-release-cvm-recovery-20260913.md)）。G1 升 GREEN（1.0.0.2 正式公证包，buildSha=6eda2203d 全链一致）。G7/G6/G10 GREEN（候选包 v2 实证，修复全部含于 6eda2203d）。G8 现在有真实升级目标（1.0.0.1 真机 → 发现 1.0.0.2），T4 可执行。剩余未闭环：T2（UI 登录截图）、T4（G8/G9/G11 真机 OTA 全链）、T6（G12 重启复验）。**G13 GREEN（降级演练 PASS）**。证据 [g7-full-chain-success-20260912.json](evidence/e2e/macos-release-1.0.0.2/g7-full-chain-success-20260912.json)。

| # | Gate | 状态 | 现有证据 | 缺失证据 | 阻断 | 对应 PR | 下一步 |
|---|------|------|---------|---------|------|---------|--------|
| G1 | 构建（产物+身份） | GREEN | **1.0.0.2 正式发布（2026-09-13）**：release run [34732266439](https://github.com/42433422/XCMAX/actions/runs/34732266439) checkout `6eda2203d`（= main HEAD #1912）构建+Developer ID 签名+公证；扫描对 A/B 双 success 锚定同 SHA（间隔 35min）；latest-mac.yml `buildSha=6eda2203d`+ed25519 签名；manifest DMG 条目 SHA256/size 与实测 artifact 逐字节一致；CVM 官方+stable 双路径五文件 SHA256 校验一致（§2） | — | 无 | #1912 | — |
| G2 | 干净环境安装 | YELLOW | 验收脚本真实下载→SHA256→挂载→安装 `~/Applications/acceptance/` 全链 PASS | 非干净机（dev 机+存量数据）；未在全新用户/VM 验证 | 无 | #1870 | 实机任务 T1：干净环境（新账户或 VM）重跑 |
| G3 | macOS 安全项 | GREEN | **1.0.0.2 正式公证包实测（2026-09-13）**：`codesign --verify --deep --strict` exit=0；hardened runtime（flags=0x10000）；TeamID `G26WSH472M`；`spctl --assess --type execute` exit=0（accepted，公证通过）；stapler validate OK——对发布 DMG 原件挂载实测（[g3-official-10002.txt](evidence/e2e/macos-release-1.0.0.2/g3-official-10002.txt)） | — | 无 | — | — |
| G4 | 首次启动 | YELLOW | 后端进程 PID 95037 监听 17500；`/api/health` 200 返回 JSON；runtime.status=healthy, blockers=[], failures=[]；neuro.status=healthy, running=true, published=496, errors=0；主窗口截图 [04-cold-start.png](evidence/e2e/macos-release-1.0.0.1/04-cold-start.png) | status=degraded（唯一原因 `LLM_RUNTIME_UNAVAILABLE`——登录前无 LLM provider 配置，属预期态，见 §7-4）；未在干净环境首次启动 | 无 | — | T2 登录后复测 health 应转绿；T1 干净环境冷启动 |
| G5 | 登录绑定 | YELLOW | 历史证据（旧版本）；2026-09-11 静态确认：行业业务（考勤等）走账号权益门控（`mod_sdk/customer_features.py` `delivery_for_account`），登录是业务任务的硬前置；CDP 登录监听器已部署（自动采集登录后证据） | **已用本地企业账号会话等效验证（2026-09-12）**：`auth/me` 200（SUNBIRD，is_active=true，shipment.* 权限下发）、attendance 权益探针 200 JSON、模板上传+出单全链走通——证明登录态是完整业务闭环的充分条件；UI 登录动作截图/日志待 T2 补齐 | 无（等效验证已过，形式证据待补） | — | T2（UI 登录截图，非阻断） |
| G6 | Mod / AI 员工加载 | YELLOW | `/api/mods` 200 返回 62 个 mod（含 attendance-industry v1.0.0 primary=True）；15 个后端 mod 加载成功；`/api/employees` 200 返回 catalog；neuro handlers=39, domains=11。**但 attendance-industry HTTP 路由注册每次启动均失败**（userData 同步版 mod import `app.mod_sdk.customer_features`，99854233 bundle 无此模块；`/attendance/capabilities|policy|rules|convert-upload|download` 不可用），证据 [g6-attendance-route-regression.txt](evidence/e2e/macos-release-1.0.0.1/g6-attendance-route-regression.txt)。**1.0.0.2 候选包重测（2026-09-12）：启动日志无任何路由注册 ERROR，f37372e97 修复确认生效**；`/attendance/capabilities` 返回 SPA HTML 属预期——路由按 `mount_entitled_client_mod_api_routes` 账号权益门控挂载，未登录必然不可达（设计行为，非缺陷） | **已验证（2026-09-12 登录态）**：`/api/mod/attendance-industry/attendance/capabilities` 200 `{"custom_features":["attendance-convert"]}`——权益门控按预期；干净首装 seed 版 mod 行为待 T1 | 考勤类业务需登录权益（不阻断 ERP 业务闭环） | f37372e97 | 终判并入 T2（登录后探针）+ T3 |
| G7 | 真实业务任务 | GREEN | **1.0.0.1 模板导入链路断裂**（证据见 §7-8，RED 历史保留）：upload/analyze/create 全 405、generate 恒 TEMPLATE_NOT_FOUND，用户无法完成发运单真实业务。**修复实证（2026-09-12 晚，1.0.0.2 候选包 v2 = buildSha 9a4a06bc4，含 PR #1895）**：带 CSRF 实测 `POST /api/templates/upload`/`analyze` 由 405 变为 **401 UNAUTHORIZED（请先登录）**——默认应用已挂载、登录+租户鉴权生效，断链根治；`progress` 实为 GET `/api/templates/progress/{task_id}`（前端契约一致，POST 405 属预期）；`GET /api/templates/list` 200、`next_number` 200。证据 [g7-retest-cand2-20260912.txt](evidence/e2e/macos-release-1.0.0.2/g7-retest-cand2-20260912.txt)、[acceptance-10002-cand2-run.zip](evidence/e2e/macos-release-1.0.0.2/acceptance-10002-cand2-run.zip) | **已达成（2026-09-12 登录态全链）**：upload 200 入库（db:12）→ generate 200 出单（发货单_26-0900001A_20260912_200002.xlsx，SHA256 4c1bf418…，record_id=1，agent_status=completed，template_resolution ok）→ list 11 条含新模板；考勤权益探针 200。证据 [g7-full-chain-success-20260912.json](evidence/e2e/macos-release-1.0.0.2/g7-full-chain-success-20260912.json) | 无 | #1895 (a4c5af2bc+0362c9052，已合并 main `62c49bae5`) | — |
| G8 | 更新发现 | YELLOW | feed 可达+ed25519 签名字段存在；本版=最新无升级目标（协议 4.4 SKIP）；历史闭环 [desktop-ota-closed-loop-20260724](evidence/e2e/desktop-ota-closed-loop-20260724/) | 无更高版本可触发真实"发现" | 无 | #583 | 下次发版 T4 触发真实发现 |
| G9 | 更新安装 | YELLOW | 历史闭环：checkForUpdates+downloadUpdate 验签+提取 buildSha 一致；`quitAndInstall` 未执行 | 真机完整"重启安装"动作从未执行过 | 无 | #583 | T4：下版发后真机全链 OTA |
| G10 | 数据保留（升级后） | GREEN | 三次实机覆盖升级全部 PASS：① 1.0.0.1 同版本重装零丢失（[data-retention.json](evidence/e2e/macos-release-1.0.0.1/data-retention.json)）；② 1.0.0.1→1.0.0.2(3d3ec8d98) 跨版本（[pre](evidence/e2e/macos-release-1.0.0.2/data-digest-preupgrade-10002.json)/[post](evidence/e2e/macos-release-1.0.0.2/data-digest-after-10002.json)）；③ 1.0.0.2(3d3ec8d98)→1.0.0.2(9a4a06bc4, 含 G7 修复) 覆盖升级：DB 字节级相同（986,615,808B）、uploads 151、mods 847、backups 4、标记存活，data-retention result=PASS（[data-retention-cand2.json](evidence/e2e/macos-release-1.0.0.2/data-retention-cand2.json)、[run log](evidence/e2e/macos-release-1.0.0.2/acceptance-10002-cand2-run.zip)） | 跨版本保留经 OTA（非手动覆盖）路径实测（T5 补充，不影响手动路径判定） | 无 | #1870 | T5（下版发后真机 OTA 路径执行） |
| G11 | 更新后重新执行业务 | UNKNOWN | — | 依赖 G9/G10 | 无 | — | T4/T5 后执行 |
| G12 | 重启 Mac 后核心功能复验 | UNKNOWN | — | 未执行真实重启（避免中断在用会话） | 无 | — | T6：发版后重启复验 |
| G13 | 回滚/恢复 | GREEN | **实机降级演练 PASS（2026-09-12）**：1.0.0.2 候选包 → 1.0.0.1 正式包（SHA256 `c39bed60…` 与线上一致）覆盖安装成功——codesign+spctl accepted、冷启动 0.2s、health PASS、业务数据零丢失（DB 986,886,144B 不变、uploads 151、mods 847、backups 4、标记存活）。证据 [g13-rollback-20260912.zip](evidence/e2e/macos-release-1.0.0.1/g13-rollback-20260912.zip)、[data-retention](evidence/e2e/macos-release-1.0.0.1/g13-rollback-data-retention.json)、[冷启动截图](evidence/e2e/macos-release-1.0.0.1/g13-rollback-cold-start.png)。观察期自动回滚（坏更新注入）路径 A 待专用验收机 | 路径 A（观察期自动回滚）实机证据 | 无 | — | 路径 A 留待专用验收机（非阻断） |

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

## 8. 实机验收任务（UNKNOWN 项 → 待执行）

| ID | 任务 | Gate | 环境 |
|----|------|------|------|
| T1 | 全新 macOS 用户账户（或干净 VM）跑 `acceptance-macos.sh`，验证无开发依赖 | G2 | 干净机 |
| T2 | 真机登录绑定（市场账号），截图+日志 | G5 | 任意真机 |
| T3 | ~~真机完成 1 单真实业务~~ **已完成（2026-09-12 登录态全链）**：upload 200 入库 → generate 200 出单（发货单_26-0900001A_20260912_200002.xlsx，record_id=1）；证据 g7-full-chain-success-20260912.json | G7 | 任意真机 |
| T4 | 下次发版后：旧版真机→检查更新→下载→安装→观察期→复验 | G8/G9/G11 | 真机（1.0.0.2 已于 2026-09-13 上线 stable feed，T4 可立即执行） |
| T5 | 跨版本覆盖升级数据保留：旧版真机装新版（`acceptance-macos.sh --version <新版> --overwrite-upgrade`），基线→比对→标记存活 | G10 | 真机 |
| T6 | 重启 Mac 后复验登录/Mod/业务 | G12 | 真机 |
| T7 | 下版本发后重测 G6/G7：日志无 `Failed to register routes for attendance-industry` 且 `/attendance/capabilities` 可达；`POST /api/templates/upload` 2xx 且入库后 `shipment/generate` 出单；随后 T2→T3 | G6/G7 | 真机（新版 feed） |
| T8 | ~~回滚/恢复演练~~ **已完成（2026-09-12 路径 B 降级）**：1.0.0.2→1.0.0.1 覆盖安装 PASS（签名 accepted、数据零丢失、health PASS），证据 g13-rollback-20260912.*；路径 A（坏更新观察期自动回滚）留待专用验收机 | G13 | 真机 |

**T7 中期回执（2026-09-12，1.0.0.2 候选包实装重测，证据 [evidence/e2e/macos-release-1.0.0.2/](evidence/e2e/macos-release-1.0.0.2/)）**：① G6——启动日志零路由注册 ERROR（f37372e97 生效✅）；`/attendance/capabilities` 未登录返 SPA HTML 属权益门控设计，终判移入 T2。② G7——upload 仍 405（根因见 §7-8 修正定性：默认应用从未挂载 upload/analyze，b97073acc 只补 create）；修复已入库（template_api.py 默认挂载），**修复并入 main 后需重建候选包重测**。③ G10——跨版本覆盖升级数据保留 PASS（digest 逐项一致，见 G10 行）。

## 9. 发版复用 Runbook（每次 macOS 发版照此执行）

1. `VERSION.md` 升版 → `version_sync.py --apply` + `verify_version_anchors.py`；
2. CI `release-desktop-mac-ota` 构建+签名+公证+发布 → `publish-macos-download-center` 更新下载中心/manifest/feed（发版 Runbook 第 2 步后必须核验 manifest `generated_at` 与构建 SHA，防"feed 已更新、manifest 未生成"漂移，见 §7-1）；
3. 真机跑 `bash FHD/scripts/package/acceptance-macos.sh --version <v>`（下载→SHA256→签名→安装→冷启动→健康检查）；跨版本数据保留走 `--overwrite-upgrade`（T5）；
4. 有新版本时真机走完整 OTA 链（G8→G12），按协议 4.1–4.2 判定；
5. 按模板填写 `FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本>-macos.md`，截图入 `assets/`；发版前回归两个历史 RED：`POST /api/templates/upload` 非 405（G7，见 §7-8）；启动日志无 attendance 路由注册 ERROR（G6，见 §7-7）；
6. 回填本文件 §1–§6；全部 Gate 无 RED 且 G1–G4 GREEN、G5–G13 无 UNKNOWN 遗留方可宣布闭环；
7. RED：只修阻断项→重测→重写状态，禁止直接改状态。

## 10. 验收候选包（非发布产物，历史记录）

> 候选包 Developer ID 签名未公证（spctl rejected），仅供实机验收，不得替代发布产物、不得进 feed；正式 1.0.0.2 已于 2026-09-13 发布（§1/§2）。构建环境三坑见 §7-9；候选包 build-info `version` 落后产品号的口径见 §7-10。

| 候选 | buildSha | 实装重测结论 | 证据 |
|------|----------|-------------|------|
| v1（2026-09-12） | `3d3ec8d9867fa43cfeb402893ae3676fd86b0b95`（构建时 main HEAD，含 b97073acc/f37372e97，**不含** G7 挂载修复；DMG `6d11b2af…`/ZIP `1092e4fa…`） | G6 修复生效（启动日志零路由 ERROR）；G7 upload 仍 405（催生 template_api.py 默认挂载方案）；G10 跨版本覆盖升级数据保留 PASS | [receipt](evidence/e2e/macos-release-1.0.0.2/candidate-build-receipt.txt)、[retest](evidence/e2e/macos-release-1.0.0.2/retest-10002-results.json)、[pre](evidence/e2e/macos-release-1.0.0.2/data-digest-preupgrade-10002.json)/[post](evidence/e2e/macos-release-1.0.0.2/data-digest-after-10002.json) |
| v2（2026-09-12 17:30，含 G7 修复） | `9a4a06bc49b8885111dc7dc4c61eb15d0dd748db`（DMG `da2a1bd7…`/ZIP `e866079b…`，PR #1895 合并 main 后干净构建，`env -u CI` 跳过公证） | 覆盖升级（3d3ec8d98→9a4a06bc4）PASS；G7 upload/analyze 405→401（断链根治、鉴权生效）；G10 PASS；冷启动 0.1s health PASS | [g7-retest-cand2-20260912.txt](evidence/e2e/macos-release-1.0.0.2/g7-retest-cand2-20260912.txt) |
