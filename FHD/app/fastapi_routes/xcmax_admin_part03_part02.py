# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


@_facade().router.get("/admin/daily-digests/{record_id}", response_model=None)
async def get_daily_digest(request: _facade().Request, record_id: int):
    """从服务器读取单条每日摘要完整正文。"""
    return await _facade()._digest_local_or_proxy(
        request, "GET", f"/api/xcmax/admin/daily-digests/{record_id}"
    )


@_facade().router.get("/admin/daily-digests/{record_id}/artifacts", response_model=None)
async def get_daily_digest_artifacts(request: _facade().Request, record_id: int):
    """日更各阶段产物清单（截图 / PPT / digest HTML 等）。"""
    return await _facade()._digest_local_or_proxy(
        request, "GET", f"/api/xcmax/admin/daily-digests/{record_id}/artifacts"
    )


@_facade().router.get("/admin/action-items", response_model=None)
async def list_action_items(
    request: _facade().Request,
    kind: str = _facade().Query("", description="patch | update"),
    day: str = _facade().Query("", description="YYYY-MM-DD"),
):
    """Vibe 预备双清单结构化条目（patch / update）。"""
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    query = "?" + "&".join(q) if q else ""
    return await _facade()._digest_local_or_proxy(request, "GET", f"/api/admin/action-items{query}")


@_facade().router.get("/admin/action-items/stats", response_model=None)
async def action_items_stats(
    request: _facade().Request,
    kind: str = _facade().Query("", description="patch | update"),
    day: str = _facade().Query("", description="YYYY-MM-DD"),
):
    """行动条目完成率 / 分布。"""
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    query = "?" + "&".join(q) if q else ""
    return await _facade()._digest_local_or_proxy(
        request, "GET", f"/api/admin/action-items/stats{query}"
    )


