# AI 员工处理订单方向 SSOT（平台订单 → AI 编排 桥接契约）

> **本文件是「AI 员工如何感知并处理平台订单」的唯一真相源（SSOT）**。
> 它连接两条既有事实源：订单/支付契约（[PAYMENT_CONTRACT.md](PAYMENT_CONTRACT.md)）与用户侧交易闭环（商品→市场→下单→支付→权益→交付→售后）。
> 与任何说明此桥接的文档冲突时，以本文件为准。
> 最后更新：2026-08-05

---

## 1. 目的与断点背景

### 1.1 一句话目标
**让平台的 AI 员工/编排层（Agent Orchestrator + NeuroBus）能感知订单、被订单事件驱动、并基于订单执行工作**——消除"AI 不知道订单"的断点。

### 1.2 断点根因（现状，代码证实）
平台已具备订单侧能力，但 AI 侧没有消费通道：

| 层 | 已有 | 缺口 |
|---|---|---|
| 订单数据 | Java 支付服务 PostgreSQL；`/api/internal/payment/user-orders` + `/value-evidence`（`X-Internal-Api-Key` 鉴权）| **FHD AI 编排层无客户端调用**（grep `FHD/app` 无 modstore/payment 引用）|
| 订单事件 | `payment.paid` / `refund.approved|rejected|failed` / `wallet.balance_changed`（webhook + NeuroBus envelope，见 PAYMENT_CONTRACT §4）| **事件未进入 FHD 编排层的 NeuroBus** |
| 鉴权 | `X-Internal-Api-Key` / Bearer JWT | 无服务端到端密钥配置约定 |

**结论**：不是缺业务能力，是**两层之间缺一条数据 + 事件桥接**。

## 2. 范围与不做什么

- ✅ 做：AI 编排层"读订单数据 + 订阅订单事件 + 基于订单执行只读/受控动作"的契约。
- ❌ 不做：订单生成本身（仍由 Java/Python 支付服务负责）；不改变支付/退款资金中心边界。
- ❌ 不做：把"订单"塞进 FHD ERP 的业务模型——本桥接是**平台订单**到 **AI 编排**的通路。

## 3. 订单侧契约（消费方依据）

### 3.1 数据读取（有序 SoT：Java 优先）
| 能力 | 端点 | 鉴权 | 说明 |
|---|---|---|---|
| 用户订单列表 | `GET /api/internal/payment/user-orders?user_id&status&limit&offset` | `X-Internal-Api-Key` | Java 直查 PG；返回 `orders[]` + `total` |
| 到款价值证据 | `GET /api/internal/payment/value-evidence?window_days&limit&offset` | `X-Internal-Api-Key` | 仅 `paid` 订单，含履约/验收证据 |
| 支付/计划（Agent 侧只读） | `/api/payment/plans`、`/api/payment/query/{out_trade_no}`、`/api/payment/orders` | Bearer JWT | Agent 代查用户订单时用 |

> 字段契约以 [PAYMENT_CONTRACT.md](PAYMENT_CONTRACT.md) §3 + Java `InternalPaymentController` 为准，禁止在桥接层再定义一份订单字段。

### 3.2 事件订阅（Agent 侧驱动源）
| 事件 | 必填 payload | 触发动作示例 |
|---|---|---|
| `payment.paid` | `out_trade_no, user_id, subject, total_amount, order_kind` | AI 触发履约/交付/感谢通知/经营统计 |
| `refund.approved` / `rejected` / `failed` | `refund_id, order_no, user_id, amount, status` | AI 更新售后看板、通知客服 |
| `wallet.balance_changed` | `user_id, amount, source_order_id, transaction_type` | AI 记账/对账 |

> Envelope 与 HMAC 头统一见 PAYMENT_CONTRACT §4，桥接层不得自定义事件格式。

## 4. 断点桥接层设计（AI 侧要补的部分）

