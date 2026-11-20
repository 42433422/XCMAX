# 自治系统运维手册

维护范围：桌面、服务器和 CI 自治；源码、运行证据及客户验收分别报告。
本文件随 autonomy 变更维护。发布门禁见 [CI_SSOT.md](./CI_SSOT.md)。

## L2–L6 缺口与闭环边界（2026-11-21）

这里的等级描述工程能力，不能用最高层的模块名称代替整套系统的生产验收。
本轮以 `main@2f386f68` 为起点，复用 #3396 的定时治理、战略候选和在职训练组件，
并整合 #3397 的锁定依赖修复（ws 8.21.0、Zod 4.6.6）。
下表列出审查发现的闭环缺口及代码承接点；实际部署、凭据配置、真实客户确认和业务观察须另有回执。

| 层级/维度 | 发现的缺口 | 代码承接及完成条件 |
|---|---|---|
| L2 任务可靠性 | 派发或 queued 被当成完成；跨进程预算身份丢失 | 复用员工执行器和持久任务身份，终态回执才完成；无预算适配的远程执行在出站前拒绝 |
| L3 staging | 继承生产环境标记、目录/端口/数据库不隔离，迁移错误被吞 | `staging_environment.py` 强制隔离；schema 与 Alembic revision 同事务恢复；按实际提交核验健康 |
| L3 发布与恢复 | HTTP 200/退出码不能证明部署身份，回滚缺幂等请求；扫描与部署判定不一致 | 复用 immutable release 脚本；当前/目标制品 CAS、同一发布锁、持久请求与实际身份读回；手动扫描共用部署严格校验器，趋势制品独立命名 |
| L3 备份与保留 | pg_restore 失败仍成功，SQL 失败被当成零行；估算行数与 dump 不同快照 | PostgreSQL 原生导出快照供 dump 与精确计数共享；恢复核对摘要与精确计数，旧估算明确未核验；事务/错误停止及清理失败如实上报 |
| L4 客户修复执行 | 模型工具能读原始 key；普通 mask 也会把 key 替换进请求正文 | SRT 官方请求过滤只向固定 HTTPS 模型端点注入 Authorization；隔离进程只有无用占位符；私钥、宿主进程、发布凭据隔离 |
| L4 发布衔接 | 执行器回报与受信发布器之间缺不可伪造的隔离身份 | GitHub artifact digest 绑定原 request/run/source/candidate；每次新写前复核管理端批准与模型分配 |
| L4 客户验收 | 部署成功、原客户确认和新反馈不能混用 | 沿用原单/原账号/原版本确认，撤销与重开阻断后续推广；已完成操作允许只读核对 |
| L5 效果判定 | measured 就计为改进，负收益可能进入成功知识 | 预注册方向、最小提升、置信区间、样本和护栏；负面拒绝、不确定等待，成败均回流下一轮 |
| L5 实验运行 | 只查已有统计，缺建实验、真实分流、曝光和停止 | GrowthBook REST + Python SDK，员工真实 system prompt 分流与 SQL outbox 曝光/结果；无数据源或样本不推广 |
| L5 失败撤回 | 仅登记回滚请求，未确认恢复 | LangGraph 恢复节点调用同一发布/实验适配器，保留当前与目标身份并实际读回；未知结果只核对 |
| L5 在职训练 | 首簇类型错误、latest 漂移、仅汇总通过数、直接覆盖 prompt | #3396 trainer + promptfoo 固定版，同 case/provider 成对回归、文件和结果哈希；仅形成待审批候选，再进入线上实验 |
| L6 战略发现 | 无真实输入到提案的消费者，候选不关联历史结果 | 复用 #3396 18 域/模型资产/仓库信号和账号反馈；统一进入 SQL 战略提案，下一轮读取真实复盘 |
| L6 资源组合 | 贪心/手工分配不能处理依赖、风险与多资源约束 | OR-Tools CP-SAT 同时约束费用、tokens、时长、依赖、并行度和风险；限整数范围并独立核验可行解 |
| L6 授权与账本 | 默认自授预算、JSONL 先读后写可并发超支、旧通用接口可伪造 | 只使用 StrategicDecision/ActionItem SQL 账本；认证管理员、原账号、提案摘要、有效期绑定；旧路径无新预算写权 |
| L6 实际消费 | 按计划费用或缺失 usage 当零；内部重试隐藏费用 | 每次平台调用先持久预留，再记供应商真实 usage；按批准费率计提，不冒充供应商账单；未知消费保留占用并停止 |
| L6 商业回报 | 全局开票/GMV 被算作本战略收入 | 同目标、同真实支付订单、同客户且有 outcome+acceptance 回执才归因；排除退款、未来时间和无关客户 |
| L6 止损与再分配 | 无预注册观察窗/阈值；停止后仍可继续消费 | 预注册假设、窗口和停止条件；每次调用/调度复查；仅在已批准候选与剩余额度内再优化 |
| L6 持续运行 | 模块存在却未调度，故障只写告警不回任务 | 既有 APScheduler 每 60 秒推进获批组合；#3396 清理空转任务、统一版本配置来源、补失败 incident；回执决定状态 |

