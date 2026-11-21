# 自治系统运维手册

维护范围：桌面、服务器和 CI 自治；源码、运行证据及客户验收分别报告。
本文件随 autonomy 变更维护。发布门禁见 [CI_SSOT.md](./CI_SSOT.md)。

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

## 自主编程与工具执行

2026-11-21 本轮审计基线为 `main@48f8f40d14dfc373afd4ca43790c560f78b44481`，随后同步 `main@171418352d24667a7123b6556c55bad445ef3440`（#3424 的规划澄清已合入）；另核对 #3398、#3418、#3428，避免重复实现候选中的预算与交付工作。下面是本次范围内已定位的断点与改造；源码与受控回归是 E1/E2，不等于原生部署、真实模型或客户验收。

| 缺口 | 原执行链中的修复与复用 |
|---|---|
| Codex 退出码 0 或文本被当成成功 | 依据固定 0.153.4 协议消费原生 JSONL，并记录实际 CLI 版本；同时要求完整 `turn.completed` 和退出 0，保留 thread、usage 与工具回执。 |
| 失败轮次只因产生 diff 就提交、发布 | 同一工具链在 finalize 前核对结构化结果；失败或未知保留工作区与回执。 |
| 执行后的配额错误触发换模型或换工具重做 | 模型选择限定于只读准入/探活；真实执行开始后禁止盲目降级重放。 |
| 超时升级终止未覆盖仍存活进程树 | 不把 `child.killed` 当退出证明，等待原生 close，必要时终止进程树；取消与超时回执继续沿原 outbox。 |
| 两个安装入口运行不同 Codex 实现 | 旧 e2e 入口转发 canonical Para 执行器，安装脚本复用原实现及依赖。 |
| 同一 unknown 回执首次 completed、幂等回读 unknown | 原 task lifecycle 分类器统一归一化，再由工具 deadline、StepExecution 和幂等账本消费。 |
| LangGraph unknown 后仍执行下游 | 原图执行器与结果验证使用同一分类；未知副作用保留 blocked/待核对，禁止自动修复重放。 |
| 已观察工具记录与历史恢复仍用另一套成功条件 | observed trace 与 safe continuation 复用同一结果合同；业务数据状态不当执行终态。 |
| 服务器把 Para accepted 当 completed | 维护循环复用已有 customer issue 执行合同，要求真实完成与原任务身份。 |
| 丢回执被作为瞬态代码故障再次派单 | 外层派发与内层代码重试均识别待核对；原 `para_task_id` 路径只读回。 |
| 派发或步骤间重启丢失进度 | 原 loop memory 在派发前持久化 request/actor/步骤；已确认步骤保留到整轮结果落盘，恢复只核对原任务及原代码分支。 |
| 原 review 未核对就被新知识拒绝分支清除 | 回读原 review 前不再执行会清检查点的知识/Retort 分支；新 review 派发仍需原门禁。 |
| 最终合并或记账后重启，再执行最终策略 | 最终策略前保存意图；有原最终回执时只续记账，已确认记账只清检查点，未知合并或投影保持待核对。 |
| 整理记忆覆盖正在执行的记录 | 公开清理/关闭/对账入口共用原 loop lease；忙时明确返回，保留原待处理项。 |
| 验证命令没有退出码仍算通过 | 提供了 delivery validation 时，要求非空命令回执及真实整数退出码 0；缺失、超时和非法回执拒绝。 |

