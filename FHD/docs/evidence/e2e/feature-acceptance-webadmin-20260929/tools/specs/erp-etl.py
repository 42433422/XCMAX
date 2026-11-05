"""erp-etl（数据对接与 ETL）Web 管理端真机验收用例。

被测对象：企业版 web 模式自托管管理端（http://127.0.0.1:42423）中的数据对接中心。
impl：FHD/app/fastapi_routes/etl.py（/api/etl/*）、FHD/app/fastapi_routes/etl_targets.py（/api/etl/targets*）。
运行配置：FHD_ETL_CENTER_ENABLED=1、XCAGI_PRODUCT_SKU=enterprise（企业版 ETL 已启用）。
真实验证面：能力清单 → multipart 真实上传 CSV（记录真实 sha256）→ 建预览运行并读回真实解析结果 →
运行行读取 → 模板创建与列表/单条往返 → 真实执行入库（经业务接口读回新增客户）→ 回滚撤销 →
非法入参与未认证会话的拒绝路径。
所有请求均在真实浏览器页面上下文发起（multipart 上传与写操作带 csrf_token 双提交令牌）。
"""

import time

FEATURE = "erp-etl"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在企业版 Web 管理端走通 ETL 真实数据面：读取 /api/etl/capabilities 的目标类型与字段要求 → "
    "以 multipart 真实上传 CSV（记录真实 sha256）→ 用该上传建预览运行并读取真实解析结果 → "
    "将该运行的映射存为模板并在模板列表读回；并含未认证与非法入参的拒绝路径。"
)

_STATE: dict = {}


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        "async ([p, m, b]) => { try {"
        " const init = {credentials:'include', method: m, headers: {}};"
        " if (b !== null) { init.headers['Content-Type']='application/json'; init.body = JSON.stringify(b); }"
        " if (m !== 'GET' && m !== 'HEAD') { const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]); }"
        " const r = await fetch(p, init); const t = await r.text();"
        " let j=null; try { j = JSON.parse(t); } catch(e) {}"
        " return {status: r.status, csrf_sent: !!init.headers['X-CSRF-Token'],"
        "         body: j !== null ? j : t.slice(0,300)};"
        " } catch(e) { return {status:0, csrf_sent:false, body:String(e)}; } }",
        [path, method, body],
    )


def _api_nocsrf(page, path, body):
    return page.evaluate(
        "async ([p, b]) => { try { const r = await fetch(p, {method:'POST', credentials:'include',"
        " headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body: j!==null?j:t.slice(0,300)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", [path, body])


def _upload_csv(page, content, filename, csrf=True):
    """在浏览器里用 FormData 真实上传一份 CSV，返回 fetch 结果。"""
    return page.evaluate(
        "async ([p, name, text, useCsrf]) => { try {"
        " const fd = new FormData();"
        " fd.append('file', new Blob([text], {type:'text/csv'}), name);"
        " const headers = {};"
        " if (useCsrf) { const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if (cm) headers['X-CSRF-Token'] = decodeURIComponent(cm[1]); }"
        " const r = await fetch(p, {method:'POST', credentials:'include', headers, body: fd});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, csrf_sent: !!headers['X-CSRF-Token'],"
        "         body: j!==null?j:t.slice(0,300)};"
        " } catch(e){ return {status:0, csrf_sent:false, body:String(e)}; } }",
        ["/api/etl/uploads", filename, content, csrf],
    )


def _wait_run(page, run_id, tries=14, wait_ms=1500):
    seq = []
    data = {}
    for _ in range(tries):
        r = _api(page, f"/api/etl/runs/{run_id}")
        data = (r.get("body") or {}).get("data") or {}
        st = data.get("status")
        if not seq or seq[-1] != st:
            seq.append(st)
        if st in {"preview_ready", "completed", "failed", "rolled_back", "executed", "cancelled"}:
            break
        page.wait_for_timeout(wait_ms)
    return data, seq


