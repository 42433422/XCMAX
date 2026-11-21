# 自治系统运维手册

维护范围：桌面、服务器和 CI 自治；源码、运行证据及客户验收分别报告。
本文件随 autonomy 变更维护。发布门禁见 [CI_SSOT.md](./CI_SSOT.md)。

## L2–L6 缺口与闭环边界（2026-11-22）

企业经营结果由原订单/库存/财务事实核验；原 dispatcher 周期发现待核验回执和未回流结果，在原 AgentRun/队列身份、租约和 CAS 下只读恢复。仅全部原步骤已完成或跳过、核验通过、授权有效且无未结副作用时收尾，unknown 只更新观察，不重放业务。客户价值汇总进入原 `strategy_planner.collect_context`；桌面安装按原发布目录核对，独立于服务器部署 SHA。

L6 反思可通过管理员配置的原 `retort_template_id` 绑定原 Retort 工作单：私有来源、原目标与工作单在同一 SQL 事务保存，原审批后再提出公司执行预算，经原组合执行器绑定 OpenCode 工作区。实际发布/效果/回滚回执进入下一轮反思；模板、权限、预算、隔离环境或外部回执不足时保留等待。代码接线与本地回归不替代主线 CI、部署身份及真实客户验收。

这里的等级描述工程能力，不能用最高层的模块名称代替整套系统的生产验收。
本轮以 `main@392d50b5` 和集成 PR #3398 的 `e4d87b02` 为起点复查后继续修复；
期间保留并整合 #3398 的 `445e2da0` 管理端小 C、`fda4306c` 工作流事务与持久交付修复、`d130d142` 网关额度与回执接线，以及 `main@48f8f40d` 的统一 LiteLLM 网关；随后正常合并 `main@17141835`，保留原 AgentRun 澄清续接、检查点和查询结果修复。
#3396 的定时治理、战略候选和在职训练已包含在该 PR，#3397 的锁定依赖修复已在 main。
同时逐一检查 #3403、#3405、#3406、#3407、#3408、#3409、#3410 的依赖变更；
它们不承接下列自治缺口，未为统一分支而纳入本轮实现。
下表列出审查发现的闭环缺口及代码承接点；实际部署、凭据配置、真实客户确认和业务观察须另有回执。

