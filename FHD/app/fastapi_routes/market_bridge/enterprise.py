"""Enterprise profile and industry entitlement orchestration through explicit providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import EnsureEnterprise, JsonObject, ProxyJSON


def _dedupe_mod_ids(mod_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in mod_ids:
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


@dataclass
class EnterpriseAccounts:
    proxy: ProxyJSON
    base_url: Callable[[], str]
    internal_key: Callable[[], str]
    error_message: Callable[[Any, int], str]
    truthy: Callable[[Any], bool]
    dedupe: Callable[[list[str]], list[str]]
    industry_seed: Callable[[str], str | None]
    industry_alias: Callable[[str], str | None]
    deliveries: Callable[[str], Iterable[Any]]
    session_meta: Callable[[str], JsonObject | None]
    claim_user_id: Callable[[str], int | None]
    resolve_token: Callable[[str], Awaitable[str]]
    ensure_profile: EnsureEnterprise
    industry_mods: Callable[[str], list[str]]
    logger: Logger

    async def ensure(
        self,
        market_user_id: int | str | None,
        *,
        username: str = "",
        company: str = "",
        mod_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Mark a registered market account as enterprise through the internal market API."""
        try:
            uid = int(str(market_user_id or "").strip())
        except (TypeError, ValueError):
            uid = 0
        if uid <= 0:
            return {
                "success": False,
                "message": "修茈市场注册成功但未返回用户ID，无法标记企业账号",
                "market_base_url": self.base_url(),
            }
        internal_key = self.internal_key()
        if not internal_key:
            return {
                "success": False,
                "message": "未配置 XCAGI_MARKET_INTERNAL_API_KEY，无法标记市场企业账号",
                "market_base_url": self.base_url(),
            }
        body: dict[str, Any] = {
            "market_user_id": uid,
            "company": (company or "").strip(),
            "display_name": (username or "").strip(),
        }
        requested_mod_ids = self.dedupe([str(x) for x in mod_ids or []])
        if requested_mod_ids:
            body["mod_ids"] = requested_mod_ids
        payload = await self.proxy(
            "POST",
            "/api/internal/cs-intake/ensure-enterprise-profile",
            json_body=body,
            extra_headers={"X-Internal-Api-Key": internal_key},
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse):
            return {
                "success": False,
                "message": "市场服务不可用，无法标记企业账号",
                "status_code": int(getattr(payload, "status_code", 502) or 502),
                "market_base_url": self.base_url(),
            }
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 502)
            raw = payload.get("payload")
            return {
                "success": False,
                "message": self.error_message(raw, status_code) or "市场企业标记失败",
                "status_code": status_code,
                "raw": raw,
                "market_base_url": self.base_url(),
            }
        if not isinstance(payload, dict):
            return {
                "success": False,
                "message": "市场企业标记返回格式异常",
                "raw": payload,
                "market_base_url": self.base_url(),
            }
        is_enterprise = self.truthy(payload.get("is_enterprise")) or self.truthy(
            payload.get("market_is_enterprise")
        )
        if not (payload.get("ok") or payload.get("success")) or not is_enterprise:
            return {
                "success": False,
                "message": str(
                    payload.get("message") or payload.get("detail") or "市场企业标记失败"
                ),
                "raw": payload,
                "market_base_url": self.base_url(),
            }
        return {
            "success": True,
            "market_user_id": uid,
            "username": str(payload.get("username") or username or "").strip(),
            "is_enterprise": True,
            "mod_ids": [
                str(x).strip()
                for x in payload.get("mod_ids") or requested_mod_ids
                if str(x or "").strip()
            ],
            "added_mod_ids": [
                str(x).strip() for x in payload.get("added_mod_ids") or [] if str(x or "").strip()
            ],
            "raw": payload,
            "market_base_url": self.base_url(),
        }

    def mod_ids(self, industry_id: str) -> list[str]:
        """Resolve the MODstore entitlements implied by a selected industry."""
        iid = str(industry_id or "").strip()
        if not iid:
            return []
        mod_ids: list[str] = []
        try:
            mid = str(self.industry_seed(iid) or "").strip()
            if mid:
                mod_ids.append(mid)
        except RECOVERABLE_ERRORS:
            self.logger.exception(
                "enterprise_mod_ids_for_industry: industry_seed failed industry=%s", iid
            )
        try:
            mid = str(self.industry_alias(iid) or "").strip()
            if mid:
                mod_ids.append(mid)
        except RECOVERABLE_ERRORS:
            self.logger.exception("enterprise_mod_ids_for_industry: alias failed industry=%s", iid)
        try:
            for row in self.deliveries(iid):
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("industry_mod_id") or "").strip()
                if mid:
                    mod_ids.append(mid)
                runtime_mid = str(row.get("runtime_mod_id") or "").strip()
                if runtime_mid:
                    mod_ids.append(runtime_mid)
        except RECOVERABLE_ERRORS:
            self.logger.exception(
                "enterprise_mod_ids_for_industry: delivery failed industry=%s", iid
            )
        return self.dedupe(mod_ids)

    async def grant(self, session_id: str, industry_id: str) -> dict[str, Any]:
        """Grant selected-industry MODstore entitlements for the current FHD session."""
        sid = str(session_id or "").strip()
        mod_ids = self.industry_mods(industry_id)
        if not mod_ids:
            return {"success": True, "mod_ids": [], "added_mod_ids": []}
        if not sid:
            return {"success": False, "message": "缺少登录会话，无法写入市场行业权限"}
        market_user_id: int | None = None
        try:
            meta = self.session_meta(sid) or {}
            raw_uid = meta.get("market_user_id")
            if raw_uid is not None:
                market_user_id = int(raw_uid)
        except (TypeError, ValueError):
            market_user_id = None
        except RECOVERABLE_ERRORS:
            self.logger.exception("grant_market_enterprise_entitlements: load session meta failed")
        if market_user_id is None:
            token = await self.resolve_token(sid)
            market_user_id = self.claim_user_id(token)
        if market_user_id is None:
            return {"success": False, "message": "当前会话没有市场用户ID，无法写入市场行业权限"}
        return await self.ensure_profile(market_user_id, mod_ids=mod_ids)
