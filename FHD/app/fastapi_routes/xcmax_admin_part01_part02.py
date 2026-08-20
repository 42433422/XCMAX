# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


async def _market_admin_proxy(
    request: _facade().Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, _facade().Any] | None = None,
    require_admin_session: bool = True,
    authorization_override: str = "",
):
    """Proxy server-function calls through the market token bound to the local session."""
    if require_admin_session:
        gate = _facade()._require_market_admin_session(request)
        if gate is not None:
            return gate
    if path in {"/api/admin/yuangon-onboard/status", "/api/admin/yuangon-onboard/run"}:
        from app.application.modstore_local_client import prefer_local_modstore

        if prefer_local_modstore():
            from app.application import self_maintenance_app_service as sm_svc

            try:
                if method.upper() == "GET":
                    return await sm_svc.get_yuangon_onboard_status_local()
                if method.upper() == "POST":
                    return await sm_svc.run_yuangon_onboard_local(json_body or {})
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.warning("local yuangon onboarding failed path=%s: %s", path, exc)
                return _facade().JSONResponse(
                    {"success": False, "message": f"本地元工登记服务不可用: {exc}"}, status_code=502
                )
    try:
        from app.fastapi_routes.market_account import (
            _auth_header,
            _authorization_from_request_resolved,
            _error_message,
            _proxy_json,
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade().JSONResponse(
            {"success": False, "message": f"市场账号代理不可用: {exc}"}, status_code=500
        )
    body_for_auth = json_body if isinstance(json_body, dict) else {}
    authorization = _auth_header(authorization_override)
    if not authorization:
        authorization = await _authorization_from_request_resolved(request, body_for_auth)
    if not authorization:
        return _facade().JSONResponse(
            {
                "success": False,
                "message": "尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization",
            },
            status_code=401,
        )
    payload = await _proxy_json(
        method, path, json_body=json_body, authorization=authorization, return_error_payload=True
    )
    if isinstance(payload, _facade().JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw_error = payload.get("payload")
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _error_message(raw_error, status_code),
                "data": raw_error,
            },
            status_code=status_code,
        )
    return payload


def _is_daily_digest_list_path(path: str) -> bool:
    bare = path.split("?", 1)[0]
    return bare in {"/api/xcmax/admin/daily-digests", "/api/agent/butler/daily-digests"}


def _is_daily_digest_detail_path(path: str) -> bool:
    bare = path.split("?", 1)[0]
    if bare.endswith("/artifacts"):
        return False
    return bare.startswith("/api/xcmax/admin/daily-digests/") or bare.startswith(
        "/api/agent/butler/daily-digests/"
    )


def _is_daily_digest_artifacts_path(path: str) -> bool:
    bare = path.split("?", 1)[0]
    return bare.endswith("/artifacts") and (
        bare.startswith("/api/xcmax/admin/daily-digests/")
        or bare.startswith("/api/agent/butler/daily-digests/")
    )


def _digest_record_id_from_path(path: str) -> int:
    bare = path.split("?", 1)[0]
    if bare.endswith("/artifacts"):
        bare = bare[: -len("/artifacts")]
    return int(bare.rstrip("/").rsplit("/", 1)[-1])


