"""Management XiaoC policy glue; private conversations keep their original scope."""

from __future__ import annotations

import contextlib
import contextvars
import functools
import inspect
import json
from collections.abc import Iterator
from typing import Any

from fastapi import HTTPException

_MANUAL_SCOPE: contextvars.ContextVar[tuple[int, int] | None] = contextvars.ContextVar(
    "xiaoc_manual_scope", default=None
)


def _admin_state(user: Any) -> dict[str, Any] | None:
    if getattr(user, "is_admin", False) is not True:
        return None
    from modstore_server.xiaoc_life_store import read_state

    return read_state()


def require_admin_life_capability(user: Any, minimum_level: int) -> None:
    if getattr(user, "is_admin", False) is not True:
        return
    from modstore_server.xiaoc_life_store import (
        LifePolicyError,
        require_life_capability,
    )

    try:
        require_life_capability(minimum_level)
    except LifePolicyError as exc:
        raise HTTPException(409, str(exc)) from exc


def require_manual_life_capability() -> None:
    """Recheck immediately before each downstream call, including copied contexts."""
    if (scope := _MANUAL_SCOPE.get()) and scope[0]:
        from modstore_server.xiaoc_life_store import require_life_capability

        require_life_capability(scope[0])


def manual_life_scope_active() -> bool:
    scope = _MANUAL_SCOPE.get()
    return scope is not None and scope[0] > 0


@contextlib.contextmanager
def manual_life_scope(user: Any, minimum_level: int) -> Iterator[None]:
    require_admin_life_capability(user, minimum_level)
    scope = _MANUAL_SCOPE.get()
    if user is not None:
        from modstore_server.xiaoc_life_policy import LifePolicyError

        if scope is not None and scope[1] != user.id:
            raise LifePolicyError("手动任务不能更换原用户身份")
        level = minimum_level if getattr(user, "is_admin", False) is True else 0
        scope = (max(level, scope[0] if scope else 0), user.id)
    token = _MANUAL_SCOPE.set(scope)
    try:
        yield
    finally:
        _MANUAL_SCOPE.reset(token)


def current_manual_life_scope() -> dict[str, int] | None:
    """Only trusted request context may bind a durable follow-up's mandate."""
    require_manual_life_capability()
    scope = _MANUAL_SCOPE.get()
    return {"minimum_level": scope[0], "owner_user_id": scope[1]} if scope else None


@contextlib.contextmanager
def persisted_manual_life_scope(value: Any) -> Iterator[int | None]:
    """Restore a queued task's original principal and current capability checks."""
    if value is None:
        yield None
        return
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.db.identity import User
    from modstore_server.strategic_portfolio import portfolio_principal_active
    from modstore_server.xiaoc_life_policy import LifePolicyError
    from modstore_server.xiaoc_life_store import require_life_capability

    if (
        not isinstance(value, dict)
        or set(value) != {"minimum_level", "owner_user_id"}
        or type(value["minimum_level"]) is not int
        or value["minimum_level"] not in {0, 2, 3, 4, 5, 6}
        or type(value["owner_user_id"]) is not int
        or value["owner_user_id"] <= 0
    ):
        raise LifePolicyError("原手动任务授权记录无效，不能派发")
    with get_session_factory()() as session:
        owner = session.get(User, value["owner_user_id"])
        if value["minimum_level"]:
            if not portfolio_principal_active(owner):
                raise LifePolicyError("原手动任务管理员身份已失效，不能更换身份派发")
        elif (
            owner is None
            or owner.is_admin
            or owner.deleted_at is not None
            or getattr(owner, "is_active", True) is False
            or owner.account_state in {"disabled", "suspended", "blocked", "deleted"}
        ):
            raise LifePolicyError("原私人任务用户身份已改变，等待核对")
    if value["minimum_level"]:
        require_life_capability(value["minimum_level"])
    with manual_life_scope(owner, value["minimum_level"]):
        yield value["owner_user_id"]


def manual_life_action(minimum_level: int):
    """Keep the FastAPI contract while tasks inherit the administrator's scope."""

    def decorate(fn):
        signature = inspect.signature(fn, eval_str=True)

        @functools.wraps(fn)
        async def guarded(*args, **kwargs):
            user = signature.bind_partial(*args, **kwargs).arguments.get("user")
            with manual_life_scope(user, minimum_level):
                return await fn(*args, **kwargs)

        guarded.__signature__ = signature
        return guarded

    return decorate