18 域、108 项验收仍使用 `FHD/config/audit_benchmark_ssot.json`，不创建第二套分数。
依赖分层、ERP、Agent、ELT、意图路由、事件内核、Mod SDK、桌面、业务前端、商城 UI、
商城后端、自治维护、Java 支付、Flutter、Retort、编码沙箱、客来来和 CI 发布都可作为
战略候选的受控来源；本轮没有据模块接入宣称这 18 域已完成全部基准或真机验收。

### 战略控制入口

`/api/xcmax/strategic/portfolios` 提供 discover、创建提案、读取、approve、plan、run、review、stop。
所有写入使用认证管理员与原 owner；approve 必须提交 `expected_proposal_sha256`。
通用 decisions/meetings/action-items 接口不能代写组合预算或执行结果。
预算包含明确币种口径的费用上限、tokens、时长、并行度、风险、过期时间和模型费率来源。
调度器只推进已批准的组合；账号失去管理权限、过期、消费不明或触发止损即停止新增消费。
旧 `strategy_bets` JSONL 仅用于历史读取，不与 SQL 预算双写。

持续选题使用 `MODSTORE_STRATEGY_DISCOVERY_TEMPLATE` 指向管理员维护的 JSON，包含
`owner_user_id`、`goal`、`limits`、`period_days`（1–90）和可选 `use_llm`。
`limits` 使用同一 `PortfolioLimits` 合同；绝对 `expires_at` 到期后须显式续订，不能定时自授新预算。
既有 `plan_strategy` 消费该模板，周期键在 SQL 中唯一领取；同周期重试读取原结果。
新结果始终为待批准提案。无模板返回 `not_configured`；旧域审计快照只提供带日期的待复查候选，
canonical 域标识来自 `FHD/config/audit_benchmark_ssot.json`，历史缺口与 `UNRATED` 不当作本次现状或得分。

在职训练仍使用 `MODSTORE_RETORT_PROTOCOLS` 内的受控模板，新增 `training_candidate` 配置：
`employee_id`、`owner_id`、`goal`、`prompt_path`、`growthbook` 与 `recovery`。
只接收原服务令牌提交的精确 bundle/result 原文与四个冻结文件，复查当前 main 提示词、
真实失败 run ID 和摘要；重试同 request_key 不新建任务。第一次批准涵盖精确 replacement，
独立验证后还有正式验收批准。原失败案例与结果保存在私有证据中，公开附件只含摘要和候选编号。
候选执行与客户修复使用同一不可导出凭据协议；线上实验只覆盖预先批准的账号 cohort，
推广也仅在该 cohort 内生效，扩大范围需新批准。配置、租约或审批失效不能把已发布候选当作默认全量结果。

### 运行与验收前提

- 生产安装 `MODstore[web,governance]` 及仓库固定版本的 Retort/LangGraph，使用现有数据库迁移。
- 战略员工须由管理员在既有 `config.workspace_policy` 中配置批准范围内的非空 `scope_globs` 或 `forbidden_globs`。
  完成回执要求实际路径检查已执行且通过、原 verification 至少一项实际检查及计数一致；未配置路径检查、缺失或未知回执保持未完成，不释放未知执行的预留额度。
- 客户代码修复使用支持的 Ubuntu 22.04 原生隔离宿主、OpenCode 专属平台模型准入、
  `DEVFLEET_FORCE_OPENCODE=1` 与 `MODSTORE_PARA_PLATFORM_POOL=1`；开关本身不构成隔离证明。
