# XCMAX / XCAGI 产品经理接手基线

评估日期：2026-09-05（北京时间）。

## 判断与评分

**综合 58 / 100：处于行业试点向可重复商业交付过渡的阶段。**

评分标准是目标客户能否独立上手、正确完成业务、持续使用并获得可验证收益。分数是本次产品管理判断，不是行业认证；没有用代码数量、功能菜单数量、历史覆盖率或自治看板百分比代替成熟度。

| 维度 | 满分 | 本次得分 | 判断依据 |
|---|---:|---:|---|
| 客户定位与价值表达 | 10 | 7 | 企业本地数据、表格与行业流程的价值明确；对外表达混入过多内部架构和员工分类概念 |
| 核心业务完整度 | 25 | 17 | ERP 有事务、幂等、审批和导入校验；首单入口、撤销语义和部分结果输出存在断点 |
| 用户体验与上手 | 15 | 9 | 主界面和业务导航已成形；任务引导、概念层次、状态反馈和错误恢复仍需收敛 |
| AI 执行可靠性 | 15 | 7 | 工具控制和审批机制已有实现；真实入口误路由，AI 健康状态没有准确传达给用户 |
| 工程与数据安全 | 15 | 9 | 有有意义的一致性、失败回滚及恢复测试；仍发现撤销覆盖和访问令牌 URL 传递问题 |
| 交付与运营 | 10 | 6 | 生产、Mac 交付和备份复制有当前证据；Windows 最新交付、移动真机和持续 SLO 证据不齐 |
| 商业验证 | 10 | 3 | 支付、验收和价值证据机制已有；真实付费交付、客户验收、持续使用收益尚未取得可核验证据 |
| **合计** | **100** | **58** | 商业项暂按证据成熟度评估，不代表企业没有客户或收入 |

本评估的阶段定义：40–59 分为有业务基础的试点产品，60–74 分为可重复的小规模交付，75–89 分为稳定商业产品，90 分以上需长期客户价值与规模运营证明。总分不能抵消数据安全或核心业务阻断项。

## 评估对象与边界

- 工作区 HEAD：`9016daab66f781614ffe91f9ab9d6428bb15d4c9`。
- 本机已安装 `/Applications/XCAGI.app`：产品版本 `1.0.0.1`，构建 `bb5a908f7c725d633ba69292eac8cf30845d2079`。
- 本轮线上检查：服务端、管理台与 Mac stable feed 对齐 `99854233c5d4`，版本 `1.0.0.1`。三种身份分别记录，不把源码存在视为已安装或已上线。
- 实际查看：智能对话、考勤人员与记录、商品、客户、订单、库存及导出、数据对接、知识库、员工空间/全景、系统设置、AI 生态、市场和审批工作台。
- 源码检查：业务事务、AI 分类与审批、ETL 预演和回滚、跨站认证、测试断言、发布与验收材料。
- 验证方式：UI 只读操作、运行态/API 与公开制品查询、只读生产日志、源代码审阅，以及原逻辑的纯内存复现。
- 未操作真实业务写入、支付、发货、打印、删除或故障切换；未重跑全套测试、未完成跨设备全流程验收。
- 设置页初始“未登录/缺少 Mod”在加载后恢复正常，不认定这些功能缺失。市场默认分类一度为空，切换全部商品并完成同步后显示 26 项，不认定市场整体无商品。

## 产品最值得保留的价值

目标客户画像：依赖 Excel、纸质单据和重复录入的中小制造/商贸企业。决策者通常是老板或运营负责人，实际使用者是行政、跟单、仓库人员。具体企业规模、付费意愿仍需访谈与成交数据确认。

主价值主张：保留企业既有表格与业务习惯，把导入、核对、查询、开单、库存和打印交给 AI 协助执行，产出用户能够核对的业务结果。行业 Mod 应帮助适配行业，而不增加使用者必须理解的技术概念。

