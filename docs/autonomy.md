# 自治系统运维手册

维护范围：桌面、服务器和 CI 自治；源码、运行证据及客户验收分别报告。
本文件随 autonomy 变更维护。发布门禁见 [CI_SSOT.md](./CI_SSOT.md)。

## L2–L6 缺口与闭环边界（2026-11-21）

这里的等级描述工程能力，不能用最高层的模块名称代替整套系统的生产验收。
本轮以 `main@392d50b5` 和集成 PR #3398 的 `e4d87b02` 为起点复查后继续修复；
期间保留并整合 #3398 的 `445e2da0` 管理端小 C、`fda4306c` 工作流事务与持久交付修复，以及 `main@48f8f40d` 的统一 LiteLLM 网关。
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
| L5 工作流业务成果 | 工作流执行身份与客户目标、真实制品及验收未关联，执行成功可能被当成业务成功 | `workflow_customer_accepted_outcome` 覆盖原企业客户自己的单原生文件员工交付图；开跑前冻结原付款、已确认 KPI、图、员工包、输入与 assignment，真实员工返回点登记制品。原客户 API 核验同制品的业务测量和独立确认；窗口未成熟或权威来源不可读时等待，窗口成熟且来源可核验但缺合格回执记失败，迟到材料不重写冻结统计 |
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
| L6 流式用量 | 原战略入口拒绝流式；SDK 可把无/不完整 usage 合成为估算；同一预留可重复出站 | 复用原 SSE 与固定 LiteLLM，逐次预留并限定一次实际出站；在 SDK 规范化前观察原始供应商 chunk；缺终态、估算、撤销、超时/取消、fallback 保留未知占用 |
| L6 托管报告 | 本地预算上下文不会自动随远程任务传播；控制器回报成功不足以完成原任务 | 原 GitHub executor/OpenCode/SRT 消费冻结的报告任务，MacControlTask 与原组合绑定；原生 OpenAI Responses SDK 逐调用预留/结算，控制回执再与真实 GitHub job 和 ZIP 制品摘要核对。停止后只读回收旧任务，未知费用不释放 |
| L6 工程执行 | 原 Retort 反馈任务在隔离配置有效后仍无条件拒绝，子任务模型调用不能归入原公司预算 | 已批准原工作单在派发前绑定公司/组合；原 Para `handleTask` 核验 event/task/subtask/attempt 后领取阶段专属模型 grant。真实 job 控制 execute/resume，原候选、独立验证、接受审批、main、部署和效果回执共同决定终态 |
| L6 长期工程阶段 | 原小 C 周期仅 300 秒，等待 GitHub 阶段后无法合法继续；本地取消入口可能误退远程责任 | 原提案显式批准 `persistent_phases` 绝对期限，同事务登记原任务与公司/组合/life 身份。原周期与预留保持，只有同 native run 的已验证阶段可继续；未知、撤权或任一期限届满拒绝新调用，远程绑定不能走本地取消 |
| L6 网关尝试次数 | 主分支改走远端 LiteLLM 网关，本地禁重试不能约束代理内部消费 | 对预算调用在真实 HTTP 正文设置零重试/禁 fallback；读取原始网关两项 attempt 响应头，缺失、非法或非零都保留未知，不能用本地 Router 的零计数覆盖代理回执 |
| L6 商业回报 | 全局开票/GMV 被算作本战略收入；不同制品/完成前的 outcome 与 acceptance 可被配对 | 同目标、同真实支付订单、同客户、同已完成制品 ID/SHA 的两种回执才归因，时间在实际完成后且位于观察窗；排除退款、未来时间和无关客户，缺完成时刻保持未知 |
| L5/L6 原退款来源 | 退款止损只能消费已登记回执，原 Java 钱包入账未被正式采集 | 复用原退款审批、钱包交易与内部认证；同一只读事务核对订单、客户、金额、幂等键和余额差额，固定边界完整分页后由服务端封装证据。原 reconciler 按退款号追加唯一订单级回执，接原止损与实验恢复；不按客户目标重复计算金额 |
| L6 原客户验收 | 管理员是战略 owner，原客户却不能用管理员身份验收；原生文件缺稳定制品身份 | 审批冻结原客户、订单、目标与原 goal 回执；真实原生文件保留摘要。只有原 KPI 达标的 outcome 与原客户的同制品 acceptance 配对才计入确认率；管理员不能代客户确认，本地文件存在不等于客户已经收到 |
| L4/L6 文件交付 | 原生文件位于管理员执行工作区，原客户没有可授权下载入口 | 原客户价值 API 列出其当前协议绑定的已完成文件；复用支付归属、SQL 批准摘要与租户路径守卫，读取后核对 SHA 并返回同一字节快照。管理员/其他账号不能代取；下载与客户验收分开记录 |
| L6 止损与再分配 | 无预注册观察窗/阈值；停止后仍可继续消费 | 预注册假设、窗口和停止条件；每次调用/调度复查；仅在已批准候选与剩余额度内再优化 |
| L6 持续运行 | 模块存在却未调度，故障只写告警不回任务 | 既有 APScheduler 每 60 秒推进获批组合；#3396 清理空转任务、统一版本配置来源、补失败 incident；回执决定状态 |