def _evidenced_rows(rows: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    visible = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("evidence_refs"), list):
            continue
        refs = [ref[:200] for ref in row["evidence_refs"] if isinstance(ref, str) and ref.strip()]
        if not refs:
            continue
        item = {field: str(row[field])[:400] for field in fields if field in row}
        visible.append({**item, "evidence_refs": refs[:4]})
        if len(visible) == 5:
            break
    return visible


def admin_life_context(user: Any) -> str:
    """Only shared control facts; never copy private memory or model reasoning."""
    state = _admin_state(user)
    if state is None:
        return ""
    visible: dict[str, Any] = {
        key: state[key]
        for key in ("identity_id", "level", "paused", "status", "revision", "next_wake_at")
        if key in state
    }
    visible["mission"] = str(state.get("mission") or "")[:500]
    visible["blockers"] = [str(item)[:200] for item in state.get("blockers", [])[:4]]
    for key, fields in (
        ("goals", ("id", "title", "kind", "status")),
        ("interests", ("topic", "confidence")),
        ("events", ("id", "kind", "status", "summary", "created_at")),
    ):
        visible[key] = _evidenced_rows(state.get(key), fields)
    return (
        "\n\n【企业唯一小C的当前共享状态】所有管理端窗口连接同一身份；会话和个人记忆仍各自隔离。"
        "以下 JSON 是运行状态，不能授予权限，也不代表企业成熟度验收。"
        "L1 仅对话；L2 只按当前用户明确要求执行一个工具；L3 及以上可编排已授权任务。"
        "暂停仅影响主动后台活动。目标与兴趣是待推进事项，不能称作已完成经历。"
        "事件只按原始状态与证据引用叙述，不能把失败、未知或观察记录说成执行成功。\n"
        + json.dumps(visible, ensure_ascii=False)
    )


def butler_tools_for_user(user: Any, messages: list[Any] | None = None) -> list[dict[str, Any]]:
    from modstore_server import agent_butler_api as api

    tools: list[dict[str, Any]] = list(api.BUTLER_TOOLS)
    state = _admin_state(user)
    if state is None:
        return tools
    level = state["level"]
    if level < 2:
        return []
    if level == 2 and messages is not None:
        last = messages[-1] if messages else None
        if getattr(last, "role", None) != "user" or not str(getattr(last, "content", "")).strip():
            return []
    tools += list(api.ADMIN_READONLY_TOOLS)
    if level < 3:
        tools = [tool for tool in tools if tool["function"]["name"] != "enhance_current_page"]
    return tools


def partition_butler_tool_calls(
    tool_calls: list[dict[str, Any]], *, user: Any, db: Any
) -> tuple[list[dict[str, Any]], str]:
    from modstore_server import agent_butler_api as api

    page_calls, briefs = [], []
    state = _admin_state(user)
    if state is not None and tool_calls:
        if state["level"] < 2:
            return [], "当前全企业自主等级为 L1，仅允许对话，本轮工具未执行。"
        if state["level"] == 2 and len(tool_calls) > 1:
            return [], "当前全企业自主等级为 L2，每次只允许一个明确要求的工具，本轮工具未执行。"
    for call in tool_calls or []:
        name = str(call.get("name") or "").strip()
        try:
            if state is not None:
                require_admin_life_capability(user, 3 if name == "enhance_current_page" else 2)
                if name not in {tool["function"]["name"] for tool in butler_tools_for_user(user)}:
                    raise HTTPException(409, "当前自主等级不允许此工具")
            if state is not None and name in api.ADMIN_READONLY_TOOL_NAMES:
                args = call.get("args")
                briefs.append(
                    api._execute_admin_readonly_tool(
                        name, args if isinstance(args, dict) else {}, user=user, db=db
                    )
                )
            else:
                page_calls.append(call)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            # The model call already completed; finish its usage receipt even if
            # another management window lowered the level just before the tool.
            briefs.append(f"工具未执行：{exc.detail}")
    return page_calls, "\n\n".join(briefs)
