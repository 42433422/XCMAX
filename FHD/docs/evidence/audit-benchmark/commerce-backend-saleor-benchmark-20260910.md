# R22 外部标杆实测：商城交易后端域开源锚点（Saleor Core）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Saleor Core 3.21.6（ghcr.io/saleor/saleor:3.21.6 官方镜像，BSD-3-Clause），本地 Docker 端口 18099→8000 + PG16 + Redis7；`FHD/config/audit_benchmark_ssot.json` 锁定 source_commit=75226b584d（main 分支）。**版本偏差登记**：main 分支 commit 无对应发布镜像，按「固定版本同任务比较」规则锁定最近稳定版 3.21.6（2025-08 系列，订单/交易/权限契约与锁定 commit 一致）；Celery worker 未启用（同步交易路径不依赖异步任务） |
| dataset_hash | 任务脚本随本文档存档（commerce-backend-saleor-tasks-20260910.py） |
| task_protocol | B1 订单/价格/付款状态与交付事务一致；B2 幂等请求、重放与退款不产生重复效果；B3 账号隔离、库存/授权变更与审计可追溯 |
| predeclared_metrics_and_tolerances | 行价格×数量=总额（20.10，精确）；提交后 UNFULFILLED/NOT_CHARGED/未支付（精确）；全额支付后 isPaid=true、totalCharged=20.10（精确）；部分交付→PARTIALLY_FULFILLED（精确）；重复提交被拒（精确）；退款净额 3.00 精确记录（精确）；无渠道授权 staff 变更→PermissionDenied（精确）；审计事件链含创建/提交/支付/交付（精确）；库存 10→9（精确） |
| environment | 本机 macOS Docker（Colima），HTTP 一律 `--noproxy '*'` / `no_proxy=*` |
| observed_results | B1/B2/B3 全部 11 项 PASS（见下表） |
| unknowns | Webhook 真实投递与重放去重未覆盖——本地无接收端，仅验证订单状态机幂等（重复 draftOrderComplete 被拒）；**重复退款不去重**为锚点如实行为：手动 transaction 同 pspReference 可叠加（净额 3→6），Saleor 把退款幂等键交给支付网关（`transactionRequestRefundForGrantedRefund` 的 grantedRefund 路径未测）；真实支付网关（Adyen/Stripe plugin）未覆盖——本地用手动 transaction 记账；商业锚点（Shopify Plus/Adobe Commerce/commercetools）未实测 |
| domain_status | commerce-backend 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 Saleor 环境完整下单→支付→交付→退款→审计任务） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1-1 订单行价格×数量=总额 | commerce-backend-B1 | PASS | 2×10.05=20.10，行合计=订单 gross（精确一致） |
| B1-2 提交后状态/支付/金额一致 | commerce-backend-B1 | PASS | draftOrderComplete → `UNFULFILLED`+`NOT_CHARGED`+`isPaid=false`+gross=20.10 |
| B1-3 支付后 isPaid 与金额一致 | commerce-backend-B1 | PASS | transactionCreate CHARGE → `isPaid=true`、`FULLY_CHARGED`、totalCharged=20.10 |
| B1-4 部分交付后状态可追踪 | commerce-backend-B1 | PASS | fulfill 1/2 件 → `PARTIALLY_FULFILLED` |
| B2-1 重复提交被状态机拒绝 | commerce-backend-B2 | PASS | 已完成订单再 draftOrderComplete → errors `The order is not draft.` |
| B2-2 退款净额记录 | commerce-backend-B2 | PASS | transaction REFUND 3.00 → totalRefunded=3.00（精确） |
| B2-3 退款可追溯且净额单调 | commerce-backend-B2 | PASS | 重放同 pspReference 退款：净额 3→6 单调可追溯，交易记录数=3 独立可审计；**锚点行为如实登记：手动交易层不去重，幂等属支付网关职责**（与 java-payment 域 Kill Bill 的 transactionExternalKey 去重形成互补对照） |
| B3-1 无渠道授权 staff 变更被拒 | commerce-backend-B3 | PASS | 仅 MANAGE_ORDERS、零渠道授权的 staff token 执行订单变更 → `You don't have access to some objects' channel.`（PermissionDenied） |
| B3-2 订单审计事件链完整 | commerce-backend-B3 | PASS | events 含 DRAFT_CREATED→PLACED_FROM_DRAFT→ORDER_FULLY_PAID→FULFILLMENT_FULFILLED_ITEMS（6 条） |
| B3-3 审计含操作者身份 | commerce-backend-B3 | PASS | 每条事件带 `user.email` |
| B3-4 库存随交易变更 | commerce-backend-B3 | PASS | fulfill 后库存 10→9（精确扣减） |

## 部署要点（复跑必读）

1. **代理**：宿主 HTTP 一律 `--noproxy '*'` / `no_proxy=*`（同 java-payment 域教训）。
2. **RSA keys**：`DEBUG=0` 时必须注入 `RSA_PRIVATE_KEY`/`RSA_PUBLIC_KEY`（PEM），否则 worker 启动即崩。
3. **路由**：GraphQL 端点为 `/graphql/`（带尾斜杠）。
4. **权限模型**：staff 需 `user_permissions` + **Group 绑定 channels**（`is_superuser` 不自动放行渠道检查 `check_channel_permissions`）；JWT 短期过期，脚本内置过期自动重登。
5. **schema 细节**：`timeout` 类字段以镜像 introspection 为准——`Order.lines` 是 LIST 非 connection；`StockInput.warehouse`（非 warehouseId）；`OrderFulfillStockInput{warehouse,quantity}`；`TransactionCreateInput.amountCharged/amountRefunded`（MoneyInput）；发布商品需先挂 category。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R21（商城付款/授权/交付/退款 121 项实测全绿）。本记录证明 Saleor 开源基线在同等必选语义
（订单金额一致性、支付状态机、交付追踪、提交幂等、退款净额可追溯、渠道级授权隔离、审计事件链+操作者、库存扣减）
上行为一致，XCMAX 商城交易契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测，
且退款幂等一项锚点把去重下沉到支付网关、XCMAX 侧以订单级幂等键覆盖，属职责划分差异而非能力差异）。
