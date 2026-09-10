# R22 外部标杆实测：Java 支付服务域开源锚点（Kill Bill）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Kill Bill 0.24.12（killbill/killbill:0.24.12 官方镜像，内嵌 H2，Apache-2.0），本地 Docker 端口 18082；SSOT 锁定 source_commit=cb60779c171391be558cd7aebb1eafea60ad2b82 |
| dataset_hash | 任务脚本随本文档存档（java-payment-killbill-tasks-20260910.sh） |
| task_protocol | B1 金额精度/币种/支付状态机/幂等键；B2 退款一致/重放/对账净额；B3 凭据隔离/事务并发/异常可定位 |
| predeclared_metrics_and_tolerances | 金额 10.05 精确回显（numeric 无损）；同 paymentExternalKey 重复提交被拒（精确）；退款后 purchased−refunded=0.00（精确）；同 transactionExternalKey 重放退款被拒（精确）；10 并发支付全部 201 且总数=11（精确）；无凭据/错 secret 一律 401（精确） |
| environment | 本机 macOS Docker（Colima），HTTP 一律 `--noproxy '*'`（见「误判更正」） |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 真实渠道回调验签（Stripe/Adyen webhook 签名）未覆盖——`__EXTERNAL_PAYMENT__` 为外部记账插件，无网关签名链；超额退款拒绝未覆盖——Kill Bill 核心设计上不校验退款≤消费（该校验属收单网关职责，开源镜像不含）；payment-test 插件在 H2 standalone 镜像缺表迁移无法启用；商业锚点（Stripe/Adyen/Braintree）未实测 |
| domain_status | java-payment 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 Kill Bill 环境完整任务+并发+幂等） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 金额精度+状态机+幂等 | java-payment-B1 | PASS | PURCHASE 10.05 USD → `status=SUCCESS`、`processedAmount=10.05` 精确无损；同 paymentExternalKey 重复提交被状态机拒绝（`Invalid payment transition PURCHASE from state PURCHASE_SUCCESS`）；账户下支付总数=1（幂等生效） |
| B2 退款一致+重放+对账 | java-payment-B2 | PASS | `POST /payments/{id}/refunds` 10.05 → REFUND SUCCESS；对账净额 `purchasedAmount−refundedAmount=0.00`；同 transactionExternalKey 重放退款被拒（`Successful transaction with external key ... already exists`，code 7030） |
| B3 凭据隔离+并发+异常 | java-payment-B3 | PASS | 无 ApiKey/Secret → 401；错 secret → 401；10 路并发创建支付全部 201、账户支付总数=11（无丢失无重复）；坏 JSON 请求返回结构化异常（UnrecognizedPropertyException 等，非静默） |

## 误判更正（重要）

2026-09-09 首次尝试记录为「环境阻塞：POST /paymentMethods 405、/plugins 404，支付状态机无法跑通」。
本次复测证明该结论错误，根因两条：

1. **宿主 curl 走了系统 HTTP 代理**：代理对 Docker 映射端口返回 502/空响应，把网络层假象误读为服务端 404/405。
   所有请求加 `--noproxy '*'` 后 `healthcheck=200`、`POST /accounts=201`。
2. **端点版本错配**：0.24.x 起支付方式/支付创建均为账户作用域——
   `POST /1.0/kb/accounts/{accId}/paymentMethods`、`POST /1.0/kb/accounts/{accId}/payments?paymentMethodId=...`
   （body 为单个 PaymentTransactionJson，含 paymentExternalKey/transactionExternalKey）；
   旧式 `POST /1.0/kb/paymentMethods`（accountId 放 body）只注册 GET/OPTIONS，故 405。

教训入档：锚点实测前必须先排除本机代理干扰（`--noproxy '*'` 或 `NO_PROXY` 环境变量），
并以镜像内实际版本的路由表为准（`Allow:` 响应头是判据）。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R09（Java 构建/支付/退款沙箱：200 单测 + 3 支付宝容器集成全绿）与
R21（商城付款/授权/交付/退款 121 项实测全绿）。本记录证明 Kill Bill 开源基线在同等必选语义
（金额精度、状态机幂等、退款对账、重放拒绝、凭据隔离、并发完整性）上行为一致，
XCMAX 支付服务契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测，
且渠道回调验签一项 XCMAX 侧以支付宝异步通知验签覆盖、锚点侧因无真实网关未覆盖，属范围差异而非能力差异）。
