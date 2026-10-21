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
  - `llm:use` —— 经平台配置/调用模型
- `/v1/mod-sync/*` 校验 `mod:sync` 和资源归属；通用账号/管理/员工/工作流入口拒绝 PAT（403），空 scope 不等于全部权限。PAT 不能创建其他 PAT 或兑换 browser handoff/JWT。

## 四、安全建议

1. **不要把 PAT 写进前端代码**——泄漏会暴露该凭证已授权能力，不应依赖前端隐藏保护密钥；
2. PAT 走 `Authorization: Bearer` 头，不要放 query string（日志容易记下来）；
3. 给每个集成单独建一个 PAT，方便单独吊销而不影响其它系统；
4. 配合 webhook 的 HMAC 共享密钥使用——PAT 解决"谁在调我"，HMAC 解决"谁在回调我"。

## 五、多账号数据隔离（与认证的关系）

JWT 或明确 scope-aware 入口验证的 PAT **user id** 是服务端按账号过滤业务数据的依据；钱包、订单、配额、个人知识库归属等与「当前凭证对应用户」绑定。详见 [07 多账号数据隔离](./07-account-data-isolation.md)。