1. ERP 有超出独立 CRUD 页面的跨模块一致性设计。报价、确认、履行、开票、收款可共享外层事务，校验租户、金额和幂等键；测试包含实际订单/库存/分录断言及失败注入。参考 `FHD/app/application/sales_app_service_salesappservice_mixin01__salesappservicepart01mixin_mixin01.py:307`、`FHD/tests/test_services/test_erp_absorb_e2e.py:957`、`:1193`。本轮检查了测试设计，没有声称本轮运行整套测试通过。
2. AI 工具控制深入到执行边界。低风险、幂等动作与需要确认的动作有区分，审批绑定用户、任务、步骤、工具和参数。参考 `FHD/app/application/agent_orchestrator/approval_grant.py:59` 及 `FHD/tests/test_services/test_erp_absorb_e2e.py:1829`。
3. 文件导入有新增/更新/重复识别、匹配变化保护、OCR 证据与人工确认机制。参考 `FHD/app/application/etl/targets/products.py:137`、`:164`、`FHD/app/application/etl/service_preview.py:418`。
4. 交付运营已有持续运行基础：生产服务健康，Mac/服务端身份对齐；今日备份及异地复制、WAL 推送、DR 制品同步有记录。这些不等同于本轮完成故障切换或证明 RTO。

## 已确认的问题与证据

### PM-001：业务助手称呼触发人员查询

桌面现有首单对话要求查询客户、商品并创建演示出货单，回复却要求绑定人员档案。原分类器纯函数复现表明，“AI 业务员工”中的“员工”与“查询/我”组合被识别为 `personnel_read`；仅将角色称呼替换为“业务助手”便不进入该分类。普通“请 AI 员工帮我查询客户订单”也存在同样问题。

证据：`FHD/frontend/src/views/product-onboarding/useProductOnboardingState.ts:238`、`FHD/app/application/chat_business_safety_core.py:169`、`FHD/app/application/ai_chat_app_service_aichatapplicationservice_mixin01__aichatapplicationservicepart01mixin_mixin01.py:150`。现有首单测试直接进入 planner，未覆盖顶层误分流。

### PM-002：导入撤销可能覆盖随后人工改动

客户回滚仅对本次导入改变的字段做冲突检查，却恢复全部旧字段。纯内存复现：导入只改变电话，之后人工修改联系人；撤销电话导入时，联系人也被静默恢复为旧值。产品及客户产品联动存在同结构，需要一并核验。没有操作真实数据库，也没有证据宣称已发生实际客户数据丢失。

证据：`FHD/app/application/etl/targets/customers.py:119`、`:130`，`FHD/app/application/etl/targets/products.py:203`，`FHD/app/application/etl/targets/helpers.py:111`。

### PM-003：跨站跳转 URL 携带可复用访问令牌

钱包/套餐跳转把市场 access token 同时放到 query 和 hash，落地站直接使用该 token，没有一次性换票。它扩大浏览器历史及 HTTP/CDN 日志中的凭证暴露面。本轮仅确认实现与页面形态，未验证实际泄露或被利用；本报告不记录任何令牌值。

证据：`FHD/mods/xcagi-model-payment-bridge/frontend/views/model-payment/mpHandoff.ts:83`、`FHD/frontend/src/api/marketAccount.ts:278`、`成都修茈科技有限公司/MODstore_deploy/market/src/infrastructure/storage/fhdMarketHandoff.ts:53`。

### PM-004：系统状态未表达 AI 就绪情况

本机 `/api/desktop/status` 为 healthy、UI 就绪；`/api/health` 则报告 `LLM_RUNTIME_UNAVAILABLE`。侧栏“系统正常”使用固定绿色状态，未读取健康结果。不能由此断言所有聊天路径不可用，但用户目前无法据此判断 AI 能否办事。

证据：`FHD/frontend/src/components/Sidebar.vue:75`。

### PM-005：部分可见操作止于开发中提示

实际点击库存导出，弹出“导出功能开发中”。另源码中的一个标签模板操作仍仅提示“打印功能开发中”；这不代表全部打印或全部导出能力缺失。

证据：`FHD/mods/xcagi-erp-domain-bridge/frontend/views/InventoryView.vue:339`、`FHD/mods/xcagi-erp-domain-bridge/frontend/views/template-preview/useTpTemplateActions.ts:41`。

