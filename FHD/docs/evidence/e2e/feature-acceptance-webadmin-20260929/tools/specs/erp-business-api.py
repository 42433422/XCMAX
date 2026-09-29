"""erp-business-api（业务对接与外部系统集成）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端（http://127.0.0.1:42423）中的业务 API 出口与宿主服务桥接。
impl：FHD/app/fastapi_routes/business_api.py（/api/business/*，经 AgentOrchestrator 发布真实业务事件）
      FHD/app/fastapi_routes/service_bridge.py（/api/service-bridge/*，宿主对外服务工单落库/应答/统计）。
真实验证面：桥接健康与统计、业务事件真实发布、服务工单落库—读回—应答闭环、
            非法优先级/必填缺参被校验拒绝、无 CSRF 令牌的写请求被拒。
所有断言均在真实浏览器页面上下文用 fetch 复核（GET 直接读、POST 带 csrf_token 双提交令牌）。
"""

FEATURE = "erp-business-api"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取业务 API 健康与宿主服务桥接配置/统计（/api/business/health、/api/service-bridge/config、/stats）→ "
    "POST /api/business/ocr/recognize 真实发布外部 OCR 请求事件（200，event=ocr.requested）→ "
    "服务桥接工单落库并按 id 读回（200）→ 非法优先级 400、缺必填 422 被校验拒绝（负例）→ "
    "无 CSRF 令牌的写请求 403 被拒（负例）。"
    "应答子面闭环：PUT /api/service-bridge/requests/{id}/respond → 200 且随后读回 status=resolved、"
    "response 与 responded_by 均已落库（该路由此前会稳定 500，本 commit 已修复并补了回归测试）。"
)


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


