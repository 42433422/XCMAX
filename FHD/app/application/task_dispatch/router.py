"""派工路由：决定一条消息是否要派工、派给谁（哪一层 + 哪个员工）。

确定性匹配为主（可离线测试、零 LLM 依赖）：
  * 显式指派：``context["dispatch"] = {"assignee_id": ..., "tier": ...}`` 直接采纳
    （供前端/移动端"派工"按钮走程序化通路）。
  * 自然语言：消息同时含「派工动词」与「已知受派人标识」才触发，避免劫持普通对话。

受派人清单来自 SSOT：
  * 超级员工(super) ← ``assistant_ssot.super_employees()``
  * 平台员工(platform) ← ``employee_tool_registry.build_employee_pack_tools_detail()``

调用链约束：小C(assistant)→super 受 ``assistant_ssot.can_call`` 升级链管控；
小C→platform 走既有平台员工派工通路（按花名册指派，非升级链），与 planner 现状一致。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.mod_sdk import assistant_ssot
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 派工动词/线索（中英）。需与受派人标识共现才触发。
_DISPATCH_CUES: tuple[str, ...] = (
    "派给",
    "派工",
    "交给",
    "分配给",
    "分配",
    "委派",
    "安排",
    "让",
    "叫",
    "dispatch",
    "assign",
    "delegate",
)


@dataclass(frozen=True)
class RoutingDecision:
    assignee_tier: str  # "super" | "platform"
    assignee_id: str
    assignee_name: str
    title: str
    reason: str
    dispatch_mode: str = "auto"


def _title_from(message: str) -> str:
    text = " ".join(str(message or "").split())
    return text[:40] if len(text) > 40 else text


def _super_catalog() -> list[dict[str, Any]]:
    """[{id, name, aliases:set}] —— 超级员工候选。"""
    out: list[dict[str, Any]] = []
    try:
        registry = assistant_ssot.super_employees()
    except RECOVERABLE_ERRORS:
        logger.debug("super_employees() 读取失败", exc_info=True)
        return out
    for emp_id, entity in registry.items():
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("display_name") or emp_id)
        aliases = {emp_id.lower(), name.lower()}
        # 从 id/显示名拆出别名 token（claude / codex 等），过滤过短/纯通用词。
        for chunk in (emp_id + "-" + name).replace("超级员工", " ").replace("-", " ").split():
            token = chunk.strip().lower()
            if len(token) >= 4 and token not in {"super", "employee"}:
                aliases.add(token)
        out.append({"id": emp_id, "name": name, "aliases": aliases})
    return out


def _platform_catalog() -> list[dict[str, Any]]:
    """[{id(pack_id), name, aliases:set}] —— 平台员工候选。"""
    out: list[dict[str, Any]] = []
    try:
        from app.mod_sdk.employee_tool_registry import build_employee_pack_tools_detail

        rows = build_employee_pack_tools_detail()
    except RECOVERABLE_ERRORS:
        logger.debug("build_employee_pack_tools_detail() 读取失败", exc_info=True)
        return out
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        pack_id = str(row.get("pack_id") or "").strip()
        if not pack_id:
            continue
        aliases = {pack_id.lower()}
        tool_name = str(row.get("tool_name") or "").strip().lower()
        if tool_name:
            aliases.add(tool_name)
        out.append({"id": pack_id, "name": pack_id, "aliases": aliases})
    return out


def _match(message_lower: str, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    """返回首个被消息命中的候选（按别名子串）。"""
    for cand in catalog:
        for alias in cand["aliases"]:
            if alias and alias in message_lower:
                return cand
    return None


class DispatchRouter:
    """无状态路由器；可注入候选目录以便测试。"""

    def __init__(
        self,
        *,
        super_catalog: list[dict[str, Any]] | None = None,
        platform_catalog: list[dict[str, Any]] | None = None,
    ) -> None:
        self._super_override = super_catalog
        self._platform_override = platform_catalog

    def route(self, message: str, context: dict[str, Any] | None = None) -> RoutingDecision | None:
        ctx = context if isinstance(context, dict) else {}
        text = str(message or "").strip()
        if not text:
            return None

        # 1) 显式指派优先（程序化通路）。
        explicit = ctx.get("dispatch")
        if isinstance(explicit, dict) and explicit.get("assignee_id"):
            tier = str(explicit.get("tier") or "").strip() or "platform"
            if tier not in ("super", "platform"):
                return None
            if tier == "super" and not assistant_ssot.can_call("assistant", "super"):
                return None
            assignee_id = str(explicit["assignee_id"])
            return RoutingDecision(
                assignee_tier=tier,
                assignee_id=assignee_id,
                assignee_name=str(explicit.get("assignee_name") or assignee_id),
                title=_title_from(text),
                reason="explicit-dispatch-context",
                dispatch_mode=str(explicit.get("mode") or "auto"),
            )

        # 2) 自然语言：需「派工动词」与「受派人标识」共现。
        lower = text.lower()
        if not any(cue in text for cue in _DISPATCH_CUES):
            return None

        supers = self._super_override if self._super_override is not None else _super_catalog()
        if assistant_ssot.can_call("assistant", "super"):
            hit = _match(lower, supers)
            if hit is not None:
                return RoutingDecision(
                    assignee_tier="super",
                    assignee_id=hit["id"],
                    assignee_name=hit["name"],
                    title=_title_from(text),
                    reason="nl-match-super",
                )

        platforms = (
            self._platform_override if self._platform_override is not None else _platform_catalog()
        )
        hit = _match(lower, platforms)
        if hit is not None:
            return RoutingDecision(
                assignee_tier="platform",
                assignee_id=hit["id"],
                assignee_name=hit["name"],
                title=_title_from(text),
                reason="nl-match-platform",
            )

        return None
