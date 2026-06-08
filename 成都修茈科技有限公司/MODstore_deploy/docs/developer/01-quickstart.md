# Quickstart — 5 分钟跑通第一次调用

## 1. 创建 Personal Access Token

打开 MODstore 前端 → 顶部用户菜单 → **开发者门户** (`/dev`) → **API Token** → **创建新 Token**。

- 起一个有意义的名字，例如 `crm-pipeline`。
- 选填权限范围（scopes）—— 当前 PR 不强制路由级 scope 校验，留空 = 全部权限。
- 推荐设置过期时间（90 天比较合理）。

> 明文 Token 形如 `pat_AbCdEfGh...`，**仅在创建时显示一次**。
> 如果窗口关掉了，只能吊销重建。

## 2. 触发一次员工执行

```bash
PAT="pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

curl -X POST https://<your-host>/api/employees/<employee_id>/execute \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -G --data-urlencode "task=请总结今天的客诉数据" \
  --data '{"input_data":{"date":"2026-04-27"}}'
```

成功后服务端返回员工执行结果，并向所有匹配 `employee.execution_completed` 事件的 webhook 订阅推送回调。

## 3. 接收 Webhook 回调

仍然在 `/dev` → **Webhook 订阅** → **新建订阅**：

- 目标 URL：你自己的 HTTP 端点，例如 `https://example.com/hooks/modstore`
- HMAC 共享密钥：建议至少 32 字节随机字符串，复制保存
- 事件：勾选 `employee.execution_completed`、`workflow.execution_completed`、`workflow.execution_failed`，或者直接选 `*` 全订阅
- 提交后点击订阅卡片上的 **发送测试** 立刻收到一条 `modstore.webhook_test`，确认链路通

## 4. 在你的服务端校验签名（Python 示例）

```python
import hashlib
import hmac
import os

SECRET = os.environ["MODSTORE_WEBHOOK_SECRET"].encode()

def verify(headers: dict[str, str], body: bytes) -> bool:
    signature = headers.get("x-modstore-webhook-signature", "")
    if not signature.startswith("sha256="):
        return False
    expected = signature.removeprefix("sha256=")
    timestamp = headers["x-modstore-webhook-timestamp"]
    event_id = headers["x-modstore-webhook-id"]
    msg = timestamp.encode() + b"." + event_id.encode() + b"." + body
    actual = hmac.new(SECRET, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected)
```

校验通过后，根据 body 中 `type` 分发到不同的处理函数。

## 5. 下一步

- 用 [REST API 文档](./03-rest-api.md) 了解可调用接口的完整列表
- 学习 [Webhook 订阅高级特性](./04-webhooks.md)（重试、手动重发、入站触发器）
- 拿一份 [代码示例](./05-sdk-examples.md) 集成到自己的项目