### PM-006：跨平台交付和稳定性证据未齐套

- [Windows stable feed](https://xiu-ci.com/releases/stable/enterprise/latest.yml) 仍为 `1.0.0.0 / 656db7b7`；[1.0.0.1 临时下载指针](https://xiu-ci.com/download-windows-hotfix.json) 显示 `download_allowed=false`、未签名，对应安装包 HEAD 404。
- 最近一次核验时，[9016daab 发布任务](https://github.com/42433422/XCMAX/actions/runs/33956311584) 仍在构建，尚不能登记完成；前次构建后的安装/启动/卸载验证失败。
- Android 有签名构建与 artifact 上传证据，发布步骤跳过；现行指南仍定义为实验骨架、非签约级。iOS 有上传流水线证据，不足以证明 App Store 上架和真实用户验收。
- [当前 SLO 快照](https://github.com/42433422/XCMAX/blob/main/FHD/metrics/slo-production/20260905T023914Z-33939497364-1.json) 已有真实源，但仍为 preflight、`day0_eligible=false`、`all_pass=false`，10 项中 3 项非空；不能把非空比例当作全量监控覆盖率。

## 商业证据与未知项

[公开脱敏商业证据](https://xiu-ci.com/download-founder-autonomy.json) 在 2026-09-05 16:51:30 的快照中，`paid_value_verified`、`paid_delivery_verified`、`customer_acceptance_verified` 均为 false，`production_value.available=false`。这意味着当前证据系统没有确认相应闭环，不代表企业没有客户、没有收入。

官网存在行业案例、99 元/30 天试用及正式企业方案，但案例宣传指标和报价不替代本轮客户验收。待用户补充：真实试用/付费企业数量、主用场景、持续使用周期、处理量、错误率、人工介入、节省工时和续费。商业维度在得到这些证据后重评。

本机演示客户/商品、空订单或空知识库，仅描述本机当前环境，不能外推所有客户的实际使用情况。历史 `CLAIMED_VS_ACTUAL.md` 的覆盖率和健康数据没有当作本次新测结果。

## 第一阶段优先级与验收标准

以下是待执行的产品验收清单；本次只建立基线，没有把这些问题登记为已修复。

| 顺序 | 事项 | 验收标准 |
|---|---|---|
| P0 | PM-002 数据撤销正确性 | 只撤销本次变更；保留后续无关人工修改；同字段冲突明确停止；客户、产品、联动目标都验证 |
| P0 | PM-003 跨站认证传递 | 用受限的一次性换票；可复用访问令牌不进入 URL；确认身份、过期、重放和失败回退行为 |
| P1 | PM-001 首次业务任务 | 从真实聊天入口完成查客户/商品、展示计划、按明确授权执行、核对单据与库存、产出结果；覆盖自然称呼变体 |
| P1 | PM-004 状态与恢复 | 分别表达桌面、AI 和业务依赖状态；给出可执行恢复入口；加载中不冒充缺失或成功 |
| P1 | PM-005 业务结果输出 | 核心可见导出/打印入口产出可打开、内容正确的文件或打印回执，不以提示框代替结果 |
| P1 | PM-006 Windows 同版本交付 | 签名制品、manifest、摘要与下载一致；干净机器验证安装、启动、业务首单、更新和数据保留 |
| P2 | 场景化导航与市场 | 按客户角色与任务推荐工作包；产品界面优先表达用途、输入、输出、条件，降低技术词汇负担 |
| P2 | 三条真实客户价值记录 | 每条记录含安装身份、首个业务产出、持续使用、错误/人工介入、量化收益与客户验收；付费与续费分别记录 |

下一次评分应基于上述验收结果更新。达到 70 分需要可重复的业务交付和客户使用证据，不能仅靠新增页面、模块或增加测试数量。

## 产品经理工作口径

后续需求统一登记问题、受影响客户、优先级、明确边界、验收标准和证据。评审分别看源码、实际安装版本、线上运行、真实业务结果和客户收益。尚未验证的项目保留为未知；检查、修复、上线、商业验收分别标记。
