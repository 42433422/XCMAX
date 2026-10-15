# XCMAX 审计对标 SSOT

> 生成视图。唯一维护源：`FHD/config/audit_benchmark_ssot.json`。
> 修改 JSON 后运行 `python scripts/dev/audit_benchmark_ssot.py generate`；CI 用 `check` 验证一致性。

标准版本：**1.0.0**；评分版本：`external-anchors-v1`；资料核对：2026-09-08。

**本版定义锚点，不包含 XCMAX 或 54 个商业参考的实测成绩。60 分为开源合格锚点，90 分为商业联合锚点。**

## 规范性规则

### 适用与唯一维护源

本标准响应用户设定：18 个领域各选 3 个商业标杆构成 90 分锚点，各选 1 个开源标杆构成 60 分合格锚点。FHD/config/audit_benchmark_ssot.json 是规范数据唯一维护源；本文由脚本生成，不手工改写。此标准不授予任何项目既定分数。

### 如何解释“最好”

“本版商业 Top 3 / 首选开源”是针对 XCMAX 业务范围的标杆选择，不是公认全球排名。依次按场景适配、企业能力覆盖、可靠性/治理的公开证据、可测试性与可维护性选择；不按价格、星数、营销排名或品牌大小直接判分。每个条目的 role 与 scope_note 给出取舍。当前未付费部署或实测全部参考产品，不声称完成了全球竞品筛选。

### 90 与 60 的含义

90=达到本领域三个商业标杆经范围适配后的联合必选目标；60=达到首选开源标杆经范围适配后的必选基线。开源项目不是能力上限 60，满足商业级证据同样可以获 90；商业产品也可能不合格。不得把许可证类型直接计入质量分。

### 新旧分数隔离

本版 scoring_version=external-anchors-v1。旧报告 73.3、77.1 属于 internal-review-v1，禁止直接换算、沿用或混合平均；按新协议实际重评后才产生新分数。历史报告只作为缺陷输入，保持原文和原证据。

### 公平比较与必选目标

每次审计先冻结任务集、账号范围、并发量、数据量、平台、故障场景、预算、模型、版本和指标方向，再测试 XCMAX、开源参考及三个商业参考。三个 anchor_90 条目分别对应商业条目 1/2/3，全部为必选；不是挑其中最弱一家。与产品目的无关的能力可事前书面排除，但必须升标准版本，不能测后删项。

### 定量参照

成功率、延迟、成本、恢复时间等只采用同协议实测的参照值：60 使用固定开源版本；90 使用三个商业版本同口径样本的中位数，并同时满足本域联合能力和全部安全不变量。按指标方向判不劣，误差区间和容差在测试前登记；没有参照实测时，只能标“锚点已定义，数值未校准”，不得用厂商广告数值补齐。

### 五轴判分

结构/可演进性 25，契约/业务闭环 20，正确性与防错 20，验证与运行证据 25，文档维护 10。每轴按同一任务范围判为 0/30/60/75/90/100：已证失败或缺失/部分基线/完整开源基线/完整基线且部分商业目标/完整商业目标/事前登记指标上超过商业参照且其他必选无退步。领域分=sum(轴权重×轴等级)/100；18 领域等权，最后一步四舍五入到 1 位。

### 合格门槛与缺失证据

任一必选基线失败，领域最终分上限 59；未通过全部商业必选项，最高 89。已确认越权、跨租户泄露、重复扣款或不可恢复数据破坏直接不合格，不能被其他轴抵消。合格线必选证据或所声称等级所需证据未知/跳过/不可访问时，领域正式分为 null、状态 UNRATED；可另列已测项与证据覆盖率，不把未知填成零或通过。任一领域 UNRATED 时不出正式 18 域总分；任一领域低于 60 时整体合格状态为 false，即使平均超过 60。

### 采样与运行窗口下限

以下下限由本审计协议规定，不是厂商宣称或既有实测结果。普通任务每域至少 30 个预先冻结用例（含至少 10 个负向/恢复用例），每个用例重复 3 次；涉及并发至少覆盖 2 个独立 worker 和 20 个重复/竞争请求。AI 意图/编码/客服类至少 100 个独立留出任务并重复 3 次，记录模型版本与预算；不得用训练集作留出集。90 分的 E4 观察窗口至少连续 30 个自然日，期间所有采样缺失和故障均记录；现有生产自治更严格的 90 天等门槛继续适用，不因本标准降低。性能比较记录原始样本、分位数和置信区间，容差必须事前登记。

### 证据分级

E0=官方资料，只用于选择参考和定义能力；E1=源码/静态证据；E2=隔离单测/集成；E3=真实软件环境或真机的完整任务与故障恢复；E4=目标部署下持续运行/客户验收。60 至少有 E2 且核心用户任务达到 E3；90 还需参考产品同协议实测、目标平台 E3 和事前约定观察窗口的 E4。文档、绿 CI 或模拟 LLM 都不能替代 E3/E4。

### 闭源与同技术栈边界

闭源产品只审公开架构、可配置契约和实际可观察行为，不推定内部代码。商业支付服务不必用 Java；移动端历史 Flutter 案例不证明当前所有模块仍使用 Flutter；框架/平台/应用只在 scope_note 定义的交集比较。不能为了表面同技术栈牺牲任务可比性。

### 版本与来源

资料核对日期 2026-09-08。商业 SaaS 固定产品、套餐、区域、测试日期与可见版本；开源条目保存本次仓库源码 SHA 和许可证边界（不是声称该 SHA 为稳定发行）。正式实测选择受支持稳定版本并将确切 tag/SHA 写入审计记录；如改变锚点版本，更新本标准并保留差异。

### 变更治理

至少每 90 天或发生停服、重命名、许可证/套餐变化时复核标杆。替换参考、调整权重/必选项/阈值必须经同一个审计标准 PR，提升版本并记录原因，不得通过降低标准提高 XCMAX 分数。普通链接修复也保留核验日期。

### 真实交付与公开声称

