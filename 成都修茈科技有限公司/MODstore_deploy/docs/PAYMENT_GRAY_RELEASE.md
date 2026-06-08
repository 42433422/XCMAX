# Payment Java 服务灰度发布与回滚 Runbook

本文档配合 [`docs/PAYMENT_CONTRACT.md`](./PAYMENT_CONTRACT.md) §6/§7 使用，覆盖 Python → Java 支付服务从灰度到回滚的全部命令和检查项。任何切换都必须按本文步骤逐项确认，**不允许跳过 §1 的预检**。

## 1. 切换前预检

### 1.1 环境变量

最低要求（详见 [`.env.example`](../.env.example)）：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `PAYMENT_BACKEND` | yes | 灰度阶段在预发设为 `java`，生产保持 `python` 直到 §3 完成 |
| `JAVA_PAYMENT_SERVICE_URL` | yes | 形如 `http://java-pay.svc.cluster.local:8080`；不要带尾斜杠 |
| `MODSTORE_JWT_SECRET` 或 `JWT_SECRET` | yes | Python 与 Java 必须使用同一 secret |
| `PAYMENT_SECRET_KEY` | yes | 与前端 `VITE_PAYMENT_SECRET` 一致 |
| `MODSTORE_ADMIN_RECHARGE_TOKEN` | yes | 仅管理员直充使用，Java 端用 `modstore.admin-recharge-token` 覆盖 |
| `ALIPAY_*` / `WECHATPAY_*` | yes | Python 不再下单时仍需保留以便回滚 |
| `ALIPAY_NOTIFY_URL` | yes | 灰度生效后必须指向 Java 公网地址：`https://<host>/api/payment/notify/alipay` |
| `MODSTORE_WEBHOOK_URL` / `MODSTORE_WEBHOOK_SECRET` | optional | 业务 Webhook 出口；建议在灰度前接入观测 |

### 1.2 数据迁移就绪

- Java 服务必须能连上与 Python 相同的 PostgreSQL；Flyway baseline 必须已成功执行 `V1__modstore_core_schema.sql` ~ `V4__user_phone_and_wechatpay.sql`。
- Redis 必须可写（Java `SecurityService` 用 `payment:nonce:*`、`payment:notify:*` 做防重放/通知幂等）。
- 计划清单 `plan_template`、CatalogItem 与用户/钱包数据已经在 PostgreSQL 中，避免回滚时数据回不到 Python SQLite。

### 1.3 静态契约自检

```bash
cd MODstore_deploy
pytest tests/test_payment_contract.py tests/test_payment_data_owner.py tests/test_payment_gateway.py tests/test_event_contracts.py
```

任何失败都视为灰度阻断。

## 2. 预发灰度

### 2.1 启动 Java 服务

```bash
cd MODstore_deploy/java_payment_service
mvn spring-boot:run
```

或使用 `Dockerfile`：

```bash
docker build -t modstore-java-payment .
docker run --rm -p 8080:8080 \
  -e JAVA_DATABASE_URL=jdbc:postgresql://... \
  -e DATABASE_USER=... -e DATABASE_PASSWORD=... \
  -e MODSTORE_JWT_SECRET=... \
  -e PAYMENT_SECRET_KEY=... \
  -e ALIPAY_APP_ID=... -e ALIPAY_PRIVATE_KEY_PATH=/secrets/app.pem \
  -e ALIPAY_PUBLIC_KEY_PATH=/secrets/alipay.pem \
  -e ALIPAY_NOTIFY_URL=https://<staging>/api/payment/notify/alipay \
  modstore-java-payment
```

### 2.2 切换 FastAPI BFF

在预发的 `MODstore_deploy/.env` 写入：

```env
PAYMENT_BACKEND=java
JAVA_PAYMENT_SERVICE_URL=http://127.0.0.1:8080
```

重启 FastAPI（`start-modstore.bat` 或 `python -m modstore_server`）。`PaymentGatewayService` 在每次请求都会重新读取环境变量，无需冷启动；但 `payment_api` 模块在 import 时执行 `init_db`，`/api/payment` 路由仍会被中间件拦截。

### 2.3 自动化预检

```bash
cd MODstore_deploy
python scripts/payment_gray_release_check.py --base-url http://127.0.0.1:8080
```

退出码 `0` = 全部通过；`!= 0` 表示某项失败，标准输出会打印 JSON 结果与失败原因。需要管理员能力时附带 `--admin-token <jwt>`：

```bash
python scripts/payment_gray_release_check.py \
  --base-url https://java-pay.staging \
  --admin-token "$MODSTORE_STAGING_ADMIN_JWT"
```

### 2.4 端到端冒烟

按顺序执行（命令式样例，请按预发地址替换）：

