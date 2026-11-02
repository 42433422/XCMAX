# Windows 发布交付 SSOT
## 1. 当前版本信息
> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域；Gate 仅用 GREEN/YELLOW/RED/UNKNOWN。判据：[真实机协议](e2e/desktop-real-machine-acceptance-protocol.md)；[未签名风险决策](../config/windows_signing_acceptance.json)。历史证据保持原样，失败须修复后实装重测。
**未闭环。** 2026-10-08：Windows日志补修#2190已合入main `a0d352aca9360964d07a7617404f3e662613f7c8`；准确候选已构建下载，SHA-256 `5746e8ce9b868e4a98c38d1bcd7c9b5ddb3609f502fbc759e1791b2ab3e447e7`，NotSigned，尚未实装。旧6302诊断包已在独立干净A正常安装并读回相同SHA；耗时过长、99显示完成和瞬时未响应保留，随后正常首启180000ms超时失败，后台迟到就绪不核销。本轮续修将收尾移出UI线程、完成状态与100同步，移除反复全目录扫描；真实WPF旧代码失败、新代码四项及七项子进程回归通过，仍待审阅重建和实机。原单WO-6a5a4e928046正文附件已持久化，派发正文62618字符截成8000导致JSON无效及工单身份丢失已复现，Mac公共主修待确认修复；不得代记AI接单。隔离C旧EDF包完成备份恢复、损坏备份拒绝、正常卸载零进程及保留数据重装，不能代替更新失败应用/库一致恢复或冻结组合复验。最终16项通过仍为0；官网604ab1531/公共后台201d1f69未发布本轮组合，stable OTA关闭。
原始运行 `WIN-VM-REGRESSION-F16373D-20261006-001`：[运行索引](evidence/e2e/windows-closeout-20261006/run.json)、[销售订单字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)。f16373d[正常重下文件](evidence/e2e/windows-closeout-20261006/redownloaded-inventory.content.json)核销空白子窗口；沿用旧任务文件不计新AI执行。旧be136e3的[库存Excel字段](evidence/e2e/windows-closeout-20261005/ai-inventory-downloaded.content.json)仅核销该包空表故障。#2096由#2107替代，#2103/#2104已入主线；[5197历史](evidence/e2e/windows-closeout-20260930/gui-36841870956.json)不能替代同一最终包复验。
## 3. Release Gate 定义
GREEN须本最终包实测通过；YELLOW为有限证据或过渡方案，RED为实测失败/门禁阻塞，UNKNOWN为未测；PR与CI不能替代客户验收。
## 4. Release Gate 状态
| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | f16373d安装与运行身份、17500所属后端已核对；最终冻结和客户入口重下未完成 |
| G2 | 首装 | YELLOW | 本轮f16373d为既有A测试机正常覆盖安装；干净首装完整A轮未完成 |
| G3 | 签名 | YELLOW | 当前包NotSigned；仅允许未签名过渡交付，不得称正式签名发布 |
| G4 | 首次启动 | RED | 复现：[本轮A原始截图/日志及五项登记](evidence/e2e/final-acceptance-1.0.0.5/windows-first-start-20261008/run.json)：EDF首启180000ms超时，迟到就绪和正常重开未核销失败；修复#2186后须新main包重测 |
| G5 | 登录、企业与设备绑定 | YELLOW | 同账号界面读回P006/W006库存20；设备绑定、工作区归属完整验收未完成 |
| G6 | 权益、Mod、AI员工 | RED | 复现：f16373d SUNBIRD正常员工空间开关已启用、托管1待命1；[定位](evidence/e2e/windows-closeout-20261006/g6-panorama-triage.json)确认[企业全景](evidence/e2e/windows-closeout-20261006/normal-enterprise-panorama-enabled-mod-not-ready.png)L1/L2/L4暂无员工Mod为预期渲染（承诺仅attendance_ai，归L3服务层），非授权或代码缺陷；缺口：最终包实机由L3考勤ai助手完成一次考勤表转化；#2163已入主线604ab1531待正式部署，生产内核TSSA-2026:1026已核销；新主线安全扫描及授权Mod实机验收待完成 |
| G7 | 真实业务与AI任务 | RED | 复现：f16373d正常审批入口和拒绝已实测；SALES ORDER 2 P006 A006 10→正常审批→SO20261006004727金额20，但product_model被忽略，订单行产品ID/名称为空；[字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)、[审批输入](evidence/e2e/windows-closeout-20261006/normal-sales-create-order-correct-approval.png)；对话另报[最大迭代失败](evidence/e2e/windows-closeout-20261006/normal-sales-conversation-max-iterations.png)，审批后[原运行与任务仍待审批](evidence/e2e/windows-closeout-20261006/post-approval-run-task-diagnostic.json)；修复#2168后须换包复验及完成出库、单据、导出、UI查询 |
| G8 | stable通道 | YELLOW | stable OTA保持关闭；本轮尚未发布客户下载指针；10-06公网曾由灾备节点接管（/xcagi-v*/与/releases/回落为首页HTML），16:50Z DNS回切旧主后stable feed latest.yml为404，下载页仍列出临时包83939363（[可用性](evidence/e2e/production-availability-20261006/run.json)） |
| G9 | OTA升级 | YELLOW | 本轮OTA关闭，覆盖安装与升级证据不得记为OTA通过 |
| G10 | 覆盖升级读回 | UNKNOWN | 支持旧版B002/PB02原ID证据已保留；最终同包升级及同账号界面读回未完成 |
| G11 | 升级后业务 | UNKNOWN | 最终候选B轮新增业务未完成 |
| G12 | 退出重开 | UNKNOWN | 旧cfa230d正常退出零进程再开读回20已实测；不能替代最终候选复验 |
| G13 | 备份恢复与故障取消 | UNKNOWN | cfa230d正式Daily产物已核对，Weekly自然触发及最终同包隔离恢复应用读回未完成；f16373d[任务与进程](evidence/e2e/windows-closeout-20261006/backup-registration-and-runtime-20261006.json)仅证明注册、未触发；f16373d[正常拒绝错误请求](evidence/e2e/windows-closeout-20261006/normal-approval-rejected-pending-zero.png)后库存仍20；不能替代最终C轮 |
## 6. 实机验收任务
最终同包独立A首装完整业务、B受支持旧版原ID同账号读回并新增、C故障取消与正式调度备份隔离恢复；每轮独立时间、输入、结果及原始证据，逐项记入[windows-a/b/c.run.json](evidence/e2e/final-acceptance-1.0.0.5/)，未完成项保持未闭环。
## 8. 发版复用 Runbook
Windows 对外交付唯一安装器为 `tools/XcagiInstaller` 新版 WPF 单文件包；`build-installer.ps1` 和双 SKU 入口均不得跳过外壳。NSIS 仅作内嵌载荷；跨平台诊断载荷不得交付。`windows-release` 域阻断旁路漂移，打包后须实际加载包内更新器依赖。
验收全过后才按既有授权发布临时下载指针，重新从客户入口完整下载核对哈希、版本、运行构建、说明及原始证据；候选验收通过但未发布须报告「候选验收通过，发布未完成」。最终INTERIM_CLOSED仅表示未签名过渡交付闭环，stable OTA仍关闭。