18 域、108 项验收仍使用 `FHD/config/audit_benchmark_ssot.json`，不创建第二套分数。
依赖分层、ERP、Agent、ELT、意图路由、事件内核、Mod SDK、桌面、业务前端、商城 UI、
商城后端、自治维护、Java 支付、Flutter、Retort、编码沙箱、客来来和 CI 发布都可作为
战略候选的受控来源；本轮没有据模块接入宣称这 18 域已完成全部基准或真机验收。

### 仍未闭合的范围

下表是代码边界与外部验收的明确区分，不能把全部项改称「只缺证据」。

| 范围 | 当前边界 | 完成所需 |
|---|---|---|
| L6 外部执行适配 | 已接报告与已批准原 Retort 工程消费者；外部 Para/Cursor 和原 PR repair 仍不具备同等合同 | 对应服务须提供原始用量、原任务终态及隔离发布身份；未接适配器继续在出站前拒绝，不能删除阻塞条件冒充全量接入 |
| L6 供应商未知用量收敛 | 原账本保留 unknown 占用且不重放，已有恢复只读取已结算的原调用与原生任务 | 尚无原供应商请求查询/账单回执经身份核验后补结原 call 的消费者；须接专用可信回查适配，不能通过重置状态、重试或修改配置释放责任 |
| L5 任意产品实验 | 每个 surface 必须有真实消费者；员工 prompt 的接入不自动覆盖 RAG、受理策略、完整工作流图和模型路由 | 分别冻结资源身份与配置，保留原权限过滤，接真实曝光及后续验收。共享工作流图不能以全局节点改写冒充分用户 A/B |
| L5 自主改进范围 | 原失败训练与候选审批已覆盖员工 prompt 和工作流生成 prompt，后者另有真实执行指标 | 其他 surface 仍需要原运行输入、独立验证和候选发布的实际适配；离线静态验证只能形成待审候选，运行改善由实际执行实验决定 |
| L5 工作流领域覆盖 | 已接真实执行终态及原企业客户的单原生文件员工交付：同执行、付款目标、实际制品、KPI 和客户确认关联原 assignment | 多员工副作用图、任意节点与其他领域 KPI 仍须各自真实生产者和授权合同；不能从普通 output_data、客户自填 run_id 或到达 end 推定业务达标 |
| L5 客户工作流计费边界 | 该交付路径沿原客户 quota/wallet，独立工作流 scope 不创建公司/组合预算身份 | CSV 消费者无需模型，不代表所有自定义员工已接公司逐调用预算或操作系统隔离；原计费告警也不能被业务完成状态代替 |
| L5 原生训练隔离验收 | 已接生产 SRT 与固定无脚本 CLI；本机只完成官方代理与真实 CLI 的受控服务验证 | Ubuntu 22.04 CI 的原生 SRT 正向合同及实际生产宿主、固定模型端点仍须验收；不把本机 native skip 写成通过 |
| L6 市场/产品战略 | 已接配置查询的 SearXNG 来源及已有客户目标的产品假设、验收率和止损 | 自建服务启用 JSON，核验实际实例版本/检索来源；无发布日期或过期资料不参与。未知新市场、自动新客获取及无原客户协议的发现尚未闭合 |
| L6 外部企业资源 | 公司总预算、跨组合执行槽和模型/计算额度已接实际 SQL 预留与结算 | 云采购、人员/供应商分配和真实财务付款仍需要对应资源、订单与权限接口；现有 quota/inventory 观察不等于外部采购或资源开通 |
| L3/L4 生产交付 | 原客户文件 API 已接通，但分支代码和受控 HTTP 测试不代表真实客户收货、生产版本或真机升级 | 原客户实际下载/确认，main 精确提交、制品摘要、服务身份、安全扫描配对、真机升级回滚仍需真实回执 |
| L5 真实效果 | 本地通过的分流/统计合同测试不是线上改善 | GrowthBook 实际数据源与查询、真实流量、样本和预注册观察窗；真实改善、推广或撤回回执 |
| L6 商业止损 | 测试可验证同单归因/阈值/停止，但不能创造真实收入 | 已支付订单、同制品客户确认、退款和观察窗；实际消费及商业结果未知时保留未知 |
| L5/L6 退款事实 | 已实现原 Java 钱包退款事实的认证采集，尚不代表支付网关现金退款 | 原支付 Java 编译/测试与真实部署须验收；银行或网关退款另需对应服务的原交易回执，不能把钱包余额入账写成现金到账 |

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