- 实验须配置真实 GrowthBook API、项目、数据源、预注册指标和实际曝光查询；首个内置流量入口是员工 prompt。
  其他产品表面须通过同一受控实验接口接入真实流量，不能伪造曝光来补足样本。
- `experiment.exposed` 写入真实账号曝光；`experiment.observed.success` 仅代表实际 cognition 模型调用结果。
  整任务成功率从既有 `EmployeeExecutionMetric` 与 verification 结果关联曝光窗口，付费结果从原支付台账关联正式制品；不能用模型返回成功替代任务或商业成果。
- 模型价格是已批准费率的计提依据，供应商账单与真实业务收入各保留自己的来源；缺失数据报告未知。
- 自动发布恢复须将 `MODSTORE_AUTO_ROLLBACK_COMMAND` 配置为 `/usr/bin/bash /opt/xcmax/releases/<approved-controller-40sha>/成都修茈科技有限公司/MODstore_deploy/scripts/xcmax-immutable-release.sh --submit-rollback-json`。
  控制器必须来自已有正式 manifest 的只读版本，不能指向 `current`。入口冻结请求后复用 systemd transient service，在独立服务中执行既有回滚；不修改服务权限。缺少既有权限返回等待，提交不明不重复执行，`accepted` 仅代表受理。
  原版本清理器保留明确配置的控制器，以及未完成恢复请求的控制器、当前和目标版本；支付服务查询异常阻断完成，只有明确未安装才跳过其身份读回。
  Retort 仅在同一请求的持久 `rollback_verified` 回执及 API、scheduler、public 和适用的 payment 身份重新核验后完成；指针已切换、命令退出零或单个入口健康均不足以确认恢复。
- 生产部署、客户确认、付费转化和观察窗口尚未实际发生时，状态维持等待，不自动登记为 L6 验收完成。

## 共同契约

| 对象 | 职责 |
|---|---|
| Signal | source、kind、severity、detail、ts、payload，记录触发事实 |
| Diagnosis | root_cause、confidence、detail、evidence，记录诊断依据 |
| Action | type、params、idempotency_key、max_attempts、risk |
| Policy | matches、gate、plan；纯函数，不读取当前时间，使用输入信号时间 |
| AutonomyAdapter | collectTruth、subscribeSignals、executeAction、audit；可选 getRemoteState |
| RuntimeTruthSnapshot | 进程、端口、磁盘、配置、备份、版本、数据库和网络状态 |
| AuditEntry | ts、source_signal、diagnosis、action、result、truth_snapshot |

执行顺序：采集现实状态 → 派生信号 → 策略计划 → 次数/冷却检查 →
影响预测 → 跨端门禁 → 执行 → 审计。失败耗尽次数转人工处理。
实际路径以当前代码为准；工作流存在不等于已完成真机或生产验收。

## 实现位置

| 端 | 控制与执行 | 策略与验证 |
|---|---|---|
| 桌面 | `FHD/desktop/autonomy/controller.ts`、`desktop-adapter.ts` | 同目录 `policies/`、`__tests__/` |
| 服务器 | `FHD/scripts/autonomy/cvm_autonomy_watcher.py`、`cvm_adapter.py` | 同目录 `policies/`；`FHD/tests/test_autonomy/` |
| CI | `FHD/scripts/ci/ai_self_heal.py`、`ai_review.py` | `FHD/tests/test_ci/`；对应 GitHub workflows |

桌面从 backend exit 等事件触发；服务器 watcher 由定时任务触发；CI 从失败任务和 PR 触发。
MODstore 维护循环另见 `modstore_server/maintenance_loop/`，包含代码任务、审核、QA 和恢复。
Rundeck 候选不替换这些代码修复及发布流程。

## Retort 改进闭环

