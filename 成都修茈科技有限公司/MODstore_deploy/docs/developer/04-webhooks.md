# Webhooks — 出站订阅 + 入站触发

MODstore 的 Webhook 双向都支持：

- **出站**：MODstore 业务事件回调到你的服务（订阅模型）
- **入站**：你的服务调用 MODstore 触发工作流执行

## 一、出站订阅

### 创建订阅

UI：`/dev` → **Webhook 订阅** → **新建订阅**。
或 API：

```bash
curl -X POST https://<host>/api/developer/webhooks \
  -H "Authorization: Bearer pat_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My CRM Sync",
    "target_url": "https://crm.example.com/hooks/modstore",
    "secret": "请用至少 32 字节的随机字符串",
    "enabled_events": ["employee.execution_completed", "workflow.execution_completed", "workflow.execution_failed"],
    "is_active": true
  }'
```

`enabled_events` 用 `["*"]` 表示全订阅。

### Envelope

服务端 POST 到你的 `target_url`，body 是 JSON：

```json
{
  "id": "<事件 id>",
  "type": "employee.execution_completed",
  "version": 1,
  "source": "modstore-employee-api",
  "aggregate_id": "<员工 id>",
  "created_at": 1714200000,
  "data": { ... 业务字段 ... }
}
```

详见 [事件参考](./04a-event-reference.md)。

### HTTP 头

| Header | 含义 |
| --- | --- |
| `X-Modstore-Webhook-Id` | 事件 id（幂等键） |
| `X-Modstore-Webhook-Event` | 事件名 |
| `X-Modstore-Webhook-Timestamp` | unix 秒时间戳 |
| `X-Modstore-Webhook-Subscription` | 你的订阅 id |
| `X-Modstore-Webhook-Signature` | `sha256=<hex>` HMAC 签名 |

### 签名校验

```
sig = HMAC_SHA256(secret, timestamp + "." + event_id + "." + body_bytes)
```

任何语言都能复刻；具体示例见 [SDK 示例](./05-sdk-examples.md)。

### 重试与失败

- 服务端默认连续重试 3 次（间隔 0.25s / 0.5s / 0.75s，可由 `MODSTORE_WEBHOOK_RETRIES` 调整）
- 4xx / 5xx 都视为失败
- 每次投递（成功+失败）都会写一条 `webhook_deliveries` 记录，可在 UI **投递日志** 抽屉里查看
- UI 上对失败投递可一键 **重试**，会复用原始 payload 投出新一次（产生新的 delivery 行）

### 安全建议

- `secret` 在服务端用 Fernet 加密保存（前提是部署时设置了 `MODSTORE_FERNET_KEY`）
- 如果未设置 Fernet，UI 会显示 ⚠ 明文存储 警示——生产强烈建议先配置 Fernet 再创建订阅
- 你的 `target_url` 必须是 HTTPS（除非内网调试）
- 验签后再消费 body，不要在校验前 trust 任何字段

## 二、入站触发器（让 MODstore 工作流被你的服务调起）

每个 `Workflow` 都可以挂 webhook 触发器：

```bash
# 1. 给工作流挂一个 webhook 触发器
curl -X POST https://<host>/api/workflow/<wid>/triggers \
  -H "Authorization: Bearer pat_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "trigger_type": "webhook",
    "trigger_key": "incoming-from-erp",
    "is_active": true,
    "config": {}
  }'

# 2. 你的 ERP 在订单变更时调用：
curl -X POST https://<host>/api/workflow/<wid>/webhook-run \
  -H "Authorization: Bearer pat_xxx" \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ORD123", "amount": 199.0}'
```

服务端拿 body 作为 `input_data` 启动工作流执行；执行完成后会再发一条 `workflow.execution_completed` 出去（这就是双向闭环）。

## 三、调试技巧

- **测试发送**：UI 订阅卡片上"发送测试"按钮，会立刻投出一条 `modstore.webhook_test`，便于配置完成后立刻确认链路通；
- **手动重试**：UI **投递日志** 抽屉里每条失败记录都能 retry；
- **查看 payload**：UI 抽屉的 "查看 Payload" 显示原始请求体与响应体（截断 1KB），方便对比 mismatch；
- **本地调试**：用 [smee.io](https://smee.io) 或 [ngrok](https://ngrok.com) 把本地 4000 端口暴露成公网 URL，立即收到事件。
