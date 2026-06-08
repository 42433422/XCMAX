# MODstore 支付契约（Python ↔ Java ↔ Frontend）

本文档是 Python `modstore_server`、Java `java_payment_service` 与前端 `MODstore_deploy/market` 三方共同遵守的支付/钱包/退款 API 与事件契约。任何跨服务字段、事件 payload、签名规则的修改都必须先更新本文件，再同步 Python `payment_contract.py`、Java `SecurityService`/`EventContracts` 与前端 `api.ts`/`paymentApi.ts`，并确保 `tests/test_payment_contract.py` 通过。

> 该契约面向"Python 当前为 BFF / 灰度路由层，Java 为支付/钱包资金中心"的迁移阶段，是 Python → Java 支付迁移期间防回归的事实源。

## 1. 服务边界

- 前端只能调 Python 暴露的 `/api/payment/**`、`/api/wallet/**`、`/api/refunds/**`。
- 当 `PAYMENT_BACKEND=java` 时，FastAPI `add_security_headers` 中间件会对 `/api/payment`、`/api/wallet`、`/api/refunds` 三个前缀整段透传给 `JAVA_PAYMENT_SERVICE_URL`。
- **订单 SoT**：`PAYMENT_BACKEND=java` 时 `payment_orders` 本地 JSON **禁止写入**（`create`/`merge_fields`/`update_status` 返回 `java_sot_readonly`）；FHD 宿主设 `MODEL_PAYMENT_BACKEND=modstore` 时走 `/api/market/payment/*`，不再写 `model_payment_orders.json`。
- 当 `PAYMENT_BACKEND=python` 或未设置时，请求由 `payment_api.py`、`market_api.py`（钱包路由）、`refund_api.py` 处理。
- 事件出口：Python `webhook_dispatcher.publish_event` 与 Java `WebhookDispatcher.publishPaymentPaid` 共用同一 envelope 与 HMAC 头。

## 2. 路由清单与归属