1. **Plan 列表**：`curl -s https://staging/api/payment/plans | jq` —— 通过中间件代理到 Java，应返回非空 `plans`。
2. **登录获取 JWT**：`curl -X POST .../api/auth/login ...`。
3. **沙箱下单**：调用 `paymentCheckout({ plan_id: 'plan_basic' })`（前端按钮或 `/api/payment/sign-checkout` + `/api/payment/checkout`）。
4. **支付宝沙箱回调**：`payme nt/notify/alipay` POST 已签名表单，期望返回纯文本 `success`。
5. **订单状态**：`GET /api/payment/query/<out_trade_no>`，期望 `status=paid`，`fulfilled=true`。
6. **Webhook replay**：`POST /api/webhooks/admin/replay {"order_no":"<out_trade_no>"}` —— 在 `PAYMENT_BACKEND=java` 时 Python 会转发到 Java，Java 应返回 `ok=true`。
7. **退款审核**：`POST /api/refunds/apply` → `POST /api/refunds/admin/<id>/review action=approve`，期望 `refund.approved` Webhook 投递成功。
8. **观测**：Prometheus 指标 `/metrics`、Java `/actuator/prometheus` 中 5xx 率为 0。

### 2.5 验收门槛

- 步骤 §2.4 全部通过且无 5xx。
- Java 日志无 `WARN`/`ERROR` 级支付/数据库异常。
- Python 日志中没有 `PAYMENT_BACKEND=java but payment_orders.<x> called locally` 警告。
- 业务 Webhook 收到的 envelope `id` 形如 `payment.paid:<out_trade_no>`，`source=modstore-java`。

## 3. 生产切换

**一键脚本（Docker Compose 单机）**：[`scripts/production_flip_payment_backend_java.sh`](../scripts/production_flip_payment_backend_java.sh)

```bash
cd MODstore_deploy
./scripts/production_flip_payment_backend_java.sh preflight   # 拉起 payment-service + 探活
./scripts/production_flip_payment_backend_java.sh flip      # 改 PAYMENT_BACKEND=java 并重启 api
# 回滚：./scripts/production_flip_payment_backend_java.sh rollback
```

验收：`curl -s http://127.0.0.1:8765/api/health/payment | jq` 应显示 `"payment_backend":"java"` 且 `java_service_healthy=true`。

预发稳定 ≥ 24 小时后再切生产（若跳过预发，仍建议先 `preflight`）：

1. 把 §1.1 的所有变量配置写入生产 `.env` / Secret Manager。
2. 部署最新 Java 镜像；确认 `/actuator/health` 全部 `UP`。
3. 切换 DNS/Nginx 让 `ALIPAY_NOTIFY_URL` 指向 Java 服务（**这一步早于 `PAYMENT_BACKEND=java`，确保旧的 pending 订单仍能被原 Python 处理完**）。
4. 等待 1 小时让进行中的 Python 订单完成支付/超时。
5. 在 FastAPI 配置中设置 `PAYMENT_BACKEND=java`，重启 FastAPI。
6. 执行 §2.3 / §2.4 在生产环境的子集（用预生产账号）。

## 4. 回滚

回滚必须保留 Python 的支付能力，因此切换流程必须可逆：

1. **保留 Python 支付配置**：`ALIPAY_APP_ID` / 私钥 / 公钥不要从 Python 服务下线，至少保留两个发布周期。
2. **临时回滚（5 分钟内）**：
   - 把 `PAYMENT_BACKEND` 改回 `python`，重启 FastAPI。
   - 中间件停止代理，Python `payment_api` 重新接管。
   - 把 `ALIPAY_NOTIFY_URL` 改回 Python 域名（如 `https://<host>/api/payment/notify/alipay`，但反代到 Python 后端）。
3. **数据一致性补偿**：Java 期间产生的订单仍存在 PostgreSQL；Python JSON 存储不会有这些订单。需要手工退款或客服介入的订单要按 Java 订单号在 PostgreSQL 直接处理，不要再写 Python JSON。
4. **回滚后立即重新预检**：再跑一次 §2.3，确认 Python 能正常签名/下单。

## 5. 已知风险

- Python `payment_api` 在 module import 时调用 `init_db()` 并 reload `alipay_service`；FastAPI 重启时如果 Java 端没准备好，Python 会瞬间承担流量。务必先确认 Java `health` 再改 `PAYMENT_BACKEND`。
- 防重放：Python 默认使用进程内 `processed_requests` 集合，**多 worker 不安全**。生产环境必须依赖 Java 的 Redis nonce 机制；如果回滚到 Python，需要把请求集中到单 worker，或临时关闭高并发支付活动。
- Webhook 投递目录：Python `webhook_dispatcher` 的事件落盘在 `MODSTORE_WEBHOOK_EVENTS_DIR`；如果切到 Java 后某事件未送达，可在 Python 端通过 `/api/webhooks/admin/replay` 重放，但前提是事件最初由 Python 发起。Java 端事件需用 Java 自身的重放接口。
