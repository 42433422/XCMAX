#!/usr/bin/env python3
"""E2E: admin mobile -> cloud relay -> desktop Cursor CLI -> reply.

Requires desktop relay poller running (see start_desktop_relay_poller.sh).
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime

import httpx

BASE = "https://xiu-ci.com/fhd-api"
FRESH_SEC = 5 * 60


def _sort_key(row: dict) -> str:
    return str(row.get("last_seen_at") or row.get("updated_at") or row.get("paired_at") or "")


def _is_fresh(row: dict) -> bool:
    raw = str(row.get("last_seen_at") or row.get("updated_at") or "").strip()
    if not raw:
        return False
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    age = (datetime.now(UTC) - dt).total_seconds()
    return age <= FRESH_SEC


def pick_relay_id(items: list[dict]) -> str:
    paired = [r for r in items if r.get("status") == "paired" and r.get("relay_id")]
    fresh = [r for r in paired if _is_fresh(r)]
    if not fresh:
        return ""
    fresh.sort(key=_sort_key)
    return str(fresh[-1]["relay_id"])


def main() -> int:
    message = " ".join(sys.argv[1:]).strip() or "1+1等于几，只回答数字"
    login = httpx.post(
        f"{BASE}/api/mobile/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
        timeout=30,
    ).json()
    token = login["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    desktops = httpx.get(
        f"{BASE}/api/mobile/v1/relay/mobile/desktops", headers=headers, timeout=30
    ).json()
    items = (desktops.get("data") or {}).get("items") or []
    relay_id = pick_relay_id(items)
    if not relay_id:
        print("FAIL: no fresh paired desktop (start desktop relay poller first)", file=sys.stderr)
        return 1
    print(f"relay_id={relay_id}")

    create = httpx.post(
        f"{BASE}/api/mobile/v1/relay/tasks",
        headers=headers,
        json={
            "relay_id": relay_id,
            "kind": "cursor.invoke",
            "payload": {
                "message": message,
                "workspace_root": "/Users/a4243342/Desktop/XCMAX",
                "context": {"client_surface": "mobile", "conversation_id": "super-employee-cursor"},
            },
        },
        timeout=30,
    ).json()
    task_id = create["data"]["task"]["task_id"]
    print(f"task_id={task_id} status={create['data']['task']['status']}")

    for i in range(90):
        time.sleep(2)
        st = httpx.get(
            f"{BASE}/api/mobile/v1/relay/tasks/{task_id}", headers=headers, timeout=30
        ).json()
        task = st.get("data", {}).get("task") or {}
        status = task.get("status")
        if i % 5 == 0:
            print(f"poll[{i}] status={status}")
        if status in ("completed", "done", "failed", "blocked", "cancelled"):
            result = task.get("result") or {}
            codex = result.get("codex") or {}
            body = (
                (codex.get("assistant_message") or {}).get("body")
                or result.get("reply")
                or result.get("error")
                or ""
            )
            print(f"FINAL status={status}")
            print(f"BODY={body[:500]}")
            return 0 if status == "completed" and body.strip() else 2

    print("FAIL: timeout waiting for relay task", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