| 层级/维度 | 发现的缺口 | 代码承接及完成条件 |
|---|---|---|
| L2 任务可靠性 | 派发或 queued 被当成完成；跨进程预算身份丢失 | 复用员工执行器和持久任务身份，终态回执才完成；GitHub OpenCode 报告及原 Retort 工程工作单绑定逐调用预算与原生回执，其他未计量远程执行仍在出站前拒绝 |
| L3 staging | 继承生产环境标记、目录/端口/数据库不隔离，迁移错误被吞；排队或等锁时 latest 可换成另一候选 | `staging_environment.py` 强制隔离；schema 与 Alembic revision 同事务恢复；派发冻结 release SHA，更新前核对且只消费同一次读取的 manifest 快照，按实际提交核验健康 |
| L3 发布与恢复 | HTTP 200/退出码不能证明部署身份，回滚缺幂等请求；扫描与部署判定不一致 | 复用 immutable release 脚本；当前/目标制品 CAS、同一发布锁、持久请求与实际身份读回；手动扫描共用部署严格校验器，趋势制品独立命名 |
| L3 异步合并交付 | `merge_requested` 稍后确认合入只更新任务，未接部署；冷却/低阈值跳过旧任务恢复 | 维护协调器在原 lease 内继续既有任务；核对原 task、request、分支和实际 merge SHA 后恢复原部署入口；不新增代码派发 |
| L3 部署输入 | 原派发使用 `loop:*`，未提供生产工作流要求的 release SHA 和安全扫描编号 | 使用 `release:<40sha>`、同 SHA/main 的成功安全扫描及真实报告制品；复用发布严格校验器，保留生产开关与环境批准 |
| L3 派发幂等 | 请求响应丢失、仅查最近 50 次运行可能重派；控制工作流 SHA 与目标制品 SHA 混用 | 复用 filelock 和原 ledger，出站前 fsync 意图；GitHub 无过滤完整分页并核对总数/唯一 ID；分支前进时验证 source、派发前/实际 controller、当前 ref 的祖先关系，只恢复原 run |
| L3 交付终态 | 成功后反复回读、部分成功重做；旧待交付被最近 20 次运行列表淘汰 | 原账本分页发现与终态核对，游标持久保存；每轮至多 256 行/2 MiB 行内容、20 个候选，核对到当前 EOF 后按原任务与版本恢复，只推进未验证环境；真实终态另记持久回执 |
| L3 备份与保留 | pg_restore 失败仍成功，SQL 失败被当成零行；估算行数与 dump 不同快照 | PostgreSQL 原生导出快照供 dump 与精确计数共享；恢复核对摘要与精确计数，旧估算明确未核验；事务/错误停止及清理失败如实上报 |
| L4 客户修复执行 | 模型工具能读原始 key；普通 mask 也会把 key 替换进请求正文 | SRT 官方请求过滤只向固定 HTTPS 模型端点注入 Authorization；隔离进程只有无用占位符；私钥、宿主进程、发布凭据隔离 |
| L4 发布衔接 | 执行器回报与受信发布器之间缺不可伪造的隔离身份 | GitHub artifact digest 绑定原 request/run/source/candidate；每次新写前复核管理端批准与模型分配 |
| L4 客户验收 | 部署成功、原客户确认和新反馈不能混用；完成后重开不再进入效果/恢复节点 | 原工单同事务登记精确版本的 `impact_recheck`，LangGraph 从已完成 delivery 检查点重进效果/恢复，不重新构建发布；处理完成后标记收敛 |
| L5 效果判定 | measured 就计为改进，负收益可能进入成功知识 | 预注册方向、最小提升、置信区间、样本和护栏；负面拒绝、不确定等待，成败均回流下一轮 |
| L5 实验运行 | 只查已有统计，缺建实验、真实分流、曝光和停止 | GrowthBook REST + Python SDK，员工真实 system prompt 分流与 SQL outbox 曝光/结果；无数据源或样本不推广 |
| L5 第二执行面 | 实验机制只被员工 prompt 消费；工作流已保存后观察入库异常会覆盖真实成功结果 | `workflow_nl_prompt` 接原自然语言工作流；保留真实 owner/workflow 与前置曝光，图/Skill/完成观察同事务提交；提交后原 outbox 重试事件，不重复生成。成功且 `sandbox_ok` 只代表静态校验 |
| L5 实际工作流效果 | 生成或静态校验成功被当成实际执行改善，触发器不写持久终态 | 原 `WorkflowExecution` 与 SQL outbox 同事务保存实际执行终态；独立 `workflow_execution_terminal` 口径，GrowthBook 读回冻结的 PostgreSQL 查询和指标定义，静态生成结果只作诊断 |
| L5 失败终态持久化 | 数据库异常后继续使用失效事务，原运行记录卡住；未提交启动被补造为失败，或覆盖其他已终态 | 原事件执行器与手动执行 API 共用独立事务收尾：先回滚，再按冻结的执行、客户、工作流、开始时间和 running/空完成时间 CAS，终态与反馈同事务。初次提交确认丢失也只核对原记录，未提交不补造；终态提交确认丢失按原异常、结果和完成时间只读确认，不重复反馈。竞争终态不覆盖、不发布虚假失败，手动入口返回固定冲突提示。HTTP 和公共失败事件不反射内部原文，原稳定准入码、账号隔离诊断及原异常链保留；业务成功的最终写入故障沿独立成功收尾路径处理 |
| L5 工作流业务成果 | 工作流执行身份与客户目标、真实制品及验收未关联，执行成功可能被当成业务成功；最终 SQL 写入失败可遗失已返回结果 | `workflow_customer_accepted_outcome` 覆盖原企业客户自己的单原生文件员工交付图；开跑前冻结原付款、已确认 KPI、图、员工包、输入与 assignment，真实员工返回点登记制品。原图在同进程实际返回且完成序列化后，触发器和原 JWT API 可按原身份与制品核对、初次/恢复 CAS 完成终态；提交回执丢失只读确认，不重跑业务或计费。业务测量与客户确认仍独立核验，成熟观察窗决定结果，迟到材料不重写冻结统计 |
| L5 推广后撤回 | 已完成改进不再被调度，新推广图丢失原实验归属，退款只能阻流却不能完成恢复 | 新推广图保留原批准的 provenance 而不增加样本；精确已验证退款经 SQL CAS 标记原 `impact_recheck`，由原 LangGraph 仅重进效果和恢复，复用 GrowthBook 撤回与不可变发布读回，重复 tick 不再发布或改写结论 |
| L5 私有执行合同 | 业务输入和工作区路径需要保存，但普通 outbox 会广播完整 payload | 契约留在原 SQL 账本；START、CLAIM、PRODUCED 三类内部事件在 NeuroBus、webhook 和原重放入口使用固定公开字段投影，不由请求方决定脱敏开关 |
| L5 持久图撤回 | 后续生成切回 control，旧 treatment 图却仍可执行 | 原生成记录、owner、实际加载的图指纹、版本、cohort 和当前批准共同控制开跑；普通执行、触发器、客服工具、服务、子工作流及关闭模拟的真实沙盒均接同一回执；撤回后拒绝旧图的新执行，迟到或漂移结果只归档，不用于推广 |
| L5 沙盒图竞态 | 执行后重新读取图，可能把旧图成功标为新图通过 | 本次实际执行的图指纹贯穿原 trace 与 WorkflowSandboxRun；运行中改图后的当前图显示 stale，模拟和静态校验保持各自口径 |
| L5 实验停止 | GrowthBook 5.2.0 temporary rollout 将 coverage 改为 1，原覆盖率比较会使部分 cohort 实验永远等待 | 仅持久停止/撤回意图允许该上游转换；本地选择仍严格限制原批准账号 cohort |
| L5 结论稳定性 | 停止后重新读取 latest 统计可能改变原判定，重启不能完成原操作 | 在停止前冻结最终测量及 payload 摘要，恢复使用原测量和原意图 |
| L5 运行期授权 | 实验创建时通过审批，后续分流未再次验证当前 owner/审批人；只查前 100 条会漏掉活动实验 | 每次真实选择/新操作核对 run、两次审批及接受摘要，撤销/失权回到 control；SQL 分批查找匹配资源，早退/异常显式关闭结果集 |
| L5 失败撤回 | 仅登记回滚请求，未确认恢复 | LangGraph 恢复节点调用同一发布/实验适配器，保留当前与目标身份并实际读回；未知结果只核对 |
| L5 在职训练 | 首簇类型错误、latest 漂移、仅汇总通过数、直接覆盖 prompt；真实 run ID 可以搭配无关案例 | #3396 trainer + promptfoo 固定版，同 case/provider 成对回归；逐项绑定实际失败样本原输入和摘要，缺原输入拒绝；仅形成待审批候选 |
| L5 工作流失败改进 | 工作流 prompt 能实验，但没有原失败输入、训练及候选发布消费者 | 原生成失败及可重现的实际执行失败关联原生成输入、图和执行参数；复用原 trainer、promptfoo chat 协议和生产静态校验，再经原候选审批、发布及线上实验。离线训练不重放客户业务副作用，静态回归不冒充运行收益 |
| L5 私有训练出口 | 关闭遥测不阻断 opt-out 请求；安装脚本可能在后续凭据出现时继续运行 | 完整依赖锁与 `npm ci --ignore-scripts`，安装步骤无模型/派发凭据；固定 SRT 官方 TLS 请求过滤只放行获批模型的精确 HTTPS 路径，worker 只有占位符，缺原生宿主能力则拒绝训练 |
| L6 战略发现 | 无真实输入到提案的消费者，候选不关联历史结果；外部检索没有进入战略 | 复用 #3396 18 域/模型资产/仓库信号与原 SearXNG JSON API，冻结来源 URL、日期、抓取时间、摘要和原客户目标；统一进入 SQL 待审提案，下一轮读取真实复盘，搜索结果仅作为待验证假设 |
| L6 资源组合 | 贪心/手工分配不能处理依赖、风险与多资源约束 | OR-Tools CP-SAT 同时约束费用、tokens、时长、依赖、并行度和风险；限整数范围并独立核验可行解 |
| L6 公司总预算与容量 | 不同 owner 的组合各自计量，不能共同争抢企业资金与执行槽；换池可能遗忘未知责任 | 运维固定公司范围和审批人；原 SQL 决策封套与任务、调用、行动项同事务 CAS。CP-SAT 使用公司实际剩余额度，未知占用不衰减，旧池未结禁止换期；工程阶段已确认结束只释放槽位，恢复须重新原子申请 |
| L6 公司联合选择 | 各组合分别优化、按更新时间抢资源；局部最优会排除公司更优的已批候选 | 原 CP-SAT 联合求解同公司全部当前可启动的已批准候选，同时保留各组合预算、容量、风险与已完成依赖；调度和实际 claim 均使用该选择。完整候选最多 256，超限拒绝截断；延后候选的原行动项与公司预留同事务创建，可信复盘仅在原批准范围内调整权重 |
| L6 暂缓后继续 | 公司暂缓会清空局部 selected，小 C 后续预留零额度或等待旧复盘时间，导致容量恢复后原任务仍不能执行 | life 按原批准且当前可启动的公司候选申请有界预留，仍受原每日与单轮额度限制；实际公司求解与 claim 再核验。历史完成任务、未完成依赖、高风险和不足额度不扩大预留，原任务仅认领一次 |
| L6 授权与账本 | 默认自授预算、JSONL 先读后写可并发超支、旧通用接口可伪造 | 只使用 StrategicDecision/ActionItem SQL 账本；认证管理员、原账号、提案摘要、有效期绑定；旧路径无新预算写权 |
| L6 执行合同 | 提案未冻结实际业务输入、租户路径和有效员工配置；模型可能覆盖已批准业务 ID | discover/提案接收有界 `input_data`；冻结包版本、manifest/archive/config/input 摘要；在实际执行入口重新核验，模型计划不能更换已批准输入 |
| L6 Python 执行字节 | 入场核验后再次加载不同包，或复用内容已改变的解包缓存 | 战略路径重新按 owner/execute 解析权限；从一次读取并核验摘要的归档字节进行私有解包和入口编译，实际执行不使用旧缓存 |
| L6 实际消费 | 按计划费用或缺失 usage 当零；内部重试隐藏费用 | 每次平台调用先持久预留，再记供应商真实 usage；按批准费率计提，不冒充供应商账单；未知消费保留占用并停止 |
| L6 流式用量 | 原战略入口拒绝流式；SDK 可把无/不完整 usage 合成为估算；中途模型漂移可被末帧别名覆盖，同一预留可重复出站，错误响应反射内部异常 | 复用原 SSE 与固定 LiteLLM，逐次预留并限定一次实际出站；SDK 规范化前独立保留原始 usage，逐帧核验模型并保留首个不匹配身份，后续别名不能覆盖。缺终态、估算、撤销、超时/取消、fallback 保留未知占用；流尾使用固定停止提示，保持原错误码、清理和责任状态 |
| L6 托管报告 | 本地预算上下文不会自动随远程任务传播；控制器回报成功不足以完成原任务 | 原 GitHub executor/OpenCode/SRT 消费冻结的报告任务，MacControlTask 与原组合绑定；原生 OpenAI Responses SDK 逐调用预留/结算，控制回执再与真实 GitHub job 和 ZIP 制品摘要核对。停止后只读回收旧任务，未知费用不释放 |
| L6 工程执行 | 原 Retort 反馈任务在隔离配置有效后仍无条件拒绝，子任务模型调用不能归入原公司预算 | 已批准原工作单在派发前绑定公司/组合；原 Para `handleTask` 核验 event/task/subtask/attempt 后领取阶段专属模型 grant。真实 job 控制 execute/resume，原候选、独立验证、接受审批、main、部署和效果回执共同决定终态 |
| L6 长期工程阶段 | 原小 C 周期仅 300 秒，等待 GitHub 阶段后无法合法继续；本地取消入口可能误退远程责任 | 原提案显式批准 `persistent_phases` 绝对期限，同事务登记原任务与公司/组合/life 身份。原周期与预留保持，只有同 native run 的已验证阶段可继续；未知、撤权或任一期限届满拒绝新调用，远程绑定不能走本地取消 |
| L6 网关尝试次数 | 主分支改走远端 LiteLLM 网关，本地禁重试不能约束代理内部消费 | 对预算调用在真实 HTTP 正文设置零重试/禁 fallback；读取原始网关两项 attempt 响应头，缺失、非法或非零都保留未知，不能用本地 Router 的零计数覆盖代理回执 |
| L6 商业回报 | 全局开票/GMV 被算作本战略收入；不同制品/完成前的 outcome 与 acceptance 可被配对 | 同目标、同真实支付订单、同客户、同已完成制品 ID/SHA 的两种回执才归因，时间在实际完成后且位于观察窗；排除退款、未来时间和无关客户，缺完成时刻保持未知 |
| L5/L6 原退款来源 | 退款止损只能消费已登记回执，原 Java 钱包入账未被正式采集 | 复用原退款审批、钱包交易与内部认证；同一只读事务核对订单、客户、金额、幂等键和余额差额，固定边界完整分页后由服务端封装证据。原 reconciler 按退款号追加唯一订单级回执，接原止损与实验恢复；不按客户目标重复计算金额 |
| L6 原客户验收 | 管理员是战略 owner，原客户却不能用管理员身份验收；原生文件缺稳定制品身份 | 审批冻结原客户、订单、目标与原 goal 回执；真实原生文件保留摘要。只有原 KPI 达标的 outcome 与原客户的同制品 acceptance 配对才计入确认率；管理员不能代客户确认，本地文件存在不等于客户已经收到 |
| L4/L6 文件交付 | 原生文件位于管理员执行工作区，原客户没有可授权下载入口 | 原客户价值 API 列出其当前协议绑定的已完成文件；复用支付归属、SQL 批准摘要与租户路径守卫，读取后核对 SHA 并返回同一字节快照。管理员/其他账号不能代取；下载与客户验收分开记录 |
| L6 止损与再分配 | 无预注册观察窗/阈值；停止后仍可继续消费 | 预注册假设、窗口和停止条件；每次调用/调度复查；仅在已批准候选与剩余额度内再优化 |
| L6 持续运行 | 模块存在却未调度，故障只写告警不回任务，遥测响应返回内部诊断 | 既有 APScheduler 每 60 秒推进获批组合；#3396 清理空转任务、统一版本配置来源、补失败 incident；回执决定状态。遥测对外使用固定错误码，真实失败计数与异常类型保留，不把原始任务或数据库诊断写入日志 |

18 域、108 项验收仍使用 `FHD/config/audit_benchmark_ssot.json`，不创建第二套分数。
依赖分层、ERP、Agent、ELT、意图路由、事件内核、Mod SDK、桌面、业务前端、商城 UI、
商城后端、自治维护、Java 支付、Flutter、Retort、编码沙箱、客来来和 CI 发布都可作为
战略候选的受控来源；本轮没有据模块接入宣称这 18 域已完成全部基准或真机验收。

### 本轮源 PR 处置

