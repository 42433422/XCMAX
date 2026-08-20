# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


@_facade().router.post("/ops/duty-runs", response_model=None)
async def ops_duty_runs(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    return await _facade()._market_admin_proxy(
        request, "POST", "/api/admin/duty-graph/runs", json_body=body
    )


@_facade().router.get("/ops/duty-runs/{run_id}", response_model=None)
async def ops_duty_run_detail(request: _facade().Request, run_id: int):
    if run_id <= 0:
        return _facade().JSONResponse({"success": False, "message": "run_id 无效"}, status_code=400)
    return await _facade()._market_admin_proxy(
        request, "GET", f"/api/admin/duty-graph/runs/{run_id}"
    )


@_facade().router.get("/ops/closure-status", response_model=None)
async def ops_closure_status(request: _facade().Request):
    from app.application.ops_closure_status import build_ops_closure_status

    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    data = build_ops_closure_status(await _facade()._remote_duty_health(request))
    return {"success": True, "data": data}


@_facade().router.get("/ops/runtime-inventory", response_model=None)
async def ops_runtime_inventory(request: _facade().Request):
    """Desired×actual 运行时真相清单（拓扑 SSOT + 本机探针），并刷新公开投影。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.runtime_inventory import write_runtime_inventory_projection

    try:
        result = write_runtime_inventory_projection(host="127.0.0.1")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("runtime inventory probe failed: %s", exc)
        return {"success": False, "error": str(exc)}
    snapshot = result.get("snapshot") or {}
    return {"success": True, "data": snapshot, "publication": result.get("publication") or {}}


@_facade().router.post("/ops/staffing/onboard", response_model=None)
async def ops_staffing_onboard(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """将编制缺岗员工登记到 MODstore Catalog（代理 yuangon-onboard/run）。"""
    payload: dict[str, _facade().Any] = {
        "dry_run": bool(body.get("dry_run", False)),
        "force": bool(body.get("force", False)),
    }
    pkg_ids = body.get("employee_ids") or body.get("pkg_ids")
    if isinstance(pkg_ids, list):
        payload["pkg_ids"] = ",".join(str(x).strip() for x in pkg_ids if str(x).strip())
    elif isinstance(pkg_ids, str) and pkg_ids.strip():
        payload["pkg_ids"] = pkg_ids.strip()
    return await _facade()._market_admin_proxy(
        request, "POST", "/api/admin/yuangon-onboard/run", json_body=payload
    )


@_facade().router.post("/ops/staffing/install-local", response_model=None)
async def ops_staffing_install_local(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """从 MODstore Catalog 安装 employee_pack 到本地 mods/_employees/。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    pkg_id = str(body.get("employee_id") or body.get("pkg_id") or "").strip()
    if not pkg_id:
        return _facade().JSONResponse(
            {"success": False, "message": "employee_id 必填"}, status_code=400
        )
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        result = await _install_from_catalog(pkg_id, "", activate=True)
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif isinstance(result, dict):
            data = result
        else:
            data = {"result": str(result)}
        return {"success": bool(data.get("success", True)), "data": data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("ops_staffing_install_local failed: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@_facade().router.post("/ops/staffing/close-gap", response_model=None)
async def ops_staffing_close_gap(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """补登记编制缺岗并安装本地缺失 employee_pack（桌面一键闭环）。"""
    from app.application.ops_closure_status import build_ops_closure_status

    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    before = build_ops_closure_status(await _facade()._remote_duty_health(request))
    onboard_result: dict[str, _facade().Any] | None = None
    missing_remote = list(before.get("missing_remote_employees") or [])
    if missing_remote and (not bool(body.get("skip_onboard", False))):
        onboard_result = await _facade()._market_admin_proxy(
            request,
            "POST",
            "/api/admin/yuangon-onboard/run",
            json_body={"pkg_ids": ",".join(missing_remote)},
        )
        if isinstance(onboard_result, _facade().JSONResponse):
            return onboard_result
    mid = build_ops_closure_status(await _facade()._remote_duty_health(request))
    install_results: list[dict[str, _facade().Any]] = []
    if not bool(body.get("skip_install", False)):
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        for employee_id in list(mid.get("missing_local_employee_packs") or []):
            try:
                result = await _install_from_catalog(employee_id, "", activate=True)
                if hasattr(result, "model_dump"):
                    data = result.model_dump()
                elif isinstance(result, dict):
                    data = result
                else:
                    data = {"result": str(result)}
                install_results.append(
                    {
                        "employee_id": employee_id,
                        "success": bool(data.get("success", True)),
                        "message": str(data.get("message") or ""),
                    }
                )
            except _facade().RECOVERABLE_ERRORS as exc:
                install_results.append(
                    {"employee_id": employee_id, "success": False, "message": str(exc)}
                )
    after = build_ops_closure_status(await _facade()._remote_duty_health(request))
    onboard_ok = True
    if isinstance(onboard_result, dict):
        onboard_ok = bool(onboard_result.get("success", True))
    return {
        "success": True,
        "data": {
            "before": before,
            "after": after,
            "onboard": onboard_result,
            "onboard_ok": onboard_ok,
            "install_results": install_results,
        },
    }


@_facade().router.get("/sync/status", response_model=None)
async def sync_status():
    """获取双向同步健康状态。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        info = db.get_status()
        return {"success": True, "data": info}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("sync_status db read failed: %s", exc)
        return {
            "success": True,
            "data": {
                "healthy": False,
                "local_cursor": None,
                "remote_cursor": None,
                "outbox_count": 0,
                "last_sync_at": None,
                "conflict_count": 0,
                "note": "同步数据库尚未初始化，请先完成 sync-foundation 阶段。",
            },
        }


@_facade().router.post("/sync/push", response_model=None)
async def sync_push():
    """触发本地 outbox 向服务器推送。"""
    try:
        from app.application.xcmax_sync_app import push_outbox

        result = push_outbox(remote_host=_facade().REMOTE_HOST, remote_port=_facade().REMOTE_PORT)
        return {"success": True, "data": result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("sync_push failed: %s", exc)
        return _facade().JSONResponse(
            {"success": False, "message": f"推送失败: {exc}"}, status_code=500
        )


@_facade().router.get("/sync/changes", response_model=None)
async def sync_changes(
    since_cursor: int = _facade().Query(0, ge=0), limit: int = _facade().Query(100, ge=1, le=1000)
):
    """获取变更日志（支持断线补拉）。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        rows = db.get_changes(since_cursor=since_cursor, limit=limit)
        return {"success": True, "data": rows, "count": len(rows)}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("sync_changes read failed: %s", exc)
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@_facade().router.post("/sync/receive", response_model=None)
async def sync_receive(body: dict | list):
    """接收远端推来的变更，写入 inbox，立即尝试应用，并记录审计日志。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        items = body if isinstance(body, list) else [body]
        written = db.enqueue_inbox(items)
        try:
            from app.application.xcmax_sync_app import apply_inbox

            result = apply_inbox(limit=len(items) + 50)
        except _facade().RECOVERABLE_ERRORS as ae:
            result = {"applied": 0, "error": str(ae)}
        try:
            from app.mod_sdk.audit import write_audit_event

            write_audit_event(
                actor=None,
                action="xcmax.sync.receive",
                payload={"received": written, "apply": result},
            )
        except _facade().RECOVERABLE_ERRORS:
            pass
        return {"success": True, "received": written, "apply_result": result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("sync_receive failed: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@_facade().router.post("/sync/pull", response_model=None)
async def sync_pull():
    """主动从远端拉取增量变更并应用到本地。"""
    try:
        from app.application.xcmax_sync_app import apply_inbox, pull_from_remote

        pull_result = pull_from_remote(
            remote_host=_facade().REMOTE_HOST, remote_port=_facade().REMOTE_PORT
        )
        apply_result = apply_inbox()
        return {"success": True, "data": {"pull": pull_result, "apply": apply_result}}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("sync_pull failed: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@_facade().router.get("/sync/entitlements/current", response_model=None)
async def sync_current_entitlements(request: _facade().Request):
    """读取当前登录账号最近一次收到的账号权益强推快照。

    企业端侧边栏用它判断管理端是否已经向本机账号推送了新权益。该接口只读，不进入
    管理员代管态，也不改变当前登录身份。
    """
    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.application.xcmax_sync_app import read_sync_meta
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        sid = _session_id_from_request(request)
        meta = load_session_account_meta(sid) if sid else None
        if not meta:
            return {
                "success": True,
                "data": {
                    "has_snapshot": False,
                    "account": None,
                    "snapshot": None,
                    "updated_at_ms": 0,
                    "note": "no active session",
                },
            }
        market_user_id = meta.get("impersonating_market_user_id") or meta.get("market_user_id")
        username_candidates = [
            str(meta.get("impersonating_username") or "").strip(),
            str(meta.get("company_brand") or "").strip(),
        ]
        try:
            from app.infrastructure.auth.dependencies import resolve_session_user

            user = resolve_session_user(request)
            if user is not None:
                username_candidates.append(str(getattr(user, "username", "") or "").strip())
                username_candidates.append(str(getattr(user, "display_name", "") or "").strip())
        except _facade().RECOVERABLE_ERRORS:
            pass
        snapshots: list[dict[str, _facade().Any]] = []
        if market_user_id not in (None, ""):
            snap = read_sync_meta(f"account_entitlements:{market_user_id}")
            if snap:
                snapshots.append(snap)
        for username in username_candidates:
            if not username:
                continue
            snap = read_sync_meta(f"account_entitlements:username:{username}")
            if snap:
                snapshots.append(snap)

        def _snap_updated_at_ms(snapshot: dict[str, _facade().Any]) -> int:
            meta_obj = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            try:
                if not isinstance(meta_obj, dict):
                    meta_obj = {}
                return int(meta_obj.get("updated_at_ms") or 0)
            except (TypeError, ValueError):
                return 0

        snapshot = max(snapshots, key=_snap_updated_at_ms) if snapshots else None
        updated_at_ms = _snap_updated_at_ms(snapshot or {})
        return {
            "success": True,
            "data": {
                "has_snapshot": bool(snapshot),
                "account": {
                    "market_user_id": market_user_id,
                    "username": next((u for u in username_candidates if u), ""),
                    "account_kind": meta.get("account_kind"),
                    "market_is_enterprise": bool(meta.get("market_is_enterprise")),
                    "market_is_admin": bool(meta.get("market_is_admin")),
                },
                "snapshot": snapshot,
                "updated_at_ms": updated_at_ms,
            },
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("sync_current_entitlements failed: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)
