# Authentication — 凭证体系

> 本页派生自[账号体系 SSOT](https://github.com/42433422/XCMAX/blob/main/FHD/docs/account_system_ssot.md#04-modstore-pat-能力边界)，不能将 scope 名称当作所有接口已开放。

MODstore 同时支持两种凭证；**两种都通过 `Authorization: Bearer xxx` 头携带**，服务端在认证管道里自动识别。

| 凭证                        | 适合谁                   | 生命周期                        | 撤销方式                             |
| --------------------------- | ------------------------ | ------------------------------- | ------------------------------------ |
| JWT access token            | Web/移动端浏览器会话     | 默认 72 小时（环境变量可调）    | 用户主动登出；过期自动失效           |
| Personal Access Token (PAT) | 第三方/SDK/CI/服务对服务 | 创建时可选 1–365 天，或永不过期 | `/dev/tokens` 一键吊销，立刻全网失效 |

## 一、PAT 工作原理

```
Authorization: Bearer pat_<32 字符 url-safe 随机串>
```

- 明文只在创建那一刻通过 `POST /api/developer/tokens` 返回，DB 只保存 `sha256(token)`；
- 每次请求服务端校验：解出明文 → 计算 sha256 → 反查 `developer_tokens` 表（带未吊销 + 未过期条件）→ 关联 user；
- 命中后服务端写一次 `last_used_at`，便于安全审计。

### 创建

```bash
curl -X POST https://<your-host>/api/developer/tokens \
  -H "Authorization: Bearer <已登录的 JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "crm-pipeline",
    "scopes": ["mod:sync"],
    "expires_days": 90
  }'
```

返回示例：

```json
{
  "id": 17,
  "name": "crm-pipeline",
  "prefix": "pat_AbCdEfGh",
  "scopes": ["mod:sync"],
  "token": "pat_AbCdEfGh.....完整明文，仅这一次返回....."
}
```

### 列表 / 吊销

```bash
curl https://<your-host>/api/developer/tokens \
  -H "Authorization: Bearer <已登录的 JWT>"

curl -X DELETE https://<your-host>/api/developer/tokens/17 \
  -H "Authorization: Bearer <已登录的 JWT>"
```

## 二、JWT 工作原理

JWT 用于浏览器会话，含 `sub`（user id）、`username`、`type=access`、`exp`。
Refresh token 由 `/api/auth/login` 返回，刷新由前端 SDK 自动处理；第三方仅在明确支持 scope 的接口使用 PAT；未迁移的接口不能通过改用管理员 PAT 获得访问权。

## 三、scope 设计

- 以下是可存储的能力名称，不代表各通用接口已迁移；当前只有明确校验 scope 的接口接受 PAT：
  - `workflow:read` —— 只读工作流
  - `workflow:execute` —— 触发执行
  - `employee:execute` —— 调用员工
  - `catalog:read` —— 浏览市场/模板
  - `webhook:manage` —— 管理订阅
  - `mod:sync` —— 调用 `/v1/mod-sync/push` 与 `/v1/mod-sync/pull`，在本地库与 XCAGI `mods/` 之间同步
  - `llm:use` —— 模型网关能力；仅在专用计费服务配置并开启后可用
- `/v1/mod-sync/*` 校验 `mod:sync` 和资源归属；通用账号/管理/员工/工作流入口拒绝 PAT（403），空 scope 不等于全部权限。PAT 不能创建其他 PAT 或兑换 browser handoff/JWT。

模型 PAT 默认关闭。部署此代码时需先应用 Java Flyway V18，以保留普通钱包和专用预授权的来源隔离；不能在缺少迁移的数据库上启动新代码。启用时 Python 侧需设置 `MODSTORE_LLM_PAT_ENABLED=1`、`PAYMENT_BACKEND=java`、`MODSTORE_LLM_WALLET_SIGNING_KEY_PATH`、`MODSTORE_LLM_WALLET_KEY_ID` 和正整数 `MODSTORE_LLM_WALLET_MAX_CENTS`；私钥文件不得对组或其他用户开放。Java 侧需显式启用 `llm.wallet.service-enabled`，配置相同 key ID、对应公钥 `llm.wallet.public-key-pem` 和正整数 `llm.wallet.max-cents`。两侧限额都必须允许本次金额。

Python 在预授权前重新核验令牌；核验成功即接受一次绑定账户、金额和请求的短期在途授权。之后吊销会阻止新授权，已经接受的操作仍可完成预授权及结算或释放。Java 验证专用声明并通过自己的数据库事务保证请求去重和账户归属，不读取 PAT 存储，不支持指定其他账户代扣。服务间请求应限制网络来源、使用受保护的传输通道，且不得记录签名声明或凭证。预授权结果、上游请求结果或结算不确定时返回待核对，不自动切换模型重试；客户端不能直接重新提交，应先凭返回的请求号及可用的预授权号人工核对，因为新 HTTP 请求会产生新请求号。目前没有自动核对或释放机制。此配置是服务间新信任，部署和启用须单独批准；轮换时须协调两侧 key ID 与公钥，避免中断在途结算。

旧 Java 版本不识别专用预授权来源：必须确认所有钱包实例均已升级后才能启用。回滚旧版本前须停止 Python 侧新授权，并保持 Java 专用接口可用以核对、处理全部未终结专用预授权；也可在旧实例入口阻断普通钱包结算和释放。不得让旧实例处理仍未终结的专用预授权。

## 四、安全建议

1. **不要把 PAT 写进前端代码**——泄漏会暴露该凭证已授权能力，不应依赖前端隐藏保护密钥；
2. PAT 走 `Authorization: Bearer` 头，不要放 query string（日志容易记下来）；
3. 给每个集成单独建一个 PAT，方便单独吊销而不影响其它系统；
4. 配合 webhook 的 HMAC 共享密钥使用——PAT 解决"谁在调我"，HMAC 解决"谁在回调我"。

## 五、多账号数据隔离（与认证的关系）

JWT 或明确 scope-aware 入口验证的 PAT **user id** 是服务端按账号过滤业务数据的依据；钱包、订单、配额、个人知识库归属等与「当前凭证对应用户」绑定。详见 [07 多账号数据隔离](./07-account-data-isolation.md)。
