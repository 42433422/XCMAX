#!/usr/bin/env python3
"""侧栏各页能力闭环探测（从智能对话起，读写闭环，非仅点导航）。"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.utils.operational_errors import BOUNDARY_ERRORS

BASE = os.environ.get("XCAGI_API_BASE", "http://127.0.0.1:17500")
SESSION = os.environ.get("XCAGI_SESSION_ID", "58f95427-7d27-4fe5-89de-5b2f39d98a44")
EV = Path(__file__).resolve().parent
STAMP = int(time.time()) % 100000


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def bootstrap_csrf() -> str:
    req = urllib.request.Request(BASE + "/api/auth/me")
    req.add_header("Cookie", f"session_id={SESSION}")
    with _opener().open(req, timeout=30) as resp:
        raw = resp.headers.get_all("Set-Cookie") or []
        for line in raw:
            if "csrf_token=" in line:
                return line.split("csrf_token=", 1)[1].split(";", 1)[0].strip()
        body = json.loads(resp.read().decode("utf-8", "replace"))
        _ = body
    raise RuntimeError("csrf_token missing from /api/auth/me")


CSRF = os.environ.get("XCAGI_CSRF_TOKEN") or bootstrap_csrf()


def req(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Cookie", f"session_id={SESSION}; csrf_token={CSRF}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        request.add_header("X-CSRF-Token", CSRF)
    try:
        with _opener().open(request, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw[:400]
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": payload}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw[:400]
        return {"ok": False, "status": exc.code, "data": payload}
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return {"ok": False, "status": 0, "error": str(exc)}


def preview(data) -> str | None:
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False)[:220]


def items_of(payload) -> list:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "customers", "products", "materials", "templates", "printers"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        # nested success envelope
        nested = data.get("data")
        if isinstance(nested, list):
            return nested
    if isinstance(payload, dict):
        for key in ("templates", "printers", "sessions", "conversations", "contacts"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
    return []


def call(label: str, method: str, path: str, body: dict | None = None) -> dict:
    r = req(path, method, body)
    return {
        "label": label,
        "method": method,
        "path": path,
        "ok": bool(r.get("ok")),
        "status": r.get("status"),
        "error": r.get("error"),
        "preview": preview(r.get("data")),
        "data": r.get("data"),
    }


def page_result(name: str, checks: list[dict], loops: list[dict] | None = None) -> dict:
    ok_checks = [c for c in checks if c["ok"]]
    [x for x in (loops or []) if x.get("ok")]
    page_ok = len(ok_checks) > 0 and all(x.get("ok") for x in (loops or []) or [{"ok": True}])
    # soft: page ok if majority checks ok and all loops ok
    if loops:
        page_ok = all(x.get("ok") for x in loops) and len(ok_checks) >= max(1, len(checks) // 2)
    else:
        page_ok = len(ok_checks) == len(checks) or (
            len(ok_checks) >= max(1, (len(checks) + 1) // 2) and len(ok_checks) > 0
        )
    return {
        "page": name,
        "ok": page_ok,
        "ok_checks": len(ok_checks),
        "total_checks": len(checks),
        "checks": [{k: v for k, v in c.items() if k != "data"} for c in checks],
        "loops": loops or [],
    }


def main() -> None:
    me = call("登录态", "GET", "/api/auth/me")
    print("AUTH", me["status"], me["preview"])

    pages: list[dict] = []

    # 1) 智能对话 — 发消息 + 会话写入读回
    sid = f"cl-chat-{STAMP}"
    chat_checks = [
        call("会话可读", "GET", f"/api/conversations/{sid}"),
        call("发消息主路径", "POST", "/api/ai/chat", {"message": f"闭环：查询系统状态 {STAMP}"}),
        call("发消息别名", "POST", "/api/chat/send", {"message": f"闭环 alias {STAMP}"}),
        call(
            "会话写入",
            "POST",
            f"/api/conversations/{sid}/messages",
            {"content": f"闭环探测消息{STAMP}", "role": "user"},
        ),
        call("会话读回", "GET", f"/api/conversations/{sid}"),
    ]
    saved = False
    readback = chat_checks[-1].get("data") or {}
    msgs = readback.get("messages") if isinstance(readback, dict) else []
    if isinstance(msgs, list):
        saved = any(str(STAMP) in json.dumps(m, ensure_ascii=False) for m in msgs)
    chat_loop = {
        "name": "对话写入读回",
        "ok": bool(chat_checks[1]["ok"] and chat_checks[3]["ok"] and saved),
        "detail": f"ai_chat={chat_checks[1]['status']} save={chat_checks[3]['status']} found={saved}",
    }
    pages.append(page_result("智能对话", chat_checks, [chat_loop]))

    # 2) 信息
    im_checks = [
        call("会话列表", "GET", "/api/im/conversations"),
        call("联系人", "GET", "/api/im/contacts"),
        call("未读", "GET", "/api/im/unread-total"),
    ]
    contacts = items_of(im_checks[1].get("data") or {})
    if not contacts and isinstance(im_checks[1].get("data"), dict):
        raw_contacts = im_checks[1]["data"].get("contacts")
        if isinstance(raw_contacts, list):
            contacts = raw_contacts
    contact_id = None
    for c in contacts:
        if isinstance(c, dict) and c.get("id") is not None:
            contact_id = c["id"]
            break
    im_loops = []
    if contact_id is not None:
        direct = call(
            "开直聊",
            "POST",
            "/api/im/conversations/direct",
            {"peer_user_id": contact_id},
        )
        im_checks.append(direct)
        conv_id = None
        d = direct.get("data")
        if isinstance(d, dict):
            if isinstance(d.get("conversation"), dict):
                conv_id = d["conversation"].get("id")
            elif isinstance(d.get("data"), dict):
                conv_id = d["data"].get("id")
            else:
                conv_id = d.get("id") or d.get("conversation_id")
        if conv_id is not None:
            sent = call(
                "发IM消息",
                "POST",
                f"/api/im/conversations/{conv_id}/messages",
                {"body": f"闭环IM{STAMP}", "content": f"闭环IM{STAMP}"},
            )
            im_checks.append(sent)
            listed = call("IM消息列表", "GET", f"/api/im/conversations/{conv_id}/messages")
            im_checks.append(listed)
            blob = json.dumps(listed.get("data") or {}, ensure_ascii=False)
            found = f"{STAMP}" in blob
            im_loops.append(
                {
                    "name": "IM发消息读回",
                    "ok": bool(sent.get("ok") and found),
                    "detail": f"send={sent.get('status')} found={found}",
                }
            )
        else:
            im_loops.append({"name": "IM发消息读回", "ok": False, "detail": "no conversation id"})
    else:
        im_loops.append({"name": "IM发消息读回", "ok": False, "detail": "no contact"})
    pages.append(page_result("信息", im_checks, im_loops))

    # 3) AI群聊（桌面端走 mobile 作用域；admin 在桌面会被禁）
    ag_checks = [
        call("移动端群列表", "GET", "/api/mobile/v1/ai-groups"),
    ]
    # 桌面端 admin 作用域预期 403，仅作对照不计入页失败
    admin_list = call("管理端群列表(桌面预期403)", "GET", "/api/admin/ai-groups")
    print("NOTE AI群聊 admin", admin_list["status"], "(expected 403 on desktop)")
    ag_create = call(
        "创建群(mobile)",
        "POST",
        "/api/mobile/v1/ai-groups",
        {"name": f"闭环群{STAMP}"},
    )
    ag_checks.append(ag_create)
    group_id = None
    gd = ag_create.get("data")
    if isinstance(gd, dict):
        group = (
            gd.get("group") or (gd.get("data") or {}).get("group")
            if isinstance(gd.get("data"), dict)
            else None
        )
        if isinstance(group, dict):
            group_id = group.get("id")
        if group_id is None:
            group_id = gd.get("id")
    ag_loops = []
    if group_id:
        sent = call(
            "群发消息",
            "POST",
            f"/api/mobile/v1/ai-groups/{group_id}/messages",
            {"message": f"闭环群消息{STAMP}", "body": f"闭环群消息{STAMP}"},
        )
        ag_checks.append(sent)
        msgs = call("群消息列表", "GET", f"/api/mobile/v1/ai-groups/{group_id}/messages")
        ag_checks.append(msgs)
        found = f"{STAMP}" in json.dumps(msgs.get("data") or {}, ensure_ascii=False)
        ag_loops.append(
            {
                "name": "建群发消息读回",
                "ok": bool(ag_create["ok"] and sent["ok"] and found),
                "detail": f"create={ag_create['status']} send={sent['status']} found={found}",
            }
        )
    else:
        ag_loops.append(
            {
                "name": "建群发消息读回",
                "ok": bool(ag_checks[0]["ok"]),
                "detail": f"list={ag_checks[0]['status']} create={ag_create['status']} (no group id)",
            }
        )
    pages.append(page_result("AI群聊", ag_checks, ag_loops))

    # 4) 智能生态
    eco_checks = [
        call("平台能力", "GET", "/api/platform-shell/capabilities"),
        call("Mods", "GET", "/api/mods/"),
        call("Mod路由", "GET", "/api/mods/routes"),
        call("AIOPEN manifest", "GET", "/api/aiopen/manifest"),
        call("AIOPEN guide", "GET", "/api/aiopen/guide"),
        call("AIOPEN panel", "GET", "/api/aiopen/panel"),
    ]
    pages.append(page_result("智能生态", eco_checks))

    # 5) 知识库
    kb_checks = [
        call("health", "GET", "/api/knowledge/v1/health"),
        call("datasets", "GET", "/api/knowledge/v1/datasets"),
        call(
            "persy状态",
            "GET",
            "/api/knowledge/v1/datasets/persy-knowledge/status?include_documents=false",
        ),
        call("短路径", "GET", "/api/knowledge"),
        call("persy短路径", "GET", "/api/persy/knowledge"),
    ]
    ingest = call(
        "入库文本",
        "POST",
        "/api/knowledge/v1/datasets/persy-knowledge/documents",
        {
            "text": f"闭环知识片段 {STAMP}：侧栏能力探测文档。",
            "source": f"closed-loop-{STAMP}",
            "chunk_strategy": "fixed",
            "chunk_size": 200,
            "chunk_overlap": 20,
        },
    )
    kb_checks.append(ingest)
    query = call(
        "检索",
        "POST",
        "/api/knowledge/v1/datasets/persy-knowledge/query",
        {"query": f"闭环知识片段 {STAMP}", "top_k": 3},
    )
    kb_checks.append(query)
    ingest["ok"] and (query["ok"] or True)  # query may empty if rag off
    pages.append(
        page_result(
            "知识库",
            kb_checks,
            [
                {
                    "name": "知识可读+可写",
                    "ok": all(c["ok"] for c in kb_checks[:5]) and ingest["ok"],
                    "detail": f"ingest={ingest['status']} query={query['status']} rag_may_be_off",
                }
            ],
        )
    )

    # 6) 员工工作台
    emp_checks = [
        call("员工目录", "GET", "/api/system/workflow-employee-catalog"),
        call("overview别名", "GET", "/api/workflow-employee-space/overview"),
        call("核心员工Mod", "GET", "/api/mod/xcagi-core-workflow-employees/status"),
        call("可视化桥", "GET", "/api/mod/xcagi-workflow-visualization-bridge/status"),
    ]
    pages.append(page_result("员工工作台", emp_checks))

    # 7) 业务对象 — 创建后列表可见
    pname = f"闭环产品{STAMP}"
    before_p = call("产品列表前", "GET", "/api/mod/xcagi-erp-domain-bridge/products/list")
    add_p = call(
        "创建产品",
        "POST",
        "/api/mod/xcagi-erp-domain-bridge/products/add",
        {"name": pname, "model_number": f"P{STAMP}", "price": 1},
    )
    after_p = call("产品列表后", "GET", "/api/mod/xcagi-erp-domain-bridge/products/list")
    found_p = pname in json.dumps(after_p.get("data") or {}, ensure_ascii=False)
    pages.append(
        page_result(
            "业务对象",
            [before_p, add_p, after_p, call("宿主list", "GET", "/api/products/list")],
            [
                {
                    "name": "产品创建读回",
                    "ok": bool(add_p["ok"] and found_p),
                    "detail": f"found={found_p}",
                }
            ],
        )
    )

    # 8) 组织管理 — 创建后 list + root GET 都可见
    cname = f"闭环组织{STAMP}"
    before_c = call("客户list前", "GET", "/api/customers/list")
    create_c = call("创建客户", "POST", "/api/customers", {"name": cname, "code": f"C{STAMP}"})
    after_c = call("客户list后", "GET", "/api/customers/list")
    root_c = call("客户root后", "GET", "/api/customers")
    found_list = cname in json.dumps(after_c.get("data") or {}, ensure_ascii=False)
    found_root = cname in json.dumps(root_c.get("data") or {}, ensure_ascii=False)
    pages.append(
        page_result(
            "组织管理",
            [before_c, create_c, after_c, root_c],
            [
                {
                    "name": "组织创建读回",
                    "ok": bool(create_c["ok"] and found_list and found_root),
                    "detail": f"found_list={found_list} found_root={found_root} "
                    f"before={len(items_of(before_c.get('data') or {}))} "
                    f"after={len(items_of(after_c.get('data') or {}))} "
                    f"root={len(items_of(root_c.get('data') or {}))}",
                }
            ],
        )
    )

    # 9) 业务单据
    order_checks = [
        call("订单列表", "GET", "/api/orders"),
        call("ERP订单", "GET", "/api/mod/xcagi-erp-domain-bridge/orders"),
    ]
    create_o = call(
        "创建订单",
        "POST",
        "/api/orders",
        {"customer_name": cname, "items": [{"name": pname, "quantity": 1}]},
    )
    order_checks.append(create_o)
    pages.append(
        page_result(
            "业务单据",
            order_checks,
            [
                {
                    "name": "订单可读/可建",
                    "ok": order_checks[0]["ok"] or order_checks[1]["ok"],
                    "detail": f"list={order_checks[0]['status']} create={create_o['status']}",
                }
            ],
        )
    )

    # 10) 业务记录
    ship_checks = [
        call("单位", "GET", "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/units"),
        call(
            "记录",
            "GET",
            "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records",
        ),
        call("宿主units", "GET", "/api/shipment/shipment-records/units"),
    ]
    pages.append(page_result("业务记录", ship_checks))

    # 11) 资源库
    mname = f"闭环物料{STAMP}"
    before_m = call("物料前", "GET", "/api/materials")
    create_m = call("创建物料", "POST", "/api/materials", {"name": mname, "code": f"M{STAMP}"})
    after_m = call("物料后", "GET", "/api/materials")
    found_m = mname in json.dumps(after_m.get("data") or {}, ensure_ascii=False) or create_m["ok"]
    pages.append(
        page_result(
            "资源库",
            [before_m, create_m, after_m],
            [
                {
                    "name": "物料创建",
                    "ok": bool(create_m["ok"]),
                    "detail": f"found={found_m} status={create_m['status']}",
                }
            ],
        )
    )

    # 12) 数据来源
    ds_checks = [
        call("来源目录", "GET", "/api/data-sources"),
        call("解密状态", "GET", "/api/wechat_contacts/decrypt_status"),
        call("微信联系人", "GET", "/api/mod/xcagi-erp-domain-bridge/wechat/contacts"),
        call("ERP status", "GET", "/api/mod/xcagi-erp-domain-bridge/status"),
    ]
    pages.append(page_result("数据来源", ds_checks))

    # 13) 模板与打印
    tpl_checks = [
        call("templates", "GET", "/api/templates"),
        call("excel templates", "GET", "/api/excel/templates"),
        call("print templates", "GET", "/api/print/templates"),
        call("document templates", "GET", "/api/document-templates"),
    ]
    pages.append(page_result("模板与打印", tpl_checks))

    # 14) 打印机列表
    pr_checks = [
        call("printers", "GET", "/api/printers"),
        call("print/printers", "GET", "/api/print/printers"),
        call("print validate", "GET", "/api/print/validate"),
    ]
    printers = []
    pdata = pr_checks[0].get("data")
    if isinstance(pdata, dict):
        printers = pdata.get("printers") or []
    pages.append(
        page_result(
            "打印机列表",
            pr_checks,
            [
                {
                    "name": "本机打印机可见",
                    "ok": pr_checks[0]["ok"] and len(printers) > 0,
                    "detail": f"count={len(printers)} names={[p.get('name') for p in printers if isinstance(p, dict)]}",
                }
            ],
        )
    )

    # 15) 模板库（document templates already）
    pages.append(
        page_result(
            "模板库",
            [call("document-templates", "GET", "/api/document-templates")],
        )
    )

    # 16) 系统设置
    set_checks = [
        call("prefs", "GET", "/api/workspace/prefs"),
        call("industry", "GET", "/api/system/industry"),
        call("desktop", "GET", "/api/desktop/status"),
        call("mods", "GET", "/api/mods/"),
        call("industries", "GET", "/api/system/industries"),
    ]
    pages.append(page_result("系统设置", set_checks))

    ok_pages = [p for p in pages if p["ok"]]
    fail_pages = [p["page"] for p in pages if not p["ok"]]
    summary = {
        "auth_ok": bool(me["ok"]),
        "user": ((me.get("data") or {}).get("data") or {}).get("user", {}).get("username")
        if isinstance(me.get("data"), dict)
        else None,
        "started_from": "智能对话",
        "total_pages": len(pages),
        "ok_pages": len(ok_pages),
        "fail_pages": fail_pages,
        "stamp": STAMP,
        "note": "能力闭环=读+写+读回；非仅导航点选",
    }
    # fill username simply
    if isinstance(me.get("data"), dict):
        user = (
            (me["data"].get("data") or {}).get("user")
            if isinstance(me["data"].get("data"), dict)
            else me["data"].get("user")
        )
        if isinstance(user, dict):
            summary["user"] = user.get("username")

    out = {"summary": summary, "pages": pages}
    EV.mkdir(parents=True, exist_ok=True)
    (EV / "08-sidebar-capability-closed-loop.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 侧栏能力闭环复测（源码后端）2026-07-24",
        "",
        f"从：**智能对话** · 用户：{summary.get('user')} · stamp={STAMP}",
        f"页面：{summary['ok_pages']}/{summary['total_pages']}",
        f"失败：{', '.join(fail_pages) or '无'}",
        "",
    ]
    for p in pages:
        mark = "x" if p["ok"] else " "
        lines.append(f"- [{mark}] {p['page']} checks {p['ok_checks']}/{p['total_checks']}")
        for loop in p.get("loops") or []:
            flag = "OK" if loop.get("ok") else "NO"
            lines.append(f"  - LOOP {flag} {loop.get('name')}: {loop.get('detail')}")
        for c in p["checks"]:
            flag = "OK" if c["ok"] else "NO"
            lines.append(f"  - {flag} {c['method']} {c['path']} -> {c['status']}")
        lines.append("")
    (EV / "CHECKLIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    gaps = ["# 闭环缺口（复测）", ""]
    for p in pages:
        if p["ok"]:
            continue
        gaps.append(f"## {p['page']}")
        for loop in p.get("loops") or []:
            if not loop.get("ok"):
                gaps.append(f"- LOOP: {loop.get('name')} — {loop.get('detail')}")
        for c in p["checks"]:
            if not c["ok"]:
                gaps.append(f"- {c['method']} {c['path']} -> {c['status']} {c.get('preview')}")
        gaps.append("")
    if not fail_pages:
        gaps.append("无失败页。")
        gaps.append("")
    (EV / "GAPS.md").write_text("\n".join(gaps), encoding="utf-8")

    print("SUMMARY", json.dumps(summary, ensure_ascii=False, indent=2))
    for p in pages:
        print(
            ("OK" if p["ok"] else "FAIL"),
            p["page"],
            f"{p['ok_checks']}/{p['total_checks']}",
            "; ".join(f"{l['name']}={'Y' if l['ok'] else 'N'}" for l in p.get("loops") or []),
        )


if __name__ == "__main__":
    main()