### 4.1 组件：`OrderBridge`（AI 编排层新增适配器）
```
┌─ FHD AI 编排层 ──────────────────────────────────────────────┐
│  Agent Orchestrator ── tool: order.read / order.analyze        │
│          │                                                     │
│   OrderBridge (新增)                                           │
│     ├─ 读通道：OrderApiClient → MODstore internal API (X-Internal-Api-Key)
│     └─ 事件通道：OrderEventConsumer → 订阅 payment.paid/refund.* → FHD NeuroBus
└───────────────────────────────────────────────────────────────┘
```

### 4.2 读通道
- FHD 新增 `OrderApiClient`，封装 internal API 调用；
- 配置：`MODSTORE_INTERNAL_API_URL` + `MODSTORE_INTERNAL_API_KEY`（服务端到端密钥，不进前端）；
- 暴露给 Agent Orchestrator 的工具：`order.read(user_id/out_trade_no)`、`order.analyze(window)`；
- 失败策略：**fail-closed**（读不到订单不做"猜测性履约"），与 `value-evidence` 的 fail-closed 语义一致。

### 4.3 事件通道
- FHD 编排层订阅 `payment.paid` / `refund.*`（经 webhook 或 RabbitMQ 转发）；
- 落到 FHD NeuroBus 后，由现有 Agent 编排/风险门禁消费；
- 幂等：以 `event.id`（`<type>:<aggregate_id>`）去重，与 PAYMENT_CONTRACT envelope 一致。

### 4.4 决策边界（AI 处理订单的自主度）
| 动作 | 风险 | 自主度 |
|---|---|---|
| 读订单 / 经营分析 / 履约状态查询 | low | ✅ AI 自主 |
| 触发履约/交付、售后协同、通知 | medium | ⚠️ AI 建议 + 人签核（可配置白名单）|
| 退款、改单、资金操作 | high | ❌ 仅人工，AI 只读提示 |

> 决策边界复用 FHD 风险门禁（`risk_gate.py`）语义，本文件只定义"订单动作"的等级归属。

## 5. 就绪度矩阵（平台全流程闭环 + AI 感知）

| 环节 | 业务侧 | AI 感知 | AI 可处理 | 就绪度 |
|---|---|:---:|:---:|---|
| 商品发布 | ✅ modman/catalog | ❌ | ❌ | 🟠 |
| 市场售卖 | ✅ AiStore | ❌ | ❌ | 🟠 |
| 下单 | ✅ Order | — | — | ✅（不需 AI）|
| 支付 | ✅ Java | ❌（事件未入 AI）| ❌ | 🔴 断点 |
| 权益/授权 | ✅ entitlements | ❌ | ❌ | 🟠 |
| 交付/激活 | ✅ delivery | ❌ | ❌ | 🟠 |
| 售后/退款 | ✅ Refund | ❌（refund.* 未入 AI）| ⚠️ | 🟡 |

图例：🟢 已 AI 编排 · 🟡 半自动 · 🟠 未接入 AI · 🔴 断点（本文档要解决）

## 6. 行动项（落地序）

P0（打通断点，最小闭环）：
1. FHD 侧实现 `OrderBridge` 读通道（`OrderApiClient` + `order.read/analyze` 工具）。
2. 配置 `MODSTORE_INTERNAL_API_KEY` 服务端密钥，打通 `user-orders` / `value-evidence`。
3. 订阅 `payment.paid` 事件进入 FHD NeuroBus，做一个"支付成功 → 触发履约/通知"的样板。

P1（扩能力）：
4. 接入 `refund.*` / `wallet.balance_changed`，AI 处理售后看板与对账。
5. 商品发布/市场侧接入 AI（AI 员工自动上架/下架/文案）。

P2（AGI 自主闭环）：
6. 在风险门禁上定义"低风险订单环节 AI 自主执行、中高风险人签核"。

## 7. 维护与一致性

- 本文件为**桥接契约 SSOT**；订单字段/事件 payload 的权威仍在 [PAYMENT_CONTRACT.md](PAYMENT_CONTRACT.md) §3–§4。
- 新增 AI 可处理的订单动作：先更新 §4.4 决策边界，再改代码。
- 实现 `OrderBridge` 时，同步本文件"已实现"状态，避免文档与代码漂移。