本表依据 `2026-11-21 20:12:03 UTC` 的远端复核及后续预发布增量核对，记录当前全部 36 个开放 PR 的完整 head；main 基线为 `22040f4c850d5baa1e1b3a7d270b39197249aea1`。`included` 表示来源意图已纳入当前集成树，`adapted` 表示按现有消费者和合同适配后纳入；两者均不表示源 PR 已关闭、最终候选已进入 main 或生产已运行。下列 SHA 是必须保留的来源身份，发布前仍须逐一核对其与最终候选的祖先关系。来源合入 main、格式或治理登记的推进，不构成覆盖本轮已验证实现的理由。

| 来源 | 固定源 head | 处置 | 保留意图与当前边界 |
|---|---|---|---|
| #3460 | `b438d8825b5d8f3cca83647ac2328bdc7294e579` | `adapted` | 21 个既有来源的集成子集，其固定源 head 已由当前候选覆盖；新增待核对回执证据已由当前深复制实现承接，保留 unknown 与禁止自动重试。澄清续跑保持原持久绑定与 CAS，不凭旧助手问句重新授权；工具目录继续完整 schema 无损压缩与原模型预算硬拒绝，不采用放宽断言或丢弃业务工具的回退，子集治理数字不覆盖最终集成树。 |
| #3459 | `26162d6b6c3226f317f29f2e05813326bdf679fd` | `adapted` | 手机侧栏导航与聊天布局已按现有组件适配，保留 #3420 的旧功能退役和 UI 会话隔离；最新增量仅为源码增长登记，最终计数按集成树生成。 |
| #3458 | `dec687a4311727fdb6eeedaedf0c48f66734948f` | `adapted` | 规划恢复、原授权动作及超时诊断与现有模型预算、完整工具 schema 和会话 CAS 合并；保留失败事实及目标证据，诊断字段不扩大执行权限。 |
| #3457 | `b129216a8350e5898ab14cec6c36189a1e9f2258` | `adapted` | 保留管理端平台默认模型与模型上下文容量修复。缺少 Mod 库时全局回退主库会破坏隔离，故保留原缺库拒绝与显式配置映射；本地 SQLite 读写负控及权限相关 44 项已通过，未据此宣称 PostgreSQL 或正式 CI 通过。 |
| #3456 | `dd1f04f0b940e472a9b22c44c08c6069e7f20356` | `adapted` | 原企业任务恢复、父子运行绑定、RAG 训练及多节点交付沿现有生产合同整合；保留加密语料、持久 claim/CAS、原 owner/批准与同制品验收，不从未知状态重派业务。 最新增量仅去除 sales.query 的重复 read_only 键，当前策略与只读守卫保持。 |
| #3455 | `e819f62b84f45f51cf79aa9fbc77c600b55d0499` | `adapted` | 安全修复与真实执行回执合并；公共错误脱敏保留稳定诊断码、内部异常链及原终态，材料删除和返回计数仍由实际结果核对。 |
| #3453 | `20008232ad80e0e8abf15329bac19a3561ac3ea7` | `adapted` | 统一能力目录与受控执行链，保留 canonical 接口及旧路径退役；有效期校验拒绝布尔、非法和非有限输入，不恢复旧调用或手工批准绕过。 |
| #3452 | `95a8b0ce00bfa6750e56c59ffd07e5572078adb9` | `included` | 保留仓库首页产品说明与原 SVG 封面；不改变运行、发布或验收状态。 |
| #3451 | `8c21152285a008ed91d4895624bd4c1cbe01276b` | `included` | 保留原始 SLO 指标快照及生成器对照视图；all_pass=false、day0=false 和真实缺项保持，快照不替代能力验收。 |
| #3450 | `f192e001dac498bbdea0ce4bf75ac21fcc8846f4` | `adapted` | 员工办公室与四/六部门任务投影复用现有导航、权限及注册生命周期；待核对回执不会因旧 completed 字段显示成功。 |
| #3449 | `a23677b89ea1479d5bf020b445eb9b9538903bfd` | `adapted` | 公司自治、L1 对话与原 PR 修复逐消费者适配：messages/protocols 承接原派工恢复，保留现有拆分核验器、ELT/价格及父子身份校验；原任务预算、模型 grant、执行/发布授权、实测用量和客户交付仍绑定原请求与不可变回执，不整文件覆盖既有期限、隐私、事务及 unknown 保护。 最新 Windows 条件导入保持 POSIX 文件锁，ledger 写仍由原 ENOTSUP 守卫拒绝；取消 fixture 与真实 PDF 制品断言保留，专项 Python 28 项、Node 6 项通过。 |
| #3448 | `d12e2df132c9af65dd1213c7c54bb55f0445d08d` | `adapted` | 独立员工工作台、工作区与图谱恢复接入管理员和桌面现有路由；保留当前身份、权限及 #3450 员工空间整合。 |
| #3447 | `4f5e0a3add093fac702b856a01ec5fd53402c45f` | `included` | 保留组件权威来源、迁移边界与验收 SSOT 文档；历史来源与当前集成结论分别记录。 |
| #3446 | `ca1f50d78bbefd7c4234aad4045bb81015963270` | `adapted` | 原子执行、权限重试、澄清/等待、浏览器及重启恢复按当前 session/provider 合同适配；PostgreSQL RETURNING 和流式能力保留。专用导入绑定原 canonical elt_import 预演、当前权限、Mod/租户与审批，产品写入和原回执同事务；事务组 34 项通过、6 项 PostgreSQL 跳过，原等待及嵌套失败恢复回归已修复。最新宿主退出修复使用独立标准 spawn 监督与 Linux 孤儿接管证明，保留原 RSS、PID 身份回收、浏览器双锁及不可重派的未知回执；非 Linux 未证明的清理仍待核对。 |
| #3441 | `852b8af0a00ac1b710d9bbf05dc99bc94aceb559` | `adapted` | 统一入口、原子准入与真实终态保留；super_employee_service 的只读恢复依据原 durable outbox，并在非阻塞发送锁内重读原账号、员工、请求和任务身份，保留 task_request_recovery_version 与 CLI 错误脱敏；单个完成回执不能覆盖其他派工的 pending/unknown。 最新签名适配在调用前检查 runtime_context/**kwargs，真实 gate 仅调用一次；原审批与 agent_loop 本地 77 项通过。 |
| #3440 | `246464dd9b31fc7219ffb9b868e91ba0113a12e0` | `adapted` | 统一工具入口、审批范围及安全重试回执复用当前能力目录与原风险门禁；最新推进合入 main 的同源内容，不回退本轮权限与核验修复。 |
| #3439 | `1055ee7eaad597824159d508cf61b22cdd9577cf` | `adapted` | AI 浏览器会话、证据与 Codex 失败处理沿原 AgentRun 和持久恢复合并；历史页面证据不替代当前会话验证或后台交易回执。 |
| #3438 | `d23e9a41a26edb09904484716a8b2fad03b53bf2` | `included` | 统一 Trace、错误终态与耗时观测；保留真实失败和身份，不补造业务结果或公司预算。 |
| #3437 | `cf1ce476af991b66ca24d0ddf757875d3fc0e46e` | `adapted` | 原生执行回执、工具幂等及重启恢复与公司逐调用预算、隔离发布合并；设备 CLI usage 不冒充供应商账单，未知结果只读核对。 |
| #3435 | `51dbc3734780c8bc3d7a153965950bded2999f40` | `adapted` | 渠道配对与明确授权保留原正文、收件人和请求 ID；独立消息读回区分受理、渠道送达和客户商业验收。 |
| #3434 | `e749c80f10acd5c88a28e014a4b866bb786103bb` | `adapted` | 原生 Playwright 浏览器执行与核验接入原任务、会话及制品合同；保留 browser extra 和执行前冻结的断言，真机与真实 Chromium 验收另行核对。 |
| #3433 | `cb8f59c8527a1497496c5f7dc246ddf80428c9ff` | `adapted` | 完整澄清历史、会话 revision、认证历史恢复和队列失败投影与最新摘要、原子任务及审批快照合同合并。 最新合入 main 的模型预算/摘要/会话合同已由现有 #3458/#3446 实现承接；治理与生成页按最终集成树刷新。 |
| #3430 | `6f51824dd74d1768f368db86df158ea607b3851b` | `adapted` | Playwright 与 PyAutoGUI 执行面保留原任务、权限和后置核验；依赖 extra、vendor package-data 与当前打包配置合并，像素/页面证据不证明业务交易。 |
| #3423 | `d20d42e4609d43455cd5f72bd811823872003cf9` | `adapted` | 保留降低规划上下文开销的意图，使用完整 schema pooling 与真实路由预算承接；不按旧目录裁剪恢复已退役工具，也不因模型失败静默降级。 |
| #3420 | `b449a9b952627b5fd5d56fbf630d206a0586d9c1` | `adapted` | 下线本地工作区并接入离线登录、对话生图；保留已登录证明和管理员桌面禁入，以及 Sidebar 权限守卫。最新登录文件增量仅为格式，不覆盖现有安全分支。 |
| #3418 | `afaac0fdfb51ce60e982594692779e06694cec42` | `adapted` | 保留既有总集成来源和 durable claim/CAS、未知结果不重派、网关及 CI 修复；最新六种等待/unknown/超时回执回归在当前实现已通过。目录超限保留完整已授权动作及 schema，不按静态通用工具白名单删除请求所需的 ELT、浏览器或员工能力；继续原模型预算与显式超限诊断，最新像素素材 ESM 构建和 PdfWriter 夹具修正已由当前实现覆盖；治理登记按最终树重算。本行记录来源身份，不代表最终候选已发布或合入。 |
| #3415 | `18a0afc3c5ac33c1561be1c336febb6b5afd1700` | `adapted` | AI 市场统一模块与员工目录、分类和既有入口；保留当前账号隔离及真实权限，不恢复退役路径。 |
| #3410 | `f1963ed6eac54c4ac4fbe0b6f574a0dc058122d2` | `included` | 商城 @vue/test-utils 2.6.0 与锁文件进入统一依赖树；本地验证以匹配该锁的实际缓存为准。 |
| #3409 | `9a322124a1785690aaceccebb1d034d51fa4961f` | `included` | 商城 desktop-shell 的 Electron 45.3.4 与锁文件保留；构建与真机运行分别验证。 |
| #3408 | `2e9c2c955ae4c6c1caa7950e0f66ad2e4a24abfc` | `included` | 前端 eventsource-parser 4.1.3 与锁文件保留；最新推进的 main/README 组合不覆盖本轮消费端适配。 |
| #3407 | `40d675e1f7879f7b1e3744e6ca900add9d90e668` | `included` | 前端八项依赖及锁文件变更保留在统一依赖树；最终依赖树的正式检查仍须通过。 |
| #3406 | `c373cd7819939fdaed554ae8b2a11403fcb2b24d` | `included` | FHD desktop 的 Electron 45.3.4 与锁文件保留；不以依赖更新代替桌面升级验收。 |
| #3405 | `d8227963de37ca94596d538aff579dc63c84ac1c` | `included` | vibe-coding 的 OpenAI 最低版本要求更新保留，其他消费者继续使用各自权威锁定版本。 |
| #3403 | `76ff8d09109167f8a03e2e183005d7596199398a` | `included` | 公司前端 @vue/test-utils 2.6.0 与锁文件保留。 |
| #3398 | `a2c4b849b215bf5899d619ae81ba15cce7a9043d` | `adapted` | 公司预算、真实实验、管理端执行及客户交付按当前授权与回执合同整合；保留逐调用真实消费、工作流事务、客户价值观察和原 Retort/L6 反思入口。 |
| #3396 | `44d42628bde411b7662988c4554f5b1c9cb3b251` | `adapted` | 定时治理、战略候选、在职训练和版本 SSOT 发布保护保留；沿当前消费者保留调度、隐私及战略组合接线。最新合入 main 不恢复已退役路径，也不覆盖已有训练脱敏和授权发布保护。 |

