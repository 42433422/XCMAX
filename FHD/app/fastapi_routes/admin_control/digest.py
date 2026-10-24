"""Authorized digest reads and explicit local/remote fallback policy."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from .ports import AdminGate, ErrorPolicy, JsonObject, LocalProxy, MarketProxy


class DigestReader:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        digest_nonempty: Callable[[object], bool],
        digest_record_id: Callable[[str], int],
        remote_digest: Callable[[str], Awaitable[JsonObject | None]],
        is_daily_digest_artifacts_path: Callable[[str], bool],
        is_daily_digest_detail_path: Callable[[str], bool],
        is_daily_digest_list_path: Callable[[str], bool],
        proxy: MarketProxy,
        gate: AdminGate,
        inject_digest_base: Callable[[JsonObject, str], JsonObject],
        read_digest: LocalProxy,
    ) -> None:
        self._errors = errors
        self._digest_nonempty = digest_nonempty
        self._digest_record_id = digest_record_id
        self._remote_digest = remote_digest
        self._call_is_daily_digest_artifacts_path = is_daily_digest_artifacts_path
        self._call_is_daily_digest_detail_path = is_daily_digest_detail_path
        self._call_is_daily_digest_list_path = is_daily_digest_list_path
        self._proxy = proxy
        self._gate = gate
        self._inject_digest_base = inject_digest_base
        self._read_digest = read_digest

    def _is_daily_digest_list_path(self, path: str) -> bool:
        bare = path.split("?", 1)[0]
        return bare in {"/api/xcmax/admin/daily-digests", "/api/agent/butler/daily-digests"}

    def _is_daily_digest_detail_path(self, path: str) -> bool:
        bare = path.split("?", 1)[0]
        if bare.endswith("/artifacts"):
            return False
        return bare.startswith("/api/xcmax/admin/daily-digests/") or bare.startswith(
            "/api/agent/butler/daily-digests/"
        )

    def _is_daily_digest_artifacts_path(self, path: str) -> bool:
        bare = path.split("?", 1)[0]
        return bare.endswith("/artifacts") and (
            bare.startswith("/api/xcmax/admin/daily-digests/")
            or bare.startswith("/api/agent/butler/daily-digests/")
        )

    def _digest_record_id_from_path(self, path: str) -> int:
        bare = path.split("?", 1)[0]
        if bare.endswith("/artifacts"):
            bare = bare[: -len("/artifacts")]
        return int(bare.rstrip("/").rsplit("/", 1)[-1])

    async def _fetch_remote_xcmax_daily_digests(self, path: str) -> dict[str, Any] | None:
        """直连修茈 ``/api/xcmax/admin/daily-digests``（生产落库副本；不依赖 butler 会话）。"""
        import httpx

        from app.application.modstore_local_client import internal_auth_headers

        base = (os.environ.get("XCAGI_MARKET_BASE_URL") or "https://xiu-ci.com").strip().rstrip("/")
        if base.endswith("/market"):
            base = base[: -len("/market")]
        bare, _, query = path.partition("?")
        if bare.startswith("/api/agent/butler/daily-digests"):
            bare = bare.replace(
                "/api/agent/butler/daily-digests", "/api/xcmax/admin/daily-digests", 1
            )
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
                    self._errors.logger.warning(
                        "remote xcmax daily-digests HTTP %s path=%s", resp.status_code, bare
                    )
                    return None
                data = resp.json()
                return data if isinstance(data, dict) else {"success": True, "data": data}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("remote xcmax daily-digests failed path=%s: %s", bare, exc)
            return None

    def _digest_payload_nonempty(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        if isinstance(data, list):
            return len(data) > 0
        if isinstance(data, dict):
            return bool(data.get("id") or data.get("body_html") or data.get("subject"))
        return False

    async def _digest_local_or_proxy(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ):
        """日更读接口：先验管理会话，任何来源均不可借服务凭据绕过拒绝。"""
        denied = self._gate(request)
        if denied is not None:
            return denied
        from app.application.modstore_local_client import prefer_local_modstore

        if prefer_local_modstore() and method.upper() == "GET":
            from app.application import digest_email_app_service as digest_svc

            local_payload: dict[str, Any] | None = None
            try:
                if self._call_is_daily_digest_list_path(path):
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
                    if self._digest_nonempty(local_payload):
                        return local_payload
                elif self._call_is_daily_digest_artifacts_path(path):
                    rid = self._digest_record_id(path)
                    return await digest_svc.get_daily_digest_artifacts_local(int(rid))
                elif self._call_is_daily_digest_detail_path(path):
                    rid = self._digest_record_id(path)
                    local_payload = await digest_svc.get_daily_digest_local(int(rid))
                    if self._digest_nonempty(local_payload):
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
                if self._call_is_daily_digest_list_path(
                    path
                ) or self._call_is_daily_digest_detail_path(path):
                    remote = await self._remote_digest(path)
                    if remote is not None:
                        return remote
                    if local_payload is not None:
                        return local_payload
            except self._errors.recoverable() as exc:
                self._errors.logger.warning(
                    "local digest/action-items read failed path=%s: %s", path, exc
                )
                if self._call_is_daily_digest_list_path(
                    path
                ) or self._call_is_daily_digest_detail_path(path):
                    remote = await self._remote_digest(path)
                    if remote is not None:
                        return remote
                return JSONResponse({"success": False, "message": str(exc)}, status_code=502)
        proxied = await self._proxy(
            request,
            method,
            path,
            json_body=json_body,
            require_admin_session=not prefer_local_modstore(),
        )
        if isinstance(proxied, JSONResponse) and proxied.status_code in {401, 403}:
            return proxied
        if method.upper() == "GET" and (
            self._call_is_daily_digest_list_path(path)
            or self._call_is_daily_digest_detail_path(path)
        ):
            if isinstance(proxied, JSONResponse) or not self._digest_nonempty(proxied):
                remote = await self._remote_digest(path)
                if remote is not None:
                    return remote
        return proxied

    def _inject_digest_api_base(self, payload: dict[str, Any], base: str) -> dict[str, Any]:
        """在 ``data`` 中写入 ``digest_api_base``，供 XCmax 页眉与「打开市场」与解锁校验同源提示。"""
        data = payload.get("data")
        if isinstance(data, dict):
            data["digest_api_base"] = base
        return payload

    async def get_digest_identity(self, request: Request):
        """透传远端「身份校验码」摘要；与修茈市场 ``verify-admin-digest-code`` 同一实现源。"""
        from app.fastapi_routes.market_account import _market_base_url

        api_base = _market_base_url()
        out = await self._proxy(request, "GET", "/api/xcmax/admin/digest-identity")
        if isinstance(out, JSONResponse) and out.status_code == 404:
            self._errors.logger.debug(
                "digest-identity: upstream 404, returning empty code payload for HTML fallback"
            )
            return {
                "success": True,
                "data": {
                    "code": "",
                    "expires_at": "",
                    "valid": False,
                    "daily_digest_id": None,
                    "digest_api_base": api_base,
                },
            }
        if isinstance(out, dict):
            return self._inject_digest_base(out, api_base)
        return out

    async def list_daily_digests(
        self,
        request: Request,
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        """从服务器读取已保存的每日摘要邮件副本。"""
        return await self._read_digest(
            request, "GET", f"/api/xcmax/admin/daily-digests?limit={limit}&offset={offset}"
        )

    async def get_daily_digest(self, request: Request, record_id: int):
        """从服务器读取单条每日摘要完整正文。"""
        return await self._read_digest(
            request, "GET", f"/api/xcmax/admin/daily-digests/{record_id}"
        )

    async def get_daily_digest_artifacts(self, request: Request, record_id: int):
        """日更各阶段产物清单（截图 / PPT / digest HTML 等）。"""
        return await self._read_digest(
            request, "GET", f"/api/xcmax/admin/daily-digests/{record_id}/artifacts"
        )

    async def list_action_items(
        self,
        request: Request,
        kind: str = Query("", description="patch | update"),
        day: str = Query("", description="YYYY-MM-DD"),
    ):
        """Vibe 预备双清单结构化条目（patch / update）。"""
        query = action_items_query(kind, day)
        return await self._read_digest(request, "GET", f"/api/admin/action-items{query}")

    async def action_items_stats(
        self,
        request: Request,
        kind: str = Query("", description="patch | update"),
        day: str = Query("", description="YYYY-MM-DD"),
    ):
        """行动条目完成率 / 分布。"""
        query = action_items_query(kind, day)
        return await self._read_digest(request, "GET", f"/api/admin/action-items/stats{query}")

    async def start_digest_vibe_prep_session(
        self,
        request: Request,
        record_id: int,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """基于每日摘要生成 Vibe-Coding 预备 Markdown（更新 + 补丁）后台会话。"""
        return await self._proxy(
            request,
            "POST",
            f"/api/agent/butler/daily-digests/{record_id}/vibe-prep/sessions",
            json_body=body,
        )

    async def start_digest_line_execute(
        self,
        request: Request,
        record_id: int,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """Phase A：消费 P-S（或指定产线）补丁清单并派发员工子任务。"""
        return await self._proxy(
            request,
            "POST",
            f"/api/agent/butler/daily-digests/{record_id}/line-execute",
            json_body=body,
        )

    async def get_digest_vibe_prep_session(self, request: Request, session_id: str):
        """轮询 Vibe 预备文档生成会话（复用 workbench session 存储）。"""
        return await self._workbench_session(request, session_id)

    async def start_all_hands_report_session(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """启动服务器员工大会后台会话，返回远端 session_id。"""
        return await self._proxy(
            request, "POST", "/api/agent/butler/all-hands-report/sessions", json_body=body
        )

    async def get_all_hands_report_session(self, request: Request, session_id: str):
        """轮询服务器员工大会后台会话。"""
        return await self._workbench_session(request, session_id)

    async def _workbench_session(self, request: Request, session_id: str):
        sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
        if not sid:
            return JSONResponse({"success": False, "message": "session_id 必填"}, status_code=400)
        return await self._proxy(request, "GET", f"/api/workbench/sessions/{sid}")


def action_items_query(kind: str, day: str) -> str:
    parts = [f"{key}={value}" for key, value in (("kind", kind), ("day", day)) if value]
    return "?" + "&".join(parts) if parts else ""
