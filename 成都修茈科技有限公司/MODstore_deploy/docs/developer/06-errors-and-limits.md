# 错误码与生产约束

## HTTP 状态码

MODstore 后端是 FastAPI，错误用 HTTP 状态码 + JSON body 表达：

```json
{ "detail": "<人类可读的错误描述>" }
```

| 状态码 | 含义 | 你应该怎么做 |
| --- | --- | --- |
| `400` | 请求体校验失败、业务参数非法（例如发布版本时图为空） | 修正请求参数 |
| `401` | 缺少 `Authorization`、Token 无效/过期/吊销 | 检查 PAT 是否仍然有效；JWT 过期需重新登录 |
| `403` | 已登录但权限不足（例如非作者删除目录项；员工未购买） | 检查授权关系，必要时购买/订阅 |
| `404` | 资源不存在或不属于当前用户 | 确认 id 是否正确 |
| `409` | 唯一约束冲突（同名资源、版本号撞车） | 重试时换一个名字或版本 |
| `422` | Pydantic 校验细节错误，包含字段路径 | 看 `detail` 数组对应字段修正 |
| `429` | 触达配额限制（计费 quota / IP 限流） | 退避后重试或升级套餐 |
| `5xx` | 服务端故障 | 退避指数重试，附带 X-Modstore-Webhook-Id 提工单 |

## 配额（quota）

部分接口（员工执行、工作流执行）会消耗 `llm_calls` 配额：

- 调用前会先 `require_quota`，不足直接 `429`
- 调用成功后才 `consume_quota` 扣减
- 失败不扣减
- 当前 quota 与套餐绑定，详见 `/api/payment/plans`

## Webhook 投递的重试

- 服务端重试 3 次（间隔 0.25–0.75s）；连续失败仅写一条 failed 记录，不会阻塞业务
- 你需要在 24 小时内通过 UI/API 手动 retry 或修复 endpoint 后重发
- 你的 endpoint 必须**幂等**——`X-Modstore-Webhook-Id` 是稳定的事件 id，应该作为去重键

## 安全约束

1. 所有 PAT / Webhook secret 都应该走环境变量或密管系统注入应用，不要写进代码仓库；
2. 生产部署务必设置：
   - `MODSTORE_JWT_SECRET`（JWT 签名）
   - `MODSTORE_FERNET_KEY`（PAT 哈希外的额外加密：webhook secret、BYOK 等）
   - `MODSTORE_WEBHOOK_SECRET` + `MODSTORE_WEBHOOK_URL`（可选，全局兜底投递）
3. 接收 webhook 时**永远先验签**再 trust body；
4. 不要把 user-supplied URL 直接当 webhook target——可能 SSRF；UI 会拒绝非 http(s)。

## 速率限制现状

- 当前 PR 没有按 IP/用户的全局限流；运维侧可以通过 nginx/cloudflare 加保护
- 建议生产前压测：默认每 PAT 持平稳定 50 RPS，瞬时 burst 200 RPS

## 报告问题

- 后端日志：每条 webhook 投递失败都会带 `subscription=<id>` `event=<type>` `error=<msg>` 字段
- 提工单时附上：
  - 你的 user_id 或 PAT 前缀（例如 `pat_AbCdEfGh`，**不要发完整明文**）
  - 失败时间、调用的接口路径、返回的 `detail`
  - 如果是 webhook，附上 `X-Modstore-Webhook-Id` 让我们能在 `webhook_deliveries` 中定位
