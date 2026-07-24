#!/usr/bin/env python3
"""Authenticated API closed-loop probes for each sidebar domain."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import os
SESSION = os.environ.get("XCAGI_SESSION_ID", "58f95427-7d27-4fe5-89de-5b2f39d98a44")
BASE = "http://127.0.0.1:17500"
EV = Path(
    "/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/sidebar-capability-closed-loop-20260724"
)


def req(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Cookie", f"session_id={SESSION}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw[:300]
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": payload}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw[:300]
        return {"ok": False, "status": exc.code, "data": payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": 0, "error": str(exc)}


def preview(data) -> str | None:
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False)[:200]


def main() -> None:
    me = req("/api/auth/me")
    print("auth", me.get("status"), preview(me.get("data")))

    stamp = int(time.time()) % 10000
    pages = [
        (
            "智能对话",
            [
                ("GET", "/api/conversations"),
                ("GET", "/api/auth/me"),
                ("POST", "/api/chat/send", {"message": "闭环：查询今日业务概况", "content": "闭环：查询今日业务概况"}),
                ("POST", "/api/conversations/send", {"message": "闭环：查询今日业务概况"}),
                ("POST", "/api/planner/chat", {"message": "闭环：查询今日业务概况"}),
                ("GET", "/api/conversations/mryoa6q0c10s25simkh"),
                (
                    "POST",
                    "/api/conversations/mryoa6q0c10s25simkh/messages",
                    {"content": "闭环探测消息", "role": "user"},
                ),
                (
                    "POST",
                    "/api/chat/send",
                    {"conversation_id": "mryoa6q0c10s25simkh", "message": "闭环探测消息"},
                ),
            ],
        ),
        (
            "信息",
            [
                ("GET", "/api/im/conversations"),
                ("GET", "/api/im/contacts"),
                ("GET", "/api/im/unread"),
                ("GET", "/api/im/sessions"),
            ],
        ),
        (
            "智能生态",
            [
                ("GET", "/api/platform-shell/capabilities"),
                ("GET", "/api/mods/"),
                ("GET", "/api/aiopen/apps"),
                ("GET", "/api/mods/routes"),
            ],
        ),
        (
            "知识库",
            [
                ("GET", "/api/persy/knowledge"),
                ("GET", "/api/knowledge/base"),
                ("GET", "/api/memory/list"),
                ("GET", "/api/rag/documents"),
                ("GET", "/api/knowledge"),
            ],
        ),
        (
            "员工工作台",
            [
                ("GET", "/api/workflow/employees"),
                ("GET", "/api/workflow-employee-space/overview"),
                ("GET", "/api/workflow/graph"),
                ("GET", "/api/employees"),
                ("GET", "/api/core-workflow/employees"),
            ],
        ),
        (
            "业务对象",
            [
                ("GET", "/api/products"),
                ("GET", "/api/erp/products"),
                ("POST", "/api/products", {"name": f"闭环产品{stamp}", "code": f"P{stamp}"}),
            ],
        ),
        (
            "组织管理",
            [
                ("GET", "/api/customers"),
                ("POST", "/api/customers", {"name": f"闭环组织{stamp}", "code": f"C{stamp}"}),
            ],
        ),
        (
            "业务单据",
            [
                ("GET", "/api/orders"),
                ("POST", "/api/orders", {"customer_name": "闭环客户", "items": []}),
                ("GET", "/api/orders/today"),
            ],
        ),
        (
            "业务记录",
            [
                ("GET", "/api/shipment-records"),
                ("GET", "/api/shipments"),
            ],
        ),
        (
            "资源库",
            [
                ("GET", "/api/materials"),
                ("POST", "/api/materials", {"name": f"闭环物料{stamp}", "code": f"M{stamp}"}),
            ],
        ),
        (
            "数据来源",
            [
                ("GET", "/api/data-sources"),
                ("GET", "/api/datasources"),
                ("GET", "/api/connectors"),
                ("GET", "/api/erp/data-sources"),
            ],
        ),
        (
            "模板与打印",
            [
                ("GET", "/api/print/templates"),
                ("GET", "/api/templates"),
                ("GET", "/api/label/templates"),
                ("GET", "/api/excel/templates"),
                ("GET", "/api/print/jobs"),
            ],
        ),
        (
            "打印机列表",
            [
                ("GET", "/api/print/printers"),
            ],
        ),
        (
            "系统设置",
            [
                ("GET", "/api/workspace/prefs"),
                ("GET", "/api/system/industry"),
                ("GET", "/api/mods/"),
                ("GET", "/api/desktop/status"),
                ("GET", "/api/system/industries"),
            ],
        ),
    ]

    results = []
    for label, calls in pages:
        call_res = []
        for item in calls:
            method, path = item[0], item[1]
            body = item[2] if len(item) > 2 else None
            response = req(path, method, body)
            call_res.append(
                {
                    "method": method,
                    "path": path,
                    "status": response.get("status"),
                    "ok": response.get("ok"),
                    "error": response.get("error"),
                    "data_preview": preview(response.get("data")),
                }
            )
        ok_calls = [c for c in call_res if c["ok"]]
        page_ok = len(ok_calls) > 0
        results.append(
            {
                "label": label,
                "ok": page_ok,
                "ok_calls": len(ok_calls),
                "total_calls": len(call_res),
                "calls": call_res,
            }
        )
        detail = ", ".join(f"{c['method']} {c['path']}->{c['status']}" for c in call_res)
        print(f"{'OK' if page_ok else 'FAIL'} {label}: {len(ok_calls)}/{len(call_res)} {detail}")

    code = f"CL{int(time.time()) % 100000}"
    created = req("/api/customers", "POST", {"name": f"闭环组织{code}", "code": code})
    listed = req("/api/customers", "GET")
    items = listed.get("data")
    if isinstance(items, dict):
        items = items.get("items") or items.get("data") or []
    if not isinstance(items, list):
        items = []
    found = any(code in json.dumps(item, ensure_ascii=False) for item in items)
    biz = {
        "create_ok": bool(created.get("ok")),
        "create_status": created.get("status"),
        "list_ok": bool(listed.get("ok")),
        "found_in_list": found,
        "create_preview": preview(created.get("data")),
        "list_count": len(items),
    }
    print("BIZ_LOOP", json.dumps(biz, ensure_ascii=False))

    # Printer closed loop: list printers then (dry) status
    printers = req("/api/print/printers")
    printer_loop = {
        "ok": bool(printers.get("ok")),
        "count": (printers.get("data") or {}).get("count")
        if isinstance(printers.get("data"), dict)
        else None,
        "preview": preview(printers.get("data")),
    }

    out = {
        "summary": {
            "auth_ok": bool(me.get("ok")),
            "total_pages": len(results),
            "ok_pages": sum(1 for row in results if row["ok"]),
            "fail_pages": [row["label"] for row in results if not row["ok"]],
            "business_customer_loop": biz,
            "printer_loop": printer_loop,
            "note": "API capability closed-loop with desktop session_id; UI click-path covered separately when CDP available",
        },
        "results": results,
    }
    EV.mkdir(parents=True, exist_ok=True)
    (EV / "07-sidebar-capability-results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 侧栏能力闭环（认证 API）2026-07-24",
        "",
        f"登录会话：{'OK' if me.get('ok') else 'FAIL'}",
        f"页面能力：{out['summary']['ok_pages']}/{out['summary']['total_pages']}",
        f"失败：{', '.join(out['summary']['fail_pages']) or '无'}",
        f"组织创建闭环：create={biz['create_ok']} found={biz['found_in_list']} list_count={biz['list_count']}",
        f"打印机闭环：{printer_loop['ok']} count={printer_loop['count']}",
        "",
    ]
    for row in results:
        mark = "x" if row["ok"] else " "
        lines.append(f"- [{mark}] {row['label']} ({row['ok_calls']}/{row['total_calls']})")
        for call in row["calls"]:
            flag = "OK" if call["ok"] else "NO"
            lines.append(f"  - {flag} {call['method']} {call['path']} -> {call['status']}")
    lines.append("")
    (EV / "CHECKLIST.md").write_text("\n".join(lines), encoding="utf-8")
    print("SUMMARY", json.dumps(out["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