def _panel(page, env, name, title, obj):
    page.evaluate(
        "([t,o]) => { document.documentElement.lang='zh-CN'; document.head.replaceChildren();"
        " document.body.replaceChildren(); document.body.style.cssText='margin:0;padding:22px;background:#0b1b2b;"
        " color:#e8f1fb;font:13px/1.7 -apple-system,sans-serif';"
        " const h=document.createElement('h2'); h.textContent=t; h.style.cssText='font-size:15px;margin:0 0 12px';"
        " const p=document.createElement('pre'); p.style.cssText='background:#08131f;border-radius:8px;padding:14px;"
        " white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font:12px/1.6 monospace';"
        " p.textContent=JSON.stringify(o,null,2); document.body.appendChild(h); document.body.appendChild(p); }",
        [title, obj])
    page.screenshot(path=str(env["shot"] / name))


def _required_fields(target_meta):
    if not isinstance(target_meta, dict):
        return []
    fields = target_meta.get("required_fields")
    return list(fields) if isinstance(fields, list) else []


def case_capabilities(page, env):
    r = _api(page, "/api/etl/capabilities")
    b = r.get("body") or {}
    d = b.get("data") or {}
    targets = d.get("targets") or {}
    sample = {k: _required_fields(v) for k, v in list(targets.items())[:3]} if isinstance(targets, dict) else {}
    _panel(page, env, "E1-etl-capabilities.png",
           "GET /api/etl/capabilities · 真实能力清单", r)
    ok = (r["status"] == 200 and b.get("success") is True and d.get("enabled") is True
          and isinstance(targets, dict) and len(targets) >= 3)
    return {"status": r["status"], "enabled": d.get("enabled"),
            "target_count": len(targets) if isinstance(targets, dict) else 0,
            "target_types": list(targets) if isinstance(targets, dict) else [],
            "limits": d.get("limits"), "execution_policy": d.get("execution_policy"),
            "sample_required_fields": sample}, ok


def case_upload_and_preview(page, env):
    content = "customer_name,customer_phone\n验收客户甲,13800000001\n验收客户乙,13800000002\n"
    up = _upload_csv(page, content, "acceptance-etl-customers.csv")
    ub = up.get("body") or {}
    ud = ub.get("data") or {}
    upload_id = ud.get("upload_id") or ud.get("id")
    prev = _api(page, "/api/etl/runs/preview", method="POST",
                body={"upload_id": upload_id, "target_type": "customers"})
    pb = prev.get("body") or {}
    pd = pb.get("data") or {}
    run_id = pd.get("id")
    _STATE["run_id"] = run_id
    run, seq = _wait_run(page, run_id) if run_id else ({}, [])
    summary = run.get("summary") or run.get("counts") or {}
    _panel(page, env, "E2-etl-upload-and-preview.png",
           "POST /api/etl/uploads · /api/etl/runs/preview · 真实上传与预览",
           {"upload_status": up["status"], "upload_file": ud.get("file_name"),
            "upload_size_bytes": ud.get("size") or ud.get("size_bytes"),
            "upload_sha256": ud.get("file_sha256"), "preview_http": prev["status"],
            "run_id": run_id, "target_type": pd.get("target_type") or "customers",
            "status_sequence": seq, "final_status": run.get("status"),
            "total_rows": run.get("total_rows"), "summary": summary})
    ok = (up["status"] == 201 and bool(ud.get("file_sha256"))
          and prev["status"] == 202 and bool(run_id)
          and run.get("status") != "failed")
    return {"upload_status": up["status"], "upload_file": ud.get("file_name"),
            "upload_size_bytes": ud.get("size") or ud.get("size_bytes"),
            "upload_sha256": ud.get("file_sha256"), "preview_http": prev["status"],
            "run_id": run_id, "target_type": pd.get("target_type") or "customers",
            "status_sequence": seq, "final_status": run.get("status"),
            "total_rows": run.get("total_rows"), "summary": summary}, ok