| Method | 路径 | 归属(java=true 表示已能由 Java 承接) | 鉴权 | 错误码 | 说明 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/payment/plans` | both | 公开（缓存 5 分钟） | 200 | `{plans: PlanItem[]}` |
| GET | `/api/payment/my-plan` | both | Bearer JWT | 200 | 返回 `plan` 与 `quotas` |
| POST | `/api/payment/sign-checkout` | both | Bearer JWT | 200 / 400 / 403 / 404 | 服务端用 `PAYMENT_SECRET_KEY` 生成 `request_id`/`timestamp`/`signature` |
| POST | `/api/payment/checkout` | both | Bearer JWT | 200 / 400 / 403 / 503 | 验签 + 防重放 + 创建订单 + 发起支付。Python 收到时若 `PAYMENT_BACKEND=java` 会再次转发到 Java |
| POST | `/api/payment/notify/alipay` | java（生产） | 仅支付宝签名 | 200 文本 `success`/`fail` | 异步通知，**`ALIPAY_NOTIFY_URL` 必须指向当前持有订单的服务** |
| POST | `/api/payment/notify/wechat` | java | 微信支付签名 | 200 | 仅 Java 支持，Python 无对应实现 |
| GET | `/api/payment/query/{out_trade_no}` | both | Bearer JWT（Java 强制 owner/admin；Python 当前未鉴权——P0 已知风险） | 200 / 404 | 查询本地订单；Python 端在 pending 时回查支付宝并触发履约 |
| GET | `/api/payment/orders` | both | Bearer JWT | 200 | 列出当前用户订单，分页字段 `limit`/`offset`/`status` |
| POST | `/api/payment/cancel/{out_trade_no}` | both | Bearer JWT | 200 / 400 / 404 | 仅 `pending` 可取消 |
| GET | `/api/payment/diagnostics` | both | Bearer JWT + admin | 200 / 403 | 支付宝/微信连通性、Redis 等运行时诊断 |
| GET | `/api/payment/entitlements` | both | Bearer JWT | 200 | 当前用户权益 |
| GET | `/api/payment/usage-metrics` | both | Bearer JWT | 200 | 员工/AI 使用统计 |
| POST | `/api/payment/refund` | python only（已 deprecate） | Bearer JWT + admin | 400 | Java 直接返回 400，**新代码必须走 `/api/refunds/admin/{id}/review`** |
| GET | `/api/wallet/balance` | both | Bearer JWT | 200 | `{balance, updated_at}` |
| GET | `/api/wallet/overview` | java | Bearer JWT | 200 | `{wallet, transactions, orders, refunds, ...}` |
| POST | `/api/wallet/recharge` | java（需 `MODSTORE_ADMIN_RECHARGE_TOKEN`） | Bearer JWT + token | 200 / 403 / 503 | Python 同名路由也存在，但生产应让 Java 接管 |
| GET | `/api/wallet/transactions` | both | Bearer JWT | 200 | 分页交易流水 |
| POST | `/api/wallet/ai/preauthorize` `…/ai/settle` `…/ai/release` | java only | Bearer JWT | 200 | LLM 用量预授权资金钩子 |
| POST | `/api/refunds/apply` | python | Bearer JWT | 200 / 400 / 404 | 用户提交退款申请 |
| GET | `/api/refunds/my` | python | Bearer JWT | 200 | 当前用户退款申请 |
| GET | `/api/refunds/admin/pending` | python | Bearer JWT + admin | 200 / 403 | 待审核退款列表 |
| POST | `/api/refunds/admin/{refund_id}/review` | python | Bearer JWT + admin | 200 / 400 / 403 / 404 | 审核：approve/reject；approve 调用支付宝退款并发布 `refund.approved` |
| POST | `/api/webhooks/admin/replay` | both | Bearer JWT + admin | 200 / 400 / 404 / 502 | 当 `PAYMENT_BACKEND=java` 且 `event_type` 不以 `refund.` 开头时由 Python 转发到 Java |
| GET | `/api/internal/payment/summary` | both（BFF 聚合） | `X-Internal-Api-Key` | 200 / 403 / 503 | FHD 客服到款核对；`market_user_id` + 可选 `min_amount_cents` / `expected_out_trade_no` |
| GET | `/api/internal/payment/user-orders` | java | `X-Internal-Api-Key` | 200 / 403 / 404 | Java 直查 PostgreSQL 订单；Python `PAYMENT_BACKEND=java` 时由 `payment_cs_internal` 调用 |

> **错误响应格式：** Python 路由抛出 `HTTPException`，序列化为 `{"detail": str}`，状态码即业务码；Java 控制器返回 `{"ok": false, "message": str}`（HTTP 200）或 `ResponseStatusException`（HTTP 4xx）。前端两种都需要兼容；新增字段时必须保留 `detail` 兼容。

## 3. 核心数据形状

### 3.1 Plan / `/api/payment/plans`

```json
{
  "plans": [
    {
      "id": "plan_basic",
      "name": "基础版",
      "description": "...",
      "price": 9.9,
      "features": ["..."],
      "requires_plan": null
    }
  ]
}
```

`requires_plan` 仅 SVIP2~SVIP8 返回 `"plan_enterprise"`。

### 3.2 Sign-checkout / `/api/payment/sign-checkout`

请求体（Python `SignCheckoutBody` / Java `Map<String, Object>`）：

| 字段 | 类型 | 默认 |
| --- | --- | --- |
| `plan_id` | string | `""` |
| `item_id` | int | `0` |
| `total_amount` | number | `0` |
| `subject` | string | `""` |
| `wallet_recharge` | bool | `false` |

校验：

- `wallet_recharge=true` 时 `total_amount > 0`，否则 400 `请填写大于 0 的充值金额`。
- 否则 `plan_id` 必须存在并 active；SVIP2~SVIP8 还需当前用户已持有任一 SVIP（含 svip 入门档 / `plan_enterprise`）档，否则 403。
- 否则 `item_id` 必须存在且 `price > 0`。
- 否则 400 `请使用 wallet_recharge、plan_id 或 item_id 之一下单`。

响应体（Python 与 Java 必须保持完全一致的字段）：

```json
{
  "plan_id": "plan_basic",
  "item_id": 0,
  "total_amount": 9.9,
  "subject": "基础版",
  "wallet_recharge": false,
  "request_id": "uuid-without-dashes",
  "timestamp": 1710000000,
  "signature": "<sha256-hex>"
}
```

### 3.3 Checkout / `/api/payment/checkout`

请求体（`CheckoutDTO`）：在 sign-checkout 字段基础上增加：

| 字段 | 类型 | 必填 |
| --- | --- | --- |
| `request_id` | string | yes |
| `timestamp` | int (秒) | yes |
| `signature` | string | yes |
| `pay_channel` | string | no（默认 `alipay`，可选 `wechat`） |
| `pay_type` | string | no（仅 Java 接受：`page`/`wap`/`precreate`） |

防重放：`request_id` 在 Redis（Java）或进程内集合（Python，仅供测试/单机）中加锁，`timestamp` 必须在 ±300 秒内。

响应体（成功）：

```json
{
  "ok": true,
  "order_id": "MOD<unix><userid>",
  "type": "page|wap|precreate|wechat",
  "redirect_url": "https://...",
  "qr_code": "data:image/png;base64,... or 支付宝二维码 URL",
  "subject": "...",
  "total_amount": "9.90"
}
```

> Python 在错误时抛 `HTTPException(400|403|502|503)`；Java 当前在 `try/catch` 内返回 200 + `{"ok": false, "message": str}`，新代码应改为 4xx 让前端统一处理。

### 3.4 Canonical 签名数据

Python `canonical_checkout_sign_data` 与 Java `SecurityService.canonicalCheckoutData` 必须产出同一组字符串字段，按 key 字典序拼成 `k=v&k=v...`，再追加 `PAYMENT_SECRET_KEY` 后做 SHA-256：

| 字段 | 字符串化规则 |
| --- | --- |
| `item_id` | `str(int(item_id or 0))` |
| `plan_id` | `(plan_id or "").strip()` |
| `request_id` | `str(request_id)` |
| `subject` | `(subject or "").strip()` |
| `timestamp` | `str(int(timestamp))` |
| `total_amount` | 整数无小数；非整数小数最多 6 位且去除末尾 0 与 `.`（例：`9` → `"9"`，`9.9` → `"9.9"`，`9.99` → `"9.99"`） |
| `wallet_recharge` | `"true"` / `"false"` |

前端 `api.ts.paymentCheckout` 不应自行计算签名，只能透传 sign-checkout 返回的 `signature/request_id/timestamp` 与解析后字段。

### 3.5 支付宝异步通知

- URL: `ALIPAY_NOTIFY_URL` 在生产应指向 Java 服务（订单事实源）。
- 验签：`alipay_service.verify_notify`（Python）或 `AlipayService.verifyNotify`（Java）。
- 接受 `trade_status ∈ {TRADE_SUCCESS, TRADE_FINISHED}`。
- 金额一致性：本地订单 `total_amount` 与回调 `total_amount` 容差 `0.01`（Python `_amounts_match`）。
- 幂等：Java 用 `payment:notify:{trade_no|out_trade_no}` Redis 锁，TTL 24h；Python 当前依赖 `order.status == 'paid'` 短路。
- 回写顺序：先 `update_status`，再 `_fulfill_paid_order` / `OrderService.fulfillOrder`，最后 `webhook_dispatcher.publish_event(payment.paid, ...)`。

### 3.6 退款流程

```
用户  -- POST /api/refunds/apply --> Python (writes RefundRequest pending)
管理员 -- POST /api/refunds/admin/{id}/review action=approve --> Python
        Python -> alipay_service.refund_order
        success: RefundRequest.status='refunded' + Entitlement.is_active=False
                 + revoke XP + payment_orders.merge_fields(refunded=True)
                 + publish refund.approved
        fail:    RefundRequest.status='refund_failed' + publish refund.failed
