# MODstore_deploy（姊妹栈 · 全仓实体）

日更全链路、Vibe 双清单、`daily_action_items` 行动看板、派发/部署状态回写的 **Python 后端实体**落在此目录。

## 关键模块

知识混合检索复用 [BM25S](https://github.com/xhluca/bm25s) `0.3.16`（MIT，`knowledge` extra 固定版本），替换 rank-bm25 与向量候选内的二次关键词筛选。关键词从当前授权语料独立召回，再与向量结果做 RRF 融合；产品侧仅保留实体权限、分页读取与结果适配。

| 模块                                      | 职责                                        |
| ----------------------------------------- | ------------------------------------------- |
| `modstore_server/digest_vibe_prep.py`     | Vibe 预备 → 更新/补丁双清单 MD              |
| `modstore_server/digest_action_items.py`  | 解析 MD → `daily_action_items` 落库 + 回写  |
| `modstore_server/action_items_api.py`     | `GET /api/admin/action-items` 等 API        |
| `modstore_server/daily_digest.py`         | 08:00 digest 主流程（含 action items 钩子） |
| `modstore_server/digest_line_executor.py` | 派发成功 → `dispatched` 回写                |
| `modstore_server/approval_dispatcher.py`  | 部署合并 → `merged` 回写                    |

## 本地启动

OpenAI 兼容客户端通过 `GET /v1/models` 发现管理员登记的池内别名，并使用同一别名请求 `POST /v1/chat/completions`。设置 `MODSTORE_LLM_POOL_ALIASES` 为别名到现有计费模型 ID 的 JSON 映射，例如 `{"xcmax-doubao-code":"doubao/doubao-seed-2-1-pro-260915"}`。仅列出当前账户能通过平台凭据调用、且已通过聊天能力和平台计费规则的条目。套餐路线应先在平台单独配置凭据和计费。

```bash
bash FHD/scripts/dev/run_modstore_daily_local.sh restart
```

默认使用本目录（工作区 `成都修茈科技有限公司/MODstore_deploy`）；若目录缺失则回退 `~/XCMAX-archives/.../MODstore_deploy`。

治理与员工包构建共用仓库包。在仓库根安装开发依赖：

```bash
python -m pip install -e packages/retort_engine -e packages/xcagi_common \
  -e './成都修茈科技有限公司/MODstore_deploy[web,governance]'
```

员工目录内的 `build_xcemp.py` 与资产流水线共用 `xcagi_common.employee_pack`，
保留原来的包内目录和各员工的文件包含规则。仓库内可直接运行入口；导出到仓库外的
员工源码需要在构建环境安装 `xcagi-common`，生成的 `.xcemp` 无此构建依赖。

## 战略与反馈闭环的开源复用

缺口清单、控制入口和运行边界统一维护在 [自治运维手册](../../docs/autonomy.md)。
本轮从 `main@392d50b5` 与 #3398 继续复查，并整合期间新增的 `main@48f8f40d` 统一网关及 #3398 的 `445e2da0` 管理端小 C、`fda4306c` 工作流事务与持久交付修复；随后同步 `main@17141835` 的原 AgentRun 澄清续接与查询结果修复。沿用已纳入的 #3396 战略候选、失败聚簇和定时治理；#3397 的依赖修复已在主干。审批预算与执行结果以既有 SQL 决策账本为准。

| 组件 | 固定版本/许可证 | 复用职责与选择理由 |
|---|---|---|
| [Google OR-Tools](https://github.com/google/or-tools/releases/tag/v9.15) | `9.15.6755` / Apache-2.0 | CP-SAT 处理依赖、风险及同公司多组合资源选择，保留各组合分组约束；产品层校验整数边界、审批范围及最终可行性 |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | 本轮验证 `2.0.58` / MIT，沿用既有依赖约束 | 公司预算、组合任务、调用预留与行动项使用同事务条件 UPDATE；真实责任未知时不采用 TTL 自动回收 |
| [GrowthBook Python SDK](https://github.com/growthbook/growthbook-python) | `4.0.1` / MIT | 官方稳定身份分流；与既有 GrowthBook `5.2.0` REST 统计接口衔接真实曝光/结果 |
| [promptfoo](https://github.com/promptfoo/promptfoo/releases/tag/0.126.0) | CLI `0.126.0` / MIT | 原员工/工作流生成失败的成对回归；保留真实 chat roles 与输入，工作流调用生产转换/静态校验器，只形成待审批候选 |
| [Anthropic Sandbox Runtime](https://github.com/anthropics/sandbox-runtime) | `0.0.83` / Apache-2.0 | 官方命名空间、seccomp、TLS 与请求过滤；原始 key 只在受信控制进程闭包中使用 |
| [LangGraph](https://github.com/langchain-ai/langgraph) / [GEPA](https://github.com/gepa-ai/gepa) | `1.2.10` / `0.1.4`，MIT | 沿用仓库固定包、持久检查点、审批中断和辅助实验；产品只实现协议适配 |
| [APScheduler](https://github.com/agronholm/apscheduler/tree/3.11.3) | `3.11.3` / MIT | 复用现有独立调度进程，推进批准组合、实验和恢复读回 |
| [LiteLLM](https://github.com/BerriAI/litellm/tree/v1.109.3) | SDK `1.109.3` / MIT | 复用现有流式路由；预算调用关闭隐性重试/fallback，在 SDK 归一化前观测供应商原始 usage，避免把本地估算当结算回执 |
| [OpenAI Python SDK](https://github.com/openai/openai-python) | `3.57.0` / Apache-2.0 | 原生 Responses 承接远程 OpenCode 的完整工具协议与逐调用预算；请求专属 `AsyncStream` 同时保留 LiteLLM 规范化前真实 chunk，不另写 SSE 解析器 |
| [SearXNG](https://github.com/searxng/searxng/tree/626105eec11d776e2dbccff6cc93fd2cd85f4d0c) | 参考提交 `626105eec11d776e2dbccff6cc93fd2cd85f4d0c` / AGPL-3.0-or-later | 复用已有服务的 JSON Search API；公开查询进入检索，原客户/订单/目标留在控制面。冻结来源快照，搜索片段作为待验证产品假设 |
| [filelock](https://github.com/tox-dev/filelock/blob/4.2.4/LICENSE) | 服务器锁定 `4.2.4` / MIT；沿用 governance 兼容范围 | 与原维护 ledger 共用派发锁；先持久化意图，再发起 GitHub 工作流，响应丢失只恢复原运行 |
| [Spring Boot](https://spring.io/blog/2026/08/20/spring-boot-4-0-8-available-now/) / [Spring Data JPA](https://docs.spring.io/spring-data/jpa/reference/jpa/transactions.html) | 原 Java 支付服务 `4.0.8` 依赖管理 / [Apache-2.0](https://github.com/spring-projects/spring-boot/blob/v4.0.8/LICENSE.txt) | 复用既有支付模型、原内部认证和同事务查询，核对已批准退款与真实钱包入账；只投影证据，不执行或批准退款 |
| [systemd](https://github.com/systemd/systemd/tree/v249) | 既有主机组件，接口基线 `v249` / LGPL-2.1-or-later | 复用 transient service，在独立服务进程中执行冻结的回滚请求；不修改服务 KillMode 或授予额外权限 |

SQLAlchemy 和 PostgreSQL 继续承载事务、并发 CAS 与持久结果；备份复用既有 PostgreSQL 16 的 [导出快照](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION)与 `pg_dump --snapshot`（PostgreSQL License），不另建快照引擎。已批准的模型费率用于计提，
真实 usage、支付与客户确认来自原台账。旧 JSONL 赌注保留只读兼容。
源码适配集中在 `strategic_portfolio*`、`retort_feedback_*` 和既有发布脚本；
候选生成、优化求解、实验分流、检查点、TLS 代理均使用上述现成实现。
仓库自行保留的胶水仅负责账号归属、审批摘要、预算/订单关联、固定发布身份和既有员工入口；
这些产品合同没有可直接替代的通用上游实现。具体上游差异已核对固定版本源码：
[GrowthBook 5.2.0](https://github.com/growthbook/growthbook/blob/v5.2.0/packages/back-end/src/services/experimentChanges/changeExperimentStatus.ts)
停止并临时推广会将 coverage 设为 1，本地仍保留原批准 cohort；
[LiteLLM 1.109.3](https://github.com/BerriAI/litellm/blob/v1.109.3/litellm/litellm_core_utils/streaming_handler.py)
可能合成或补齐流式 usage，适配器在 Router 预读首块之前通过专属 SDK client 保留原始 chunk 中的两项 token 计数并核对最终值。
CI 安装既有 `llm-router` extra，使用真实固定版 SDK 回归缺失、部分用量和取消场景。
工作流训练通过私有 `WorkflowSandboxRun` 保存原失败；promptfoo 以原 system/user 文本调用同一生产图转换和静态校验器，服务端重验冻结证据。实际 `WorkflowExecution` 终态另用独立 GrowthBook 指标与冻结 SQL 查询，按账号分流并核对实际加载图，撤回会阻止旧 treatment 图再启动；关闭模拟的真实沙盒也使用同一持久回执，运行中改图后原成功不会计到新图。静态校验、执行完成和领域业务达标各保留自己的口径。
`workflow_customer_accepted_outcome` 将原企业客户的单原生文件员工工作流与原付款/KPI 协议、实际 producer 制品、管理员测量及客户确认关联到原 assignment。复用原客户 receipt API 和 GrowthBook 账号统计；窗口成熟、同制品且同协议才形成业务结果。推广后继续原授权交付，不增加实验样本；精确退款通过原 SQL CAS、LangGraph 效果/恢复尾链和不可变发布控制器撤回。真实执行合同保留在 SQL，三个内部事件的总线、webhook 与重放仅输出固定身份摘要。多节点副作用图与其他业务 KPI 未接入此合同。
该客户合同的原触发器和 JWT 执行 API 在真实图返回且序列化成功后，共用原 SQLAlchemy 事务收尾：初次写与 SQL 故障后的唯一恢复都按原执行身份和 running 状态 CAS，并核验原 START/CLAIM/PRODUCED 及制品字节；先前 COMMIT 已成功时只读确认，不重复反馈、业务或计费。持续故障保留未知；进程重启后的 PRODUCED 不能证明整个图已返回，尚不自动补结。
失败收尾则复用原事件执行器抽出的同一事务核心，手动执行 API 的初始 COMMIT/refresh、准入和实际执行故障均先回滚再核对冻结身份；未提交不补造，终态与反馈同事务，确认丢失只读核对。竞争终态保持且不发布虚假失败，公共 HTTP/事件仅使用固定提示或原稳定准入码；诊断保留在原账号隔离记录，成功计费位置与业务执行次数不变。
原支付服务的退款审批与钱包入账通过内部只读 `/api/internal/payment/refund-evidence` 投影，复用原服务密钥、Spring 事务和 JPA 查询。Python 读完固定边界的全部分页后，核对同一订单、客户、退款与钱包交易，按原退款号向既有客户价值账本追加唯一回执；普通字典不能冒充服务端核验事实。这里记录钱包余额退款，银行或支付网关现金退款仍须各自原回执。
该客户工作流沿原客户 quota/wallet 计费，不自动继承公司战略预算。观察窗成熟且权威来源可核验后，没有同制品的合格业务测量和客户确认即记失败；来源不可读时保持等待。未知模型用量目前保留责任，原供应商账单回查并补结的专用消费者尚未接通。
训练 CLI 与 SRT 使用 `capability_trainer_deps` 的完整依赖锁、无安装脚本安装和分步骤凭据；官方 SRT 请求过滤仅允许获批模型的精确 HTTPS 路径。[`5e71eb4b` 的 Ubuntu 22.04 CI](https://github.com/42433422/XCMAX/actions/runs/44895286614) 已通过真实固定 CLI/Python 断言、官方代理及原生 SRT 正向合同；生产宿主和固定模型端点仍须实际验收。
远程报告复用现成 GitHub executor、OpenCode `1.19.6`、SRT 及原任务回执；原生 Responses 支持显式 `function_call_output` 历史，拒绝隐藏历史、付费托管工具和缺失用量。流尾失败返回固定停止提示，不反射内部异常原文，仍执行原清理并保留未知消费。控制器返回成功后仍须核对原 GitHub job 与报告 ZIP 摘要。
工程任务复用原 Retort/Para `handleTask`、候选 Git bundle、独立验证和发布链，原公司/组合预算关联每个 event/task/subtask/attempt 与阶段 grant；候选工件不是完成回执。公司封套和执行槽由原 SQL 事务统一争抢，未知责任禁止换池，阶段结束只释放有原生 job 证明的槽位。原提案可显式批准 `remote_execution.life_lease.mode=persistent_phases` 与绝对 `expires_at`，在原 life policy/组合/公司期限内恢复同一工程任务；原周期与预留不变，默认仍为 300 秒。外部采购、支付和未接入的 Para/Cursor 仍有明确适配边界。
公司调度复用同一 CP-SAT，纳入全部当前可合法启动的原批准候选，包括局部计划曾延后的项目；同时约束公司和每个组合的剩余额度、依赖与容量。实际 claim 再核对并 CAS 预留，完整候选超过 256 时拒绝截断；限时可行解与已证明最优分别记录，不能扩大原批准额度或覆盖未知占用。小 C 预留同样覆盖原批准的就绪候选，容量恢复后不会因旧局部空计划或历史复盘时间饿死任务；原客户验收率的真实复盘进入下一轮认知。
最新主分支的 LiteLLM 网关按[官方逐请求重试控制](https://docs.litellm.ai/docs/proxy/reliability)接线：在实际 HTTP 正文禁重试/fallback，并读取原始代理 attempt 响应头；本地 Router 自己的零计数不能替代网关回执。缺失或非零回执不结算成零消费。
另选择性复用 [#3418 的现成修复](https://github.com/42433422/XCMAX/pull/3418)：在真实 SDK 的每帧规范化前保留原始模型，首个不匹配不会被末帧批准别名或 usage 更新覆盖；直接 SSE 与 Router 都保留未知责任。训练 mine CLI 只输出统计，语料删除重复 employee_id，保留原 surface/resource_id、输入、generation_context 与 case 哈希及旧语料兼容；内部认证采集接口保持原私有合同。
客户原生文件沿用原客户价值 API、SQL 协议/支付归属和 FastAPI/Starlette HTTP 响应；只返回原客户目标下已完成制品的摘要一致字节，下载不自动生成验收或效果回执。
SearXNG 参考提交用于固定接口与许可证审查，不代表 `MODSTORE_SEARXNG_URL` 指向的现有实例已经核验版本或启用 JSON。
战略 Python 任务复用标准库 ZipFile/SourceFileLoader 与原员工解析器，从已批准归档字节创建执行快照；
这项合同核验不代表新建 OS 沙箱，也不把宿主所有依赖声明为不可变。
组件版本、配置可用性、测试、生产回执分别核验；接入组件不代表 L6 生产验收完成。

## 前端看板

`XCAGI-Full-Pipeline.html` → `#s-gaps` / `#s-roadmap` 由 `docs/xcagi-dashboard/emp-wf-action-items.js` 拉取本栈 `:8788` API 动态渲染。

## Para 的 OpenCode 工作设备

使用 [anomalyco/opencode v1.19.6](https://github.com/anomalyco/opencode/releases/tag/v1.19.6)（MIT）和 [anthropics/sandbox-runtime v0.0.83](https://github.com/anthropics/sandbox-runtime/tree/v0.0.83)（Apache-2.0）。工作设备可用 `npm install -g opencode-ai@1.19.6` 安装 CLI，也可用 `DEVFLEET_OPENCODE_AGENT` 指定原生可执行文件；在设备代理所在目录执行 `npm install --prefix <代理目录> @anthropic-ai/sandbox-runtime@0.0.83`，或用 `DEVFLEET_OPENCODE_SANDBOX_ENTRY` 指定该固定版本的 `dist/cli.js`。需 Node 22.12+；Linux 仅支持 Ubuntu 22.04 的非 root 用户，且用户命名空间不得被宿主策略限制，还需系统 bubblewrap、socat、ripgrep；macOS 需原生 sandbox-exec 与 ripgrep。GitHub 安装器准备同一组固定依赖。缺少沙箱时工具不就绪，执行失败不会降级到无沙箱进程。

GitHub 安装步骤不接收模型、网关、设备或 GitHub 凭据；使用 `runtime_tools/github_executor_deps` 中的完整性锁执行 `npm ci --ignore-scripts --include=optional`，禁止依赖生命周期脚本留下同用户后台进程。Ubuntu 22.04 x64 直接启动官方 `opencode-linux-x64-baseline@1.19.6` 的原生入口，不运行 npm 包的 postinstall stub；安装后无凭据核对 CLI 版本、固定沙箱及 seccomp、bubblewrap、socat、ripgrep。原 Codex 路径锁定当前已配置的 [openai/codex 0.153.4](https://github.com/openai/codex)（Apache-2.0）；`PARA_CODEX_VERSION` 改动须同时评审并更新对应 manifest 与 lock，版本不符会停止。只有随后的执行步骤注入授权并写入 Codex 配置，OpenCode 仍按获批分配选取凭据。

每个任务使用独立配置、缓存和临时目录，只允许任务目录内的授权写入，网络限于受信网关和 npm 依赖源。只读任务不能写任务目录；原生会话权限拒绝未知工具，交互授权请求自动拒绝。Windows 的固定版沙箱尚不能保持本适配器的模型配置传递与原生会话校验合同，因此设备明确报告 OpenCode 不就绪。客户反馈修复仅在原生 Linux 隔离与 `srt-0.0.83-header-only-platform-v1` 准入同时满足时执行；原 PR repair 保持[凭据迁移边界](../../FHD/docs/autonomy/CREDENTIAL_VAULT_MIGRATION.md)中的暂停，历史完成回执继续只读核对。

`opencode_sandbox_controller.mjs` 每任务嵌入一个固定版 SRT 实例，真实 key 捕获后从环境删除；隔离进程只收到无用占位符。官方 `filterRequest` 只允许获批模型的精确 HTTPS `POST /v1/responses` 与 `GET /v1/models`，并仅设置 Authorization 请求头；不启用会替换请求正文的通用 mask。CA 控制目录与任务可读写目录分离，启动模型前验证私钥不可读。发布器另核对 GitHub 执行 artifact 的 digest、原任务、run/source/candidate 身份，每次新增发布动作前重读授权。

Linux 复用 [Ubuntu 22.04 的 bubblewrap 0.6.1 系列安全包](https://packages.ubuntu.com/jammy/bubblewrap)（LGPL-2.0-or-later）和固定 SRT 原生 seccomp helper，不附加能力或替换 bwrap 入口。[SRT 0.0.83 的 Linux 前提](https://github.com/anthropics/sandbox-runtime/blob/v0.0.83/README.md#linux)要求可用的用户命名空间；[Ubuntu 的 bwrap 子进程策略](https://documentation.ubuntu.com/release-notes/25.04/#apparmor-profile-for-bwrap)会拒绝该初始化链路需要的能力。因此其他 Linux 版本及受限宿主在安装／就绪／执行前明确拒绝，不修改 AppArmor、sysctl 或宿主权限。仅显式开启 OpenCode 的 GitHub execute/resume 任务选择 `ubuntu-22.04`，默认 Codex 与发布任务保持 `ubuntu-24.04`；无凭据准备步骤通过后才进入授权步骤。

工作进程启动前核对 `CapEff/CapPrm/CapAmb/CapInh=0`、`NoNewPrivs=1`、`Seccomp=2` 与单层 `NSpid`。CI 保留 Ubuntu 26.04 的实际拒绝验证，并要求 Ubuntu 22.04 与 macOS 的原生沙箱正向用例通过，包含受保护文件、只读写入、嵌套命名空间、Unix socket 和交互授权拒绝；单元测试不能替代目标系统验收。

`DEVFLEET_FORCE_OPENCODE` 默认关闭；须先部署支持 OpenCode 的 DevFleet 协调服务（配套 `devfleet-private#17`）与工作设备，确认设备工具就绪后，再由运维在 MODstore、设备和 GitHub 仓库变量中显式设置为 `1`。未升级的设备保持等待，不将任务转给其他工具。首次派工遵循该可信策略，既有请求与 attempt 继续按原身份核对回执。

GitHub Worker 还须启用下文的云端平台模型准入。客服与 Retort 先持久化同一次额度分配，再启动工作流；可信控制进程使用该分配的模型、受信 `PARA_PLATFORM_GATEWAY_URL` 和对应专用 key，模型工作进程只接收占位符。`MODSTORE_PARA_ARK_PLAN_FIRST=1` 的专用计划组合暂不兼容，明确等待。本地非池设备仍可显式配置网关、`PARA_OPENCODE_MODEL` 和 `OPENCODE_API_KEY`，并通过 `MODSTORE_CREDENTIAL_GRANT_SCOPES` 授予控制进程该模型凭据。平台请求沿用原生 `/v1/responses`，执行前回读有效模型、网关和认证配置。增量文字、工具活动与实际 token 用量经现有任务 WebSocket 回传。

## 管理端小 C

管理端智能聊天提供 L1–L6 自主模式滑杆。全企业固定身份为 `xcmax:management:xiaoc`；多个管理员、浏览器和模型共享同一状态，设置使用服务端 revision 比较更新。默认 L3，后台模型预算为零。L1 对话、L2 单次明确工具、L3 任务编排、L4 企业活动、L5 兴趣探索、L6 反思与受控改进；等级是运行权限，不是能力得分。暂停仅停止后台自主活动。旧工具卡执行前也读取当前等级，工具不能修改自身模式或预算。

「工作动态 → 自主状态」显示使命、真实经历、目标、兴趣、模型用量和阻塞原因，并提供每日 token 额度、探索占比、轮次、间隔和授权期限设置。授权管理员是既有平台模型额度的责任主体，不因此从个人钱包扣款。独立的企业任务预算模板选择现有员工和模型，冻结费用、费率来源、输入与执行限制；研究目标转为提案后，管理员须核对原提案及其精确摘要，再走既有战略审批。滑杆和模板不会替代任务审批。

认知循环复用 [LangGraph 1.2.10](https://github.com/langchain-ai/langgraph/tree/1.2.10)（MIT）的有界图执行、现有 APScheduler 的单进程任务注册，以及 SQLAlchemy/PostgreSQL 的事务和比较更新。图本身不启用新的 checkpointer；固定身份、租约、预算、出站身份和经历存在同一业务数据库，由原模型/员工账本提供事实。`20261121_xiaoc_life` 迁移承接原 Alembic head，生产须按既有升级脚本迁移后再启动 API 与 scheduler。

平台模型选择、精确额度准入、实际 usage、OR-Tools 资源组合、员工执行、实验与交付回执继续使用原实现。探索只调用已配置的自托管 SearXNG（[上游，AGPL-3.0-or-later](https://github.com/searxng/searxng)）；本次没有安装另一个搜索服务或改变其部署版本，无配置时明确阻塞探索。每轮最多一次认知模型调用、一次搜索、三个外部来源。新目标必须引用实际观察来源；真实任务与业务复盘进入下一轮，能力自评保持待验证假设。

L6 可用 `policy.retort_template_id` 选择 `MODSTORE_RETORT_PROTOCOLS` 中已有的冻结验收方案。该记录保留原 `name/criterion_ids/checks/container_image`，并配置 `life_reflection: {"owner_id": 7, "goal": "公开的工程目标与范围", "provider": "openai", "model": "已配置的模型 ID"}`；责任人须等于原预算管理员，模型须匹配企业任务模板的费率。带实际来源的反思与原 Retort 请求在同一事务内绑定；私有假设和来源摘要只进入原审批及隔离员工上下文，公开 Issue/PR 使用方案里的公开范围。原派工批准后，下一反思周期形成引用同一请求、协议与批准摘要的公司工程预算提案；管理员通过原战略审批后，继续复用现有 OpenCode、持久阶段租约、独立验收与发布。提案阶段不启动额外 GEPA 模型试验。暂停时仍只读回流原结果；测试、批准、发布身份缺失时标记证据不完整，失败和回滚状态也进入后续反思。客户价值只消费已有权威账本的脱敏汇总，未知读数不补零，发布核验不代表业务收益已证明。

统一 LiteLLM 网关默认模型沿用聊天的实际平台目录，保留显式 runtime/bench 配置。精确预算读取复用固定 [LiteLLM 1.109.3](https://github.com/BerriAI/litellm/tree/v1.109.3)（MIT）的 `GET /user/info?user_id=litellm-proxy-budget` 同周期聚合；`GET /global/spend` 仅交叉核对生效的 `max_budget`，不拿滚动 30 天消费计算当前余额。按[官方预算协议](https://docs.litellm.ai/docs/proxy/users)，网关须连接数据库、启用消费记账、配置正有限 USD `max_budget` 和 `budget_duration`，且管理凭证可读完整且未到期的预算记录；任一条件缺失保持阻塞。该预算与上游订阅 token/预付余额分别标识。健康探测只检验指定路由，回退或未知回退收据不能当作原路由成功或零额外消费。

新增自有代码只承接企业唯一身份、全局模式、两类预算、原账本关联和管理界面合同。没有引入第二套代理平台或任务队列；纯认领后中断可安全释放，已出站但结果不明只核对原请求，不重放。持久本地队列携带原租约恢复，暂停、降级、授权撤回或超时在下一动作边界生效。同步 handler 已经开始的操作不能强制撤销。全部缺口映射及上线前提见 [自治手册](../../docs/autonomy.md#管理端小-c双重自主闭环)。

已用仓库 CSV 员工贯通管理端配置、提案、精确摘要审批、调度、实际文件生成、原任务验收及后续反馈。感知富化不再修改批准的输入；标准文件参数在冻结和执行前检查目录与批准范围，旧文件输出复用原路径检查、SHA-256 和验证器形成真实产物回执。该适配只证明已覆盖的参数和文件回执，不提供新的操作系统沙箱。

工作动态复用 [Element Plus Timeline 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（MIT）呈现工单回执。交付跟进沿用现有客服工单的员工路由、恢复和显式审批；站内提醒由 [APScheduler 3.11.3](https://github.com/agronholm/apscheduler/tree/3.11.3)（MIT）在 MODstore 调度进程运行。只有显式关注的交付工单进入提醒，截止时间来自工单字段。

私人记忆由 FHD 的 MemoryV2 保持权威记录并用 [Mem0 2.2.1](https://github.com/mem0ai/mem0/tree/v2.2.1)（Apache-2.0）召回。管理端从 Persona-A 读取对话风格。管理员通过「工作动态 → 我的记忆」主动新增、更正或删除记忆。部署时在 FHD API 和 MODstore API 的受保护环境中配置同一个专用 `XIAOC_ADMIN_CONTEXT_TOKEN`，MODstore 通过 `XIAOC_ADMIN_CONTEXT_FHD_URL`（未设置时用 `XCAGI_FHD_INTERNAL_URL`）访问 FHD 内网。管理员需用同一账号在 FHD 保持有效的管理端登录。未联通时，记忆区会提示不可用，普通小 C 对话和交付跟进仍可使用。详见 [FHD 复用说明](../../FHD/README.md#对话上下文与技能的来源)。

# Company ticket read grants

`GET /api/customer-service/tickets?offset=0&limit=50` and
`GET /api/customer-service/tickets/{id}` accept an independent `cst_ro_` service
credential with exactly `customer-tickets:read`. All other paths/methods are
denied before dispatch; ordinary account ownership rules remain in place.
The scope covers existing customer-service ticket intents, including delivery
tickets stored in that table. It does not grant artifact downloads or access to
Para development tasks. Deadlines are not recorded in this table, so overdue
state is returned as unknown, never inferred from age.

Set `MODSTORE_INSTANCE_ID` and `MODSTORE_TICKET_READ_GRANTS_FILE` on the server.
The latter must be a regular owner-only file (0600), owned by root/service user:

```json
{"instance_id":"fixed-instance","company_id":"fixed-company","owner_user_ids":[1,2],"grants":[{"id":"dot-read","principal":"dot","scopes":["customer-tickets:read"],"token_sha256":"SHA256_OF_RANDOM_SERVICE_CREDENTIAL","expires_at":"2026-11-01T00:00:00Z","revoked":false}]}
```

An operator must populate `owner_user_ids` from the company's authoritative
account membership, including its customer accounts; no wildcard is supported.
New accounts require an explicit membership update. Create separate grants for
`dot` and `grok-bot`. Only credential hashes belong on the server. Keep plaintext
credentials in each executor's protected local file or credential manager, never
in source, chat, tool arguments or Para tasks. Removing a grant or setting
`revoked:true` takes effect on the next request. `ticket_read` logs record grant,
route, allow/deny and response status; retain INFO logs in the server audit sink.

## Para 云端平台模型

XCMAX 读取现有平台额度快照。启用 `MODSTORE_PARA_PLATFORM_POOL=1` 后，新派工先检查已验收的流式 Responses、工具调用和实际 token 回执，再按供应商及资源的有效余量选模。共享额度无法核验或低于保留线时等待。`MODSTORE_PARA_PLATFORM_RESERVE_PERCENT` 默认 80，可提高到 100 暂停新派工。

在 `MODSTORE_PARA_PLATFORM_ROUTES` 里登记 LiteLLM 别名及对应的上游资源，例如 `{"xcmax-para-coding":{"provider":"minimax","resource":"general","capabilities":["responses_stream","tool_calling","token_usage"]}}`。`MODSTORE_PARA_PLATFORM_CAPABILITY_PROFILES` 可分别为 `repair` 和 `benchmark` 添加入场所需能力，例如 `{"benchmark":["verified_long_context"]}`。角色配置不能移除基础能力。只登记实际验收过的能力。

额度余量相同时，在 `benchmark_ids` 按来源配置精确标识，如 `{"livebench_coding":"mimo-v2.6-pro"}`。使用 [LiveBench 2.0 Coding](https://livebench.ai/) 和 [DeepSWE](https://deepswe.datacurve.ai/) 的公开源，每 6 小时按需刷新。每榜只有覆盖所有同额度候选时才计入排名，DeepSWE 限同一 mini-swe-agent 测试范围及完整跑分。按榜内名次汇总，避免直接混合不同榜单的分数。回执记录采用的榜单和日期。修改别名所指模型后须重新验收并更新确切标识。

MiniMax 和小米 Token Plan 读取供应商公开的真实余量，使用同池 `general` 资源。其他供应商在没有可核验共享余量时等待。管理端回执仅携带通过能力和额度检查的候选。Para 复用已有 Codex 模型回退器，真实任务前若只读探活报额度不足，按回执候选顺序切换。实际任务已开始时保留原回执和变更供核对。

GitHub 配置 `PARA_PLATFORM_POOL=1` 和 `PARA_PLATFORM_GATEWAY_URL=https://…/v1`。Secret `PARA_PLATFORM_GATEWAY_KEYS_JSON` 映射网关别名到独立限额虚拟密钥，如 `{"alias-a":"<key-a>","alias-b":"<key-b>"}`。旧的单密钥 Secret `PARA_PLATFORM_GATEWAY_KEY` 仍可用于共用额度。使用 [LiteLLM Proxy 的 Codex Responses 接入](https://docs.litellm.ai/docs/proxy/client_setup/codex_cli) 和有限额的虚拟密钥。启用前在网关配置 Para 的模型白名单、预算及 RPM/TPM，按需要在供应商侧划分硬配额。派工检查只控制新任务准入，运行中金额和速率由网关限制。缺少可核验额度时任务等待。

网关验收目标固定为 [BerriAI/litellm v1.108.6 LTS](https://github.com/BerriAI/litellm/releases/tag/v1.108.6)，镜像 `ghcr.io/berriai/litellm:v1.108.6`；使用上游该版本发布页指定的固定公钥验证 cosign 签名后再部署。上游非 enterprise 目录使用 [MIT 许可证](https://github.com/BerriAI/litellm/blob/v1.108.6/LICENSE)，enterprise 目录适用其独立许可证。此记录不代表网关已部署或生产验收通过；实际镜像摘要、签名、配置和端到端计费仍需核对。

如 Para 使用专用火山 Agent Plan，可在平台池模式下设置 `MODSTORE_PARA_ARK_PLAN_FIRST=1`，并在 GitHub 将 `PARA_CODEX_MODEL_CANDIDATES` 设为 `ark-code-latest`。Codex 使用专用 `PARA_CODEX_API_KEY` 直连。关闭火山超额后付费可确保套餐用尽时返回额度错误。只读探活收到火山套餐额度耗尽错误后，从已通过平台保留额度检查的候选中切换。 [火山错误码](https://docs.volcengine.com/docs/ark/error-codes?lang=zh) · [超额后付费规则](https://docs.volcengine.com/docs/ark/agent-plan-personal-over-quota-postpaid-rules?lang=zh)

2026-11-20 生产 `/v1/responses` 已实测的别名如下。供应商目录中的模型在实测通过前只作为待验收项。实际 Para 派工仍要求额度通过。

| 网关别名 | 上游模型 | 计价依据 |
| --- | --- | --- |
| `xcmax-para-coding` | MiniMax-M2.7 | Token Plan 共享额度。普通 API 价表仅供参考 |
| `xcmax-xiaomi-fast` | MiMo V2.6 Flash | 小米 Token Plan 共享积分。普通 API 价表仅供参考 |
| `xcmax-xiaomi-code` | MiMo V2.6 Pro | 小米 Token Plan 共享积分 |
| `xcmax-doubao-code` | 豆包 Seed 2.1 Pro 260915 | 方舟按量。标准在线推理非音频输入 ¥6、输出 ¥30 / 百万 token。缓存按官方表单列 |
| `xcmax-kimi-code` | kimi-for-coding | Kimi Code 会员共享额度 |
| `xcmax-kimi-k3-256k` | k3-256k | Kimi Code 会员共享额度 |
| `xcmax-kimi-k3-1-pro` | k3.1-pro | Kimi Code 会员共享额度 |

[小米价表](https://mimo.mi.com/docs/price) · [MiniMax 价表](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise) · [火山方舟价表](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh) · [Kimi Code 会员额度](https://www.kimi.com/resources/coding-plan)

### 模型池组件

复用现有模型目录、凭据路由和钱包预授权。跨供应商对话路由及模型限制元数据使用
[LiteLLM 1.109.3](https://github.com/BerriAI/litellm/tree/v1.109.3) 的 MIT 许可 SDK。
对话与看图使用现有 Chat API，图片生成使用图像代理，语音使用现有 MiMo 协议适配。
管理端可调用 `POST /api/llm/admin/runtime-route/probe-operation` 验证指定模型的指定操作。

桌面生图复用现有 OpenAI 图像适配器及 Java 钱包。平台代付只接受官方
[OpenAI 图像生成用量回执](https://developers.openai.com/api/reference/resources/images/methods/generate)，
且需要为实际模型配置有效 token 定价。缺用量或结算回执不确定时保留原请求待核对。

计费继续使用 LiteLLM 1.109.3 的标准用量字段、现有 Java 钱包和客户端请求账本。
流式对话与生图在结算前保存用量、价格、请求号和预授权号。响应丢失后用认证钱包读回
核对已结算的同一请求，原子补齐用量流水及请求回执。事件持久化参考
[Lago](https://github.com/getlago/lago) 的幂等用量事件，资金状态参考
[TigerBeetle](https://docs.tigerbeetle.com/coding/two-phase-transfers/) 的两阶段转账。

兼容网关接受 `Idempotency-Key`，原生对话及视频接口接受 `client_request_id`。
实时语音沿用回合标识与现有请求账本。视频回执在上游任务未完成时标记等待用量，
独立语音返回经校验的用量或未计费状态。没有有效计费合同的媒体入口继续报告零平台扣费。
