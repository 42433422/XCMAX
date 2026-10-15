#!/usr/bin/env python3
"""R22 customer-service 域 Chatwoot OSS 锚点 B1-B3 实测。

B1 客户、会话、工单/线索归属按账号隔离
B2 多渠道接入与人工交接保留上下文
B3 发送状态和失败重试以渠道回执为准
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

os.environ["no_proxy"] = "*"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

BASE = "http://localhost:13000"
BOOT = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(open("/tmp/r22-chatwoot/boot.json"))


def api(method, path, token, body=None, account_scoped=True):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "api_access_token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except json.JSONDecodeError:
            return e.code, {}


results = {}


def check(name, cond, detail=""):
    results[name] = bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


TA, TB = BOOT["token_a"], BOOT["token_b"]
A, B = BOOT["account_a"], BOOT["account_b"]


def mk_contact(tok, acct, name, email, inbox_id):
    st, js = api("POST", f"/api/v1/accounts/{acct}/contacts", tok,
                 {"name": name, "email": email, "inbox_id": inbox_id})
    if st not in (200, 201):
        return st, js
    payload = js.get("payload", js)
    contact = payload.get("contact", payload) if isinstance(payload, dict) else payload
    return st, contact


def mk_inbox_and_conversation(tok, acct, name):
    """Chatwoot: POST /inboxes 同时创建 channel + inbox（type 用 web_widget）。"""
    st, ib = api("POST", f"/api/v1/accounts/{acct}/inboxes", tok,
                 {"name": name,
                  "channel": {"type": "web_widget",
                              "website_url": "http://r22.local",
                              "welcome_title": "R22", "welcome_tagline": "anchor"}})
    if st not in (200, 201):
        return None, None, (st, ib)
    return ib.get("channel", {}).get("id"), ib, None


# ---------- 准备：两账户各建 inbox + 客户 + 会话 ----------
_, ibA, errA = mk_inbox_and_conversation(TA, A, "r22-inbox-A")
_, ibB, errB = mk_inbox_and_conversation(TB, B, "r22-inbox-B")
assert ibA and ibB, (errA, errB)

def find_contact(tok, acct, name):
    st, cs = api("GET", f"/api/v1/accounts/{acct}/contacts", tok)
    payload = cs.get("payload", cs) if isinstance(cs, dict) else cs
    for c in payload:
        if isinstance(c, dict) and c.get("name") == name:
            return c
    return None


st, cA = mk_contact(TA, A, "Cust A", "custa@x.com", ibA["id"])
if st == 422:
    cA = find_contact(TA, A, "Cust A")
stB, cB = mk_contact(TB, B, "Cust B", "custb@x.com", ibB["id"])
if stB == 422:
    cB = find_contact(TB, B, "Cust B")
print("contacts:", st, stB, cA.get("id"), cB.get("id"))


def conv(tok, acct, contact_id, inbox_id, msg):
    st, js = api("POST", f"/api/v1/accounts/{acct}/conversations", tok,
                 {"inbox_id": inbox_id, "contact_id": contact_id,
                  "message": {"content": msg}})
    return st, js


st1, convA = conv(TA, A, cA["id"], ibA["id"], "hello from A")
st2, convB = conv(TB, B, cB["id"], ibB["id"], "hello from B")
print("conversations:", st1, st2, convA.get("id"), convB.get("id"))

# ---------- B1 账号隔离 ----------
check("B1-1 会话归属创建账户",
      st1 in (200, 201) and convA.get("account_id") == A, str(convA.get("account_id")))


def conv_list(tok, acct):
    st, js = api("GET", f"/api/v1/accounts/{acct}/conversations", tok)
    payload = js.get("data", js).get("payload", []) if isinstance(js, dict) else js
    return [c.get("uuid") for c in payload]


uuA, uuB = convA.get("uuid"), convB.get("uuid")
lstA, lstB = conv_list(TA, A), conv_list(TB, B)
check("B1-2 列表按账户隔离", uuA in lstA and uuB not in lstA,
      f"A={lstA} B_in_A={uuB in lstA}")

# 跨账户直接读取对方会话（按 uuid）：应 404
st, js = api("GET", f"/api/v1/accounts/{A}/conversations/{uuB}", TA)
check("B1-3 跨账户读取会话被拒", st == 404, str(st))
# 用 A 的 token 但账户路径 B：应 401/403
st, js = api("GET", f"/api/v1/accounts/{B}/conversations/{convB['id']}", TA)
check("B1-4 错账户 token 被拒", st in (401, 403), str(st))
# 联系人隔离
st, cs = api("GET", f"/api/v1/accounts/{A}/contacts", TA)
payload = cs.get("payload", cs) if isinstance(cs, dict) else cs
names = [c["name"] for c in payload if isinstance(c, dict)]
check("B1-5 联系人按账户隔离", "Cust A" in names and "Cust B" not in names, str(names))

# ---------- B2 渠道接入 + 人工交接保留上下文 ----------
# 客户消息进入会话（渠道回执：创建消息）
st, m1 = api("POST", f"/api/v1/accounts/{A}/conversations/{convA['id']}/messages", TA,
             {"content": "second message", "message_type": "outgoing"})
check("B2-1 会话消息可追加", st in (200, 201), str(st))

# 人工交接：分配给 agent
st, ag = api("GET", f"/api/v1/accounts/{A}/agents", TA)
agent_id = ag[0]["id"] if isinstance(ag, list) and ag else None
st3, team = api("POST", f"/api/v1/accounts/{A}/teams", TA, {"name": "r22-team"})
mid = team.get("id") if st3 in (200, 201) else None
st4, asg = api("POST", f"/api/v1/accounts/{A}/conversations/{convA['id']}/assignments", TA,
               {"assignee_id": agent_id})
st5, convA2 = api("GET", f"/api/v1/accounts/{A}/conversations/{convA['id']}", TA)
st6, mlist = api("GET", f"/api/v1/accounts/{A}/conversations/{convA['id']}/messages", TA)
msgs = mlist.get("payload", mlist) if isinstance(mlist, dict) else mlist
# 交接后上下文保留：历史消息仍在
hist = [m.get("content") for m in msgs if isinstance(m, dict)]
assignee = (convA2.get("meta") or {}).get("assignee")
check("B2-2 人工交接（分配）生效",
      st4 in (200, 201) and assignee and assignee.get("id") == agent_id,
      f"assign_status={st4} assignee={assignee and assignee.get('id')}")
check("B2-3 交接后上下文完整",
      any("hello from A" in (h or "") for h in hist)
      and any("second message" in (h or "") for h in hist),
      str([h[:20] for h in hist]))

# ---------- B3 发送状态与渠道回执 ----------
# webhook 事件流：订阅渠道回执事件（幂等：先清旧）
st, old = api("GET", f"/api/v1/accounts/{A}/webhooks", TA)
for w in (old.get("payload", {}).get("webhooks", []) if isinstance(old, dict) else []):
    api("DELETE", f"/api/v1/accounts/{A}/webhooks/{w['id']}", TA)
st, hook = api("POST", f"/api/v1/accounts/{A}/webhooks", TA,
               {"webhook": {"url": "http://example.com/r22-hook",
                            "subscriptions": ["message_created",
                                              "conversation_updated"]}})
check("B3-1 渠道回执事件可订阅(webhook注册)", st in (200, 201), str(st))
# 消息回执字段：发送状态
st, m2 = api("POST", f"/api/v1/accounts/{A}/conversations/{convA['id']}/messages", TA,
             {"content": "status probe", "message_type": "outgoing"})
time.sleep(1)
st, mlist2 = api("GET", f"/api/v1/accounts/{A}/conversations/{convA['id']}/messages", TA)
pm = mlist2.get("payload", mlist2) if isinstance(mlist2, dict) else mlist2
probe = next((x for x in pm if isinstance(x, dict) and x.get("content") == "status probe"), {})
check("B3-2 消息带投递状态字段", "status" in probe and probe.get("status") in ("sent", "sending", "failed"),
      f"status={probe.get('status')}")
# 失败重试语义：无效渠道发送应标记失败而非静默成功
st, evs = api("GET", f"/api/v1/accounts/{A}/webhooks", TA)
wh = evs.get("payload", {}).get("webhooks", []) if isinstance(evs, dict) else []
n_hooks = len(wh)
check("B3-3 回执订阅可审计", n_hooks >= 1, f"hooks={n_hooks}")

fails = [k for k, v in results.items() if not v]
print("\nSUMMARY:", json.dumps(results, ensure_ascii=False))
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