本配置的角色约定：**终极员工**与**超级员工**均定位为管理员层级；小X的预期角色为管理员。这里描述角色设计，不是账户授权或已启用权限的证明。
实际 Retort 管理接口仍使用 `retort_evolution_api.py` 的既有 `require_admin` 检查；称谓本身不授予权限，也不改变 `AGENTS.md` 中终极员工与超级员工的合入职责、审批或发布门禁。
管理端 Claude CLI 默认保留 `acceptEdits`；无人值守工具执行由运维通过既有 `DEVFLEET_CLAUDE_PERMISSION_MODE` 显式配置。普通产品域强制受限，已配对手机中继保留原默认模式；管理员角色说明不替代工具执行授权。
管理端「改进闭环」使用既有 Element Plus；Retort 负责方案和吸收任务，LangGraph 1.2.10 负责持久执行、审批中断和恢复，GEPA 0.1.4 仅提供实测辅助方案（上游分别为 langchain-ai/langgraph、gepa-ai/gepa，MIT）。
18 域及 108 项要求仍以 `FHD/config/audit_benchmark_ssot.json` 为准，参考仓库不等于已经通过相应基准。

固定流程：冻结要求、测试文件哈希与 main 提交 → Retort 方案 → 可选 GEPA 实验 →
管理端批准公开任务 → GitHub Issue → 现有员工经 Para 在 Actions 执行 →
独立 job 用固定镜像验证前后提交 → 管理端确认实际效果 → 已验收知识回流 Loop。
GEPA 训练、验证、最终留出任务隔离；旧 prompt 入口不再通过模型投票自动覆盖员工提示词。
辅助实验失败保留原方案并交管理员审阅。部署及 CI 使用仓库内固定版本的 LangGraph 包，
PostgreSQL 检查点为带既有安全回补的 `3.1.1+xcagi.1`，不可替换成未回补的公共 `3.1.1`；版本以 `FHD/packages/xcagi_langgraph_*` 为单一真源，Dependabot 不得把 `FHD` 或 `packages/retort_engine` 里的对应依赖单独改成 PyPI 新版本（包括把该 fork 换成公共 `3.1.3`），升级须连同 vendor 与分叉补丁一并评审。
检查通过只形成 E2 任务证据，不自动给域打分，也不代表合并、上线或客户验收。

`MODSTORE_RETORT_CHECKPOINT_DSN` 选现有 PostgreSQL；`sqlite:///...` 仅供单机验收。
原生数据库会话锁协调多个调度器，外部 Issue/执行先记意图；回执不明时只核对、不重复派发。
现有 APScheduler 每 30 秒推进未结束任务，未配置持久存储时不运行。
`MODSTORE_RETORT_PROTOCOLS` 指向受控验收方案 JSON：键为方案 ID，值含 name、criterion_ids、
checks（id、criterion_ids、argv、files 的 SHA256、timeout_seconds）和固定 digest 的 container_image。
测试在无网络、只读项目挂载的 Docker 中运行；原始日志与 Actions artifact digest 一起核验。
验收前复用 Retort 的加密工件组件，将证据持久写入 `MODSTORE_RUNTIME_DIR/retort-evidence`，
沿用 `RETORT_ARTIFACT_MASTER_KEY` 或已有 `MODSTORE_LLM_MASTER_KEY`；不能仅依赖 90 天的 Actions 附件。
`MODSTORE_RETORT_RSI_PROTOCOL` 可选：project、check、container_image、evidence_dir、
trainset/valset/holdout（唯一 id）及 max_metric_calls；评估命令从 stdin 读取 candidate/task，
只输出 score（0–1）、output、feedback JSON。基线与留出结果均保留原始证据。
配置及生产启用另行验收；组件测试不能代替云端真跑与原业务场景验收。

## 动作与边界

| 范围 | 动作 |
|---|---|
| 桌面 | restart_backend、rollback_version、clear_cache、repair_config、escalate、noop |
| 服务器 | restart_service、rollback_to_last_tarball、freeze_manifest、unfreeze_manifest、clear_logs、open_incident_issue |
| CI | create_pr、comment_pr、escalate |

服务器策略包括 health_down、manifest_drift、disk_full、compose_unhealthy。
桌面策略包括 backend-crash、degraded-remediation、update-rollback。
高风险动作不得因迁移执行器绕过审批；medium 冷却和最大尝试次数仍由现有守护链控制。
任何执行结果都须核对实际恢复，不能仅依据命令退出码宣称故障已关闭。

## 跨端门禁与冻结

`XCAGI_CROSS_TIER_GATE` 默认启用，值为 `0/false/no` 时关闭。
桌面回滚检查服务器冻结状态，服务器回滚检查桌面待回滚状态，发布流程检查服务器冻结状态。
未知远端状态应阻断受保护动作；各端实际代理信号和降级路径需分别验收。