源码评分、main 集成、构建产物、已安装身份、生产运行、客户效果分别报告。公开报告需列标准版本、源码 SHA、参考版本与套餐、证据级别、未知项及原始文件哈希；未完成对标实测不能宣称超过某商业产品、行业排名或第三方认证。

## 18 个领域标杆总表

商业列从左至右对应本域 C1/C2/C3 必选验收目标。名称和日期固定于本版，不代表全球公认排名。

| # | 领域 | 商业标杆 1 | 商业标杆 2 | 商业标杆 3 | 60 分首选开源 |
|---|---|---|---|---|---|
| 01 | 依赖注入与分层 | [SAP BTP](https://help.sap.com/docs/btp/sap-business-technology-platform/developing-applications-and-services) | [Mendix Platform](https://www.mendix.com/evaluation-guide/architecture/openness-extensibility/) | [OutSystems](https://www.outsystems.com/blog/posts/building-composable-architecture) | [Spring Framework](https://github.com/spring-projects/spring-framework) |
| 02 | ERP 订单与资金闭环 | [SAP S/4HANA Cloud Public Edition](https://www.sap.com/products/erp/s4hana.html) | [Oracle Fusion Cloud ERP](https://www.oracle.com/erp/) | [Microsoft Dynamics 365 Finance](https://www.microsoft.com/en-us/dynamics-365/products/finance) | [ERPNext](https://github.com/frappe/erpnext) |
| 03 | Agent 编排与审批 | [Microsoft Copilot Studio](https://www.microsoft.com/en-us/microsoft-365-copilot/microsoft-copilot-studio) | [Salesforce Agentforce](https://www.salesforce.com/agentforce/) | [UiPath Maestro](https://www.uipath.com/product/maestro) | [LangGraph OSS](https://github.com/langchain-ai/langgraph) |
| 04 | ETL 与业务文件处理 | [Informatica IDMC](https://www.informatica.com/platform.html) | [Qlik Talend Cloud](https://www.qlik.com/us/products/qlik-talend-cloud) | [Microsoft Fabric Data Factory](https://learn.microsoft.com/en-us/fabric/data-factory/data-factory-overview) | [Apache NiFi](https://github.com/apache/nifi) |
| 05 | AI 意图与工具路由 | [Google Dialogflow CX](https://docs.cloud.google.com/dialogflow/cx/docs) | [Amazon Lex V2](https://docs.aws.amazon.com/lexv2/latest/dg/what-is.html) | [IBM watsonx Orchestrate（助手能力）](https://www.ibm.com/products/watsonx-orchestrate) | [Rasa Open Source](https://github.com/RasaHQ/rasa) |
| 06 | NeuroBus 事件内核 | [Confluent Cloud](https://docs.confluent.io/cloud/current/overview.html) | [Solace Event Broker](https://solace.com/products/event-broker/) | [Amazon EventBridge](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html) | [Apache Kafka](https://github.com/apache/kafka) |
| 07 | Mod SDK 与行业模块 | [Salesforce Platform（官网现称 Headless 360）](https://www.salesforce.com/platform/) | [Atlassian Forge](https://developer.atlassian.com/platform/forge/) | [Shopify App Platform](https://help.shopify.com/en/partners/build-integrate/making-apps) | [Odoo Community](https://github.com/odoo/odoo) |
| 08 | 桌面壳与更新恢复 | [Microsoft Teams 桌面客户端](https://learn.microsoft.com/en-us/microsoftteams/teams-client-desktop-admin) | [Slack 桌面客户端](https://slack.com/help/articles/212475728-Deploy-Slack-for-Windows) | [JetBrains IntelliJ IDEA 商业订阅](https://www.jetbrains.com/help/idea/update.html) | [Code - OSS](https://github.com/microsoft/vscode) |
| 09 | FHD 前端与用户任务 | [SAP Fiori（商业 ERP 应用体验）](https://www.sap.com/products/technology-platform/fiori.html) | [Microsoft Dynamics 365 Business Central](https://www.microsoft.com/en-us/dynamics-365/products/business-central) | [Oracle NetSuite ERP](https://www.netsuite.com/portal/products/erp.shtml) | [ERPNext Desk](https://github.com/frappe/erpnext) |
| 10 | 商城前端与工作流 UI | [Shopify Admin](https://help.shopify.com/en/manual/shopify-admin) | [Salesforce AgentExchange（原 AppExchange）](https://www.salesforce.com/eu/solutions/appexchange/apps/) | [Atlassian Marketplace](https://developer.atlassian.com/platform/marketplace/) | [Saleor Dashboard](https://github.com/saleor/saleor-dashboard) |
| 11 | 商城交易与交付后端 | [Shopify Plus](https://www.shopify.com/plus) | [Adobe Commerce](https://business.adobe.com/products/magento/magento-commerce.html) | [commercetools Composable Commerce](https://commercetools.com/composable-commerce) | [Saleor Core](https://github.com/saleor/saleor) |
| 12 | 自治与维护执行 | [ServiceNow ITOM](https://www.servicenow.com/products/it-operations-management.html) | [PagerDuty Runbook Automation](https://www.pagerduty.com/platform/automation/runbook/) | [UiPath Automation Cloud](https://www.uipath.com/product/automation-cloud) | [Rundeck Community](https://github.com/rundeck/rundeck) |
| 13 | Java 支付服务 | [Stripe Payments](https://docs.stripe.com/payments) | [Adyen](https://docs.adyen.com/) | [PayPal Braintree](https://developer.paypal.com/braintree/docs/) | [Kill Bill](https://github.com/killbill/killbill) |
| 14 | Flutter 移动端 | [My BMW App](https://flutter.dev/showcase/bmw) | [Nubank 移动应用](https://flutter.dev/showcase/nubank) | [eBay Motors](https://flutter.dev/showcase/ebay) | [AppFlowy（开源 Flutter 客户端）](https://github.com/AppFlowy-IO/AppFlowy) |
| 15 | Retort 共享引擎 | [Temporal Cloud](https://docs.temporal.io/cloud) | [Camunda 8 SaaS](https://docs.camunda.io/docs/components/saas/) | [AWS Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html) | [Temporal OSS](https://github.com/temporalio/temporal) |
| 16 | Vibe 编码与沙箱 | [GitHub Copilot Enterprise](https://docs.github.com/en/copilot) | [Cursor Enterprise](https://cursor.com/enterprise) | [Replit Agent](https://docs.replit.com/features/agent/overview) | [OpenHands OSS](https://github.com/OpenHands/OpenHands) |
| 17 | 客来来独立子系统 | [Zendesk Suite](https://support.zendesk.com/hc/en-us/articles/4408838041370-Welcome-to-the-Zendesk-Suite) | [Intercom / Fin](https://fin.ai/) | [Salesforce Service Cloud](https://www.salesforce.com/service/) | [Chatwoot Community](https://github.com/chatwoot/chatwoot) |
| 18 | CI、发布与治理 | [GitHub Enterprise Cloud](https://github.com/enterprise) | [GitLab Ultimate](https://about.gitlab.com/pricing/) | [Harness CI/CD](https://www.harness.io/products/continuous-integration) | [Jenkins](https://github.com/jenkinsci/jenkins) |

## 逐领域范围与验收协议

以下 B/C 条目是 XCMAX 审计的规范性测试要求；官方来源支持参考选择，不表示已在这些厂商产品上跑过相同测试。每域同时应用五轴与统一实验协议。

### 01 依赖注入与分层 (`architecture`)

XCMAX 范围：`FHD/app/di/`。

闭源平台比较公开架构和扩展契约；不猜测内部 DI 实现，也不要求使用同一种语言。

**90 分商业参照与取舍：**

- [SAP BTP](https://help.sap.com/docs/btp/sap-business-technology-platform/developing-applications-and-services)：应用与服务的边界、扩展和生命周期。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Mendix Platform](https://www.mendix.com/evaluation-guide/architecture/openness-extensibility/)：可替换扩展、API 与工程工具集成。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [OutSystems](https://www.outsystems.com/blog/posts/building-composable-architecture)：可组合应用和复用模块。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Spring Framework](https://github.com/spring-projects/spring-framework)**。许可证 `Apache-2.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`572850bdcf125bdc306f30fd74709897540bf62b`](https://github.com/spring-projects/spring-framework/tree/572850bdcf125bdc306f30fd74709897540bf62b)；[许可证元数据](https://api.github.com/repos/spring-projects/spring-framework/license?ref=572850bdcf125bdc306f30fd74709897540bf62b)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `architecture-B1`：明确组合根与生命周期，替换适配器无需修改业务核心。
- `architecture-B2`：领域边界和接口契约可自动验证。
- `architecture-B3`：依赖初始化、并发访问和释放失败可定位。

**C：90 分追加必选目标**

- `architecture-C1`（参照 SAP BTP）：建立可独立演进的应用/服务边界并验证兼容升级。
- `architecture-C2`（参照 Mendix Platform）：扩展接口在替换实现、版本升级和故障时保持兼容。
- `architecture-C3`（参照 OutSystems）：跨业务复用组件保持单向依赖，变更影响面可量化。

### 02 ERP 订单与资金闭环 (`erp`)

XCMAX 范围：`FHD/app/application/`。

只比较 XCMAX 已声明业务范围；不把全球税务、本地化数量或客户规模当作已测能力。

**90 分商业参照与取舍：**

- [SAP S/4HANA Cloud Public Edition](https://www.sap.com/products/erp/s4hana.html)：订单、采购、库存与财务的一体化流程。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Oracle Fusion Cloud ERP](https://www.oracle.com/erp/)：财务与跨业务域 ERP 闭环。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Microsoft Dynamics 365 Finance](https://www.microsoft.com/en-us/dynamics-365/products/finance)：财务操作、分析与业务控制。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[ERPNext](https://github.com/frappe/erpnext)**。许可证 `GPL-3.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`e0d6d797d7086b214f74bf29e2ffbd75894e7b74`](https://github.com/frappe/erpnext/tree/e0d6d797d7086b214f74bf29e2ffbd75894e7b74)；[许可证元数据](https://api.github.com/repos/frappe/erpnext/license?ref=e0d6d797d7086b214f74bf29e2ffbd75894e7b74)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `erp-B1`：订单、库存、应收与收付款在同一任务中保持一致。
- `erp-B2`：多租户、金额精度、退款/撤销有明确业务约束。
- `erp-B3`：对重复请求、部分失败和导出账表做回归。

**C：90 分追加必选目标**

- `erp-C1`（参照 SAP S/4HANA Cloud Public Edition）：验证订单到收款与采购到付款跨模块完整流程。
- `erp-C2`（参照 Oracle Fusion Cloud ERP）：跨组织、币种和期间的对账与异常处理有可复核证据。
- `erp-C3`（参照 Microsoft Dynamics 365 Finance）：角色职责分离、审批与审计可追到实际账务结果。

### 03 Agent 编排与审批 (`agent-orchestration`)

XCMAX 范围：`FHD/app/application/agent_orchestrator/`。

LangGraph OSS 与付费平台能力分开；真实模型和跨 worker 场景必须另验。

**90 分商业参照与取舍：**

- [Microsoft Copilot Studio](https://www.microsoft.com/en-us/microsoft-365-copilot/microsoft-copilot-studio)：企业 Agent 创建与动作编排。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Salesforce Agentforce](https://www.salesforce.com/agentforce/)：业务上下文、权限与企业 Agent。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [UiPath Maestro](https://www.uipath.com/product/maestro)：人、Agent 和自动化流程的编排。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[LangGraph OSS](https://github.com/langchain-ai/langgraph)**。许可证 `MIT`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1`](https://github.com/langchain-ai/langgraph/tree/81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1)；[许可证元数据](https://api.github.com/repos/langchain-ai/langgraph/license?ref=81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `agent-orchestration-B1`：任务/步骤状态持久化，暂停后可恢复。
- `agent-orchestration-B2`：工具输入校验、权限和人工审批绑定实际动作。
- `agent-orchestration-B3`：超时、重试、取消及恢复不重复产生副作用。

**C：90 分追加必选目标**

- `agent-orchestration-C1`（参照 Microsoft Copilot Studio）：多步骤 Agent 在配置、版本切换和工具故障后可靠恢复。
- `agent-orchestration-C2`（参照 Salesforce Agentforce）：主体、数据权限与动作授权贯穿每个工具调用。
- `agent-orchestration-C3`（参照 UiPath Maestro）：人、Agent 与确定性流程协作有端到端执行回执。

### 04 ETL 与业务文件处理 (`etl`)

XCMAX 范围：`FHD/app/application/etl/`。

NiFi 的数据流能力不直接等同于 ERP 撤销；撤销与业务关联是 XCMAX 额外必选约束。

**90 分商业参照与取舍：**

- [Informatica IDMC](https://www.informatica.com/platform.html)：数据集成、质量与治理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Qlik Talend Cloud](https://www.qlik.com/us/products/qlik-talend-cloud)：数据集成和数据质量。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Microsoft Fabric Data Factory](https://learn.microsoft.com/en-us/fabric/data-factory/data-factory-overview)：数据管道、连接与转换。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Apache NiFi](https://github.com/apache/nifi)**。许可证 `Apache-2.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`7d29d839c9d956e4530adb570e42c8c6833a5bfb`](https://github.com/apache/nifi/tree/7d29d839c9d956e4530adb570e42c8c6833a5bfb)；[许可证元数据](https://api.github.com/repos/apache/nifi/license?ref=7d29d839c9d956e4530adb570e42c8c6833a5bfb)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `etl-B1`：输入校验、字段映射、预览和错误定位可复现。
- `etl-B2`：可追踪处理来源并安全重试，不覆盖后续人工编辑。
- `etl-B3`：客户/产品关联、租户隔离与输出文件一致。

**C：90 分追加必选目标**

- `etl-C1`（参照 Informatica IDMC）：从连接、转换到质量规则的全链路来源与影响分析可查。
- `etl-C2`（参照 Qlik Talend Cloud）：脏数据、重复、漂移和冲突有治理、隔离与纠正流程。
- `etl-C3`（参照 Microsoft Fabric Data Factory）：调度、增量处理和故障恢复在同等任务下通过压力验证。

### 05 AI 意图与工具路由 (`intent-routing`)

XCMAX 范围：`FHD/app/application/chat_business_safety_core.py`。

采用 Rasa OSS 3.6 系列代码快照，不把 Rasa Pro 算作开源；模型自报置信度不等于准确率。

**90 分商业参照与取舍：**

- [Google Dialogflow CX](https://docs.cloud.google.com/dialogflow/cx/docs)：多轮对话、流程、实体及测试。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Amazon Lex V2](https://docs.aws.amazon.com/lexv2/latest/dg/what-is.html)：意图、槽位与业务函数履行。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [IBM watsonx Orchestrate（助手能力）](https://www.ibm.com/products/watsonx-orchestrate)：企业对话助手与工具协作；原 assistant 产品页重定向至此。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Rasa Open Source](https://github.com/RasaHQ/rasa)**。许可证 `Apache-2.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`60a3cff9c08183760355b07bd60f5223d8916d6b`](https://github.com/RasaHQ/rasa/tree/60a3cff9c08183760355b07bd60f5223d8916d6b)；[许可证元数据](https://api.github.com/repos/RasaHQ/rasa/license?ref=60a3cff9c08183760355b07bd60f5223d8916d6b)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `intent-routing-B1`：固定中文跨域意图集，统计混淆矩阵和误触发。
- `intent-routing-B2`：槽位校验、歧义澄清与拒绝执行有稳定行为。
- `intent-routing-B3`：规则/模型回退不绕过动作白名单与审批。

**C：90 分追加必选目标**

- `intent-routing-C1`（参照 Google Dialogflow CX）：多轮、未知意图和上下文切换在独立留出集稳定。
- `intent-routing-C2`（参照 Amazon Lex V2）：槽位和业务履行正确率与延迟在同协议下达到参考水平。
- `intent-routing-C3`（参照 IBM watsonx Orchestrate（助手能力））：对话、企业工具与权限协作有真实模型多次试验。

### 06 NeuroBus 事件内核 (`event-kernel`)

XCMAX 范围：`FHD/app/neuro_bus/`。

Kafka 是持久事件流基线，内存总线不直接按吞吐对比；先对齐持久化和确认语义。

**90 分商业参照与取舍：**

- [Confluent Cloud](https://docs.confluent.io/cloud/current/overview.html)：托管事件流、连接与治理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Solace Event Broker](https://solace.com/products/event-broker/)：企业事件路由与事件网格。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Amazon EventBridge](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)：事件总线、目标路由与集成。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Apache Kafka](https://github.com/apache/kafka)**。许可证 `Apache-2.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`a6d66b7403389bc77ac00651c2fead6fee141b04`](https://github.com/apache/kafka/tree/a6d66b7403389bc77ac00651c2fead6fee141b04)；[许可证元数据](https://api.github.com/repos/apache/kafka/license?ref=a6d66b7403389bc77ac00651c2fead6fee141b04)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `event-kernel-B1`：事件契约与顺序/投递语义明确且测试覆盖。
- `event-kernel-B2`：重复投递、消费失败、积压与死信有处理。
- `event-kernel-B3`：进程重启后可恢复，有丢失和延迟观测。

**C：90 分追加必选目标**

- `event-kernel-C1`（参照 Confluent Cloud）：契约演进、隔离与事件治理在多服务下可操作。
- `event-kernel-C2`（参照 Solace Event Broker）：跨服务路由和故障隔离经过网络分区/恢复验证。
- `event-kernel-C3`（参照 Amazon EventBridge）：路由目标重试、重放与交付状态可追溯。

### 07 Mod SDK 与行业模块 (`mod-sdk`)

XCMAX 范围：`FHD/app/mod_sdk/`。

只取 Odoo Community LGPL 范围，不纳入 Enterprise；签名和账号交付是 XCMAX 必选要求。

**90 分商业参照与取舍：**

- [Salesforce Platform（官网现称 Headless 360）](https://www.salesforce.com/platform/)：平台扩展、组织数据和可管理的应用能力。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Atlassian Forge](https://developer.atlassian.com/platform/forge/)：应用运行环境与平台权限。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Shopify App Platform](https://help.shopify.com/en/partners/build-integrate/making-apps)：应用开发、安装分发和商业化。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Odoo Community](https://github.com/odoo/odoo)**。许可证 `LGPL-3.0`；Odoo Community LGPLv3；不含 Enterprise，捆绑第三方许可证另核。

固定源码快照：[`a51ca77c825d2dba326dd540e2b4c04ef6c2385d`](https://github.com/odoo/odoo/tree/a51ca77c825d2dba326dd540e2b4c04ef6c2385d)；[许可证元数据](https://api.github.com/repos/odoo/odoo/license?ref=a51ca77c825d2dba326dd540e2b4c04ef6c2385d)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `mod-sdk-B1`：模块清单、依赖、生命周期和卸载边界稳定。
- `mod-sdk-B2`：共享宿主下各账号只加载其授权模块和数据。
- `mod-sdk-B3`：升级保留模块配置，并可查看运行版本。

**C：90 分追加必选目标**

- `mod-sdk-C1`（参照 Salesforce Platform（官网现称 Headless 360））：平台版本与扩展版本独立演进，组织权限完整。
- `mod-sdk-C2`（参照 Atlassian Forge）：扩展权限、运行隔离与平台接口变更可验证。
- `mod-sdk-C3`（参照 Shopify App Platform）：从开发、签名、授权到客户安装升级形成交付回执。

### 08 桌面壳与更新恢复 (`desktop`)

XCMAX 范围：`FHD/desktop/`。

Code - OSS 为 MIT 源码，不包括 Microsoft VS Code 专有发行、市场服务；不比较聊天或 IDE 功能。

**90 分商业参照与取舍：**

- [Microsoft Teams 桌面客户端](https://learn.microsoft.com/en-us/microsoftteams/teams-client-desktop-admin)：企业安装、跨平台部署与更新管理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Slack 桌面客户端](https://slack.com/help/articles/212475728-Deploy-Slack-for-Windows)：企业部署、更新和用户数据迁移。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [JetBrains IntelliJ IDEA 商业订阅](https://www.jetbrains.com/help/idea/update.html)：桌面版本更新与维护；不比较 IDE 功能。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Code - OSS](https://github.com/microsoft/vscode)**。许可证 `MIT`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`4603a7f7b9102fb602967c9518ac60acddd735a6`](https://github.com/microsoft/vscode/tree/4603a7f7b9102fb602967c9518ac60acddd735a6)；[许可证元数据](https://api.github.com/repos/microsoft/vscode/license?ref=4603a7f7b9102fb602967c9518ac60acddd735a6)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `desktop-B1`：桌面安装、启动、升级和卸载可重复。
- `desktop-B2`：进程、IPC、凭据与本地数据边界受控。
- `desktop-B3`：更新失败保留数据并给出可操作恢复入口。

**C：90 分追加必选目标**

- `desktop-C1`（参照 Microsoft Teams 桌面客户端）：Windows/macOS 管理部署、更新状态与诊断可查。
- `desktop-C2`（参照 Slack 桌面客户端）：安装方式/旧数据迁移和批量更新在目标设备验证。
- `desktop-C3`（参照 JetBrains IntelliJ IDEA 商业订阅）：版本更新及恢复有确切 artifact、运行身份和回归证据。

### 09 FHD 前端与用户任务 (`business-frontend`)

XCMAX 范围：`FHD/frontend/`。

比较完整任务与交互，不按页面数、UI 框架或截图美观度直接给分。

**90 分商业参照与取舍：**

- [SAP Fiori（商业 ERP 应用体验）](https://www.sap.com/products/technology-platform/fiori.html)：角色与任务导向的企业操作界面。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Microsoft Dynamics 365 Business Central](https://www.microsoft.com/en-us/dynamics-365/products/business-central)：中小企业 ERP 的日常操作流程。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Oracle NetSuite ERP](https://www.netsuite.com/portal/products/erp.shtml)：统一 ERP 工作台与业务可见性。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[ERPNext Desk](https://github.com/frappe/erpnext)**。许可证 `GPL-3.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`e0d6d797d7086b214f74bf29e2ffbd75894e7b74`](https://github.com/frappe/erpnext/tree/e0d6d797d7086b214f74bf29e2ffbd75894e7b74)；[许可证元数据](https://api.github.com/repos/frappe/erpnext/license?ref=e0d6d797d7086b214f74bf29e2ffbd75894e7b74)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `business-frontend-B1`：登录后能完成核心业务任务，输入校验和空状态清晰。
- `business-frontend-B2`：加载、失败、健康和结果状态来自真实服务。
- `business-frontend-B3`：筛选、编辑、导入与导出语义保持一致。

**C：90 分追加必选目标**

- `business-frontend-C1`（参照 SAP Fiori（商业 ERP 应用体验））：角色导向任务流、可访问性和跨页面状态一致。
- `business-frontend-C2`（参照 Microsoft Dynamics 365 Business Central）：真实企业用户在日常 ERP 流程中完成任务并可恢复错误。
- `business-frontend-C3`（参照 Oracle NetSuite ERP）：跨模块工作台可追踪业务结果与异常，而非只有统计卡片。

### 10 商城前端与工作流 UI (`marketplace-ui`)

XCMAX 范围：`成都修茈科技有限公司/MODstore_deploy/market/`。

Saleor Dashboard 仅是管理 UI 能力基线；插件授权和运行回执需加 XCMAX 适配测试。

**90 分商业参照与取舍：**

- [Shopify Admin](https://help.shopify.com/en/manual/shopify-admin)：商品、订单与后台操作体验。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Salesforce AgentExchange（原 AppExchange）](https://www.salesforce.com/eu/solutions/appexchange/apps/)：企业应用发现、安装与管理；原页面现提示品牌迁移。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Atlassian Marketplace](https://developer.atlassian.com/platform/marketplace/)：应用目录、开发者分发与市场管理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Saleor Dashboard](https://github.com/saleor/saleor-dashboard)**。许可证 `BSD-3-Clause`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`66d28330ed0ad22a4c307049e69ed9c49ffc85cf`](https://github.com/saleor/saleor-dashboard/tree/66d28330ed0ad22a4c307049e69ed9c49ffc85cf)；[许可证元数据](https://api.github.com/repos/saleor/saleor-dashboard/license?ref=66d28330ed0ad22a4c307049e69ed9c49ffc85cf)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `marketplace-ui-B1`：目录、搜索、订单/授权和后台状态一致。
- `marketplace-ui-B2`：权限不足、付款失败和交付等待均可解释。
- `marketplace-ui-B3`：用户操作可以追到实际授权与运行版本。

**C：90 分追加必选目标**

- `marketplace-ui-C1`（参照 Shopify Admin）：后台商品/订单操作在复杂状态下可用且一致。
- `marketplace-ui-C2`（参照 Salesforce AgentExchange（原 AppExchange））：应用发现、授权安装和组织管理流程可实际完成。
- `marketplace-ui-C3`（参照 Atlassian Marketplace）：开发者上架、版本与用户管理有连续可验证体验。

### 11 商城交易与交付后端 (`commerce-backend`)

XCMAX 范围：`成都修茈科技有限公司/MODstore_deploy/modstore_server/`。

实体商品交易与数字 Mod 授权不同；映射订单到授权交付，不假设参考平台自带 Mod 签名。

**90 分商业参照与取舍：**

- [Shopify Plus](https://www.shopify.com/plus)：企业交易、订单与可扩展商业平台。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Adobe Commerce](https://business.adobe.com/products/magento/magento-commerce.html)：企业电商交易与业务管理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [commercetools Composable Commerce](https://commercetools.com/composable-commerce)：API 化、可组合的商业后端。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Saleor Core](https://github.com/saleor/saleor)**。许可证 `BSD-3-Clause`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`75226b584dee0150e35f0a8f573c5f4063d7e341`](https://github.com/saleor/saleor/tree/75226b584dee0150e35f0a8f573c5f4063d7e341)；[许可证元数据](https://api.github.com/repos/saleor/saleor/license?ref=75226b584dee0150e35f0a8f573c5f4063d7e341)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `commerce-backend-B1`：订单、价格、付款状态与交付事务保持一致。
- `commerce-backend-B2`：幂等请求、Webhook 重放和退款不产生重复效果。
- `commerce-backend-B3`：账号隔离、库存/授权变更与审计可追溯。

**C：90 分追加必选目标**

- `commerce-backend-C1`（参照 Shopify Plus）：交易高峰与支付故障下订单和交付仍一致。
- `commerce-backend-C2`（参照 Adobe Commerce）：复杂业务规则、退款与多组织管理可复核。
- `commerce-backend-C3`（参照 commercetools Composable Commerce）：API 契约和独立业务组件支持安全演进与恢复。

### 12 自治与维护执行 (`autonomy`)

XCMAX 范围：`成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_subprocess.py`。

Rundeck 开源部分和 PagerDuty 商业产品区分；生产自主写入仍受现有自治风险门槛约束。

**90 分商业参照与取舍：**

- [ServiceNow ITOM](https://www.servicenow.com/products/it-operations-management.html)：运维事件、服务可见性和自动化。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [PagerDuty Runbook Automation](https://www.pagerduty.com/platform/automation/runbook/)：受控运行手册和运维任务执行。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [UiPath Automation Cloud](https://www.uipath.com/product/automation-cloud)：自动化任务管理与企业运行平台。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Rundeck Community](https://github.com/rundeck/rundeck)**。许可证 `Apache-2.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`1b944fd3ab24b2cedbe96de8e3cb3847113cd01e`](https://github.com/rundeck/rundeck/tree/1b944fd3ab24b2cedbe96de8e3cb3847113cd01e)；[许可证元数据](https://api.github.com/repos/rundeck/rundeck/license?ref=1b944fd3ab24b2cedbe96de8e3cb3847113cd01e)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `autonomy-B1`：运维动作有白名单、执行权限、时间与资源上限。
- `autonomy-B2`：真实子进程超时、截断和取消可回收后代进程。
- `autonomy-B3`：任务记录、重试、审批与人工接管可追溯。

**C：90 分追加必选目标**

- `autonomy-C1`（参照 ServiceNow ITOM）：告警到诊断、处理和服务恢复有因果证据。
- `autonomy-C2`（参照 PagerDuty Runbook Automation）：受限运行手册可跨节点执行并控制凭据、审批与审计。
- `autonomy-C3`（参照 UiPath Automation Cloud）：任务队列、运行容量、失败恢复和持续运行效果可核验。

### 13 Java 支付服务 (`java-payment`)

XCMAX 范围：`成都修茈科技有限公司/MODstore_deploy/java_payment_service/`。

按支付业务协议比较；不声称 Stripe/Adyen/Braintree 的内部服务用 Java，也不要求复制收单牌照业务。

**90 分商业参照与取舍：**

- [Stripe Payments](https://docs.stripe.com/payments)：支付状态、集成与支付业务协议。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Adyen](https://docs.adyen.com/)：支付接口与渠道集成。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [PayPal Braintree](https://developer.paypal.com/braintree/docs/)：支付集成、服务端 SDK 与交易流程。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Kill Bill](https://github.com/killbill/killbill)**。许可证 `Apache-2.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`cb60779c171391be558cd7aebb1eafea60ad2b82`](https://github.com/killbill/killbill/tree/cb60779c171391be558cd7aebb1eafea60ad2b82)；[许可证元数据](https://api.github.com/repos/killbill/killbill/license?ref=cb60779c171391be558cd7aebb1eafea60ad2b82)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `java-payment-B1`：金额精度、币种、支付状态机和幂等键正确。
- `java-payment-B2`：回调验签、重放、退款和对账在沙箱通过。
- `java-payment-B3`：凭据隔离、事务并发和异常恢复可复核。

**C：90 分追加必选目标**

- `java-payment-C1`（参照 Stripe Payments）：支付意图/交易生命周期、重试和退款形成一致账务。
- `java-payment-C2`（参照 Adyen）：渠道异常、异步通知与对账差异可完整定位处理。
- `java-payment-C3`（参照 PayPal Braintree）：服务端 SDK 与支付业务流程有跨版本和异常验收。

### 14 Flutter 移动端 (`flutter-mobile`)

XCMAX 范围：`FHD/mobile-flutter-poc/`。

三个商业引用是历史 Flutter 官方案例，未实测其当前版本；AppFlowy 只映射客户端/同步，不映射金融或车辆业务。

**90 分商业参照与取舍：**

- [My BMW App](https://flutter.dev/showcase/bmw)：Flutter 跨平台一致性及多变体交付的历史官方案例。来源类型 `historical_official_case_study`；核对 2026-09-08；尚未实测。
- [Nubank 移动应用](https://flutter.dev/showcase/nubank)：Flutter 工程规模化与跨端一致性的历史官方案例。来源类型 `historical_official_case_study`；核对 2026-09-08；尚未实测。
- [eBay Motors](https://flutter.dev/showcase/ebay)：Flutter 商业移动应用的历史官方案例。来源类型 `historical_official_case_study`；核对 2026-09-08；尚未实测。

**60 分首选开源：[AppFlowy（开源 Flutter 客户端）](https://github.com/AppFlowy-IO/AppFlowy)**。许可证 `AGPL-3.0`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`5cf3a365dec0d59f64bad1ee4bb1050471a39b93`](https://github.com/AppFlowy-IO/AppFlowy/tree/5cf3a365dec0d59f64bad1ee4bb1050471a39b93)；[许可证元数据](https://api.github.com/repos/AppFlowy-IO/AppFlowy/license?ref=5cf3a365dec0d59f64bad1ee4bb1050471a39b93)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `flutter-mobile-B1`：固定 Flutter 版本构建 iOS/Android，真机核心任务一致。
- `flutter-mobile-B2`：凭据、后台切换、断网和恢复不丢状态。
- `flutter-mobile-B3`：跨设备布局与同步冲突有可复核测试。

**C：90 分追加必选目标**

- `flutter-mobile-C1`（参照 My BMW App）：跨系统、设备和发布变体的一致性与构建链可证实。
- `flutter-mobile-C2`（参照 Nubank 移动应用）：特性扩展、测试与团队交付效率有量化证据。
- `flutter-mobile-C3`（参照 eBay Motors）：商业核心任务在真实设备上具备稳定体验和性能。

### 15 Retort 共享引擎 (`shared-engine`)

XCMAX 范围：`packages/retort_engine/`。

映射 Retort 的执行/恢复/证据底座；这些产品不是 Retort 吸收算法的直接竞品，能力吸收真实性仍单独验证。

**90 分商业参照与取舍：**

- [Temporal Cloud](https://docs.temporal.io/cloud)：持久工作流、执行历史与恢复。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Camunda 8 SaaS](https://docs.camunda.io/docs/components/saas/)：流程执行、运营与管理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [AWS Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)：状态机、重试和工作流执行。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Temporal OSS](https://github.com/temporalio/temporal)**。许可证 `MIT`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`990081baf768f664f98f734e3599f4c718895151`](https://github.com/temporalio/temporal/tree/990081baf768f664f98f734e3599f4c718895151)；[许可证元数据](https://api.github.com/repos/temporalio/temporal/license?ref=990081baf768f664f98f734e3599f4c718895151)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `shared-engine-B1`：共享执行协议、状态持久化和插件接口稳定。
- `shared-engine-B2`：重放、超时与恢复不虚报完成或重做副作用。
- `shared-engine-B3`：执行证据与输入、版本、产物哈希绑定。

**C：90 分追加必选目标**

- `shared-engine-C1`（参照 Temporal Cloud）：长期执行、版本演进和历史恢复可证明。
- `shared-engine-C2`（参照 Camunda 8 SaaS）：流程运行与运维可观察，异常可人工处置。
- `shared-engine-C3`（参照 AWS Step Functions）：状态机的重试、补偿与失败状态可复现。

### 16 Vibe 编码与沙箱 (`coding-sandbox`)

XCMAX 范围：`成都修茈科技有限公司/vibe-coding/`。

只取开源授权部分；禁止用模型自评分、演示视频或同实现镜像测试替代任务结果。

**90 分商业参照与取舍：**

- [GitHub Copilot Enterprise](https://docs.github.com/en/copilot)：编码辅助、Agent 和企业管理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Cursor Enterprise](https://cursor.com/enterprise)：代码上下文、Agent 工作流与企业控制。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Replit Agent](https://docs.replit.com/features/agent/overview)：应用生成、执行与迭代。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[OpenHands OSS](https://github.com/OpenHands/OpenHands)**。许可证 `MIT`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`f7fb0c4b21f5ed726edbba8a6309634ef434b004`](https://github.com/OpenHands/OpenHands/tree/f7fb0c4b21f5ed726edbba8a6309634ef434b004)；[许可证元数据](https://api.github.com/repos/OpenHands/OpenHands/license?ref=f7fb0c4b21f5ed726edbba8a6309634ef434b004)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `coding-sandbox-B1`：生成补丁可审查、测试和撤销。
- `coding-sandbox-B2`：文件/命令/网络权限受控，阻断逃逸与秘密泄露。
- `coding-sandbox-B3`：真实编码任务以测试和可运行产物判成败。

**C：90 分追加必选目标**

- `coding-sandbox-C1`（参照 GitHub Copilot Enterprise）：仓库上下文、代码修改和企业策略在同一任务中验证。
- `coding-sandbox-C2`（参照 Cursor Enterprise）：多文件 Agent 修改质量与沙箱策略有留出任务评测。
- `coding-sandbox-C3`（参照 Replit Agent）：从需求到运行产物的迭代有检查点、恢复与人工控制。

### 17 客来来独立子系统 (`customer-service`)

XCMAX 范围：`成都修茈科技有限公司/MODstore_deploy/market/src/domain/客来来/`。

Chatwoot 仅取非 enterprise/ 的 MIT 核心；真实发送须另获业务授权，本任务只定义协议。

**90 分商业参照与取舍：**

- [Zendesk Suite](https://support.zendesk.com/hc/en-us/articles/4408838041370-Welcome-to-the-Zendesk-Suite)：多渠道客服、知识与工单。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Intercom / Fin](https://fin.ai/)：客服 Agent、知识回答与业务处理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Salesforce Service Cloud](https://www.salesforce.com/service/)：客服流程、客户上下文与企业服务。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Chatwoot Community](https://github.com/chatwoot/chatwoot)**。许可证 `MIT`；仅非 enterprise/ 的 MIT 核心；enterprise/LICENSE 另行授权。

固定源码快照：[`b227f8042738a124fea7bf65ac413e4dc9c8196a`](https://github.com/chatwoot/chatwoot/tree/b227f8042738a124fea7bf65ac413e4dc9c8196a)；[许可证元数据](https://api.github.com/repos/chatwoot/chatwoot/license?ref=b227f8042738a124fea7bf65ac413e4dc9c8196a)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `customer-service-B1`：客户、会话、工单/线索归属按账号隔离。
- `customer-service-B2`：多渠道接入与人工交接保留上下文。
- `customer-service-B3`：发送状态和失败重试以渠道回执为准。

**C：90 分追加必选目标**

- `customer-service-C1`（参照 Zendesk Suite）：跨渠道工单、知识和服务指标有完整客户流程。
- `customer-service-C2`（参照 Intercom / Fin）：Agent 回答、执行和人工接管有真实结果评估。
- `customer-service-C3`（参照 Salesforce Service Cloud）：服务流程、客户信息与权限联动可追踪。

### 18 CI、发布与治理 (`ci-release`)

XCMAX 范围：`FHD/scripts/`。

Jenkins 插件版本与许可证单独锁定；不以 CI 项目数、绿灯数量或历史覆盖率作为当前质量。

**90 分商业参照与取舍：**

- [GitHub Enterprise Cloud](https://github.com/enterprise)：代码协作、自动化、安全与治理。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [GitLab Ultimate](https://about.gitlab.com/pricing/)：企业软件交付、安全和治理能力组合。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。
- [Harness CI/CD](https://www.harness.io/products/continuous-integration)：可复用交付流水线与企业 CI。来源类型 `official_product_or_documentation`；核对 2026-09-08；尚未实测。

**60 分首选开源：[Jenkins](https://github.com/jenkinsci/jenkins)**。许可证 `MIT`；仅仓库开源核心，第三方组件按各自许可证；付费企业目录/服务不纳入 60 分参考。

固定源码快照：[`2701fc6c4e75540703fd68205d9f2e87189a6d71`](https://github.com/jenkinsci/jenkins/tree/2701fc6c4e75540703fd68205d9f2e87189a6d71)；[许可证元数据](https://api.github.com/repos/jenkinsci/jenkins/license?ref=2701fc6c4e75540703fd68205d9f2e87189a6d71)。该 SHA 为选标时源码快照，不自动等于正式实测版本。

**B：60 分必选基线**

- `ci-release-B1`：流水线可从固定源码与锁文件重建产物。
- `ci-release-B2`：失败检查真实拦截，测试/覆盖率/报告与 SHA 一致。
- `ci-release-B3`：凭据、权限和部署操作有最小权限与审计。

**C：90 分追加必选目标**

- `ci-release-C1`（参照 GitHub Enterprise Cloud）：代码、安全检查、artifact 和发布身份形成完整链路。
- `ci-release-C2`（参照 GitLab Ultimate）：质量/安全/审批政策覆盖实际变更并有负向用例。
- `ci-release-C3`（参照 Harness CI/CD）：可复用流水线、部署验证和失败恢复在目标环境验收。

## 统一实验与审计记录

- 正常业务任务与预期账/文件/状态核对。
- 账号切换与跨租户负向验证。
- 并发重复请求、超时、断网和进程重启。
- 坏输入、版本升级和恢复/补偿。
- 测试/门禁负向样例，确认错误确实被拦截。

以下字段必须随每次审计保存；不适用项写明原因，未知项不能填假值：

```json
{
  "standard_version": null,
  "scoring_version": null,
  "source_sha": null,
  "main_sha": null,
  "artifact_sha256": null,
  "installed_git_sha": null,
  "reference_versions_editions_regions": null,
  "dataset_hash": null,
  "task_protocol": null,
  "predeclared_metrics_and_tolerances": null,
  "model_and_budget": null,
  "environment": null,
  "evidence_ids": null,
  "observed_results": null,
  "unknowns": null,
  "axis_levels": null,
  "domain_status": null,
  "score": null,
  "auditor": null,
  "observed_at": null
}
```

数值分、合格状态、证据等级与交付状态分列。开源参考许可证只限定参考范围，不决定 XCMAX 源码许可证；复用代码另走仓库许可证流程。

## 本地检查

在 `FHD/` 运行：

```bash
python scripts/dev/audit_benchmark_ssot.py check
python scripts/dev/ssot_cli.py check audit-benchmark
```

该检查只校验标准结构、引用数量和生成文档是否漂移；通过不表示业务通过 60/90 分验收。