## 9. Windows 候选五模式账号隔离

`fhd-windows-candidate-acceptance.yml` 默认 `account_mode=shared-serial`，沿用 `XCAGI_TEST_USER/PASS`，最多一项。选择 `isolated-parallel` 前，配置五个专用企业测试账号；即使只选 Lifecycle/Rollback，也必须完整配置五组，缺项或重复身份直接失败，不回退共享账号。

| 模式 | Actions Secrets（用户名、密码） | Actions Variable（云端身份） |
|---|---|---|
| Clean | `XCAGI_TEST_CLEAN_USER`、`XCAGI_TEST_CLEAN_PASS` | `XCAGI_TEST_CLEAN_MARKET_USER_ID` |
| Upgrade | `XCAGI_TEST_UPGRADE_USER`、`XCAGI_TEST_UPGRADE_PASS` | `XCAGI_TEST_UPGRADE_MARKET_USER_ID` |
| Gui | `XCAGI_TEST_GUI_USER`、`XCAGI_TEST_GUI_PASS` | `XCAGI_TEST_GUI_MARKET_USER_ID` |
| Recovery | `XCAGI_TEST_RECOVERY_USER`、`XCAGI_TEST_RECOVERY_PASS` | `XCAGI_TEST_RECOVERY_MARKET_USER_ID` |
| Rollback | `XCAGI_TEST_ROLLBACK_USER`、`XCAGI_TEST_ROLLBACK_PASS` | `XCAGI_TEST_ROLLBACK_MARKET_USER_ID` |

五个用户名与五个正整数市场用户 ID 必须分别唯一；用已核实的 `/api/auth/me` 的 `data.market_user_id` 配置 ID。每项在业务操作前核验实际云端身份、企业资格、非管理员及无代操作身份，证据只增加身份哈希。桌面 tenant_id 是各 VM 本地编号，可以都为 1；同一模式升级、重装、恢复、回滚仍保留原账号及本地 tenant/workspace 断言。

五项都核对现有企业桌面访问资格，兼容企业授权也可满足，不要求新购套餐。只有 Gui/Recovery 需要可写 ERP Mods 与现有普通 `user`/`operator` 角色；申请人可处理自己的审批请求，不新增平台管理员、审批管理员、生产运维或发布权限。不要以猜测的 purchase/inventory 权限或自建租户角色替换现有业务角色。

Gui/Recovery 保留聊天入口的 `ai_business` 用例，Recovery 另测取消自己的授权；当前客户写入可走确定性规划，这不构成付费模型调用、充值或无限额度的要求。Clean/Upgrade/Rollback 不因账号池含五项而增配 ERP/AI 权益。

复用前须取得管理员确认的五行非秘密清单：模式、市场用户 ID、用户名、专用合成测试用途、未删除及桌面访问资格、现有角色/Mod 权益、凭据库引用。仓库演示配置和历史验收不能证明当前账号库存。现有 `/api/admin/users?is_enterprise=true&limit=50&offset=0` 与 `/api/admin/users/{id}/mods` 需要既有管理员会话，且不能单凭企业标记判定可复用；不读取密码、密码哈希或模型凭据。名单核验后只申请把指定凭据库中的现有凭据写入上述十个 Secrets，并写入五个 ID Variables；新建账号、扩权、购买或充值须另有具体证据与授权。不得使用客户数据、复制发布签名私钥或创建额外 GitHub 账号。

每项使用新的 GitHub 托管 Windows VM，安装目录、APPDATA、端口、注册表、备份任务及 SQLite 均在 VM 内；GUI 标记包含 run、attempt、mode、phase。现有 fixtures 只改本地合成数据，没有远端批量清理。账号池由固定 concurrency group 排队复用，禁止同时手动运行未使用该锁的历史工作流。每项仍校验同一原包来源和 SHA-256，发布仍要求五项全部通过；单项/Lifecycle 结果不能充当完整发布验收。账号配置与真实五账号验收未完成时，不得宣称并发已上线。