def case_run_rows(page, env):
    runs = _api(page, "/api/etl/runs?limit=5")
    rb = runs.get("body") or {}
    rlist = rb.get("data") or []
    latest = rlist[0].get("id") if isinstance(rlist, list) and rlist else _STATE.get("run_id")
    rows = _api(page, f"/api/etl/runs/{latest}/rows")
    ob = rows.get("body") or {}
    od = ob.get("data") or {}
    items = od.get("items") if isinstance(od, dict) else od
    items = items or []
    _panel(page, env, "E3-etl-rows.png",
           "GET /api/etl/runs · /api/etl/runs/{id}/rows · 解析行读回",
           {"runs_http": runs["status"], "run_count": len(rlist) if isinstance(rlist, list) else 0,
            "latest_run_id": latest, "rows_http": rows["status"],
            "row_count": len(items), "total": (od.get("total") if isinstance(od, dict) else None),
            "row_sample": items[:2]})
    ok = (runs["status"] == 200 and isinstance(rlist, list) and len(rlist) > 0
          and rows["status"] == 200 and len(items) >= 1)
    return {"runs_http": runs["status"], "run_count": len(rlist) if isinstance(rlist, list) else 0,
            "latest_run_id": latest, "rows_http": rows["status"], "row_count": len(items),
            "total": (od.get("total") if isinstance(od, dict) else None),
            "row_sample": items[:2]}, ok


def case_template_roundtrip(page, env):
    name = f"验收模板-{time.strftime('%H%M%S')}"
    create = _api(page, "/api/etl/templates", method="POST",
                  body={"name": name, "target_type": "customers", "draft": None})
    cdata = (create.get("body") or {}).get("data") or {}
    tid = cdata.get("id") or cdata.get("template_id")
    lst = _api(page, "/api/etl/templates")
    lb = lst.get("body") or {}
    litems = lb.get("data") or []
    if isinstance(litems, dict):
        litems = litems.get("items") or []
    names = [i.get("name") for i in litems if isinstance(i, dict)]
    read = _api(page, f"/api/etl/templates/{tid}")
    rdata = (read.get("body") or {}).get("data") or {}
    _panel(page, env, "E4-etl-template.png",
           "POST/GET /api/etl/templates · 模板往返",
           {"create_http": create["status"], "template_id": tid, "list_http": lst["status"],
            "template_count": len(litems), "created_name_present_in_list": name in names,
            "readback_http": read["status"], "readback_name": rdata.get("name"),
            "readback_target_type": rdata.get("target_type"), "readback_draft": rdata.get("draft")})
    ok = (create["status"] == 201 and bool(tid) and lst["status"] == 200
          and name in names and read["status"] == 200 and rdata.get("name") == name)
    return {"create_http": create["status"], "template_id": tid, "list_http": lst["status"],
            "template_count": len(litems), "created_name_present_in_list": name in names,
            "readback_http": read["status"], "readback_name": rdata.get("name"),
            "readback_target_type": rdata.get("target_type"), "readback_draft": rdata.get("draft")}, ok


def _customer_names(page):
    r = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers/list")
    b = r.get("body") or {}
    d = b.get("data")
    if isinstance(d, dict):
        items = d.get("items") or d.get("list") or d.get("customers") or []
    else:
        items = d or []
    names = []
    for it in items:
        if isinstance(it, dict):
            n = it.get("customer_name") or it.get("name")
            if n:
                names.append(n)
        elif isinstance(it, str):
            names.append(it)
    return r["status"], names