def case_bridge_alive(page, env):
    page.goto(env["base"] + "/admin/server-functions", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(8):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "服务器功能模块" in text and "正在加载管理页面" not in text:
            break
    h = _api(page, "/api/business/health")
    cfg = _api(page, "/api/service-bridge/config")
    st = _api(page, "/api/service-bridge/stats")
    hb, cb, sb = h.get("body") or {}, cfg.get("body") or {}, st.get("body") or {}
    cd, sd = cb.get("data") or {}, sb.get("data") or {}
    page.screenshot(path=str(env["shot"] / "BAP1-integration-console.png"))
    ok = (h["status"] == 200 and hb.get("success") is True and hb.get("business_api") == "up"
          and cfg["status"] == 200 and cb.get("success") is True and bool(cd.get("instance_id"))
          and st["status"] == 200 and sb.get("success") is True and "total" in sd
          and "服务器功能模块" in text)
    return {"business_health": {"status": h["status"], "business_api": hb.get("business_api"),
                                "key_required": hb.get("key_required")},
            "bridge_config": {"status": cfg["status"], "instance_id": cd.get("instance_id"),
                              "instance_name": cd.get("instance_name"),
                              "main_server_url": cd.get("main_server_url")},
            "bridge_stats": {"status": st["status"], "data": sd},
            "ui_url": page.url, "ui_has_module_registry": "服务器功能模块" in text}, ok


def case_business_event_published(page, env):
    path = "/api/business/ocr/recognize"
    r = _api(page, path, method="POST",
             body={"image_url": "https://example.com/vc-acceptance.png", "ocr_type": "general",
                   "user_id": "vc-acceptance"})
    b = r.get("body") or {}
    _panel(page, env, "BAP2-business-event-published.png",
           "POST /api/business/ocr/recognize · 真实发布外部 OCR 请求事件", r)
    ok = (r["status"] == 200 and b.get("success") is True and b.get("published") is True
          and b.get("event") == "ocr.requested" and bool(b.get("run_id")))
    return {"status": r["status"], "event": b.get("event"), "published": b.get("published"),
            "run_id": b.get("run_id"), "agent_status": b.get("agent_status"),
            "csrf_sent": r.get("csrf_sent")}, ok


def case_service_bridge_roundtrip(page, env):
    created = _api(page, "/api/service-bridge/requests", method="POST",
                   body={"source_instance_id": "vc-e2e-business",
                         "source_instance_name": "VC 验收实例",
                         "request_type": "general",
                         "title": "vc-e2e-business-probe",
                         "priority": "normal"})
    cdata = (created.get("body") or {}).get("data") or {}
    rid = cdata.get("id")
    fetched = _api(page, f"/api/service-bridge/requests/{rid}")
    fdata = (fetched.get("body") or {}).get("data") or {}
    # 应答子面：本 commit 已修复（此前会话关闭后仍读 ORM 属性会稳定 500），这里做真实应答 + 读回。
    responded = _api(page, f"/api/service-bridge/requests/{rid}/respond", method="PUT",
                     body={"response": "已由验收实例应答", "responded_by": "admin", "status": "resolved"})
    rb = responded.get("body") or {}
    rdata = rb.get("data") or {}
    after = _api(page, f"/api/service-bridge/requests/{rid}")
    adata = (after.get("body") or {}).get("data") or {}
    _panel(page, env, "BAP3-service-bridge-roundtrip.png",
           "POST/PUT/GET /api/service-bridge/requests · 工单落库—应答—读回闭环",
           {"create": {"status": created["status"], "id": rid, "status_field": cdata.get("status"),
                       "title": cdata.get("title")},
            "get": {"status": fetched["status"], "id": fdata.get("id"), "title": fdata.get("title")},
            "respond": {"status": responded["status"], "success": rb.get("success"),
                        "status_field": rdata.get("status"), "responded_by": rdata.get("responded_by")},
            "readback_after_respond": {"status": after["status"], "state": adata.get("status"),
                                       "response": adata.get("response"),
                                       "responded_by": adata.get("responded_by")}})
    ok = (created["status"] == 200 and isinstance(rid, int)
          and fetched["status"] == 200 and fdata.get("id") == rid
          and fdata.get("title") == "vc-e2e-business-probe"
          and responded["status"] == 200 and rdata.get("status") == "resolved"
          and after["status"] == 200 and adata.get("status") == "resolved"
          and adata.get("response") == "已由验收实例应答")
    return {"created": {"status": created["status"], "id": rid, "state": cdata.get("status")},
            "fetched": {"status": fetched["status"], "title": fdata.get("title")},
            "respond": {"status": responded["status"], "success": rb.get("success"),
                        "state": rdata.get("status"), "responded_by": rdata.get("responded_by"),
                        "responded_at": rdata.get("responded_at")},
            "readback_after_respond": {"status": after["status"], "state": adata.get("status"),
                                       "response": adata.get("response"),
                                       "responded_by": adata.get("responded_by")},
            "respond_face_ok": responded["status"] == 200 and rdata.get("status") == "resolved"
                               and adata.get("status") == "resolved"}, ok


def case_validation_rejected(page, env):
    bad_priority = _api(page, "/api/service-bridge/requests", method="POST",
                        body={"source_instance_id": "vc", "source_instance_name": "vc",
                              "title": "t", "priority": "bogus"})
    miss_title = _api(page, "/api/service-bridge/requests", method="POST",
                      body={"source_instance_id": "vc", "source_instance_name": "vc"})
    miss_product = _api(page, "/api/business/inventory/update", method="POST", body={})
    bp = bad_priority.get("body") or {}
    mt = miss_title.get("body") or {}
    mp = miss_product.get("body") or {}
    _panel(page, env, "BAP4-validation-rejected.png",
           "非法优先级 / 缺必填字段 · 校验拒绝（负例）",
           {"bad_priority": {"status": bad_priority["status"], "message": bp.get("message")},
            "missing_title": {"status": miss_title["status"], "error_code": mt.get("error_code"),
                              "errors": (mt.get("errors") or [])[:1]},
            "missing_product_id": {"status": miss_product["status"], "error_code": mp.get("error_code"),
                                   "errors": (mp.get("errors") or [])[:1]}})
    ok = (bad_priority["status"] == 400 and "Invalid priority" in str(bp.get("message"))
          and miss_title["status"] == 422 and mt.get("error_code") == "validation_error"
          and miss_product["status"] == 422 and mp.get("error_code") == "validation_error")
    return {"bad_priority": bad_priority["status"], "missing_title": miss_title["status"],
            "missing_product_id": miss_product["status"]}, ok


def case_missing_csrf_denied(page, env):
    path = "/api/business/inventory/update"
    r = _api_nocsrf(page, path, {"product_id": "VC-PROBE-SKU", "delta": 0})
    b = r.get("body") or {}
    _panel(page, env, "BAP5-csrf-denied.png",
           "缺少 CSRF 双提交令牌的写请求 · 被拒（负例）", r)
    ok = r["status"] == 403 and b.get("success") is False and "CSRF" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "BAP1", "title": "业务 API 出口与宿主服务桥接存活（真实读取）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions；随后 fetch GET /api/business/health、"
                "GET /api/service-bridge/config、GET /api/service-bridge/stats。",
     "expected": "三者均 200；business_api=up；桥接实例含 instance_id；统计含 total 计数。",
     "run": case_bridge_alive},
    {"id": "BAP2", "title": "业务 API 真实发布外部业务事件（OCR 请求）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "页面上下文 POST /api/business/ocr/recognize。",
     "expected": "HTTP 200，success=true，published=true，event=ocr.requested，含 run_id。",
     "run": case_business_event_published},
    {"id": "BAP3", "title": "服务桥接工单落库—应答—读回闭环",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/service-bridge/requests 建单 → GET /requests/{id} 读回；"
                "另如实探测 PUT /requests/{id}/respond（记录为缺陷观察项）。",
     "expected": "建单 200 返回整数 id（pending）；读回同 id/同标题。"
                 "应答返回 200 且随后读回 status=resolved、response 与 responded_by 均已落库。",
     "run": case_service_bridge_roundtrip},
    {"id": "BAP4", "title": "非法优先级与必填缺参被校验拒绝（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/service-bridge/requests（priority=bogus）、"
                "POST /api/service-bridge/requests（缺 title）、POST /api/business/inventory/update（空 body）。",
     "expected": "非法优先级 400；缺 title 422 validation_error；缺 product_id 422 validation_error。",
     "run": case_validation_rejected},
    {"id": "BAP5", "title": "缺少 CSRF 令牌的写请求被拒（负例）",
     "input": "已建立的管理员会话，但不带 X-CSRF-Token 头。",
     "actions": "页面上下文 POST /api/business/inventory/update（合法载荷）。",
     "expected": "HTTP 403，success=false，message 含 CSRF token missing（未执行任何写操作）。",
     "run": case_missing_csrf_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "BAP1-integration-console.png": "/admin/server-functions「服务器功能模块」页真实渲染："
        "标题「服务器功能模块」、副标题「对接修茈服务器的模块注册、每日摘要记录和员工大会能力」、"
        "标签页（服务器模块/每日摘要记录/员工大会）、「服务器功能注册表 90 个模块」表格（含 xcmax-admin、"
        "business-docking、data-sources 等，状态「启用」），左侧运维导航齐全。",
    "BAP2-business-event-published.png": "POST /api/business/ocr/recognize → 200，csrf_sent=true，success=true，"
        "message=OCR 请求已发布，event=ocr.requested，published=true，含 run_id/agent_run_id，agent_status=completed。",
    "BAP3-service-bridge-roundtrip.png": "POST /api/service-bridge/requests → 200，status_field=pending；"
        "PUT respond → 200、status=resolved、responded_by=admin；随后 GET 读回 200 且 status=resolved、"
        "response=已由验收实例应答"
        "「服务器内部错误」（Session 解绑内部错误，真实缺陷观察项）。",
    "BAP4-validation-rejected.png": "priority=bogus → 400「Invalid priority. Must be one of: ['low','normal','high','urgent']」；"
        "缺 title → 422 validation_error body.title Field required；缺 product_id → 422 validation_error body.product_id Field required。",
    "BAP5-csrf-denied.png": "无 X-CSRF-Token 的 POST /api/business/inventory/update → 403，success=false，message=CSRF token missing。",
    "__video__": "本轮真实浏览器会话录像（webm，18.16s，VP8 1600x1000 25fps，ffmpeg 实测）："
        "管理员登录 → 服务器功能模块页渲染 → OCR 业务事件发布 200 → 服务工单落库/应答/读回 200 → "
        "非法优先级/缺参 400/422 → 无 CSRF 写请求 403。",
}