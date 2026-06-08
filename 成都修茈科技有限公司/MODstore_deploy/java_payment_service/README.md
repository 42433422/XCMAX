# Java 支付服务

本目录承载 MODstore 订单、支付、钱包与权益履约服务。生产切换时由 FastAPI 网关通过
`PAYMENT_BACKEND=java` 将 `/api/payment/*` 与 `/api/wallet/*` 代理到本服务。

## 关键环境变量

- `JAVA_DATABASE_URL`: JDBC PostgreSQL URL，例如 `jdbc:postgresql://127.0.0.1:5432/modstore`
- `DATABASE_USER` / `DATABASE_PASSWORD`: PostgreSQL 账号
- `REDIS_URL`: Redis URL，生产环境必须带认证/TLS
- `MODSTORE_JWT_SECRET`: 与 Python `auth_service.py` 相同，用于校验 SPA Bearer Token
- `PAYMENT_SECRET_KEY`: 与 Python 兼容的 checkout 签名密钥
- `MODSTORE_ADMIN_RECHARGE_TOKEN`: 与 Python 钱包直充接口一致；未配置时 `/api/wallet/recharge` 返回不可用，避免普通用户自充值
- `ALIPAY_*`: 支付宝应用、私钥、公钥、回调 URL

## 启动

```bat
cd MODstore_deploy\java_payment_service
mvn spring-boot:run
```

或在 `MODstore_deploy` 下设置 `PAYMENT_BACKEND=java` 后运行 `deploy.bat`，脚本会同时启动
Java 支付服务和现有 FastAPI 网关。

## Python 兼容约定

FastAPI 网关切到 `PAYMENT_BACKEND=java` 后，`/api/payment/*` 与 `/api/wallet/*`
会整体代理到本服务。为保持前端兼容：

- `/api/wallet/transactions` 同时返回 `txn_type` 与旧前端使用的 `type`。
- `/api/payment/entitlements` 同时返回 `entitlements`、`items` 与 `total`。
- `/api/payment/usage-metrics` 提供空指标响应，避免代理切换后 404。
- `/api/payment/refund` 当前只返回明确未启用提示；退款主流程仍建议走 Python `/api/refunds/*` 审核接口，或后续在 Java 侧补完整退款事务。

## 验证

```bat
mvn test
```

若本机没有 Maven，请先安装 Maven 或补充 Maven Wrapper 后再运行；Cursor 当前环境中 `mvn`
不可用时，Java 编译/测试无法在本机完成。

## 数据库

服务使用 Flyway 管理支付相关 PostgreSQL 表，默认 `spring.jpa.hibernate.ddl-auto=validate`。
SQLite 迁移与历史 JSON 订单导入使用：

```bat
set SQLITE_PATH=path\to\modstore.db
set DATABASE_URL=postgresql://modstore:password@127.0.0.1:5432/modstore
set MODSTORE_PAYMENT_ORDERS_DIR=path\to\payment_orders
python -m modstore_server.scripts.migrate_sqlite_to_pg
```