本轮复用 Codex 0.153.4（Apache-2.0）、仓库内 LangGraph 1.2.10 及其检查点回补（MIT）、MCP 2.3.0（MIT）、现有 SQL/CAS、Para 任务/outbox 和维护账本。选择依据与固定来源见 FHD README。官方 [LangGraph 重试与副作用规则](https://docs.langchain.com/oss/python/langgraph/fault-tolerance#retry-boundaries-and-idempotency)要求持久化幂等身份并核对丢失的确认；检查点本身不能保证外部副作用恰好一次。没有引入 OpenHands、Temporal 或第二套总控；本次薄适配承担本产品身份与回执规则。

| 尚未闭合的范围 | 具体条件 |
|---|---|
| 原 PR 自动修复 | 原 `MacControlTask` 来源与 Retort 的公司预算/attempt 合同不同。须把原 PR/source SHA/run/attempt 与已批准额度、原生隔离及 publisher 回执接通；保留 `original_pr_repair` 阻断，不能冒用 Retort 身份。 |
| 候选中的客户反馈修复 | #3398 的受信 SRT/OpenCode、逐调用预算和隔离发布已经有消费者；属于未合入候选覆盖，不能当作主线已运行，也不重新写一套。 |
| 原生线程续跑与远程取消 | 本轮保留 Codex thread ID 并修复工作进程信号退出；自动 `codex exec resume`、远程 task cancel 到 thread interrupt 的身份/批准适配仍需独立接线。任务状态回读不等于恢复原生线程。 |
| 请求已发送但无远端任务号 | 持久执行意图保持待核对，禁止新派单；须由远端提供同一 request ID 的可信查找/对账，不能按相似文本推断完成。 |
| 最终副作用丢确认 | 合并/部署已开始而最终回执缺失、或记账已开始但持久投影无法确认时保持待核对；自动恢复仍须按原 task/source/head/merge SHA 接通可信回读，不能重放策略。 |
| 模型硬预算和其他执行器 | Codex 原生 usage 已记录；设备 CLI 的输出 token 上限仍标明 `output_limit_enforced=false`，真实费用/公司额度硬停未闭合。Cursor/Claude 沿用原退出码/stream 合同，尚未统一到同等级原生终态。 |
| 真实环境与长期质量 | 原生 Windows/macOS 进程树、Ubuntu 22.04 SRT、实际模型账单、真实多文件编程留出任务及客户验收分别验证；固定 CLI 的受控进程测试不代表付费模型质量。 |
| 正式交付 | exact head CI、正式审查/合入、同 main SHA 安全扫描和发布、运行版本回读仍走原门禁；受控回归不提升 L1–L6 等级或对标分数。 |

定向验证沿用 `runtime_tools` 的 Node 测试、FHD 的工具/幂等/AgentRun/LangGraph 测试，以及 MODstore 的维护循环、持久恢复和记忆并发测试。按层使用受控替身，另以真实文件锁、进程、Git 和持久化回归验证边界；检查未知后无下游、无重派、无发布，成功正例仍能完成。测试结果以对应提交的 CI/PR 回执为准。

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

## 员工工作空间迁移候选（未合入主线）

管理端默认展示 GitHub 工单工作空间，Element Plus 承担界面；原 LangGraph 任务、事件、
Vue Flow 图和产物保留在「原执行记录」，不从历史页新增或恢复本地任务。
产品问题由管理员确认独立的公开技术摘要后创建 Issue，客户原文与附件不自动外发。
关联写入既有客服动作与 Work Order 事件；未知提交只查询回执，不重复创建。
共享产品工单进入 GitHub 待办，私有 Mod 保留原交付流程；已有 Mac 小组仍核对原回执。
执行复用生产已有的员工编排、事务 outbox、事故领取与 Para 回执；核查、修复、验证岗位
保留原员工身份。代码修复交给 Para，Codex 是 Para 内部执行工具，不接 Codex Action。
当前 GitHub 临时执行器明确停用：返回 `blocked_isolated_publisher_required`，在注入模型、管理端及发布凭据或启动模型前终止。
环境变量白名单不是操作系统身份隔离；须先实现并验证独立可信发布器，不能删除 guard 或设置开关强行启用。
服务端新派工返回 503，已有排队回执在再次消费时转为可查询的 blocked，不伪装为运行中或执行成功；正式发布仍沿用主线 CI 与管理端审批。
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