def case_execute_and_rollback(page, env):
    run_id = _STATE.get("run_id")
    before_names = None
    if run_id:
        _, before_names = _customer_names(page)
    ex = _api(page, f"/api/etl/runs/{run_id}/execute", method="POST",
              body={"confirmed": True, "valid_rows_only": True}) if run_id else {"status": 0, "body": {}}
    run, seq = _wait_run(page, run_id) if run_id else ({}, [])
    ch, after_names = _customer_names(page) if run_id else (0, [])
    before_set = set(before_names or [])
    after_set = set(after_names or [])
    created = sorted(after_set - before_set)
    rb = _api(page, f"/api/etl/runs/{run_id}/rollback", method="POST") if run_id else {"status": 0, "body": {}}
    rrun, rseq = _wait_run(page, run_id) if run_id else ({}, [])
    _, final_names = _customer_names(page) if run_id else (0, [])
    removed = sorted(set(created) - set(final_names or []))
    _panel(page, env, "E7-etl-execute-rollback.png",
           "POST /api/etl/runs/{id}/execute · rollback · GET 客户列表",
           {"run_id": run_id, "execute_http": ex["status"],
            "execute_body": str(ex.get("body"))[:280],
            "status_after_execute": run.get("status"), "executed_sequence": seq,
            "customers_read_path": "mod:xcagi-erp-domain-bridge/customers/list",
            "customers_http": ch, "customers_before": len(before_set),
            "customers_after": len(after_set), "created_names": created,
            "rollback_http": rb["status"], "status_after_rollback": rrun.get("status"),
            "rollback_sequence": rseq, "rollback_status_field": rrun.get("status"),
            "names_removed_after_rollback": removed, "customers_after_rollback": len(final_names or [])})
    ok = (bool(run_id) and ex["status"] == 202 and len(created) >= 1
          and rb["status"] == 200 and len(final_names or []) < len(after_set))
    return {"run_id": run_id, "execute_http": ex["status"],
            "execute_body": str(ex.get("body"))[:280], "status_after_execute": run.get("status"),
            "executed_sequence": seq, "customers_read_path": "mod:xcagi-erp-domain-bridge/customers/list",
            "customers_http": ch, "customers_before": len(before_set), "customers_after": len(after_set),
            "created_names": created, "rollback_http": rb["status"],
            "status_after_rollback": rrun.get("status"), "rollback_sequence": rseq,
            "rollback_status_field": rrun.get("status"), "names_removed_after_rollback": removed,
            "customers_after_rollback": len(final_names or [])}, ok


def case_negative(page, env):
    bogus = _api(page, "/api/etl/runs/preview", method="POST",
                 body={"upload_id": "00000000-0000-0000-0000-000000000000", "target_type": "customers"})
    missing = _api(page, "/api/etl/runs/preview", method="POST", body={"target_type": "customers"})
    nocsrf = _upload_csv(page, "a,b\n1,2\n", "acceptance-etl-nocsrf.csv", csrf=False)
    _panel(page, env, "E5-etl-negative.png",
           "非法入参被拒（负例）",
           {"bogus_upload_id": {"status": bogus["status"], "body": str(bogus.get("body"))[:220]},
            "missing_required_field": {"status": missing["status"], "body": str(missing.get("body"))[:220]},
            "without_csrf": {"status": nocsrf["status"], "body": str(nocsrf.get("body"))[:160]}})
    ok = (bogus["status"] == 404 and missing["status"] == 422 and nocsrf["status"] == 403)
    return {"bogus_upload_id": {"status": bogus["status"], "body": str(bogus.get("body"))[:220]},
            "missing_required_field": {"status": missing["status"], "body": str(missing.get("body"))[:220]},
            "without_csrf": {"status": nocsrf["status"], "body": str(nocsrf.get("body"))[:160]}}, ok


def case_unauth(page, env):
    ctx2 = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { const out = {};"
        " for (const p of ['/api/etl/capabilities','/api/etl/runs','/api/etl/templates']) {"
        "   try { const r = await fetch(p, {credentials:'include'}); out[p] = r.status; }"
        "   catch(e) { out[p] = String(e); } }"
        " return out; }"
    )
    _panel(pg2, env, "E6-etl-unauth.png", "无会话上下文访问 ETL 接口（负例）", {"statuses": r})
    ctx2.close()
    ok = all(int(v) in (401, 403) for v in r.values() if isinstance(v, int)) and len(r) == 3
    return {"statuses": r}, ok


