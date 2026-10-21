# SDK 示例

目前 MODstore 还没有官方 SDK。下面这些是直接拼 HTTP 的最小示例，只演示已明确支持的能力与 Webhook 验签。

> 本页派生自[账号体系 SSOT](https://github.com/42433422/XCMAX/blob/main/FHD/docs/account_system_ssot.md#04-modstore-pat-能力边界)，不能将 scope 名称当作所有接口已开放。

## 场景 1：读取获授权的 Mod 列表

```python
import os
import httpx

with httpx.Client(timeout=30) as client:
    response = client.get(
        os.environ["MODSTORE_BASE"].rstrip("/") + "/v1/mod-sync/mods",
        headers={"Authorization": "Bearer " + os.environ["MODSTORE_PAT"]},
    )
    response.raise_for_status()
    print(response.json())
```

PAT 必须含 `mod:sync`，资源归属继续校验。通用员工、工作流、凭证管理及登录交接入口不接受 PAT；不能用更高权限账号的 PAT 替代路由级授权。

## 场景 2：接收 webhook 并校验签名

### Python (FastAPI)

```python
import hashlib
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Request

SECRET = os.environ["MODSTORE_WEBHOOK_SECRET"].encode()

app = FastAPI()


@app.post("/hooks/modstore")
async def modstore_webhook(
    request: Request,
    x_modstore_webhook_id: str = Header(...),
    x_modstore_webhook_timestamp: str = Header(...),
    x_modstore_webhook_signature: str = Header(...),
):
    body = await request.body()
    expected = x_modstore_webhook_signature.removeprefix("sha256=")
    msg = (
        x_modstore_webhook_timestamp.encode()
        + b"."
        + x_modstore_webhook_id.encode()
        + b"."
        + body
    )
    actual = hmac.new(SECRET, msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise HTTPException(401, "bad signature")

    event = await request.json()
    if event["type"] == "employee.execution_completed":
        # 你的处理逻辑
        ...
    return {"ok": True}
```

### TypeScript (Express)

```ts
import crypto from 'node:crypto'
import express from 'express'

const SECRET = process.env.MODSTORE_WEBHOOK_SECRET!
const app = express()

app.post('/hooks/modstore', express.raw({ type: 'application/json', limit: '1mb' }), (req, res) => {
  const sig = String(req.header('x-modstore-webhook-signature') ?? '')
  const expected = sig.replace(/^sha256=/, '')
  const ts = String(req.header('x-modstore-webhook-timestamp') ?? '')
  const id = String(req.header('x-modstore-webhook-id') ?? '')
  const msg = Buffer.concat([Buffer.from(ts + '.' + id + '.'), req.body as Buffer])
  const actual = crypto.createHmac('sha256', SECRET).update(msg).digest('hex')
  if (!crypto.timingSafeEqual(Buffer.from(actual), Buffer.from(expected))) {
    return res.status(401).send('bad signature')
  }

  const event = JSON.parse((req.body as Buffer).toString('utf8'))
  if (event.type === 'workflow.execution_completed') {
    // 你的处理逻辑
  }
  res.json({ ok: true })
})

app.listen(4000)
```

## 接入前检查

未迁移接口返回 403 不是重试或扩权信号。需要员工/工作流机器接入时，先完成对应接口的 scope 合同和正反验收；本页不提供绕过方案。
