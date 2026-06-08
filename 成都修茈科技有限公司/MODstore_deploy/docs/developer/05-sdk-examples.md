# SDK 示例

目前 MODstore 还没有官方 SDK。下面这些是直接拼 HTTP 的最小示例，覆盖最常见 3 个场景。

## 场景 1：触发员工执行

### Python

```python
import os
import httpx

PAT = os.environ["MODSTORE_PAT"]
BASE = os.environ.get("MODSTORE_BASE", "https://your-host")

def execute_employee(employee_id: str, task: str, input_data: dict) -> dict:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{BASE}/api/employees/{employee_id}/execute",
            params={"task": task},
            json={"input_data": input_data},
            headers={"Authorization": f"Bearer {PAT}"},
        )
        resp.raise_for_status()
        return resp.json()
```

### TypeScript (Node 18+)

```ts
const PAT = process.env.MODSTORE_PAT!
const BASE = process.env.MODSTORE_BASE ?? 'https://your-host'

export async function executeEmployee(
  employeeId: string,
  task: string,
  inputData: Record<string, unknown>,
) {
  const url = new URL(`${BASE}/api/employees/${encodeURIComponent(employeeId)}/execute`)
  url.searchParams.set('task', task)
  const r = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${PAT}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ input_data: inputData }),
  })
  if (!r.ok) throw new Error(`MODstore ${r.status} ${await r.text()}`)
  return r.json()
}
```

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

app.post(
  '/hooks/modstore',
  express.raw({ type: 'application/json', limit: '1mb' }),
  (req, res) => {
    const sig = String(req.header('x-modstore-webhook-signature') ?? '')
    const expected = sig.replace(/^sha256=/, '')
    const ts = String(req.header('x-modstore-webhook-timestamp') ?? '')
    const id = String(req.header('x-modstore-webhook-id') ?? '')
    const msg = Buffer.concat([
      Buffer.from(ts + '.' + id + '.'),
      req.body as Buffer,
    ])
    const actual = crypto.createHmac('sha256', SECRET).update(msg).digest('hex')
    if (!crypto.timingSafeEqual(Buffer.from(actual), Buffer.from(expected))) {
      return res.status(401).send('bad signature')
    }

    const event = JSON.parse((req.body as Buffer).toString('utf8'))
    if (event.type === 'workflow.execution_completed') {
      // 你的处理逻辑
    }
    res.json({ ok: true })
  },
)

app.listen(4000)
```

## 场景 3：用工作流模板批量初始化

```bash
PAT=pat_xxx

# 1. 找到合适的模板
curl "https://your-host/api/templates?category=客服&difficulty=intermediate" \
  -H "Authorization: Bearer $PAT"

# 2. 一键安装
curl -X POST https://your-host/api/templates/<template_id>/install \
  -H "Authorization: Bearer $PAT"
# 返回 { workflow_id: 42, ... }

# 3. 立即执行
curl -X POST https://your-host/api/workflow/42/execute \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -d '{"input_data":{"ticket_id":"T001"}}'
```
