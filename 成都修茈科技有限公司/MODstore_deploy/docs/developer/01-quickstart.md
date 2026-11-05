# Quickstart — 5 分钟跑通第一次调用

> 本页派生自[账号体系 SSOT](https://github.com/42433422/XCMAX/blob/main/FHD/docs/account_system_ssot.md#04-modstore-pat-能力边界)，不能将 scope 名称当作所有接口已开放。

## 1. 创建 Personal Access Token

打开 MODstore 前端 → 顶部用户菜单 → **开发者门户** (`/dev`) → **API Token** → **创建新 Token**。

- 起一个有意义的名字，例如 `crm-pipeline`。
- 本例选择 `mod:sync`。空 scope 不授予任何已声明能力；其他 scope 不自动开放通用接口。
- 推荐设置过期时间（90 天比较合理）。

> 明文 Token 形如 `pat_AbCdEfGh...`，**仅在创建时显示一次**。
> 如果窗口关掉了，只能吊销重建。

## 2. 读取获授权的 Mod 列表

```bash
curl https://<your-host>/v1/mod-sync/mods \
  -H "Authorization: Bearer $MODSTORE_PAT"
```

凭证须含 `mod:sync`，列表受账号授权范围限制。员工执行、工作流及凭证管理的通用入口当前不接受 PAT；不要改用管理员 PAT 绕过。

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