@_facade().router.post("/admin/daily-digests/{record_id}/vibe-prep/sessions", response_model=None)
async def start_digest_vibe_prep_session(
    request: _facade().Request,
    record_id: int,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """基于每日摘要生成 Vibe-Coding 预备 Markdown（更新 + 补丁）后台会话。"""
    return await _facade()._market_admin_proxy(
        request,
        "POST",
        f"/api/agent/butler/daily-digests/{record_id}/vibe-prep/sessions",
        json_body=body,
    )


@_facade().router.post("/admin/daily-digests/{record_id}/line-execute", response_model=None)
async def start_digest_line_execute(
    request: _facade().Request,
    record_id: int,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """Phase A：消费 P-S（或指定产线）补丁清单并派发员工子任务。"""
    return await _facade()._market_admin_proxy(
        request, "POST", f"/api/agent/butler/daily-digests/{record_id}/line-execute", json_body=body
    )


@_facade().router.get("/admin/digest-vibe-prep/sessions/{session_id}", response_model=None)
async def get_digest_vibe_prep_session(request: _facade().Request, session_id: str):
    """轮询 Vibe 预备文档生成会话（复用 workbench session 存储）。"""
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        return _facade().JSONResponse(
            {"success": False, "message": "session_id 必填"}, status_code=400
        )
    return await _facade()._market_admin_proxy(request, "GET", f"/api/workbench/sessions/{sid}")


@_facade().router.post("/admin/all-hands-report/sessions", response_model=None)
async def start_all_hands_report_session(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """启动服务器员工大会后台会话，返回远端 session_id。"""
    return await _facade()._market_admin_proxy(
        request, "POST", "/api/agent/butler/all-hands-report/sessions", json_body=body
    )


@_facade().router.get("/admin/all-hands-report/sessions/{session_id}", response_model=None)
async def get_all_hands_report_session(request: _facade().Request, session_id: str):
    """轮询服务器员工大会后台会话。"""
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        return _facade().JSONResponse(
            {"success": False, "message": "session_id 必填"}, status_code=400
        )
    return await _facade()._market_admin_proxy(request, "GET", f"/api/workbench/sessions/{sid}")


def _probe_remote_health_sync() -> dict[str, _facade().Any]:
    """同步探测远端 HTTP /api/health；供 asyncio.to_thread 调用，避免阻塞事件循环。"""
    # MODstore may share this production host while only listening on loopback.
    # Prefer its configured internal address so the dashboard does not report a
    # false outage when a public-IP hairpin is unavailable.
    internal_base = str(
        _facade().os.environ.get("XCMAX_REMOTE_HEALTH_BASE_URL")
        or _facade().os.environ.get("MODSTORE_INTERNAL_BASE_URL")
        or _facade().os.environ.get("MODSTORE_LOCAL_BASE_URL")
        or ""
    ).strip()
    remote_url = (
        f"{internal_base.rstrip('/')}/api/health"
        if internal_base
        else f"http://{_facade().REMOTE_HOST}:{_facade().REMOTE_PORT}/api/health"
    )
    t0 = _facade().time.time()
    try:
        req = _facade().urllib.request.Request(remote_url, method="GET")
        if _facade().urllib.request.urlopen is _facade()._DEFAULT_URLOPEN:
            direct_opener = _facade().urllib.request.build_opener(
                _facade().urllib.request.ProxyHandler({})
            )
            response_ctx = direct_opener.open(req, timeout=5)
        else:
            response_ctx = _facade().urllib.request.urlopen(req, timeout=5)
        with response_ctx as resp:
            latency_ms = round((_facade().time.time() - t0) * 1000)
            body = _facade().json.loads(resp.read(4096).decode("utf-8", errors="replace"))
            return {
                "success": True,
                "data": {
                    "reachable": True,
                    "latency_ms": latency_ms,
                    "version": body.get("version") or body.get("git_sha") or "",
                    "deploy_time": body.get("timestamp") or "",
                    "host": _facade().REMOTE_HOST,
                    "port": _facade().REMOTE_PORT,
                },
            }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("remote_status probe failed: %s", exc)
        return {
            "success": True,
            "data": {
                "reachable": False,
                "latency_ms": None,
                "version": "",
                "deploy_time": "",
                "host": _facade().REMOTE_HOST,
                "port": _facade().REMOTE_PORT,
                "error": str(exc),
            },
        }


@_facade().router.get("/admin/remote-status", response_model=None)
async def remote_status():
    """探测远端服务器连接状态（轻量 HTTP GET /api/health）。"""
    return await _facade().asyncio.to_thread(_facade()._probe_remote_health_sync)


@_facade().router.get("/admin/deploy/check", response_model=None)
async def admin_deploy_check(request: _facade().Request, channel: str = _facade().Query("stable")):
    """管理端检查本地版本、update 中转站版本、企业端待更新状态。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    normalized_channel = "staging" if str(channel).strip() == "staging" else "stable"
    from app.application.admin_deploy_push import check_deploy_updates

    data = await _facade().asyncio.to_thread(check_deploy_updates, normalized_channel)
    return {"success": True, "data": data}


@_facade().router.post("/admin/deploy/push", response_model=None)
async def admin_deploy_push(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """管理端推送更新包到 update 中转站；企业端自行拉取。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    payload = dict(body or {})
    channel = "staging" if str(payload.get("channel") or "").strip() == "staging" else "stable"
    options = {
        "include_backend": bool(payload.get("include_backend", True)),
        "include_frontend": bool(payload.get("include_frontend", True)),
        "skip_pack": bool(payload.get("skip_pack", False)),
        "channel": channel,
    }
    ssh_key = str(payload.get("ssh_key") or "").strip()
    if ssh_key:
        options["ssh_key"] = ssh_key
    try:
        from app.application.admin_deploy_push import start_deploy_push

        job = await start_deploy_push(options)
        return {"success": True, "data": job.to_dict()}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("admin deploy push failed to start: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=409)


@_facade().router.get("/admin/deploy/jobs/{job_id}", response_model=None)
async def admin_deploy_job(request: _facade().Request, job_id: str):
    """查询管理端更新包推送任务。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    normalized_job_id = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[:128]
    if not normalized_job_id:
        return _facade().JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
    from app.application.admin_deploy_push import get_deploy_job

    job = get_deploy_job(normalized_job_id)
    if job is None:
        return _facade().JSONResponse(
            {"success": False, "message": "推送任务不存在"}, status_code=404
        )
    return {"success": True, "data": job.to_dict()}


@_facade().router.get("/ops/duty-health", response_model=None)
async def ops_duty_health(request: _facade().Request):
    from app.application.ops_closure_status import build_ops_closure_status

    remote = await _facade()._remote_duty_health(request)
    closure = build_ops_closure_status(remote if isinstance(remote, dict) else {})
    if not isinstance(remote, dict):
        return closure.get("remote_health") or {
            "success": False,
            "staffing": closure.get("staffing") or {},
        }
    merged = {**remote, "staffing": closure.get("staffing") or remote.get("staffing") or {}}
    merged["planned_employee_ids"] = closure.get("planned_employee_ids")
    merged["registered_employee_ids"] = closure.get("registered_employee_ids")
    merged["planned_local_installed_count"] = closure.get("planned_local_installed_count")
    merged["extra_local_employee_pack_ids"] = closure.get("extra_local_employee_pack_ids")
    return merged


@_facade().router.post("/ops/dispatch", response_model=None)
async def ops_dispatch(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    payload = dict(body or {})
    payload.setdefault("dispatch_source", "desktop")
    return await _facade()._market_admin_proxy(
        request, "POST", "/api/ops/orchestrate/async", json_body=payload
    )


@_facade().router.get("/ops/jobs", response_model=None)
async def ops_jobs(request: _facade().Request, limit: int = _facade().Query(20, ge=1, le=100)):
    return await _facade()._market_admin_proxy(
        request, "GET", f"/api/ops/orchestrate/jobs?limit={limit}"
    )


@_facade().router.get("/ops/jobs/{job_id}", response_model=None)
async def ops_job_detail(request: _facade().Request, job_id: str):
    jid = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[:128]
    if not jid:
        return _facade().JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
    return await _facade()._market_admin_proxy(request, "GET", f"/api/ops/orchestrate/jobs/{jid}")