当前 outstanding 分别记录，不能由上述 included/adapted 状态推定已完成：

- #3446 的专用导入事务组 34 项通过、6 项 PostgreSQL 跳过，覆盖两库同 ID、宿主审批与原 Mod 业务数据隔离、撤权和回执恢复。澄清/等待/记忆/恢复原 160 例首轮为 124 通过、24 失败、12 跳过；原 24 个失败已在对应回归中验证修复：等待沿受控客户动作和真实 ToolCall 回执核对，原生恢复拒绝嵌套失败或未核验结果。100/20 轮真实 SQL 澄清链已通过且不重复计数；等待模块含新增无回执假完成负控共 40 例分组覆盖，恢复与核验五模块另为 201 通过、12 个原 PostgreSQL 条件跳过。各组存在重叠，不相加为独立用例总数。
- #3457 的本地 SQLite 读写隔离及权限相关 44 项已通过；缺库保持拒绝，显式数据库映射仍受原配置约束。该结果不覆盖 PostgreSQL 实际环境或 GitHub 正式 CI。
- #3459 本地相关 Vitest 为 235 项通过；来源的 239 项包含 4 项已随 #3420 退役的旧生图按钮测试。真实 Chromium 未在本地执行；MODstore 另有 9 项原测试因缺少固定 Gitleaks 8.18.4 保持跳过，均交原 CI 门禁，不能记为通过。
- 本节记录提交前的本地验证；最终来源祖先、治理文件、GitHub 必需 CI、审查及 main 合入状态分别以整合 PR #3418 的实际提交和检查回执为准。桌面安全扫描保留 main 原有每周 medium 阻断规则；244 项 CI/发布契约测试及 64 份工作流镜像校验通过。源码合入不替代同 SHA 部署或客户交付回执。

客来来仓库的 #3 已进入其独立 `main@d680714`；这是配对服务的源码事实，不代表本 XCMAX 候选已合入、两个运行实例已配对部署或真实渠道已送达。源提交的祖先关系、最终总集成 SHA 的必需 CI、主线合入和同 SHA 交付回执须分别核对。

### 仍未闭合的范围

下表是代码边界与外部验收的明确区分，不能把全部项改称「只缺证据」。

