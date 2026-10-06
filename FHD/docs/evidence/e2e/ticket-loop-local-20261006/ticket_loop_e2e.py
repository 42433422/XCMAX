"""Cross-process run of the customer ticket loop: FHD desktop backend + MODstore, both local.

Every step goes over HTTP through the same routes the desktop client, the admin console
and the release pipeline use. Prints one JSON line per step and exits non-zero on the
first broken expectation.

Processes (all SQLite, see run.jsonl topology line for the exact commit):
  MODstore   uvicorn modstore_server.app:app --port 8765  MODSTORE_DB_PATH, MODSTORE_JWT_SECRET,
             MODSTORE_PYTEST_USE_SQLITE=1, MODSTORE_RUN_BACKGROUND_JOBS=0
  FHD desk   uvicorn run:app --port 17500  XCAGI_DESKTOP_MODE=1, XCAGI_DATA_DIR, XCAGI_MODS_ROOT
             (a copy of FHD/mods: entitled industry Mods are seeded into it),
             XCAGI_MARKET_BASE_URL=http://127.0.0.1:8765
  FHD web    uvicorn run:app --port 5000   same market URL, DATABASE_URL=sqlite:///...,
             WORK_ORDER_MARKET_BASE=http://127.0.0.1:8765, WORK_ORDER_MARKET_TOKEN=<owner JWT>
Accounts: e2e_customer / e2e_other with an active saas-trial-30 UserPlan, e2e_owner is_admin.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sys
import time
import uuid
import zipfile

import httpx
from PIL import Image

# Customers use the desktop-mode backend; the admin console only runs on the web backend.
FHD_DESKTOP = "http://127.0.0.1:17500"
FHD_WEB = "http://127.0.0.1:5000"
MARKET = "http://127.0.0.1:8765"
PASSWORD = "E2e-pass-2026!"
RUN = uuid.uuid4().hex[:8]


def step(name: str, ok: bool, **facts) -> None:
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "step": name,
        "ok": ok,
        **facts,
    }
    print(json.dumps(row, ensure_ascii=False), flush=True)
    if not ok:
        sys.exit(1)


def fhd_session(username: str, base: str = FHD_DESKTOP, kind: str = "enterprise") -> httpx.Client:
    client = httpx.Client(base_url=base, timeout=180)
    body = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD, "account_kind": kind}
    ).json()
    step(
        f"fhd_login:{username}",
        body.get("success") is True,
        tenant_id=body.get("tenant_id"),
        market_admin=body.get("market_is_admin"),
    )
    client.headers["X-Session-ID"] = body["session_id"]
    client.get("/api/auth/me")
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token") or ""
    return client


def market_token(username: str) -> str:
    body = httpx.post(
        f"{MARKET}/api/auth/login", json={"username": username, "password": PASSWORD}
    ).json()
    return body["access_token"]


def screenshot_png() -> bytes:
    out = io.BytesIO()
    Image.linear_gradient("L").resize((1920, 1080)).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def owner_work_order(owner: httpx.Client, wo_id: str) -> dict:
    items = owner.get("/api/ops/autonomy/work-orders").json().get("items") or []
    return next((item for item in items if item.get("wo_id") == wo_id), {})


def transition(token: str, wo_id: str, to_state: str, ref: dict) -> dict:
    return httpx.post(
        f"{MARKET}/api/work-orders/transition",
        headers={"Authorization": f"Bearer {token}"},
        json={"wo_id": wo_id, "to_state": to_state, "ref": ref, "source": "release_pipeline"},
    ).json()


def decide(
    client: httpx.Client, ticket_id: int, decision: str, note: str, key: str
) -> httpx.Response:
    return client.post(
        f"/api/mod-store/issue-runtime/{ticket_id}/decision",
        json={"decision": decision, "note": note, "idempotency_key": key},
    )


def main() -> None:
    customer = fhd_session("e2e_customer")
    png = screenshot_png()
    message = f"[{RUN}] 导出考勤表时报错。期望：点击导出后下载考勤表 Excel。实际：页面提示导出失败，没有生成文件。"
    attachments = [
        {
            "kind": "image",
            "filename": "export-error.png",
            "mime_type": "image/png",
            "data_url": "data:image/png;base64," + base64.b64encode(png).decode(),
        }
    ]
    reply = ""
    with customer.stream(
        "POST",
        "/api/ai/chat/stream",
        json={
            "message": message,
            "context": {"multimodal_attachments": attachments},
            "source": "desktop",
        },
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip() or "{}")
                if event.get("type") == "token":
                    reply += str(event.get("text") or "")
    wo_id = (re.search(r"Work Order：(\S+?)，", reply) or [None, ""])[1]
    ticket_no = (re.search(r"市场工单：(\S+?)。", reply) or [None, ""])[1]
    sha = (re.search(r"SHA256：([0-9a-f]{64})", reply) or [None, ""])[1]
    step(
        "chat_report_routed",
        bool(wo_id and ticket_no and sha) and "支持包已附截图 1/1 张" in reply,
        screenshot_png_bytes=len(png),
        reply=reply,
    )

    customer_token = market_token("e2e_customer")
    mine = httpx.get(
        f"{MARKET}/api/customer-service/issues/mine",
        headers={"Authorization": f"Bearer {customer_token}"},
    ).json()["items"]
    issue = next(row for row in mine if row["ticket_no"] == ticket_no)
    ticket_id = int(issue["id"])
    step(
        "market_ticket_created",
        issue["status"] not in {"resolved", "closed"},
        ticket_id=ticket_id,
        status=issue["status"],
        state=issue["state"],
        can_resolve=issue["can_resolve"],
        can_reopen=issue["can_reopen"],
    )

    owner = fhd_session("e2e_owner", FHD_WEB, "admin")
    view = owner_work_order(owner, wo_id)
    step(
        "owner_sees_routed_work_order",
        view.get("status") == "routed"
        and view.get("gates", {}).get("intake") == "ROUTED"
        and view.get("gates", {}).get("evidence") == "COLLECTED",
        status=view.get("status"),
        gates=view.get("gates"),
        source=view.get("source"),
    )

    detail = owner.get(f"/api/xcmax/market-proxy/customer-service/tickets/{ticket_id}").json()
    evidence = (detail.get("ticket") or {}).get("evidence") or {}
    bundle = base64.b64decode(evidence.get("support_bundle_base64") or "")
    digest = hashlib.sha256(bundle).hexdigest()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        with Image.open(io.BytesIO(archive.read("screenshots/1.jpg"))) as shot:
            shot_size = shot.size
    step(
        "owner_bundle_verified",
        digest == sha == evidence.get("support_bundle_sha256")
        and len(bundle) <= 256_000
        and manifest.get("screenshots") == {"selected": 1, "included": 1}
        and max(shot_size) <= 1600,
        bundle_bytes=len(bundle),
        sha256=digest,
        entries=names,
        screenshot_size=shot_size,
    )

    owner_token = market_token("e2e_owner")
    for to_state, ref in (
        ("in_dev", {"branch": f"cursor/e2e-{RUN}"}),
        ("merged", {"merge_sha": "f" * 40}),
        ("released", {"release_version": "1.0.0.5", "git_sha": "f" * 40}),
    ):
        moved = transition(owner_token, wo_id, to_state, ref)
        step(f"pipeline_{to_state}", moved.get("ok") is True, result=moved)

    other = fhd_session("e2e_other")
    denied = decide(other, ticket_id, "resolved", "我来关掉别人的工单", uuid.uuid4().hex)
    step(
        "other_customer_cannot_decide",
        denied.status_code >= 400 and "原工单不存在" in denied.text,
        http=denied.status_code,
        message=denied.json().get("message"),
    )

    listing = customer.get("/api/mod-store/issue-runtime").json()
    row = next(item for item in listing["data"]["items"] if item["id"] == ticket_id)
    step(
        "desktop_lists_own_issue",
        row["can_resolve"] is True,
        status=row["status"],
        state=row["state"],
        lifecycle=row["lifecycle_label"],
        ready=row["ready"],
    )

    resolve_key = uuid.uuid4().hex
    resolved = decide(customer, ticket_id, "resolved", "重新导出后考勤表已正常下载", resolve_key)
    replay = decide(customer, ticket_id, "resolved", "重新导出后考勤表已正常下载", resolve_key)
    issue = resolved.json()["data"]["issue"]
    step(
        "customer_resolved",
        resolved.status_code == 200
        and issue["status"] == "resolved"
        and replay.json()["data"]["replayed"] is True
        and issue["can_reopen"] is True,
        status=issue["status"],
        state=issue["state"],
        replayed=replay.json()["data"]["replayed"],
    )
    view = owner_work_order(owner, wo_id)
    step(
        "work_order_closed_by_customer",
        view.get("status") == "closed"
        and view.get("gates", {}).get("customer_decision") == "RESOLVED",
        status=view.get("status"),
        gates=view.get("gates"),
    )

    reopen_key = uuid.uuid4().hex
    reopened = decide(customer, ticket_id, "reopen", "隔天再次导出又提示失败", reopen_key)
    conflict = decide(customer, ticket_id, "reopen", "换一个说法再提交一次", reopen_key)
    issue = reopened.json()["data"]["issue"]
    step(
        "customer_reopened",
        reopened.status_code == 200
        and issue["status"] == "processing"
        and issue["state"] == "reopened"
        and issue["reopen_count"] == 1
        and conflict.status_code >= 400
        and "同一操作标识" in conflict.text,
        status=issue["status"],
        state=issue["state"],
        reopen_count=issue["reopen_count"],
        conflict_http=conflict.status_code,
        conflict_message=conflict.json().get("message"),
    )
    view = owner_work_order(owner, wo_id)
    step(
        "work_order_reopened",
        view.get("status") == "reopened"
        and view.get("gates", {}).get("customer_decision") == "REOPENED",
        status=view.get("status"),
    )

    redo = transition(owner_token, wo_id, "in_dev", {"branch": f"cursor/e2e-{RUN}-reopen"})
    step("pipeline_picks_reopened_work_order", redo.get("ok") is True, result=redo)

    detail = owner.get(f"/api/xcmax/market-proxy/customer-service/tickets/{ticket_id}").json()
    audits = [row.get("event_type") for row in detail.get("audit_logs") or []]
    history = [
        (row.get("event"), row.get("to") or (row.get("ref") or {}).get("gate"))
        for row in owner_work_order(owner, wo_id).get("history") or []
    ]
    step(
        "owner_timeline",
        {"customer_issue_resolved", "customer_issue_reopen"} <= set(audits)
        and ("transition", "closed") in history
        and ("transition", "reopened") in history,
        audit_events=audits,
        work_order_history=history,
    )


if __name__ == "__main__":
    main()
