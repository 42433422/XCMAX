#!/usr/bin/env python3
"""Authenticated API closed-loop probes for each sidebar domain (correct primary paths)."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

SESSION = os.environ.get("XCAGI_SESSION_ID", "58f95427-7d27-4fe5-89de-5b2f39d98a44")
BASE = os.environ.get("XCAGI_API_BASE", "http://127.0.0.1:17500")
EV = Path(__file__).resolve().parent


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def req(path: str, method: str = "GET", body: dict | None = None, csrf: str | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Cookie", f"session_id={SESSION}" + (f"; csrf_token={csrf}" if csrf else ""))
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if csrf and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        request.add_header("X-CSRF-Token", csrf)
    try:
        with _opener().open(request, timeout=60) as resp:
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


def _extract_csrf(me_payload) -> str | None:
    if not isinstance(me_payload, dict):
        return None
    # cookie probe via /api/auth/me response headers isn't available here; use env
    return os.environ.get("XCAGI_CSRF_TOKEN") or None


def main() -> None:
    me = req("/api/auth/me")
    print("auth", me.get("status"), preview(me.get("data")))
    csrf = _extract_csrf(me.get("data"))

    stamp = int(time.time()) % 100000
    pages = [
        (
            "智能对话",
            [
                ("GET", "/api/auth/me"),
                ("POST", "/api/ai/chat", {"message": f"闭环：ping {stamp}"}),
                ("POST", "/api/chat/send", {"message": f"闭环：alias {stamp}"}),
                (
                    "POST",
                    f"/api/conversations/cl{stamp}/messages",
                    {"content": f"闭环探测消息{stamp}", "role": "user"},
                ),
                ("GET", f"/api/conversations/cl{stamp}"),
            ],
        ),
        (
            "信息",
            [
                ("GET", "/api/im/conversations"),
                ("GET", "/api/im/contacts"),
            ],
        ),
        (
            "智能生态",
            [
                ("GET", "/api/platform-shell/capabilities"),
                ("GET", "/api/mods/"),
                ("GET", "/api/mods/routes"),
            ],
        ),
        (
            "知识库",
            [
                ("GET", "/api/knowledge/v1/health"),
                ("GET", "/api/knowledge/v1/datasets"),
                ("GET", "/api/persy/knowledge"),
                ("GET", "/api/knowledge"),
            ],
        ),
        (
            "员工工作台",
            [
                ("GET", "/api/system/workflow-employee-catalog"),
                ("GET", "/api/workflow-employee-space/overview"),
                ("GET", "/api/mod/xcagi-core-workflow-employees/status"),
            ],
        ),
        (
            "业务对象",
            [
                ("GET", "/api/erp/products/list"),
                ("GET", "/api/products/list"),
            ],
        ),
        (
            "组织管理",
            [
                ("GET", "/api/customers/list"),
                ("GET", "/api/customers"),
            ],
        ),
        (
            "业务单据",
            [
                ("GET", "/api/orders"),
                ("GET", "/api/orders/today"),
            ],
        ),
        (
            "业务记录",
            [
                ("GET", "/api/shipment/shipment-records/units"),
                ("GET", "/api/mod/xcagi-erp-domain-bridge/status"),
            ],
        ),
        (
            "资源库",
            [
                ("GET", "/api/materials"),
            ],
        ),
        (
            "数据来源",
            [
                ("GET", "/api/data-sources"),
                ("GET", "/api/wechat_contacts/decrypt_status"),
            ],
        ),
        (
            "模板与打印",
            [
                ("GET", "/api/templates"),
                ("GET", "/api/excel/templates"),
                ("GET", "/api/print/templates"),
            ],
        ),
        (
            "打印机列表",
            [
                ("GET", "/api/printers"),
                ("GET", "/api/print/printers"),
            ],
        ),
        (
            "系统设置",
            [
                ("GET", "/api/system/industry"),
                ("GET", "/api/mods/"),
                ("GET", "/api/desktop/status"),
            ],
        ),
    ]

    results = []
    for label, calls in pages:
        call_res = []
        for item in calls:
            method, path = item[0], item[1]
            body = item[2] if len(item) > 2 else None
            response = req(path, method, body, csrf=csrf)
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
    name = f"闭环组织{code}"
    before = req("/api/customers/list")
    created = req("/api/customers", "POST", {"name": name, "code": code}, csrf=csrf)
    after = req("/api/customers/list")
    after_root = req("/api/customers")

    def _items(payload):
        data = payload.get("data")
        if isinstance(data, dict):
            items = data.get("items") or data.get("data") or []
            if isinstance(items, list):
                return items
            return []
        if isinstance(data, list):
            return data
        return []

    before_items = _items(before)
    after_items = _items(after)
    root_items = _items(after_root)
    found = any(code in json.dumps(item, ensure_ascii=False) or name in json.dumps(item, ensure_ascii=False) for item in after_items)
    found_root = any(code in json.dumps(item, ensure_ascii=False) or name in json.dumps(item, ensure_ascii=False) for item in root_items)
    biz = {
        "create_ok": bool(created.get("ok")),
        "create_status": created.get("status"),
        "list_ok": bool(after.get("ok")),
        "found_in_list": found,
        "found_in_root_get": found_root,
        "before_count": len(before_items),
        "after_count": len(after_items),
        "root_count": len(root_items),
        "create_preview": preview(created.get("data")),
    }
    print("BIZ_LOOP", json.dumps(biz, ensure_ascii=False))

    printers = req("/api/printers")
    pdata = printers.get("data") if isinstance(printers.get("data"), dict) else {}
    if not pdata and isinstance(printers.get("data"), dict) is False:
        # /api/printers JSONResponse may flatten count/printers at top of parsed body
        raw = printers.get("data")
        pdata = raw if isinstance(raw, dict) else {}
    # When FastAPI JSONResponse returns flat body, req stores whole JSON as data
    if isinstance(printers.get("data"), dict) and "printers" in printers["data"]:
        pdata = printers["data"]
    elif isinstance(printers.get("data"), dict) and "count" in printers["data"]:
        pdata = printers["data"]
    printer_loop = {
        "ok": bool(printers.get("ok")),
        "count": pdata.get("count") if isinstance(pdata, dict) else None,
        "preview": preview(printers.get("data")),
    }
    if printer_loop["count"] is None and isinstance(printers.get("data"), dict):
        printer_loop["count"] = len(printers["data"].get("printers") or [])

    out = {
        "summary": {
            "auth_ok": bool(me.get("ok")),
            "total_pages": len(results),
            "ok_pages": sum(1 for row in results if row["ok"]),
            "fail_pages": [row["label"] for row in results if not row["ok"]],
            "business_customer_loop": biz,
            "printer_loop": printer_loop,
            "note": "Primary paths aligned with frontend; aliases covered for discovery probes",
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
        f"组织创建闭环：create={biz['create_ok']} found_list={biz['found_in_list']} found_root={biz['found_in_root_get']} after={biz['after_count']}",
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
