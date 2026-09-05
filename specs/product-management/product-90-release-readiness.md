# 本次产品修复的交付路径核查

核查时间：2026-09-05 17:45 Asia/Shanghai 左右。范围：本分支源码、GitHub 工作流/checks/configuration 名称与历史设备证据；没有部署、读取 secret 值、支付或修改生产。

## 最短正式路径

1. 根集成并完成 draft PR；生成 Mod 镜像、OpenAPI/契约及工作流镜像后完成本次范围回归。待 required checks 全通过再 ready/merge。2026-09-05 当前 `main` strict protection 的 11 个 required contexts 为：`guard-temp-scripts`、`arch-fitness`、`security-scan`、`gitleaks`、`analyze (python)`、`analyze (javascript-typescript)`、`SSOT Drift Gate`、`Release gate (hard block)`、`backend-test`、`frontend-test`、`mutation-smoke`。PR 检查不是 merge SHA 检查：合并后重新验证该完整 40 字符 SHA，且编排器要求它等于当时 current main。
2. 冻结最终 merge SHA。`fhd-security-full-scan.yml` 对此同一 SHA 在连续两个 UTC 日扫描；前日证据 <=48 小时，本日 <=24 小时；每种必需 scanner 全部达到零 critical/high 等门槛。不要借用旧提交 scan run ID、补造日期或把同一天重复扫描当两日。最近可见 5 次 full scan（33942910543 等）均失败，不能充当本次放行证据；本次新 SHA 尚无两日证据，具体最早时间取决于扫描成功时刻跨 UTC 日界。
3. 运行 `fhd-release-orchestrator.yml`，真实参数为 `product_version=1.0.0.1`、`release_sha=<final main SHA>`、`security_scan_run_id=<current successful run>`、`previous_security_scan_run_id=<prior-day successful run>`。保留现有固定版本 anchors 和旧 tag；以完整 SHA/release_id/build-info 标识新构建，不移动旧 tag。
4. 编排顺序：`fhd-ci-cd.yml` staging -> `modstore-prod-deploy.yml` exact SHA -> FHD stable 制品上传 -> `fhd-deploy.yml` production apply-latest -> observability验证。MODstore immutable release 在切换 symlink 前运行 `scripts/upgrade_database.py`，因此 PM003 migration 必须先于消费/签发服务切换；同一 immutable release 内构建 Market，能让后端和消费页同时就绪。FHD pack release 内构建并校验管理台 SHA，不能只推前端静态页就声称服务端/管理台完成。
5. 同一 shared `xcagi-vue-dist` 供 desktop/web 使用；Windows、macOS构建签名/公证，通过双平台manifest、Ed25519元数据、公网完整下载SHA256/size、独立Windows签名校验后才更新网站下载指针。新客户端在服务端和 Market就绪后发布，旧 xcagi_mt URL 仅清理并提示普通登录。
6. 用此最终 SHA 的公开下载制品在 macOS、Win10、Win11 安装与升级，核对 build-info、主进程/后端、SKU、Mod manifest SHA与真实 UI。最短业务验收包括：实际表单登录 -> 钱包/选中套餐/充值额 -> 系统浏览器正确账号与目的页；代码过期/重放/旧URL回干净登录；导入/撤销/保存/打印/聊天按本分支其余修复验收。记录装机平台、版本、完整SHA、制品hash、操作与截图/回执。runner smoke不替代客户设备内容验收；无需真实付款。
7. `fhd-release-convergence-readback.yml` 再确认所有配置源和未撤销设备回执收敛于 `xcagi-1.0.0.1-<SHA>`。这一步当前另缺下面的凭据配置。

## 具体阻塞和边界