管理员 -- POST /api/refunds/admin/{id}/review action=reject --> Python
        Python: RefundRequest.status='rejected' + publish refund.rejected
```

`/api/payment/refund` 是历史路由，**只允许返回 deprecation 信息**，不再写钱包/权益。

## 4. 事件契约（business webhook + NeuroBus envelope）

事件常量定义在：

- Python: `modstore_server.eventing.contracts`
- Java: `com.modstore.event.EventContracts`

| 事件 type | version | 必填 payload 字段 |
| --- | --- | --- |
| `payment.paid` (canonical of `payment.order_paid`) | 1 | `out_trade_no`, `user_id`, `subject`, `total_amount`, `order_kind` |
| `wallet.balance_changed` | 1 | `user_id`, `amount`, `source_order_id`, `transaction_type` |
| `refund.approved` / `refund.rejected` / `refund.failed` | 1 | `refund_id`, `order_no`, `user_id`, `amount`, `status` |

Envelope（HTTP body 与 NeuroBus 内部统一）：

```json
{
  "id": "<event_type>:<aggregate_id>",
  "type": "payment.paid",
  "version": 1,
  "source": "modstore-python|modstore-java",
  "aggregate_id": "MOD123",
  "created_at": 1710000000,
  "data": { /* contract.required_payload + 可选扩展 */ }
}
```

HTTP 投递头：`X-Modstore-Webhook-Id`、`X-Modstore-Webhook-Event`、`X-Modstore-Webhook-Timestamp`、`X-Modstore-Webhook-Signature: sha256=<hmac>`。

## 5. 鉴权与请求头

- Bearer JWT：`Authorization: Bearer <access_token>`，secret 共享 `MODSTORE_JWT_SECRET`/`JWT_SECRET`，过期 86400 秒。
- 替换 `_get_current_user`：所有路由通过 `modstore_server.api.deps._get_current_user` 解析，禁止再写新版本。
- 管理员动作（diagnostics、refund review、webhook replay、payment refund deprecation、wallet recharge）必须 `user.is_admin == true`。
- 钱包直充：除 JWT 之外还要求 `X-Modstore-Recharge-Token` 或请求体 `recharge_token` 与 `MODSTORE_ADMIN_RECHARGE_TOKEN` 一致。

## 6. 单一事实源与回调归属

P0 必须遵守：

1. 生产环境 `PAYMENT_BACKEND=java`；Python 不再下单或履约。
2. `ALIPAY_NOTIFY_URL` 必须指向最终持有订单的服务（默认为 Java 公网域名 + `/api/payment/notify/alipay`）。
3. 在 `PAYMENT_BACKEND=java` 的环境，禁止再向 Python 的 `payment_orders/` JSON 目录写入业务订单；Python 退款审核需要订单时，先尝试 Java 查询，再回退 JSON 兼容只读。
4. Webhook replay：Python `/api/webhooks/admin/replay` 在 `PAYMENT_BACKEND=java` 且 `event_type` 非 `refund.*` 时，必须把请求转发到 Java 的 `/api/webhooks/admin/replay`。

## 7. 切换/回滚开关

- `PAYMENT_BACKEND=python|java`：不重启不可改；改后 FastAPI `PaymentGatewayService` 立即生效。
- `JAVA_PAYMENT_SERVICE_URL`：默认 `http://127.0.0.1:8080`，灰度时建议改成预发地址再切真实流量。
- 验证清单（详见 `docs/PAYMENT_GRAY_RELEASE.md`）：
  - `/api/payment/diagnostics` 返回的服务名、Alipay/Wechat 配置、Redis 状态。
  - 触发一次沙箱下单 + Alipay notify 模拟；确认订单 `status=paid` + `fulfilled=true` 且 `payment.paid` webhook 已投递。
  - 用 `/api/webhooks/admin/replay` 重放最新订单，结果 `ok=true`。
  - 触发 `/api/refunds/apply` + `admin/review approve` 流，验证 `refund.approved` payload。

