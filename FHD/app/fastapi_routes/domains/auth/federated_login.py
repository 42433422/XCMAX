"""OIDC authorization handoff and one-time QR session exchange."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.application.session_account_meta import AccountKind
from app.domain.auth.ports import (
    AttachCookie,
    ErrorTypes,
    FinalizeOidc,
    JsonObject,
    LoginBackend,
    QrIssuer,
    RouteResult,
)
from app.http.error_codes import (
    QR_NOT_FOUND,
    error_envelope,
)


@dataclass(frozen=True)
class FederatedLogin:
    backend: Callable[[], LoginBackend]
    product_sku: Callable[[], str | None]
    normalize_kind: Callable[[object, str], AccountKind]
    enabled: Callable[[], bool]
    frontend_path: Callable[[], str]
    sign_state: Callable[[str], str]
    verify_state: Callable[[str], tuple[bool, str | None]]
    authorize_url: Callable[[str], Awaitable[str]]
    exchange: Callable[[str], Awaitable[JsonObject]]
    finalize: FinalizeOidc
    issue_qr: QrIssuer
    poll_qr: Callable[[str, str], JsonObject | None]
    consume_qr: Callable[[str, str], JsonObject | None]
    attach_cookie: AttachCookie
    infra_errors: ErrorTypes
    logger: Logger

    def oidc_status(self) -> RouteResult:
        return {"success": True, "data": {"enabled": self.enabled()}}

    async def oidc_start(self, request: Request) -> RouteResult:
        if not self.enabled():
            return JSONResponse({"success": False, "message": "OIDC 未启用"}, status_code=404)
        return_to = str(request.query_params.get("return") or "").strip()
        state = self.sign_state(return_to)
        url = await self.authorize_url(state)
        return RedirectResponse(url=url, status_code=302)

    async def oidc_callback(
        self, request: Request, background_tasks: BackgroundTasks | None
    ) -> RouteResult:
        from urllib.parse import quote

        base = self.frontend_path()
        if not self.enabled():
            return RedirectResponse(url=f"{base}?oidc_error=OIDC_DISABLED", status_code=302)
        code = str(request.query_params.get("code") or "").strip()
        state = str(request.query_params.get("state") or "").strip()
        ok, _rt = self.verify_state(state)
        if not ok or not code:
            return RedirectResponse(
                url=f"{base}?oidc_error=OIDC_STATE&oidc_message={quote('状态校验失败')}",
                status_code=302,
            )
        try:
            oidc_session = await self.exchange(code)
            raw_profile = oidc_session.get("profile")
            profile: dict[str, Any] = dict(raw_profile) if isinstance(raw_profile, dict) else {}
        except self.infra_errors() as exc:
            self.logger.exception("OIDC exchange failed")
            return RedirectResponse(
                url=f"{base}?oidc_error=OIDC_EXCHANGE&oidc_message={quote(str(exc))}",
                status_code=302,
            )
        auth_app_service = self.backend()
        auth_result = auth_app_service.authenticate_oidc_user(profile)
        if not auth_result.get("success"):
            msg = str(auth_result.get("message") or "OIDC 登录失败")
            return RedirectResponse(
                url=f"{base}?oidc_error=OIDC_AUTH&oidc_message={quote(msg)}", status_code=302
            )
        sku = self.product_sku() or "personal"
        account_kind = self.normalize_kind(
            request.query_params.get("account_kind"),
            "enterprise" if sku == "enterprise" else "personal",
        )
        payload = await self.finalize(
            auth_result=auth_result,
            oidc_profile=profile,
            background_tasks=background_tasks,
            oidc_access_token=str(oidc_session.get("access_token") or ""),
            account_kind=account_kind,
            sku=sku,
        )
        if payload.get("success") is False:
            message = str(payload.get("message") or "OIDC 登录失败")
            return RedirectResponse(
                url=f"{base}?oidc_error=OIDC_AUTH&oidc_message={quote(message)}", status_code=302
            )
        resp = RedirectResponse(url=f"{base}?oidc=ok", status_code=302)
        return self.attach_cookie(resp, payload.get("session_id"))

    async def qr_issue(self, request: Request, body: JsonObject) -> RouteResult:
        client_hint = str(body.get("client_hint") or request.headers.get("User-Agent") or "")[:256]
        kwargs: dict[str, Any] = {"client_hint": client_hint}
        if "account_kind" in body:
            kwargs["account_kind"] = self.normalize_kind(body.get("account_kind"), "enterprise")
        data = self.issue_qr(**kwargs)
        return {"success": True, "data": data}

    async def qr_status(self, qr_id: str, poll_secret: str) -> RouteResult:
        rec = self.poll_qr(qr_id, poll_secret)
        if not rec:
            return JSONResponse(error_envelope(QR_NOT_FOUND, "二维码无效"), status_code=404)
        status = str(rec.get("status") or "pending")
        if status == "confirmed":
            confirmed = self.consume_qr(qr_id, poll_secret)
            if confirmed and confirmed.get("session_id"):
                payload = confirmed.get("login_payload") or {}
                resp = JSONResponse(
                    {
                        "success": True,
                        "data": {
                            "status": "confirmed",
                            "session_id": confirmed.get("session_id"),
                            **payload,
                        },
                    }
                )
                return self.attach_cookie(resp, str(confirmed.get("session_id")))
        if status == "expired":
            return {"success": True, "data": {"status": "expired"}}
        return {"success": True, "data": {"status": status}}