服务器冻结标记为 `${MANIFEST}.frozen`，保持 manifest 本身不移动。
解除冻结前核对 hold_ttl、健康检查和发布身份；不得沿用旧 `.hold` 操作命令。
相关实现：`cross-tier-gate.ts`、`cross_tier_gate.py`、`cvm_adapter.py`。

## 审计与人工介入

桌面审计位于用户数据目录 `audit/autonomy-audit.jsonl`；服务器适配器写部署目录
`autonomy/audit.jsonl`；实际路径可由启动配置覆盖。CI 结果保留在对应 workflow run。
查询工具：

```bash
cd FHD
python scripts/autonomy/audit_query.py --source server --since 24h --limit 100 --path /actual/audit.jsonl
```

支持 `desktop/server/ci`、时间窗口及重复 `--filter`，例如 `result.ok=false`。
最大尝试次数耗尽、风险门禁拒绝、真实执行失败或状态不明时，保留证据并进入人工处理。
查看 GitHub Issues、审计记录和目标服务器状态；原有通知入口及审批账本保持原职责。
CI 相同故障指纹有 24 小时去重，`autonomy/` 分支避免递归触发自愈。
模型诊断不可替代执行授权；confirmed-high 审查发现按 CI 门禁处理。

## 验证与变更

```bash
cd FHD
python -m pytest tests/test_autonomy/test_cvm_adapter.py tests/test_autonomy/test_cvm_watcher.py
python -m pytest tests/test_autonomy/test_rundeck_executor.py
```

桌面使用 `XCAGI_DESKTOP_TEST=1 npx vitest run autonomy/__tests__/`。
测试数量与通过状态只引用当前运行回执，不沿用历史计数。
故障演练覆盖 backend 连续崩溃、健康检查失败、冻结阻断、升级回退、重复事件及执行器失联。
CI 自愈还需证明日志、目标 diff、生成 PR 与原失败关联，测试通过不等于已发布。

新增策略须注册并测试；新增动作同步类型契约、适配器、影响预测和适用的跨端门禁。
跨端规则应验证 TypeScript/Python 的语义一致性。保留人工接管和可追溯审计。

## Rundeck 迁移候选（尚未生产启用）

服务器 `CvmAutonomyAdapter` 可通过 `XCAGI_MAINTENANCE_EXECUTOR=rundeck`
将 `restart_service` / `clear_logs` 交给预登记的 Rundeck Job；其他动作仍走原路径。
配置 `XCAGI_RUNDECK_URL`（远端必须 HTTPS）、`XCAGI_RUNDECK_TOKEN` 与
`XCAGI_RUNDECK_JOBS`（动作名到 Job UUID 的 JSON 映射）。令牌仅授予对应项目、
Job 的运行、读取与取消权限；禁止任意命令、Job 编辑和代用户执行权限。
Job 必须由运维预先绑定固定目标、超时和维护脚本，不能把模型输入插入命令。

执行回执保存在原 audit 目录的 `rundeck/`。网络结果不明时保留 submitting 回执，
禁止自动重发或降级到本机执行；需核对 Rundeck 历史后人工处理。
固定故障类别映射到持久化事件实例；仅 Job 成功且后续健康检查通过才结束实例。
未知提交和失败任务需人工核对，不自动重试。Job 模板及固定动作脚本位于 `FHD/deploy/rundeck/`。
部署前需核对目标节点、部署目录和本地健康端口；候选尚未完成目标服务器验收。
命令成功只代表 Job 成功，仍需原健康检查确认实际恢复。
管理端 Loop 复用 Element Plus、现有轮询及审批入口；Rundeck 日志经管理端会话校验和 Job 绑定检查后读取，无需单独登录。维护状态与操作固定使用同一目标，默认既有运营服务，仅 `MODSTORE_LOCAL_AUTOMATION=1` 选择本地；连接失败不跨目标重放。只读监控允许管理端会话读取，写入仍保留运营授权和原审批门控。
该候选未覆盖代码修复流程、桌面自治或发布回滚，不能标为全量迁移完成。

## OpenIM 员工群迁移候选（默认关闭）