| 范围 | 当前边界 | 完成所需 |
|---|---|---|
| 通用工具与自动核验 | 已接宿主明确登记的只读合同及限定业务/surface 适配，原 dispatcher 自动只读观察；旧任务无冻结契约时不补造通过 | 未登记只读且没有适配器的动作保持 `inconclusive`；自动 observer 不能结清 unknown、续期权限或重做未完成步骤，需逐来源接入真实证据 |
| 电脑/浏览器执行面 | 原生、Computer、AIOPEN 和持久 MCP 已接原任务；证据明确为历史 DOM/像素/制品或当前同会话页面条件 | 保持沙箱的真实 Chromium CI、授权客户站点与 Windows/macOS 真机验收；无后置条件或会话丢失不能完成，DOM/像素不能代替订单、付款和外发事实 |
| L6 外部执行适配 | 已接报告、已批准原 Retort 工程消费者和具有原请求预算批准的 PR 修复；其他外部 Para/Cursor 未统一到同等合同 | 对应服务须提供原始用量、原任务终态及隔离发布身份；未接适配器继续在出站前拒绝，不能删除阻塞条件冒充全量接入 |
| L6 供应商未知用量收敛 | 已接 LiteLLM 1.109.3 原生 `LiteLLM_AccountingEvent` 实测账本，经原传输 request/key/model/时间/attempt 与绑定摘要核验后只补结原 call；原调度和 life 对账消费恢复 | 配置原网关只读 PostgreSQL 账本与同步落账；估计、缺失、重试聚合、换端点及无绑定的历史调用保持 unknown。实测费用不替代原业务完成，也不恢复撤销或超额授权 |
| L5 任意产品实验 | 员工 prompt、工作流生成和 `rag_context_prompt` 已接实际消费者；RAG 在原授权检索后注入候选并核对引用 | RAG 引用完整性不证明事实正确或业务达标；受理策略、任意完整图和模型路由仍需各自授权、实际曝光和独立结果适配 |
| L5 自主改进范围 | 原失败训练与候选审批覆盖员工 prompt、工作流生成 prompt 和原 RAG 输入；固定 promptfoo 配对验证后进入原 Retort/GrowthBook 审批、曝光、推广与撤回 | 其他 surface 继续要求原运行输入与真实消费；离线结果只能形成候选，生产改善须实际样本和预注册观察窗 |
| L5 工作流领域覆盖 | 客户合同扩至无条件串行多个原生文件员工，逐节点冻结实际员工包、静态输入与产物字节，保留最终 output_mapping；FHD 多员工按原父子 AgentRun 独立核对 | 动态输入/任意分支和其他领域 KPI 仍需对应生产者合同；到达 end、SQL completed 或自报输出均不能替代客户同单同制品验收 |
| L5 工作流收尾故障回收 | 原图实际返回后持久写入 `workflow.customer.graph_returned`，与较早 PRODUCED 分开；原调度启动及周期消费，在 SQL CAS 下只读收尾。历史已完成记录保留封存结果，兼容旧版本已持久完成的单员工合同 | 未完成执行须有完整原图返回与当前产物证明；旧 running/failed 不能借兼容分支补成功，新协议不能降级。下载与新增客户验收继续核对当前文件字节，不重跑员工、模型或计费 |
| L5 客户工作流计费边界 | 该交付路径沿原客户 quota/wallet，独立工作流 scope 不创建公司/组合预算身份 | CSV 消费者无需模型，不代表所有自定义员工已接公司逐调用预算或操作系统隔离；原计费告警也不能被业务完成状态代替 |
| L5 原生训练上线验收 | `5e71eb4b` 的 Ubuntu 22.04 CI 已实际通过固定 OpenCode、promptfoo CLI 与原生 SRT 正向合同；macOS 原生 SRT 通过，实际 OpenCode CLI 两项仍跳过 | 实际生产宿主、固定模型端点和相应系统的真实 CLI 仍须验收；不把其他系统的 skip 写成通过。回执见 [运行时 CI](https://github.com/42433422/XCMAX/actions/runs/44895286614) |
| L6 市场/产品战略 | SearXNG 来源与原客户目标继续保留；原公开线索在接收事务内创建唯一 WorkOrder，运营链核对真实客户绑定、原付款、交付、使用、结果、验收、发票与对账 | 真实新客、付款与客户确认须由原授权入口形成；没有已验证客户身份的线索只记 prospect，未知新市场与其他获客渠道仍需来源及渠道适配 |
| L6 外部企业资源 | 公司预算/容量与原 ERP 采购已接：原审批数量、价格、供应商额度约束入库，库存与应付同事务；独立核验绑定原 run/step/tenant/PO/入库/凭证 | 已配置供应商与有效原审批是前提；ERP 入库/应付不能证明外部云资源已开通、外部供应商已履约或实际资金已支付，对应外部接口仍须单独接入 |
| 原生产步骤 P1–P9 | 原 brief 指纹绑定 DutyGraph 和变更请求；宿主改动核对原暂存字节、原 PR/main 文件，客户 Mod 读取原工作流交付。测试/打包/进化绑定同源 CI、完整包校验器、版本及日报；部署/下载/监控/安全使用各自原发布者和审计来源 | 每步保留原审批和实际证据要求。等待发布后只读恢复，不因审批回调重复派发；构建通过不证明部署完成，签名下载不证明客户安装。供应商外部操作和任意新业务域仍需对应真实来源 |
| L3/L4 生产交付 | 原客户文件 API 已接通，但分支代码和受控 HTTP 测试不代表真实客户收货、生产版本或真机升级 | 原客户实际下载/确认，main 精确提交、制品摘要、服务身份、安全扫描配对、真机升级回滚仍需真实回执 |
| L5 真实效果 | 本地通过的分流/统计合同测试不是线上改善 | GrowthBook 实际数据源与查询、真实流量、样本和预注册观察窗；真实改善、推广或撤回回执 |
| L6 商业止损 | 测试可验证同单归因/阈值/停止，但不能创造真实收入 | 已支付订单、同制品客户确认、退款和观察窗；实际消费及商业结果未知时保留未知 |
| L5/L6 退款事实 | 已实现原 Java 钱包退款事实的认证采集；`5e71eb4b` 的 Java 17 与 PostgreSQL 10.23/16 原支付 CI 已通过，包括原服务退款集成测试与 NULL 审核时间分页回归 | 真实部署仍须验收；银行或网关退款另需对应服务的原交易回执，不能把钱包余额入账写成现金到账。回执见 [支付 CI](https://github.com/42433422/XCMAX/actions/runs/44895286690) |

因此可报告已落实的具体代码机制及测试，不能把整套系统命名为「完整 L5/L6」或赋予小数等级。

### 战略控制入口

`/api/xcmax/strategic/portfolios` 提供 discover、创建提案、读取、approve、plan、run、review、stop。
所有写入使用认证管理员与原 owner；approve 必须提交 `expected_proposal_sha256`。
通用 decisions/meetings/action-items 接口不能代写组合预算或执行结果。
预算包含明确币种口径的费用上限、tokens、时长、并行度、风险、过期时间和模型费率来源。
调度器只推进已批准的组合；账号失去管理权限、过期、消费不明或触发止损即停止新增消费。
旧 `strategy_bets` JSONL 仅用于历史读取，不与 SQL 预算双写。

公司范围由 `MODSTORE_STRATEGY_COMPANY_CONTROL` 配置 `scope`、`authorizer_user_ids` 和
`eligible_owner_user_ids`，全部使用现有有效管理员 ID。配置不产生额度：
`/api/xcmax/strategic/portfolios/company-budgets` 的创建、读取、精确摘要 approve 和 stop
负责原公司封套。提案包含 `period`、`limits`、`member_owner_ids`、`idempotency_key`；
limits 使用 `cost_cents`、`tokens`、`compute_seconds`、`max_parallel`、`expires_at` 和原 `tariffs`。
组合自动冻结 `company_budget_id`，成员不能省略 ID 绕过，旧活动政策存在时删除环境变量也不会恢复无限制。
公司状态只显示汇总和调用者自己的占用。撤销/过期拒绝新增消费，原调用仍按持久身份结算；
初次启用前必须收敛既存独立任务，旧池仍有未知预留或槽位时不能批准换期。
公司联合选择包含原提案内曾被局部计划延后的候选；不会越过其他 owner 的 life 授权、依赖或高风险门槛。
求解同时满足每个组合剩余额度与公司剩余总量，记录实际 solver 状态和快照摘要，不把限时可行解声称为已证明最优。
已经开始或用量未知的任务保持原责任；实际成熟复盘只降低原批准置信权重，新增预算或扩大权限仍须原审批。

持续选题使用 `MODSTORE_STRATEGY_DISCOVERY_TEMPLATE` 指向管理员维护的 JSON，包含
`owner_user_id`、`goal`、`limits`、`period_days`（1–90）和可选 `use_llm`。
`limits` 使用同一 `PortfolioLimits` 合同；绝对 `expires_at` 到期后须显式续订，不能定时自授新预算。
既有 `plan_strategy` 消费该模板，周期键在 SQL 中唯一领取；同周期重试读取原结果。
新结果始终为待批准提案。无模板返回 `not_configured`；旧域审计快照只提供带日期的待复查候选，
canonical 域标识来自 `FHD/config/audit_benchmark_ssot.json`，历史缺口与 `UNRATED` 不当作本次现状或得分。
战略 CLI 与定时日志只输出固定状态和数量；完整候选、原 owner、决定编号与证据继续保留在原私有返回及认证审批入口。
可选 `market_research` 使用同一 API/模板：每个查询明确 `domain_id`、`allowed_hosts`、现有 `employee_id`、
`customer_user_id`、`order_no`、`customer_goal_ids`、`acceptance_target` 和 `window_days`。
复用 `MODSTORE_SEARXNG_URL`，最多四个配置查询；服务不可用、JSON 未启用或没有新鲜来源时如实返回状态。
模型引用只能对应本次实际检索快照；审批后保留原客户协议身份。`customer_acceptance_ratio` 仍需原 KPI 实测达标和
原客户同制品确认，窗口未结束不提前认定效果，窗口冻结后晚到回执不重写结论。
原客户用既有认证访问 `/api/customer-value/deliveries?order_no=...&customer_goal_id=...`，
按返回的 `download_url` 获取原生文件；列表按 SQL 游标分页，不返回其他任务输入、日志或执行账号工作区路径。
每次下载重新核验权威付款、原客户协议和完成制品；文件丢失、换代、退款或协议改变均拒绝读取。
服务返回已核验的字节快照，仍须由原 `/acceptance-receipts` 接收客户的独立确认。

在职训练仍使用 `MODSTORE_RETORT_PROTOCOLS` 内的受控模板，新增 `training_candidate` 配置：
`employee_id`、`owner_id`、`goal`、`prompt_path`、`growthbook` 与 `recovery`。
只接收原服务令牌提交的精确 bundle/result 原文与四个冻结文件，复查当前 main 提示词、
真实失败 run ID 和摘要；重试同 request_key 不新建任务。第一次批准涵盖精确 replacement，
独立验证后还有正式验收批准。原失败案例与结果保存在私有证据中，公开附件只含摘要和候选编号。
候选执行与客户修复使用同一不可导出凭据协议；线上实验只覆盖预先批准的账号 cohort，
推广也仅在该 cohort 内生效，扩大范围需新批准。配置、租约或审批失效不能把已发布候选当作默认全量结果。
工作流训练选择 `surface=workflow_nl_prompt`，使用原 `WorkflowSandboxRun` 的生成阶段私有失败记录，
冻结原任务、转换上下文和 main 的 `SYSTEM_PROMPT`；promptfoo 调用同一图转换/静态校验代码，
system/user 原文与模板括号不经第二次插值。实际执行失败还须能关联原生成记录、图指纹及执行输入；
离线回归不自动重放客户副作用。固定依赖与完整性锁位于 `runtime_tools/capability_trainer_deps`，
生产 CLI 经 `promptfoo_sandbox.mjs` 使用官方 SRT 的精确模型出口；安装步骤不接收执行凭据。
正式业务工作流执行结果仍由自己的运行和验收回执决定。
持久回归语料沿用 `MODSTORE_LLM_MASTER_KEY` 与现有 Fernet 加密，原 `.jsonl` 路径保持不变，
通过 trainer 的 `load_cases` 解密读取。旧明文记录在同目录写锁下原子迁移，原 case_id、身份、任务和转换上下文不变；
缺密钥、密钥不匹配或记录损坏时拒绝改写，不丢弃旧样本。持久目录须保管原密钥，不能生成新密钥覆盖已有语料。
Actions 的 prepare 步骤只在新建私有临时目录内使用进程内临时密钥，完成后删除该语料；
原输入继续进入受限 promptfoo 回归及原候选审批，临时密钥不写日志、环境文件或公开附件。

### 运行与验收前提

- 原钱包退款采集沿用 `JAVA_PAYMENT_SERVICE_URL` 和原内部服务密钥（`MODSTORE_INTERNAL_API_KEY` 或 `XCAGI_MARKET_INTERNAL_API_KEY`），读取 `/api/internal/payment/refund-evidence`。生产源为 `java_postgresql_wallet_refunds_v1`；完整快照经核验后进入原 `reconcile_paid_customer_value`，普通客户请求不能自行提交可信退款。测试、内部及自动续费订单沿用原排除规则。
- 生产安装 `MODstore[web,governance,llm-router]` 及仓库固定版本的 Retort/LangGraph，使用现有数据库迁移；原生 Responses 路径使用固定 OpenAI Python SDK `3.57.0`。
- 战略员工须由管理员在既有 `config.workspace_policy` 中配置批准范围内的非空 `scope_globs` 或 `forbidden_globs`。
  完成回执要求实际路径检查已执行且通过、原 verification 至少一项实际检查及计数一致；未配置路径检查、缺失或未知回执保持未完成，不释放未知执行的预留额度。
- 客户代码修复使用支持的 Ubuntu 22.04 原生隔离宿主、OpenCode 专属平台模型准入、
  `DEVFLEET_FORCE_OPENCODE=1` 与 `MODSTORE_PARA_PLATFORM_POOL=1`；开关本身不构成隔离证明。
- 只读战略报告显式配置 `MODSTORE_STRATEGIC_REPORTS_ENABLED=1`、既有协调服务身份及平台模型；
  `MODSTORE_PUBLIC_ORIGIN` 或 `PUBLIC_ORIGIN` 冻结本环境的 HTTPS 控制入口，staging 不借用生产网关。
  提案 `input_data.remote_execution` 冻结 `kind=github_opencode_report`、仓库、main `source_sha`、provider/model。
  任务专属 `/api/service/mac-control/strategic-runs/<request_id>/v1/responses` 只恢复原有效租约与批准费率。
  OpenCode 使用显式上下文、`store=false` 和本地 function tools；隐藏历史、后台运行及服务端付费内建工具不在此合同内。
  模型调用须预留全部输入/工具定义与输出的额度；报告 job 成功及原制品摘要读回后才完成组合。
  真实二进制/SDK 的受控 HTTP 回归不等同于本机已验收 SRT 宿主或生产凭据。
- 工程任务另启用 `MODSTORE_STRATEGIC_WORKSPACES_ENABLED=1`，必须已有公司预算与原 Retort 派工审批。
  `input_data.remote_execution.kind=github_opencode_workspace`，除报告共用字段外冻结
  `original_request_id`、`protocol_digest`、`approval_digest`。先绑定后由原 Retort 调度，
  已派发任务不能事后补预算。bootstrap 只允许核对原任务，逐 subtask grant 才能消费模型；
  execute/resume 互斥，原 job 终态和全部已结算调用控制槽位释放。候选生成仍等待原发布、独立验证及交付验收。
  小 C 发起的任务默认受原 life scope/300 秒截止限制；过期只读收回原回执。
  长期工程须在原提案的 `input_data.remote_execution` 中显式包含
  `life_lease={"mode":"persistent_phases","expires_at":"明确批准的 UTC 绝对时间"}`，由原管理员按完整提案摘要批准。
  期限不能超过原 life policy、组合和公司三者的到期时间；不得事后添加或复活过期周期。
  只允许原 request/source/owner/task 的模型调用和已验证阶段恢复，原周期、token 与预留保持不变；
  上一阶段原生终态与用量须已知，再通过原 CAS 竞争容量并撤销旧 grant。报告和本地 worker 不继承该授权。
- 平台 `litellm` 模型沿用最新主分支的网关密钥、目录和默认路由。预算 chat、stream 与 Responses
  同时限定 SDK 和代理重试，要求原始 `x-litellm-attempted-retries` 与
  `x-litellm-attempted-fallbacks` 均为零。实际网关不提供这些回执时保留未知；模型别名与原上游模型分开记录，
  不改写回执来伪造批准模型。该合同不替代真实网关版本/配置和供应商账单核对。
- 实验须配置真实 GrowthBook API、项目、数据源、预注册指标和实际曝光查询；已接线入口为员工 prompt 与自然语言工作流生成 prompt。
  后者使用 `surface=workflow_nl_prompt`、`resource_id=workflow_nl_generator`、`measurement_scope=workflow_generation_static_validation`；
  按认证账号分流，每次结果绑定实际归属的 workflow。`ok=true` 但静态校验失败仍记失败；静态校验通过不等于工作流真实业务完成。
  衡量实际执行时另选 `measurement_scope=workflow_execution_terminal`，配置 `execution_outcomes` 的
  `source=modstore_event_outbox_postgres_v1`、独立 `success_metric_id`、`failure_metric_id` 与
  `maximum_treatment_failures`。GrowthBook 数据源/指标必须读回匹配本版本 `retort_workflow_metrics.execution_queries()`；
  成功指标上升、失败护栏下降，binomial 按批准账号在窗口内实际执行成功/失败的转化判断，
  重复执行不算独立用户扩大样本。treatment 实际失败次数达到预注册上限立即走原停止/撤回；
  版本、输入、图或批准改变后的迟到回执只归档。
  原客户文件交付使用独立 `measurement_scope=workflow_customer_accepted_outcome` 与
  `customer_outcomes.source=modstore_customer_workflow_postgres_v1`，配置原 `employee_id`、
  `success_metric_id`、`failure_metric_id`、`maximum_treatment_failures` 和 1–168 小时的
  `observation_hours`，`maturation_hours` 至少覆盖该观察窗。仅支持原企业客户拥有的
  start → 单个不可变原生 Python 文件员工 → end 图；无重试节点、额外分支或跨客户委托。
  执行输入的 `customer_delivery={order_no,customer_goal_id}` 必须对应当前权威生产付款和原客户确认的 KPI。
  原 `/api/customer-value/workflow-deliveries` 返回该客户可下载的真实制品，
  原客户确认与管理员业务测量仍分别使用既有 receipt API。
  KPI、制品 SHA、实际完成时间、发生时间与入账时间均核对，成熟观测按账号去重；
  此客户口径的 `maximum_treatment_failures` 按失败账号数止损，重复执行不会增加独立样本。
  推广后继续原授权交付而不扩大实验样本，精确退款沿原恢复流程撤回。
  其他产品表面须接入真实消费者和结果，不能伪造曝光来补足样本。
- `experiment.exposed` 写入真实账号曝光；`experiment.observed.success` 仅代表实际 cognition 模型调用结果。
  整任务成功率从既有 `EmployeeExecutionMetric` 与 verification 结果关联曝光窗口，付费结果从原支付台账关联正式制品；不能用模型返回成功替代任务或商业成果。
- 模型价格是已批准费率的计提依据，供应商账单与真实业务收入各保留自己的来源；缺失数据报告未知。
- 自动发布恢复须将 `MODSTORE_AUTO_ROLLBACK_COMMAND` 配置为 `/usr/bin/bash /opt/xcmax/releases/<approved-controller-40sha>/成都修茈科技有限公司/MODstore_deploy/scripts/xcmax-immutable-release.sh --submit-rollback-json`。
  控制器必须来自已有正式 manifest 的只读版本，不能指向 `current`。入口冻结请求后复用 systemd transient service，在独立服务中执行既有回滚；不修改服务权限。缺少既有权限返回等待，提交不明不重复执行，`accepted` 仅代表受理。
  启用客户业务实验前，API 与 scheduler 的该命令都须指向已合入并验收、包含
  `verified_customer_refund` 原因的不可变控制器版本。现有合同不协商旧控制器支持的原因集合；
  旧版本会拒绝该原因并保持 `waiting_recovery` 与本地 control，不能登记恢复成功或原地修改旧控制器。
  原版本清理器保留明确配置的控制器，以及未完成恢复请求的控制器、当前和目标版本；支付服务查询异常阻断完成，只有明确未安装才跳过其身份读回。
  Retort 仅在同一请求的持久 `rollback_verified` 回执及 API、scheduler、public 和适用的 payment 身份重新核验后完成；指针已切换、命令退出零或单个入口健康均不足以确认恢复。
- 生产部署、客户确认、付费转化和观察窗口尚未实际发生时，状态维持等待，不自动登记为 L6 验收完成。

## 管理端小 C：双重自主闭环

本次先完成 MODstore 管理端：全企业只有 `xcmax:management:xiaoc` 一个持续身份。
企业目标驱动工作，兴趣与真实经历驱动探索、反思；两者共用模型、员工和事实账本，
探索额度单独受限。桌面端、移动端和普通客户聊天不因此获得企业自主权限。
这里的 L1–L6 是可执行行为的开关，不修改上文 18 域基准，也不证明主观意识或生产成熟度。

| 模式 | 管理端行为 | 后台行为 |
|---|---|---|
| L1 | 对话、读取已授权上下文；不发工具动作 | 不启动自主循环 |
| L2 | 用户明确请求下的一次工具动作；禁止委派编排 | 不启动自主循环 |
| L3 | 使用现有任务编排、审批与员工 | 不启动自主循环 |
| L4 | 同 L3，显示企业目标和执行动态 | 在授权范围内观察企业、提出任务并推进已批准任务 |
| L5 | 可把有来源的兴趣结果转为原战略提案 | 按独立额度探索，持久保留兴趣及其依据 |
| L6 | 读取实际经历、失败与业务反馈，形成改进提案 | 反思并更新带证据的能力假设；训练、发布仍走原批准和验收 |

### L1 对话闭环

本轮从 #3449 的已发布源码 `f71246900c1b7141b40c7ba61c654d0b4211d6d7` 开始核查，提交前同步到其已发布增量 `e2b985fdbac101b08fe9f6a80417ed9fd240b7c4`；不将 PR 描述或另一工作树的未提交改动当作已合入代码。L1 允许对话、写作和代码建议及已授权上下文，不自动执行工具。以下是原调用链的故障回归范围，不能替代生产、真实模型或客户验收。

上下文快照与回复审核选择性适配已提交来源 `cbb9b5541da`，普通回复/向量解释入口选择性适配 `f350f1a6667`，并保留本轮的完整终态检查；这些是核对过的本地提交来源，不据此声称对应远端 PR 已合入。运行时仍复用原 LangGraph、模型适配器和 Pydantic 结构化解析；产品只补完成事实、会话归属与权限传递。

| 原断点 | 代码中的收口 | 回归入口 |
|---|---|---|
| 解释向量检索被误当表格任务、正常文字回复被当计划格式错误 | 兼容入口统一进入原 planner，原生工具选择仍允许无工具的普通回复；无执行回执不得声称已写入或完成业务 | `FHD/tests/test_application/test_native_tool_calling.py` 及兼容入口回归 |
| 规划与二次审核读取不同上下文、审核失败状态留在复制字典 | 审核复用本轮授权上下文快照和失败状态；对话使用结构化 ReplyReview，不强迫写作建议生成执行图 | `FHD/tests/test_application/test_planner_context_continuity.py`、`test_planner_reply_completion.py` |
| 流中断后补齐 JSON，将半句话记为成功 | 原供应商和 planner 保留结束原因，要求完整终态；已发布片段随失败回执保存，不自动再请求另一份答案 | `FHD/tests/test_application/test_planner_reply_completion.py` |
| 计费回执丢失结束原因、兼容网关固定写 stop | 原 LiteLLM/供应商、同步计费和 OpenAI 兼容输出传递实际 finish_reason；缺失保持未知 | `tests/test_llm_billed_route_snapshot.py`、`tests/test_openai_llm_gateway_models.py` |
| 管家空答复、空白、截断或无终态进入成功历史 | 同步与流式在成功日志前核对正文和结束事实；不将推理字段替代正文 | `tests/test_agent_butler_api.py` |
| 输入重复、加载/失败占位混入上下文 | 捕获已完成历史，本轮用户输入只发送一次；L1 技能关键词不能截断正常模型建议 | `market/src/composables/agent/useAgentEngine.behavior.test.ts` |
| 并发、清空、停止、换账号后旧结果覆盖新消息 | 绑定原消息、账号和会话代次；取消接收、权限等待与工具前复核共同拒绝迟到回写/动作；旧无归属操作记录不交给新账号 | 同上及 `useActionExecutor.test.ts`、`stores/agent.test.ts` |
| 模型请求失败或截图失败后悄悄换成另一动作 | 故障沿原对话回报；截图未取得时不声称已看图，HTTP 失败不替代执行关键词技能 | `market/src/composables/agent/useAgentEngine.behavior.test.ts` |
| 工作流生成 await 期间降 L1，仍写入图和技能 | 写入前及提交前复查原 manual scope，失败回滚；私人任务保持原权限 | `tests/test_xiaoc_life_execution.py` |
| 员工转交离开请求上下文后丢失原管理员和等级 | 原建议单持久保存可信来源；调度恢复原责任人和等级，撤权/降级保持待核对，不换管理员执行 | `tests/test_xiaoc_life_handoff.py` |
| 降级中断下一动作时丢弃前一步回执和模型用量 | 保留原 outputs 与真实 token；下一动作标记 blocked/not_started，已有 unknown 仍待核对，阻断后不启动验证工具 | `tests/test_xiaoc_life_execution.py` |

上表 `tests/` 与 `market/` 均相对 `成都修茈科技有限公司/MODstore_deploy`。桌面和移动端原有缺少 SSE done、账号切换、原回执查询以及 unknown 禁重放保护继续保留；它们不是本轮新实现。停止接收与降级只阻止未发起的新动作，已经出站的动作仍按原回执核对。待办的批准、主线合入、发布和运行身份继续走原门禁。

### 管理端缺口与代码承接

以下列出本轮代码审查发现的管理端缺口；文件均位于 `MODstore_deploy`，不把新增入口本身算作运行成功。

| 缺口 | 复用及实现位置 | 可核验的完成条件 |
|---|---|---|
| 身份随窗口、用户或模型分裂 | `db/xiaoc_life.py`、`xiaoc_life_store.py`，SQLAlchemy 唯一主键 | 多会话读取同一身份；换模型不新建主体 |
| 滑杆只改前端提示词 | `XiaoCLifeControl.vue`、`useXiaoCLife.ts`、`xiaoc_life_api.py` | 全局 revision 比较更新；并发冲突刷新最新值，跨窗口主动读回 |
| 旧卡片和重试绕过降级 | `xiaocLifeActionGuard.ts`、`xiaoc_life_chat.py`、原模型代理 | 旧卡执行、流式/重试和员工下一动作边界复查权限 |
| 工具能给自己加权限 | 管理设置容器标记与前端动作门控 | 拒绝工具操作模式、预算和审批控制区；服务端仍要求管理员 |
| 没有无人输入时的消费者 | `workflow_scheduler.py`、`xiaoc_life_runtime.py` | 既有 APScheduler 唤醒，LangGraph 执行观察、决策、行动、反思 |
| 多进程重复认领与预算超卖 | SQL 版本比较更新、单次租约、上海自然日账本 | 并发仅一个认领；消耗不会被降级、调低预算或跨日未知调用清除 |
| 自主调用无预算责任主体 | `xiaoc_life_policy.py`、原 `strategic_portfolio_usage.py` | 有效管理员、非零额度和明确期限；平台模型准入与真实 usage 结算 |
| 企业工作与兴趣互相耗尽额度 | 同一日账本的企业/探索份额 | 探索只占分配份额；企业与反思共用剩余份额 |
| 进程中断后重复消费 | 出站前持久身份、`xiaoc_life_reconciliation.py` | 未出站认领可释放；已出站只读原请求/任务账本，缺回执保留占用 |
| 持久本地队列丢失生命身份 | 原 worker 绑定与 `strategic_portfolio_worker.py` | 恢复原 owner/cycle/lease/期限；等待回执不撤掉有效 lease、不续期 |
| 私人记忆混入全企业状态 | 保留原 MemoryV2/Mem0，另存共享事实经历 | 私人记忆按原账号隔离；共享经历只含可引用的企业事实与摘要 |
| 经历只写不读、重复提目标 | `xiaoc_life_cognition.py`、稳定目标身份 | 下一轮读取历史、兴趣、反馈及假设；已绑定目标不重复建立任务 |
| 兴趣由模型无依据编造 | 真实观察引用校验与已有 SearXNG 适配器 | 一轮至多一次搜索/三个来源；无配置阻塞探索，不换付费服务 |
| 研究结果没有企业执行出口 | `/life/goals/{id}/portfolio`、原战略 API | 有来源目标、现有员工和冻结预算形成待审提案 |
| 有审批 API 但没有管理审核页面 | `XiaoCLifeTaskBudget.vue`、`XiaoCLifeProposal.vue` | 显示原任务/来源/费率/摘要，明确勾选后以精确 hash 调用原 approve |
| queued、工具返回或模型总结被当完成 | 原员工终态与验证合同、回执核对 | 持久队列只显示等待；真实执行验证和商业效果分别记录 |
| 感知富化原地污染已批准输入 | 原员工感知入口对输入深复制 | 分类与上下文富化可更新感知结果，原业务参数与批准摘要保持一致 |
| 旧文件员工的真实产物无法进入验收 | 原 `sha256_file`、`check_path_guard`、通用 verification 的薄适配 | 文件实际存在、目录与范围获批、读取期间稳定，才形成带路径/长度/摘要的终态回执 |
| 任务文件参数可绕过已选目录 | 原冻结及执行合同检查实际输入别名和输出路径 | 审批前及实际加载前检查规范化路径、符号链接与批准范围；输出越界在执行前拒绝 |
| 实际业务复盘未反馈给小 C | 原 `review_portfolio`、白名单聚合反馈、`reconcile_goals` | 原客户同单同制品的验收率 hit/miss、窗口与来源摘要保留，归因和停止原因变化形成新经历并进入下一轮模型输入 |
| 自我评价冒充已提升能力 | 带证据的 `self_model.status=hypothesis` | 后续上下文可读取；实际改进仍依赖成对评估、实验和原验收 |
| 经历难以追查与分页丢记录 | `/life/experiences`、时间与 ID 组合游标 | 同时间记录不漏页；真实原事件保留，后续核对另追加回执 |
| 冷启动或升级缺表 | `20261121_xiaoc_life`、原升级脚本 | 新库与旧 head 均可升级；幂等迁移保留已有身份和经历 |
| 新网关默认模型被旧默认值遮蔽 | `services/llm.py`、原平台默认路由及实际模型目录 | 自主认知与聊天使用相同平台默认解析；保留显式 runtime/bench 配置 |
| 网关没有精确额度，所有自主调用被挡 | `llm_quota_monitor.py`、原 `planning_admission` | 官方聚合用户的当前预算周期与生效上限一致；USD 余额明确标识，未知/无限/过期预算不准入 |
| 健康探测把备用路由成功算给原路由 | `llm_runtime_route.py`、原平台调用 | 探测禁用本地回退，并拒绝回退回执或 provider 不一致 |
| 网关回退信息在 SDK/原生 HTTP 中丢失 | 原 LiteLLM Router、HTTP 适配与平台用量账本 | 流式/非流式保留原回退信息；未知额外消费保留预留，模型身份和真实 usage 门槛不变 |

### 复用选择、恢复边界与上线前提

通用部分采用已锁定的 LangGraph 1.2.10（MIT）、APScheduler 3.11.3（MIT）、
Element Plus 2.14.8（MIT）、原 SQLAlchemy/PostgreSQL、LiteLLM 和 OR-Tools。
本轮没有新增依赖版本或代理平台。LangGraph 的单轮图不装 checkpointer；
跨进程恢复使用现有 SQL 状态、原模型调用 ID、原员工任务及不可改写的事实经历。
自有逻辑只负责 XCMAX 的企业身份、模式、两类额度、原审批摘要和回执关联。
固定版本、上游与许可证详见 [MODstore README](../成都修茈科技有限公司/MODstore_deploy/README.md#管理端小-c)。

默认 L3、每日自主模型额度为零。使用后台循环前，管理员必须配置 token/轮次/间隔/探索占比，
并明确授权到期时间（最多未来 31 天）；企业任务另用现有冻结预算及审批。
平台模型须有真实能力与健康额度观测；统一网关须连接数据库并配置有限 USD 预算、有效预算周期与可读管理接口，具体协议见 README。
SearXNG、员工执行范围、实验数据源和交付链路按原合同配置。
缺失配置会显示阻塞，不用空响应、估算用量、假员工或模拟业务收益补齐。

暂停与降级阻止后续动作，真实已发生的费用仍结算。已绑定的本地 worker 只在原租约内恢复，
尚未开始且可核验的失效队列可取消；正在执行或未知出站不能假装零消费。
显式批准的长期工程使用上文同一任务阶段合同；本地 worker 在任何取消副作用之前拒绝远程绑定。
模型账本写入或出站阶段不明确时继续保留占用，等待原回执，不自动重放。
同步 handler 无法强制撤销已经开始的动作；远程 Para/Cursor 的逐调用预算桥仍遵循上文阻塞边界。
本轮不会把这些未实现的远程执行适配器标成管理端闭环的一部分。

生产完成仍要求本 PR 的精确 head 通过检查和评审、按原主序列合入、执行数据库升级，
并核对同一 main SHA 的 API、scheduler、管理 UI，以及真实授权下的一轮模型/员工/业务回执。
受控 HTTP 和 SQLite 回归证明实现合同，不代替真实供应商消费或企业经营效果。
管理端贯通回归使用真实 JWT、SQL Catalog、原精确摘要审批、生命周期调度和仓库 CSV 员工，
生成真实文件并核对 SHA、路径、验证报告、任务账本及下一轮反馈；该确定性员工路径不消费模型。
标准文件参数的路径检查不是新增 OS 沙箱，也不代表任意自定义脚本的所有文件访问都已被拦截。

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

本轮已吸收的固定来源与未纳入范围见[源 PR 处置](#本轮源-pr-处置)，包括 #3437 的原生回执与 #3398 的预算/交付消费者。下面说明原链路中的断点与改造；源码与受控回归是 E1/E2，不等于原生部署、真实模型或客户验收。

### L3 原执行链补齐（2026-11-22）

本次在 PR #3449 已发布的 `f71246900c1b` 上继续修改，并保留后续 `e2b985fdbac` 的原经营归因修复与 `ca35d7d025a` 的 L1 原回复、会话和降级回执修复。复用现有执行器、公司预算、GitHub Actions、独立 publisher、filelock 和持久账本；独立 publisher 在本次之前已经存在，原 PR 修复缺的是自身批准与计量合同的接入。

| 已复现的断点 | 当前代码行为与原承接点 |
|---|---|
| 原 PR repair 无条件阻断 | `para_github_repair.py` 与 `strategic_workspace_*` 保留原 MacControlTask，预算记录使用由原请求派生的独立 UUID。原组合批准须冻结 `original_request_kind=original_pr_repair`、原请求 ID 和 `approval_digest`；原 PR/source、可信控制器 SHA、原 task/subtask/attempt/device 均核对后才发阶段 grant。缺批准或未知用量继续等待。 |
| 候选/发布与修复完成混用 | `github_para_executor.mjs` 和 `publish_para_candidate.py` 仅放行上述原预算与 SRT 隔离；回读原 attempt 的完成 publisher job、候选及分支。原 Issue dispatcher 在受信 bare Git 中核对祖先、变更范围及未漂移的原 head 后，按 CAS 快进原 PR 分支；原精确候选的 CI 通过才结清修复，明确失败记失败，交付仍为未核验。 |
| 自愈 workflow_dispatch 丢确认永久悬挂 | `ai_self_heal.py` 先在原机器人评论保存请求 UUID，再传入原工作流。`self_heal_reconcile.py` 通过完整原运行列表找回唯一相符 run 并写回原评论；后续沿原 run/控制任务继续，不再 POST 新任务。旧无请求标识的未知记录仍不能猜测。 |
| 合入后原 CI 消失时替换成另一成功 run | `ai_self_heal_sla.py` 将原 PR/head 的稳定请求标识接入两条原主干 CI；已知 run ID 暂不可见只保留观察，未知 ID 仅接受唯一匹配。列表截断、重复 ID、总数漂移及错仓库/attempt 不得结单。 |
| 合并/部署最终确认丢失，或部署 pending 被清检查点 | `maintenance_loop` 在出站前冻结原任务、head、批准及部署范围，读回原远端任务和 GitHub 合并身份，或本地已发布 Git 的真实父提交。沿原部署请求继续，冷却与阈值不丢弃原恢复；不重做代码、审核、QA 或合并。 |
| 首次收尾落盘后、合并意图之前崩溃 | 原子保存 `before_policy`、原终态、gate 与部署范围，只允许此阶段恢复纯预检。已落 `merge_intent` 后只读回；不能取得有效原 head/base SHA 或不支持的仓库在 POST 前 hold，避免产生无法核对的合并。 |
| 结果记账或知识回写中断重复消费 | 原终态、结果摘要和知识文件复用原账本/记忆投影；正式投影按原 run 与冻结内容幂等续写，历史缺证明或内容冲突保留待核对。 |
| 管理端停止意图没有到达原设备进程 | `mac_control_receipts.py` 沿既有认证回执返回原停止意图，核对 device/correlation/attempt/task/subtask；`control_receipt_outbox.mjs` 与 `para_e2e_agent.mjs` 按单任务 AbortController 停止原 Codex 进程树并等待退出。原设备停止证据和 Para 终态均核对后收口；双 outbox 可乱序，已完成子任务和独立失败保留，未知用量不结零。 |
| 汇总证据凭文件名与自报成功即放行 | `build_closure_reports.py` 读回原成功 main 工作流、attempt 与不可变 ZIP 摘要，核对完整制品目录、源码祖先关系及读取期间身份；版本取原发布目录。修正工作目录重复 FHD 和浅历史校验。 |
| 人工回滚 JSON 伪装实测通过 | `verify_upgrade_rollback_evidence.py` 只给出结构校验与 `submitted_claims` 范围，不能产生测量通过。闭环汇总保留缺少独立原生测量的 blocker；当前 Windows 托管机和 macOS 启动回执均不能代替 Win10/Win11/mac 真机 OTA/回滚。 |

主干 CI 的请求标识不代表生产批准；生产审批与 Retort 回读继续核对原 release SHA、控制器 SHA、原成功 run、签名制品及运行身份。上述修复的正向和反向回归覆盖真实 SQL、文件锁、持久 JSON、Git 与 ZIP；外部 API 用受控传输替身，不能记为真实模型/机器/生产验收。没有创建第二套执行引擎或为本轮调整审批与发布保护。

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
| 修复重试换提示词却复用旧幂等键 | 持久 request ID 的步骤只执行或回读一次；明确失败由原外层修复生成新身份，审查和 QA 保留原代码目标。 |
| 派发或步骤间重启丢失进度 | 原 loop memory 在派发前持久化 request/actor/步骤；已确认步骤保留到整轮结果落盘，恢复只核对原任务及原代码分支。 |
| 原 review 未核对就被新知识拒绝分支清除 | 回读原 review 前不再执行会清检查点的知识/Retort 分支；新 review 派发仍需原门禁。 |
| 最终合并或记账后重启，再执行最终策略 | 最终策略前保存意图；按冻结身份读回原合并、续查原部署及幂等记账。没有原意图或内容漂移的历史记录保持待核对。 |
| 整理记忆覆盖正在执行的记录 | 公开清理/关闭/对账入口共用原 loop lease；忙时明确返回，保留原待处理项。 |
| 验证命令没有退出码仍算通过 | 提供了 delivery validation 时，要求非空命令回执及真实整数退出码 0；缺失、超时和非法回执拒绝。 |

本轮复用 Codex 0.153.4（Apache-2.0）、仓库内 LangGraph 1.2.10 及其检查点回补（MIT）、MCP 2.3.0（MIT）、现有 SQL/CAS、Para 任务/outbox 和维护账本。选择依据与固定来源见 FHD README。官方 [LangGraph 重试与副作用规则](https://docs.langchain.com/oss/python/langgraph/fault-tolerance#retry-boundaries-and-idempotency)要求持久化幂等身份并核对丢失的确认；检查点本身不能保证外部副作用恰好一次。没有引入 OpenHands、Temporal 或第二套总控；本次薄适配承担本产品身份与回执规则。

| 尚未闭合的范围 | 具体条件 |
|---|---|
| 原 PR 修复上线验收 | 自身 MacControlTask 与原组合预算、逐调用 grant、SRT 和 publisher 已接线；须配置针对原请求摘要的真实批准，再取得最终主线 SHA 上的执行与原 PR CI 回执。没有批准的旧任务继续等待，不冒用 Retort 身份。 |
| 客户反馈修复的生产验收 | #3398 的受信 SRT/OpenCode、逐调用预算与隔离发布已进入本集成候选；仍需最终主线 SHA、真实执行、发布身份及客户效果回执，不能据接线状态宣称已在生产运行。 |
| 原生线程续跑 | 设备 Codex 当前使用 `--ephemeral`，原生线程续跑缺少持久 thread/工作区/原批准与预算的绑定及恢复消费者；不能仅凭回传 thread ID 调用 `resume`。已配对 Codex 任务的原进程停止已接通；其他工具或覆盖执行器没有原生停止证明时继续待核对。 |
| 请求已发送但无远端任务号 | 配套 Para 原请求回执表与 task/subtask 同事务，按 owner+client_request_id 唯一查回；首确认丢失、进程重启和多设备部分派发均保留原身份。客户端须同时核对恢复能力和原正文摘要，旧部署仍等待升级；其他未提供该合同的外部渠道不能按相似文本猜测。 |
| 历史最终副作用缺证明 | 新冻结意图可恢复原合并、部署和结果投影；旧 finalizing 记录缺 head/批准绑定、或不可幂等的自定义投影仍保持待核对，不能补造身份或重放策略。 |
| 设备模型硬预算和其他执行器 | 设备 CLI 的输出 token 上限仍标明 `output_limit_enforced=false`。可复用的逐调用 SQL 预留与真实模型出口限制已用于 GitHub OpenCode；设备 Codex 的原批准预算→原任务 grant→受限出口适配尚未接通，直接 key/ChatGPT 登录和事后 usage 不能冒充事前硬限制。Cursor/Claude 也未统一到同等级原生终态。 |
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
客户反馈、训练候选和有原预算批准的 PR 修复仅接受 `srt-0.0.83-header-only-platform-v1`：可信控制进程持有 key，
模型进程只拿占位符，SRT 官方 TLS 代理按精确主机、路径、方法和批准模型注入请求头。
普通 mask 的请求正文替换功能不启用。原 PR repair 使用自身控制任务批准与预算记录，不借用客户工单或 Retort 身份。
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

- 最终 SSOT 复核补登记原 workflow.resume_params_rejected 事件，原生成器检查及 6 项契约测试通过。三段无状态确认回复归回现有回复构造器，函数/会话类 AST 不变；原确认恢复 22 项、目标类型和格式检查通过，结构计数保持 G12=1/1、G11=181/181，未调整结构阈值。 最新宿主退出监督组合共 223 项：211 通过、12 项原 PostgreSQL 环境跳过，退出码 0；四生产文件的独立只读复核及目标 mypy 通过，未将平台不支持的孤儿接管描述为已验证回收。 工作流复核另恢复原真实 Electron 端口占用负控到当前 update-rollback E2E：保留五项原测试，发现六项且类型检查通过；真实 macOS 执行仍以本次追加提交的原 CI 为准，不用旧提交绿色结果替代。