- **编排调用缺参已在源码关闭**：原 production apply-latest 调用缺少必需的release_sha及同SHA两次扫描输入；`df3f77763` 已透传经过security-preflight验证的三个输入，52项相关回归通过。实际生产编排尚未执行。
- **Windows稳定签名未配置**：只读 `gh secret list --json name` 未见 `ES_USERNAME`、`ES_PASSWORD`、`CREDENTIAL_ID`、`ES_TOTP_SECRET`；`gh variable list --json name` 未见 `XCAGI_WINDOWS_PUBLISHER_NAME`。近期真实成功Windows job也显示签名工具步骤skipped、`AllowUnsigned=True`。需要账户持有人完成SSL.com证书/eSigner，配置4个secret及精确publisher变量。不要创建伪值或静默退回未签名稳定更新。
- **Windows已有新手动制品构建证据，但当前下载工件缺失**：[run 33956311584](https://github.com/42433422/XCMAX/actions/runs/33956311584)，SHA `9016daab66f781614ffe91f9ab9d6428bb15d4c9`，Windows安装、启动runtime smoke和卸载于2026-09-05 09:01:41 UTC通过；`windows_installer_only` 明确unsigned，stable发布相关jobs均skipped，receipt约定 `customer_machine_acceptance=not_verified`。job日志证明上传artifact ID `9966637265`，ZIP size `242526977`，ZIP digest `f0eade3fb5a666fb4fa616704ba96ea9f8e990faddc213bd79eb4e39621aa3cb`；但当前runs/artifacts API返回 `total_count=0`，无法从该Actions run再次下载。未推断其被删除原因或其他位置是否已归档，不能把过去上传日志当当前可下载证据。
- **未签名Windows临时安装测试可独立先做**：同 `fhd-release-desktop.yml` 设置 `windows_installer_only=true`、完整本次SHA和version。它保留资源/安装/启动/卸载检查，5项签名配置全缺时允许明确unsigned；任意部分配置或签名错误会阻断。此路不更新stable，也不代替正式两日扫描、稳定签名及三平台收敛。
- **convergence credential未见配置**：该workflow只使用 `RELEASE_CONVERGENCE_ADMIN_TOKEN`，当前repo secret名称列表没有此名；不能以别的凭据猜测替换，需要按已授权账号配置或明确暂不能取得自动收敛结果。
- **production environment没有required reviewer**：当前GitHub API `environments/production` 返回 `protection_rules=[]`，原源码注释与此不符，已更正注释。仍存在exact-SHA安全和autonomy校验；本核查未修改environment。正式发布按既有用户授权处理，不能声称GitHub已自动设置人工审批。
- **旧文档命令过时，后续已修正**：核查时`FHD/docs/runbooks/windows-code-signing.md`的示例仍传version1.0.0.0且没有新必需SHA/scan/frontend输入。本轮已改为完整SHA及两日同SHA真实扫描ID的总编排入口，前端run ID由编排生成；命令合同按候选及固定main工作流核对，未执行发布。

## 历史实机证据，不能冒充本次验收

- `/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/w02-win11-para-acceptance-2026-07-12.md`：Win11 命令/API冒烟通过，表单登录和业务主区可见内容验收明确FAIL；API-cookie fallback与空白壳不能签字。
- `/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/desktop-real-machine-acceptance-2026-07-05.md`：历史Win10独立机缺口；7月16日记录Win11设备离线。此次未重新盘点设备，离线不能视为当前状态。
- `/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/mac-notarize-cdn-closure-2026-07-12.md` 有macOS Developer ID、公证、staple和公网验证历史闭环；当前repo也存在相关secret名称，但未验证值有效性。这些不是本次SHA制品证据。

## 关键源码入口

- `FHD/.github/workflows/release-orchestrator.yml` 与生成镜像 `.github/workflows/fhd-release-orchestrator.yml`
- `.github/workflows/fhd-deploy.yml`（root-only），`FHD/.github/workflows/ci-cd.yml`
- `成都修茈科技有限公司/MODstore_deploy/.github/workflows/prod-deploy.yml`，`scripts/xcmax-immutable-release.sh`，`scripts/upgrade_database.py`
- `FHD/.github/workflows/release-desktop.yml`、`release-web.yml`、`security-full-scan.yml`、`release-convergence-readback.yml`
- `FHD/scripts/package/verify-windows-installed-runtime.ps1`、`FHD/desktop/build/windows-sign.cjs`
- `FHD/scripts/security/verify_security_scan_pair.py`、`FHD/scripts/dev/verify_version_anchors.py`

## 已完成的编排修复

编排缺参已修复并提交为 `df3f77763`：

- `FHD/.github/workflows/release-orchestrator.yml`
- `.github/workflows/fhd-release-orchestrator.yml`（由仓根 `scripts/dev/publish_ci_workflows_to_root.py --apply` 生成；仅该镜像发生漂移）
- `FHD/tests/release_gate/test_orchestrator_dispatch_contract.py`

三个生产相关调用共同透传已通过security-preflight的真实SHA/current+previous run ID。扫描ID通过env读取，避免直接把workflow表达式拼入shell；缺少、非数字或相同run ID会在任何子部署前明确exit1。生产apply-latest新增完整SHA与两次scan参数；被调用方exact-SHA/两日扫描门禁保持原样。未修改GitHub签名或environment配置。

新增契约测试先复现6项失败，再用无副作用的子调用记录器执行真实source+mirror shell片段，通过5步顺序、SHA/证据不漂移、缺失证据零调用检查。相关回归命令（cwd FHD）：

```sh
TMPDIR=/private/tmp/xcmax-product-90-20260905/worktree/.tmp-pm003 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/release_gate/test_orchestrator_dispatch_contract.py tests/release_gate/test_server_release_push_policy.py tests/release_gate/test_security_release_gate.py tests/test_dev/test_publish_ci_workflows.py --confcutdir=tests/release_gate --no-cov --tb=short --basetemp=/private/tmp/xcmax-product-90-20260905/worktree/.tmp-pm003/orchestrator-final
```

结果：52 passed。工作流发布器 `--check`、Ruff、diff-check均通过。本记录已由根代理整理到此持久文档；`.tmp-pm003` 中测试材料在不再使用后按本任务边界清理。未执行发布。

## 本轮远端检查与后续安全证据

草稿 [PR #1768](https://github.com/42433422/XCMAX/pull/1768) 已建立。首轮发现继承分支中的行业种子文件501行及两处格式漂移，已分别拆分职责与格式修正。2026-09-05 10:09 UTC已观察到的检查头为 `72890062d`：架构、SSOT、发布门禁、CodeQL、gitleaks、基础security-scan、mutation、完整前端检查、桌面测试和构建通过；后端完整覆盖率测试仍在运行。此处记录一次观察，不替代最终SHA的required checks。

该后端回归随后于10:13 UTC结束：36655通过、47跳过、1失败，尚未执行后续覆盖率门禁。根侧复现并核对原提交 `f37372e97`，确认失败断言仍假定账号定制已完全移除，与当前保留考勤转换定制权益的规则不符。`4b4a34b56` 修正测试，保留共享运行模块与账号定制身份的区别，员工工具缺失仍阻断完整就绪；相关31项通过。最终头必须重新跑完整CI，不能借用此旧结果放行。

另下载核对了 [2026-09-05 03:49 UTC 完整发布扫描](https://github.com/42433422/XCMAX/actions/runs/33942910543) 的规范化报告。其扫描SHA为 `f54e8e4fe61e36dff20e35ae1323b0d87241e726`，与本次PR和待发布SHA不同。报告门禁统计3项critical、293项high并拒绝放行；其中CodeQL与Dependabot包含按现有规则仍需核验的手工dismissed项，不能把这个数量直接当成新提交确认的独立漏洞数量。

| 报告来源 | 该次报告情况 | 后续要求 |
|---|---|---|
| CodeQL | 205项high，其余56项medium/low | 在最终SHA核对当前告警、历史处置理由和可复现性 |
| Dependabot | 23项high，其余15项medium/low | 以实际发布锁文件及当前告警状态核验 |
| 主机 | 3项critical、62项high，含运行内核落后提示 | 核对当前补丁/运行内核及维护窗口，不能用旧快照代替更新结果 |
| 凭据轮换 | 3条事故轮换尚未被该报告确认 | 取得对应服务的真实轮换与旧凭据失效证据；报告不保存凭据值 |
| gitleaks / Python / Trivy文件系统与镜像 | 该次报告无finding | 必须对最终SHA重新扫描 |

基础PR扫描通过与完整发布扫描通过是两个不同门禁。当前不能登记正式发布已就绪，也不能为了交付忽略上述完整扫描和两UTC日证据要求。

## b970 本地制品与下一候选

完整SHA `b97073acc61baca1ce8b0d86a4ad06bdb86349eb` 的隔离macOS包通过Developer ID深度严格签名与16项运行依赖检查，实际桌面UI已完成导入、价格更新、保留人工改动的显式授权撤销、模板保存和中文PDF下载。新用户目录匿名冷启动的登录衔接、标签回程和内嵌预览仍失败，修复后需要新SHA构建和复验。该制品未公证、未替换Applications安装版、未更新stable指针；本地Market的同SHA钱包读回也不替代正式服务部署。

2026-09-05 11:56 UTC再次只读查询配置名称，Windows四项eSigner secrets、publisher变量及RELEASE_CONVERGENCE_ADMIN_TOKEN仍未见配置；结果见任务目录 `release-config-presence-current.json`，未读取secret值。真实客户价值、物理打印、跨平台安装、生产收敛和最终SHA连续两UTC日完整扫描仍需各自证据。本地回归数量和临时包签名不能代替这些门禁。

## 70da 终端与桌面候选的交付状态

`70da5cdf6ca18abc44eb5370734314ca6663fb8f` 已推送到草稿PR #1768。该提交将智脑开发功能迁移到 `xcagi-brain`，移除前端页面与导航，保留主聊天、智能生态和后端能力。独立wheel安装及23项真实后端流程通过；单独构建的macOS包通过Developer ID深度严格签名。21:26–21:31原生UI复验确认智脑入口消失、正常登录与行业引导贯通、首单明确确认后产生业务记录、标签保存返回保留选择、三页中文PDF内嵌展示和下载成功。详见[本地验收记录](product-90-live-acceptance.md)。

此包未公证、未发布、未替换Applications中的安装版。包内健康接口的git_sha为空，身份目前由build-info、已核验启动路径和资源hash确认；缺失的运行身份待修。Market仍是此前b970隔离环境，不声称其与70da同步正式部署。

70da的完整前端CI通过；[完整后端任务](https://github.com/42433422/XCMAX/actions/runs/33968197745/job/101311999347)为36773通过、62跳过、1失败，唯一失败为行业管理员切换接口返回500。旧模板认证污染案例在此全套CI已通过，新失败需独立定位。

[安全门禁任务](https://github.com/42433422/XCMAX/actions/runs/33968197750/job/101312657556)明确失败：CodeQL分析成功后，门禁发现两个新增HIGH告警记录（#3685、#3686，`py/polynomial-redos`），指向首单查询解析第19、20行。实际分析merge SHA为`9560cbf0f812d44c8c45d7c8bc57142fbaab8ae0`，父提交为当时main `de4a4755259865851f7b9def13f29b1e2a62a4ca`与70da；该源码文件在main、b970、4c4及70da哈希完全相同。因此这是本次分析新发现的既有代码风险，不能说是CLI新引入的漏洞，也不能因为既有就忽略门禁。源码修复与局部回归不等于告警已关闭；后续提交必须取得新的正常CI分析结果。现有证据只读核验未运行额外扫描、关闭告警或改变规则。

正式交付仍需最终main SHA、必要CI、连续两UTC日完整安全证据、签名/公证与可下载制品、跨平台实机与业务验收、生产收敛和真实客户价值。70da的本地通过项不能替代这些条件。

14:00 UTC只读配置复核仍未见四项eSigner secret、publisher变量或convergence token；查询成功但仅证明仓库级名称缺失，未读取值。GitHub仓库runner清单为空，DevFleet唯一Windows设备当时offline且linkHealthy=false，因此当前没有可用的Windows实机验收来源。7月的Win11命令PASS/UI FAIL、Win10 pending仍是历史证据。原始名称、设备清单及固定main SHA的工作流副本见任务目录 `release-preflight-70da-current/`。

本地候选与当前main的Desktop工作流必须区分：候选含之前继承的`windows_installer_only`分支，但14:00查询的main `de4a4755259865851f7b9def13f29b1e2a62a4ca`并未声明该输入，正式Desktop要求version、verify_only、frontend_run_id、完整release_sha及两次scan ID。上文手动制品路径仅说明本地候选及历史run，不能直接当作当前main可执行命令。正式入口使用总编排器，在同SHA安全证据和上游服务、前端制品就绪后调用Desktop。

70da之后的源码修复已将首单正则改为线性扫描、将既有no-op全局行业POST明确退役为保留鉴权的410，并接通真实打包Resources身份。局部回归及旧实现反证见任务目录 `onboarding-slot-parser-fix/`、`ci-70da-backend-failure/`、`packaged-build-identity-fix/`。这次范围未改变安全扫描规则、告警状态、默认用户权限或签名门禁；必须等待后续完整CI及新包验收，不能将70da的红色门禁改写为通过。
