"""Validate a profile change completely before mutating a committing transaction."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Body, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy, JsonObject
from .profile_store import ProfileRepository

if TYPE_CHECKING:
    from app.db.models.user import User


def _invalid(message: str, status: int = 422) -> JSONResponse:
    return JSONResponse({"success": False, "message": message}, status_code=status)


@dataclass(frozen=True)
class ProfileChange:
    username: str
    tier: str
    industry_id: str
    account_tier: str | None
    budget_range: str
    entitled_industries: list[str] | None

    @classmethod
    def parse(cls, payload: JsonObject, valid_tiers: set[str]) -> ProfileChange | JSONResponse:
        from app.domain.app_pure.account_tier_derivation import (
            VALID_ACCOUNT_TIERS,
            normalize_account_tier,
        )
        from app.domain.app_pure.entitled_industries_init import merge_entitled_industries

        username = str(payload.get("username") or "").strip()
        tier = str(payload.get("tier") or "").strip()
        if not username:
            return _invalid("username 必填")
        if tier and tier not in valid_tiers:
            return _invalid(f"tier 必须是 {sorted(valid_tiers)} 之一")
        raw_account_tier = str(payload.get("account_tier") or "").strip()
        account_tier = normalize_account_tier(raw_account_tier) if raw_account_tier else None
        if raw_account_tier and account_tier is None:
            return _invalid(f"account_tier 必须是 {sorted(VALID_ACCOUNT_TIERS)} 之一")
        entitled = payload.get("entitled_industries")
        return cls(
            username=username,
            tier=tier,
            industry_id=str(payload.get("industry_id") or "").strip(),
            account_tier=account_tier,
            budget_range=str(payload.get("budget_range") or "").strip(),
            entitled_industries=(
                merge_entitled_industries([str(x or "").strip() for x in entitled], [])
                if isinstance(entitled, list)
                else None
            ),
        )

    def values_for(self, user: User | None) -> JsonObject | JSONResponse:
        from app.domain.app_pure.account_tier_derivation import should_have_account_tier
        from app.domain.app_pure.entitled_industries_init import (
            merge_entitled_industries,
            validate_industry_in_entitled,
        )

        final_tier = (
            (self.tier or str(getattr(user, "tier", "") or "") or "personal").strip().lower()
        )
        if self.account_tier is not None and not should_have_account_tier(final_tier):
            return _invalid("账号等级（account_tier）仅企业用户可设置")
        entitled = (
            self.entitled_industries
            if self.entitled_industries is not None
            else list(getattr(user, "entitled_industries", None) or [])
        )
        if self.industry_id:
            if self.entitled_industries is not None:
                if not validate_industry_in_entitled(self.industry_id, entitled):
                    return _invalid("industry_id 必须在 entitled_industries 内")
            else:
                entitled = merge_entitled_industries(entitled or ["通用"], [self.industry_id])
        values: JsonObject = {"username": self.username}
        for key in ("tier", "industry_id", "budget_range"):
            value = getattr(self, key)
            if value:
                values[key] = value
        if self.account_tier is not None:
            values["account_tier"] = self.account_tier
        elif not should_have_account_tier(final_tier):
            values["account_tier"] = None
        if self.entitled_industries is not None or self.industry_id:
            values["entitled_industries"] = entitled
        return values


class UserProfiles:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        valid_tiers: Callable[[], set[str]],
        gate: AdminGate,
        repository: Callable[[], AbstractContextManager[ProfileRepository]],
    ) -> None:
        self._errors = errors
        self._valid_tiers = valid_tiers
        self._gate = gate
        self._repository = repository

    async def admin_set_user_profile(
        self, request: Request, user_id: int, payload: dict = Body(...)
    ):
        """设置用户账号体系字段（本地 User 表持久化）。

        body: {
            username: str,
            tier?: personal|enterprise|admin,
            industry_id?: str,
            account_tier?: normal|pro|max|ultra,   # 仅 enterprise 可设
            budget_range?: str,
            entitled_industries?: list[str],
        }
        校验：account_tier 仅企业可设；industry_id 必须 ∈ entitled_industries（显式提供时）。
        """
        denied = self._gate(request)
        if denied is not None:
            return denied
        change = ProfileChange.parse(payload, self._valid_tiers())
        if isinstance(change, JSONResponse):
            return change
        try:
            with self._repository() as repository:
                by_market, by_name = repository.find_identity(int(user_id), change.username)
                if by_market is not None and by_name is not None and by_name is not by_market:
                    return _invalid(
                        "市场用户 ID 与用户名分别绑定了不同的本地资料，请先合并冲突账号", 409
                    )
                bound_id = getattr(by_name, "market_user_id", None) if by_name is not None else None
                if (
                    by_market is None
                    and by_name is not None
                    and isinstance(bound_id, int)
                    and bound_id != int(user_id)
                ):
                    return _invalid("该用户名已经绑定其他市场用户 ID", 409)
                user = by_market or by_name
                values = change.values_for(user)
                if isinstance(values, JSONResponse):
                    return values
                # No add/flush/binding/rename has occurred before every rejection check.
                result = repository.save(user, int(user_id), values)
            return {"success": True, "data": result}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("设置用户 profile 失败: %s", exc)
            return _invalid(str(exc), 500)

    async def admin_list_user_profiles(self, request: Request):
        """返回本地所有用户的账号体系字段映射（按 username 索引）。

        前端拿到远端用户列表后，调此端点合并本地 profile。
        """
        denied = self._gate(request)
        if denied is not None:
            return denied
        try:
            with self._repository() as repository:
                rows = repository.list_profiles()
            data = {
                row["username"]: {key: value for key, value in row.items() if key != "username"}
                for row in rows
            }
            return {
                "success": True,
                "data": data,
                "by_market_user_id": {
                    str(row["market_user_id"]): data[row["username"]]
                    for row in rows
                    if row["market_user_id"] is not None
                },
            }
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("读取用户 profile 列表失败: %s", exc)
            return _invalid(str(exc), 500)