复用 OpenIM 官方服务和 WASM SDK，管理端原会话换取当前用户令牌；管理密钥仅在后端。
`FHD/scripts/ops/openim_candidate.py <目录>` 准备固定版本官方 Compose（只开放本机端口）；
在该目录运行 `docker compose --env-file candidate.env -f candidate-compose.yaml -p xcmax-openim-candidate up -d`。
后端设置 `XCAGI_AI_GROUP_TRANSPORT=openim`、`XCAGI_OPENIM_API`、`XCAGI_OPENIM_SECRET`、
`XCAGI_OPENIM_PUBLIC_API`、`XCAGI_OPENIM_PUBLIC_WS`；前端无需第二次登录。
SDK 固定 `@openim/wasm-client-sdk@3.8.3`，同时发布其实际 Apache-2.0 LICENSE 和官方 WASM。
仅员工群消息传输试迁移；派工、权限及加密执行审计仍由宿主负责，普通私聊未迁移。
已确认投递记录保存在审计目录 `openim-publication.sqlite3`；未知回执先核对，不自动重发。
群成员在打开/发布消息时同步；候选禁止删除群和消息，避免两边历史不一致。
生产启用前须完成同源 HTTPS/WSS 代理、WASM 内容安全策略、删除/成员同步和多端验收；
当前仅本机开发候选，不代表主线发布、完整替换或 AI 员工真实任务验收通过。

聊天界面候选直接使用 `vue-advanced-chat@2.1.2`（MIT），员工/普通会话/群聊共享组件；
宿主只适配消息、草稿和业务动作，许可证随前端 `/licenses/vue-advanced-chat.txt` 发布。

## 员工工作空间与受信发布器

管理端默认展示 GitHub 工单工作空间，Element Plus 承担界面；原 LangGraph 任务、事件、
Vue Flow 图和产物保留在「原执行记录」，不从历史页新增或恢复本地任务。
产品问题由管理员确认独立的公开技术摘要后创建 Issue，客户原文与附件不自动外发。
关联写入既有客服动作与 Work Order 事件；未知提交只查询回执，不重复创建。
共享产品工单进入 GitHub 待办，私有 Mod 保留原交付流程；已有 Mac 小组仍核对原回执。
执行复用生产已有的员工编排、事务 outbox、事故领取与 Para 回执；核查、修复、验证岗位
保留原员工身份。代码修复交给 Para，Codex 是 Para 内部执行工具，不接 Codex Action。
当前工作流使用独立 execute、publish、resume 和 verification 任务；发布令牌不进入模型任务。
旧 `github_para_worker.mjs` 的 `blocked_isolated_publisher_required` 仍保留，不能借旧入口绕过边界。
客户反馈与训练候选修复仅接受 `srt-0.0.83-header-only-platform-v1`：可信控制进程持有 key，
模型进程只拿占位符，SRT 官方 TLS 代理按精确主机、路径、方法和批准模型注入请求头。
普通 mask 的请求正文替换功能不启用。原 PR repair 尚未接此专用协议，仍保持原暂停状态。
隔离、模型分配或回执不满足时保持 blocked/waiting；正式发布仍沿用主线 CI 与管理端审批。
本地自研 LLM 实现引擎及进化账本本地回退已移除，原 Para 工作流与授权检查保留。
服务端使用 `MODSTORE_GITHUB_TOKEN`（Issues/Actions 写、Contents/PR 读）、
`MODSTORE_GITHUB_REPOSITORY` 和 `MODSTORE_PARA_GITHUB_{API_BASE,AUTH_TOKEN,DEVICE_ID}`。
`para-github-worker.yml` 只负责临时机器生命周期，既有员工与 Para 引擎保持原实现；
派工必须同时核对工作流、请求、运行次数、在线设备回报，不能以监控桥代替执行器。
工作流变量为 `PARA_GITHUB_API_URL`、`PARA_CODEX_VERSION`、`PARA_CODEX_MODEL_CANDIDATES`；
沿用 Para 授权配置至受保护 secrets：`PARA_GITHUB_DEVICE_TOKEN`、`PARA_CODEX_AUTH_JSON`
（或已有 `PARA_CODEX_API_KEY`）、可选 `PARA_CODEX_CONFIG_TOML`，以及原派工与提交令牌。
工作流重跑不会重新执行；响应丢失保留原回执核对。尚未配置时禁止派工。
PR 合入不关闭客户工单，仍按原客户验收规则处理。
候选须管理端验收、主线集成、服务部署和云端真实运行验证；不能据此宣称迁移完成。
