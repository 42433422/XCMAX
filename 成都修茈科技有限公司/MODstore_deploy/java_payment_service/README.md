# Java 支付服务

本目录承载 MODstore 订单、支付、钱包与权益履约服务。生产切换时由 FastAPI 网关通过
`PAYMENT_BACKEND=java` 将 `/api/payment/*` 与 `/api/wallet/*` 代理到本服务。

## 关键环境变量

- `JAVA_DATABASE_URL`: JDBC PostgreSQL URL，例如 `jdbc:postgresql://127.0.0.1:5432/modstore`
- `DATABASE_USER` / `DATABASE_PASSWORD`: PostgreSQL 账号
- `REDIS_URL`: Redis URL，生产环境必须带认证/TLS
- `MODSTORE_JWT_SECRET`: 与 Python `auth_service.py` 相同，用于校验 SPA Bearer Token
- `PAYMENT_SECRET_KEY`: 与 Python 兼容的 checkout 签名密钥。**必填**：未设置、长度不足 16 字节或仍为历史占位值 `default_secret_key` 时服务启动即失败（fail-closed），本地启动也需显式设置，例如 `set PAYMENT_SECRET_KEY=local-dev-please-change-me-0123456789`
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

### 免费个人方案赠额

免费方案开通不要求领取现金额度。Python 服务的
`MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS` 是本次活动的累计总预算（分），由运营明确设置；
留空、无效或 0 时不发放平台现金额度。单次金额仍唯一取计划的 `quota_cents`。
当前账号须完成邮箱验证码验证，同一规范化邮箱及账号在本次活动各只能领取一次。
注册时未填邮箱的账号可先开通免费方案，再通过已有邮件发码接口及
`POST /api/account/personal-plan` 的 `{email, verification_code}` 首次绑定；该接口不允许改绑已有邮箱。

部署执行现有 `alembic upgrade head`（`20261119_personal_allowance`）；现有 `init_db()`
也会幂等补齐验证字段及专用领取记录。预算检查由计划行写锁串行化，待确认记录也占用预算。
领取记录冻结钱包后端、金额和一次生成的幂等键；`PAYMENT_BACKEND` 后续切换不重新领取。
Java 模式通过已鉴权的内部 credit 接口入账，Python 不再写第二笔钱包收入；两端需同步更新。
只有真实回执的用户、金额、幂等键及有效余额匹配时才确认领取。Java 超时、失败或回执无效
保留 `pending` 记录，重试同一幂等键；不得删除待确认记录或把预算占用释放给其他账号。
`allowance.status` 区分 `verification_required`、`available`、`unavailable`、`already_claimed`、
`pending`、`granted`，仅 `granted` 表示已入账；其他状态不影响免费方案本身。
内部 credit 的金额单位为元（500 分发送 `"5.00"`），须带 `X-Internal-Api-Key`。
幂等键全局唯一且最长 128 字符；同键重放必须匹配已完成流水的用户、金额和类型，否则 409。
回执中的 `balance` 是该次入账后的历史快照，不表示当前实时钱包余额。

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

## 微信通知验签（审计 A03 候选）

通知入口保留原始请求体，使用微信支付官方 Java SDK 0.2.17 校验签名后解密，再核对 appid、mchid 和五分钟时间窗。重复或缺失签名请求头、过期通知、错误签名和商户不匹配均拒绝；业务处理异常返回失败，不伪报成功。

平台公钥模式需成对配置 `WECHAT_PLATFORM_PUBLIC_KEY_PATH`（服务端 PEM 公钥文件）与 `WECHAT_PLATFORM_PUBLIC_KEY_ID`（微信提供的公钥 ID），同时保留 APIv3 密钥。未配置公钥模式时沿用商户私钥、商户证书序列号和 APIv3 密钥，由官方 SDK 获取并维护平台证书。配置缺失、证书不可获取或验签失败不会回退到仅解密。上线前须在支付沙箱校验当前公钥/平台证书与轮换过程；不得将私钥或 APIv3 密钥提交仓库。

`WechatNotificationVerificationTest` 使用临时 RSA/AES 合成密钥验证真实通知入口；它不替代支付提供方沙箱、数据库故障与生产配置验收。