async def _fetch_remote_xcmax_daily_digests(path: str) -> dict[str, _facade().Any] | None:
    """直连修茈 ``/api/xcmax/admin/daily-digests``（生产落库副本；不依赖 butler 会话）。"""
    import httpx

    from app.application.modstore_local_client import internal_auth_headers

    base = (
        (_facade().os.environ.get("XCAGI_MARKET_BASE_URL") or "https://xiu-ci.com")
        .strip()
        .rstrip("/")
    )
    if base.endswith("/market"):
        base = base[: -len("/market")]
    bare, _, query = path.partition("?")
    if bare.startswith("/api/agent/butler/daily-digests"):
        bare = bare.replace("/api/agent/butler/daily-digests", "/api/xcmax/admin/daily-digests", 1)
    elif not bare.startswith("/api/xcmax/admin/daily-digests"):
        return None
    url = f"{base}{bare}"
    if query:
        url = f"{url}?{query}"
    headers = {"Accept": "application/json", **internal_auth_headers()}
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                _facade().logger.warning(
                    "remote xcmax daily-digests HTTP %s path=%s", resp.status_code, bare
                )
                return None
            data = resp.json()
            return data if isinstance(data, dict) else {"success": True, "data": data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("remote xcmax daily-digests failed path=%s: %s", bare, exc)
        return None


def _digest_payload_nonempty(payload: _facade().Any) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return bool(data.get("id") or data.get("body_html") or data.get("subject"))
    return False


async def _digest_local_or_proxy(
    request: _facade().Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, _facade().Any] | None = None,
):
    """日更读接口：本地 MODstore → 市场代理 → 直连生产 xcmax 存档（三选一回退）。"""
    from app.application.modstore_local_client import prefer_local_modstore

    if prefer_local_modstore() and method.upper() == "GET":
        from app.application import digest_email_app_service as digest_svc

        local_payload: dict[str, _facade().Any] | None = None
        try:
            if _facade()._is_daily_digest_list_path(path):
                q = path.split("?", 1)[1] if "?" in path else ""
                limit, offset = (20, 0)
                for part in q.split("&"):
                    if part.startswith("limit="):
                        limit = int(part.split("=", 1)[1])
                    elif part.startswith("offset="):
                        offset = int(part.split("=", 1)[1])
                local_payload = await digest_svc.list_daily_digests_local(
                    limit=limit, offset=offset
                )
                if _facade()._digest_payload_nonempty(local_payload):
                    return local_payload
            elif _facade()._is_daily_digest_artifacts_path(path):
                rid = _facade()._digest_record_id_from_path(path)
                return await digest_svc.get_daily_digest_artifacts_local(int(rid))
            elif _facade()._is_daily_digest_detail_path(path):
                rid = _facade()._digest_record_id_from_path(path)
                local_payload = await digest_svc.get_daily_digest_local(int(rid))
                if _facade()._digest_payload_nonempty(local_payload):
                    return local_payload
            elif path.startswith("/api/admin/action-items/stats?"):
                q = path.split("?", 1)[1] if "?" in path else ""
                kind = day = ""
                for part in q.split("&"):
                    if part.startswith("kind="):
                        kind = part.split("=", 1)[1]
                    elif part.startswith("day="):
                        day = part.split("=", 1)[1]
                return await digest_svc.action_items_stats_local(kind=kind, day=day)
            elif path.startswith("/api/admin/action-items?"):
                q = path.split("?", 1)[1] if "?" in path else ""
                kind = day = ""
                for part in q.split("&"):
                    if part.startswith("kind="):
                        kind = part.split("=", 1)[1]
                    elif part.startswith("day="):
                        day = part.split("=", 1)[1]
                return await digest_svc.list_action_items_local(kind=kind, day=day)
            if _facade()._is_daily_digest_list_path(path) or _facade()._is_daily_digest_detail_path(
                path
            ):
                remote = await _facade()._fetch_remote_xcmax_daily_digests(path)
                if remote is not None:
                    return remote
                if local_payload is not None:
                    return local_payload
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("local digest/action-items read failed path=%s: %s", path, exc)
            if _facade()._is_daily_digest_list_path(path) or _facade()._is_daily_digest_detail_path(
                path
            ):
                remote = await _facade()._fetch_remote_xcmax_daily_digests(path)
                if remote is not None:
                    return remote
            return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=502)
    proxied = await _facade()._market_admin_proxy(
        request,
        method,
        path,
        json_body=json_body,
        require_admin_session=not prefer_local_modstore(),
    )
    if method.upper() == "GET" and (
        _facade()._is_daily_digest_list_path(path) or _facade()._is_daily_digest_detail_path(path)
    ):
        if isinstance(proxied, _facade().JSONResponse) or not _facade()._digest_payload_nonempty(
            proxied
        ):
            remote = await _facade()._fetch_remote_xcmax_daily_digests(path)
            if remote is not None:
                return remote
    return proxied