## 8. 兼容性测试钩子

强制由 `tests/test_payment_contract.py` 校验的项目：

- `payment_contract.PROXY_PREFIXES` 与 `PaymentGatewayService.should_proxy_to_java` 一致。
- `payment_contract.SIGN_FIELDS` 与 `payment_api.canonical_checkout_sign_data` 输出键集合一致，且 `_amount_sign_str` 处理 `9`/`9.9`/`9.99`/`0.10` 与契约一致。
- `payment_contract.PAYMENT_PAID_PAYLOAD_FIELDS` 与 `eventing.contracts.EVENT_CONTRACTS[PAYMENT_PAID].required_payload` 一致；`webhook_api._payment_payload` 与 `payment_api._fulfill_paid_order` 发布的 payload 包含全部必填项。
- 前端 `market/src/api.ts` 与 `market/src/application/paymentApi.ts` 中的 endpoint 路径与本文件 §2 一致。
- Java `SecurityService.canonicalCheckoutData` 顺序与本文件 §3.4 一致（通过文件文本静态校验）。
- Java：`mvn verify` 的 JaCoCo 使用「全 BUNDLE 底限 + 契约类 CLASS 0.80/0.70」两档门禁（`java_payment_service/pom.xml`），与 Python 对 `payment_orders` / `payment_contract` 等关键文件的 80% 门禁原则对齐。