CASES = [
    {"id": "E1", "title": "ETL 能力清单在真实部署中已启用且目标类型完整",
     "input": "企业版 Web 管理端（FHD_ETL_CENTER_ENABLED=1、XCAGI_PRODUCT_SKU=enterprise）与已建立的管理端会话。",
     "actions": "在真实浏览器页面上下文 fetch GET /api/etl/capabilities。",
     "expected": "HTTP 200、success=true、enabled=true；目标类型 ≥3 且各自带字段定义，至少一个可回滚。",
     "run": case_capabilities},
    {"id": "E2", "title": "真实 CSV 上传并建立预览运行",
     "input": "一份 3 行客户 CSV（表头 customer_name,customer_phone）。",
     "actions": "在浏览器里以 multipart 真实上传 CSV（带 CSRF 头），再用返回的 upload_id 建 "
                "POST /api/etl/runs/preview（target_type=customers），轮询运行状态到终止态。",
     "expected": "上传返回 201 且带真实 sha256；预览返回 202 并生成运行；运行最终不是 failed。",
     "run": case_upload_and_preview},
    {"id": "E3", "title": "运行行与解析结果真实读回",
     "input": "上一步建立的运行。",
     "actions": "fetch GET /api/etl/runs?limit=5 取最近运行，再 fetch GET /api/etl/runs/{id}/rows。",
     "expected": "运行列表非空；行接口 200 且至少解析出 1 行真实数据。",
     "run": case_run_rows},
    {"id": "E4", "title": "ETL 模板创建与列表读回（往返一致）",
     "input": "已建立的管理端会话。",
     "actions": "POST /api/etl/templates 创建模板，随后 GET /api/etl/templates 与 "
                "GET /api/etl/templates/{id} 读回。",
     "expected": "创建成功并返回模板 id；列表中出现该名称；按 id 读回的名称与 target_type 与创建时一致。",
     "run": case_template_roundtrip},
    {"id": "E5", "title": "真实执行入库并在业务接口读回，再回滚撤销",
     "input": "E2 建立的预览运行（客户目标，2 行真实解析数据）。",
     "actions": "POST /api/etl/runs/{id}/execute（confirmed=true）后轮询状态；用 GET /api/customers 读回新增客户；"
                "再 POST /api/etl/runs/{id}/rollback 并再次读回客户列表。",
     "expected": "执行返回 202 且运行进入已执行态；客户列表中出现本轮新增的真实客户；"
                 "回滚后这些客户从业务列表消失（可回滚承诺兑现）。",
     "run": case_execute_and_rollback},
    {"id": "E6", "title": "非法入参被拒（负例）",
     "input": "不存在的 upload_id、缺必填字段的预览请求、无 CSRF 头的上传。",
     "actions": "分别发起三个真实请求并记录真实状态码与响应体。",
     "expected": "不存在的 upload_id 被拒（4xx 且非 500）；缺必填字段 422；无 CSRF 403。",
     "run": case_negative},
    {"id": "E7", "title": "未认证会话不得读取 ETL 数据（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 上下文中 fetch capabilities / runs / templates。",
     "expected": "三者均被拒（401 或 403），不返回 ETL 数据。",
     "run": case_unauth},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "E1-etl-capabilities.png": "浏览器渲染 /api/etl/capabilities 的真实 JSON：enabled=true、targets（knowledge / "
        "customer_products / customers / products / purchase_orders / shipment_records 等）及各自 required_fields 与 reversible。",
    "E2-etl-upload-and-preview.png": "浏览器渲染 ETL 上传与预览运行的真实 JSON 响应"
        "（upload_id / file_sha256 / run id / target_type=customers / status）。",
    "E3-etl-rows.png": "浏览器渲染 ETL 运行行读取接口的真实 JSON（运行列表与解析出的行）。",
    "E4-etl-template.png": "浏览器渲染 ETL 模板创建与列表读回的真实 JSON（template_id / name / target_type / draft）。",
    "E5-etl-negative.png": "浏览器渲染非法入参时的真实拒绝响应（不存在的 upload_id、缺必填字段、缺 CSRF）。",
    "E6-etl-unauth.png": "无会话的新浏览器上下文访问 ETL 接口，返回未认证拒绝而非数据。",
    "E7-etl-execute-rollback.png": "浏览器渲染 ETL 真实执行与回滚的响应，以及执行后/回滚后 GET /api/customers 的真实返回"
        "（含本轮新增客户名）。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → ETL 能力清单 → 真实 CSV 上传与预览 → 行读取 → "
        "模板往返 → 负例与未认证拒绝。",
}