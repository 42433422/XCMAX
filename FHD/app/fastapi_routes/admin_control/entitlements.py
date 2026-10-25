"""AccountEntitlements control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy


class AccountEntitlements:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        remote_host: Callable[[], str],
        remote_port: Callable[[], int],
        valid_tiers: Callable[[], set[str]],
        clean_strings: Callable[[object], list[str]],
        gate: AdminGate,
        truthy: Callable[[object], bool],
    ) -> None:
        self._errors = errors
        self._remote_host = remote_host
        self._remote_port = remote_port
        self._valid_tiers = valid_tiers
        self._clean_strings = clean_strings
        self._gate = gate
        self._call_truthy = truthy

    def _clean_string_list(self, raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _truthy(self, raw: Any) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    async def admin_force_push_user_entitlements(
        self,
        request: Request,
        user_id: int,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        """把账号权益完整快照强制推送到企业端同步链路。

        这个接口服务管理端的“账号权益”页，不进入代管会话，也不污染桌面端当前登录态。
        """
        from app.application.session_account_meta import audit_admin_action
        from app.application.xcmax_sync_app import push_outbox, record_change

        gate = self._gate(request)
        if gate is not None:
            return gate
        user_data = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        profile_data = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        wallet_data = payload.get("wallet") if isinstance(payload.get("wallet"), dict) else None
        if not isinstance(user_data, dict):
            user_data = {}
        username = str(user_data.get("username") or payload.get("username") or "").strip()
        if not username:
            return JSONResponse({"success": False, "message": "username 必填"}, status_code=422)
        if not isinstance(profile_data, dict):
            profile_data = {}
        tier = str(profile_data.get("tier") or user_data.get("tier") or "").strip().lower()
        if tier not in self._valid_tiers():
            tier = "enterprise" if self._call_truthy(user_data.get("is_enterprise")) else "personal"
        industry_id = str(
            profile_data.get("industry_id") or user_data.get("industry_id") or "通用"
        ).strip()
        entitled_industries = self._clean_strings(profile_data.get("entitled_industries"))
        if industry_id and industry_id not in entitled_industries:
            entitled_industries.append(industry_id)
        snapshot = {
            "market_user_id": str(user_id),
            "username": username,
            "email": str(user_data.get("email") or payload.get("email") or "").strip(),
            "is_admin": self._call_truthy(user_data.get("is_admin")),
            "is_enterprise": self._call_truthy(user_data.get("is_enterprise"))
            or tier == "enterprise",
            "profile": {
                "username": username,
                "tier": tier,
                "industry_id": industry_id or "通用",
                "account_tier": str(profile_data.get("account_tier") or "").strip(),
                "budget_range": str(profile_data.get("budget_range") or "").strip(),
                "entitled_industries": entitled_industries,
            },
            "mod_ids": self._clean_strings(payload.get("mod_ids")),
            "wallet": wallet_data,
            "workflow_employees": payload.get("workflow_employees")
            if isinstance(payload.get("workflow_employees"), list)
            else [],
            "installed_mods": payload.get("installed_mods")
            if isinstance(payload.get("installed_mods"), list)
            else [],
            "source": "admin_entitlements_force_push",
            "meta": {
                "updated_at_ms": int(time.time() * 1000),
                "target": "enterprise",
                "push_mode": "forced",
            },
        }
        change_id = record_change(
            "account_entitlements", str(user_id), "sync", snapshot, actor="admin"
        )
        if change_id < 0:
            return JSONResponse(
                {"success": False, "message": "写入账号权益同步队列失败"}, status_code=500
            )
        push_result = push_outbox(remote_host=self._remote_host(), remote_port=self._remote_port())
        if int(push_result.get("failed") or 0) > 0 or int(push_result.get("sent") or 0) <= 0:
            return JSONResponse(
                {
                    "success": False,
                    "message": "账号权益已写入本地队列，但推送企业端失败，请检查云端同步服务",
                    "data": {"change_id": change_id, "snapshot": snapshot, "push": push_result},
                },
                status_code=502,
            )
        audit_admin_action(
            request,
            "force_push_user_entitlements",
            target_user_id=user_id,
            detail=f"username={username}; change_id={change_id}; sent={push_result.get('sent')}",
        )
        return {
            "success": True,
            "data": {"change_id": change_id, "snapshot": snapshot, "push": push_result},
        }

    async def sync_current_entitlements(self, request: Request):
        """读取当前登录账号最近一次收到的账号权益强推快照。

        企业端侧边栏用它判断管理端是否已经向本机账号推送了新权益。该接口只读，不进入
        管理员代管态，也不改变当前登录身份。
        """
        try:
            from app.application.session_account_meta import (
                effective_entitlement_market_user_id,
                load_session_account_meta,
            )
            from app.application.xcmax_sync_app import read_sync_meta
            from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
            from app.infrastructure.auth.dependencies import get_logged_in_user

            sid = _session_id_from_request(request)
            try:
                user = get_logged_in_user(request) if sid else None
            except HTTPException as exc:
                if exc.status_code not in (401, 403):
                    raise
                user = None
            meta = load_session_account_meta(sid) if user is not None else None
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
            market_user_id = effective_entitlement_market_user_id(sid)
            username_candidates = [
                str(meta.get("impersonating_username") or "").strip(),
                str(meta.get("company_brand") or "").strip(),
                str(getattr(user, "username", "") or "").strip(),
                str(getattr(user, "display_name", "") or "").strip(),
            ]
            snapshots: list[dict[str, Any]] = []
            if market_user_id is not None:
                snap = read_sync_meta(f"account_entitlements:{market_user_id}")
                if snap and str(snap.get("market_user_id", "")).strip() == str(market_user_id):
                    snapshots.append(snap)
            elif (
                meta.get("market_user_id") is None
                and meta.get("impersonating_market_user_id") is None
            ):
                # Name aliases are only a compatibility path for unbound sessions.
                # A missing bound snapshot or failed identity reload cannot use it.
                for username in username_candidates:
                    if not username:
                        continue
                    snap = read_sync_meta(f"account_entitlements:username:{username}")
                    if snap:
                        snapshots.append(snap)

            def _snap_updated_at_ms(snapshot: dict[str, Any]) -> int:
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
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("sync_current_entitlements failed: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
