"""SQLAlchemy CAS control plane for the management enterprise's single XiaoC.

The existing model/portfolio ledgers remain authoritative for money and task
completion. This layer owns global policy, bounded daily cognition allowances,
single-flight leases and experiences; it never creates a second employee queue.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import json
import uuid
from datetime import UTC, timedelta
from typing import Any, Callable, Iterator, TypeVar, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from modstore_server.db.db_base import get_session_factory
from modstore_server.db.identity import User
from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
from modstore_server.xiaoc_life_policy import (
    IDENTITY_ID,
    MINIMUM_LEVEL,
    LifePolicy,
    LifePolicyError,
    LifeUpdate,
    parse_time,
    utcnow,
)

T = TypeVar("T")
_CLAIM: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xiaoc_life_claim", default=None
)


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _day() -> str:
    return utcnow().astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _budget() -> dict[str, Any]:
    return {
        "date": _day(),
        "timezone": "Asia/Shanghai",
        "used_tokens": 0,
        "reserved_tokens": 0,
        "cycles": 0,
        "exploration_tokens": 0,
        "exploration_reserved_tokens": 0,
    }


def _initial() -> dict[str, Any]:
    return {
        "identity_id": IDENTITY_ID,
        "scope": "enterprise",
        "revision": 1,
        "level": 3,
        "paused": False,
        "owner_user_id": None,
        "mission": "持续改善 XCMAX 的交付与经营，并在授权预算内探索和学习。",
        "policy": LifePolicy().model_dump(),
        "goals": [],
        "interests": [],
        "self_model": {},
        "budget": _budget(),
        "active_cycle": None,
        "unknown_usage": False,
        "next_wake_at": None,
        "last_status": "idle",
    }


def _ensure() -> None:
    with get_session_factory()() as session:
        if session.get(XiaoCLifeState, IDENTITY_ID) is not None:
            return
        session.add(
            XiaoCLifeState(
                identity_id=IDENTITY_ID,
                version=1,
                state_json=_json(_initial()),
                updated_at=utcnow(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()  # Another API/scheduler created the same identity.


def _mutate(callback: Callable[[dict[str, Any], Session], T]) -> T:
    _ensure()
    for attempt in range(6):
        with get_session_factory()() as session:
            row = session.get(XiaoCLifeState, IDENTITY_ID)
            assert row is not None
            data = json.loads(row.state_json)
            try:
                result = callback(data, session)
                encoded = _json(data)
                if encoded == row.state_json and not session.new and not session.dirty:
                    return result
                changed = cast(
                    CursorResult[Any],
                    session.execute(
                        update(XiaoCLifeState)
                        .where(
                            XiaoCLifeState.identity_id == IDENTITY_ID,
                            XiaoCLifeState.version == row.version,
                        )
                        .values(state_json=encoded, version=row.version + 1, updated_at=utcnow())
                        .execution_options(synchronize_session=False)
                    ),
                ).rowcount
                if changed != 1:
                    session.rollback()
                    continue
                session.commit()
                return result
            except (IntegrityError, OperationalError):
                session.rollback()
                if attempt == 5:
                    raise
    raise LifePolicyError("小 C 状态已变动，请读取最新状态")


def _active_principal(session: Session, user_id: int | None) -> bool:
    from modstore_server.strategic_portfolio import portfolio_principal_active

    return bool(user_id and portfolio_principal_active(session.get(User, user_id)))


def _blockers(data: dict[str, Any], session: Session) -> list[str]:
    from modstore_server.strategic_remote_life import waiting_deadline

    if data["level"] < 4 or data["paused"]:
        return []
    blocked = []
    if not _active_principal(session, data.get("owner_user_id")):
        blocked.append("自主活动尚未绑定有效的管理员授权")
    policy = data["policy"]
    if policy["daily_token_limit"] <= 0:
        blocked.append("自主活动每日模型预算为零")
    expiry = policy.get("authorization_expires_at")
    if not expiry or parse_time(expiry) <= utcnow():
        blocked.append("自主活动预算未授权或已到期")
    if data.get("unknown_usage"):
        blocked.append("上一轮模型用量或执行结果未知，保留额度等待回执核对")
    active = data.get("active_cycle")
    if active and waiting_deadline(data) <= utcnow():
        blocked.append("上一轮运行租约已到期，等待原回执，不重复执行")
    return blocked


def _event(
    session: Session,
    event_id: str,
    *,
    kind: str,
    status: str,
    summary: str,
    evidence_refs: list[str],
    actual_tokens: int | None = 0,
    model: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        XiaoCLifeEvent(
            id=event_id,
            identity_id=IDENTITY_ID,
            kind=kind[:32],
            status=status[:32],
            summary=summary[:1000],
            evidence_json=_json(evidence_refs[:32]),
            details_json=_json(details or {}),
            model=model[:320],
            actual_tokens=actual_tokens,
            created_at=utcnow(),
        )
    )


def _event_dict(row: XiaoCLifeEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "summary": row.summary,
        "evidence_refs": json.loads(row.evidence_json),
        "details": json.loads(row.details_json),
        "model": row.model,
        "actual_tokens": row.actual_tokens,
        "created_at": row.created_at.replace(tzinfo=UTC).isoformat(),
    }


def read_state() -> dict[str, Any]:
    _ensure()
    with get_session_factory()() as session:
        row = session.get(XiaoCLifeState, IDENTITY_ID)
        assert row is not None
        data = json.loads(row.state_json)
        blockers = _blockers(data, session)
        active = data.pop("active_cycle", None)
        data["self_authority_active"] = _active_principal(session, data.get("owner_user_id"))
        data["self_promptfoo_checks"] = [
            _event_dict(event)
            for event in session.scalars(
                select(XiaoCLifeEvent)
                .where(
                    XiaoCLifeEvent.identity_id == IDENTITY_ID,
                    XiaoCLifeEvent.kind == "self_promptfoo_check",
                )
                .order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc())
                .limit(20)
            )
        ]
        data["self_identity_checks"] = [
            _event_dict(event)
            for event in session.scalars(
                select(XiaoCLifeEvent)
                .where(
                    XiaoCLifeEvent.identity_id == IDENTITY_ID,
                    XiaoCLifeEvent.kind == "self_identity_check",
                )
                .order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc())
                .limit(20)
            )
        ]
        data["events"] = [
            _event_dict(event)
            for event in session.scalars(
                select(XiaoCLifeEvent)
                .where(XiaoCLifeEvent.identity_id == IDENTITY_ID)
                .order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc())
                .limit(20)
            )
        ]
        from modstore_server.xiaoc_life_experience_review import review_facts

        data["experience_review_facts"] = review_facts(session, data)
        data["status"] = (
            "paused"
            if data["paused"]
            else (
                "blocked"
                if blockers
                else (
                    ("waiting" if active.get("awaiting_worker") else "thinking")
                    if active
                    else "idle" if data["level"] < 4 else data["last_status"]
                )
            )
        )
        data["activity"] = (
            {
                "id": active["cycle_id"],
                "domain": active["domain"],
                "started_at": active["started_at"],
                "status": data["status"],
                "summary": (
                    "等待原队列任务的执行回执"
                    if active.get("awaiting_worker")
                    else "正在处理已认领的自主活动"
                ),
            }
            if active
            else None
        )
        data["blockers"] = blockers
        data["updated_at"] = row.updated_at.replace(tzinfo=UTC).isoformat()
        if data["budget"]["date"] != _day() and not active and not data.get("unknown_usage"):
            data["budget"] = _budget()
        return cast(dict[str, Any], data)


def _settled_owner_goals(
    data: dict[str, Any], session: Session
) -> list[tuple[dict[str, Any], str]] | None:
    """Keep original execution/usage holds; completed history is not ownership."""
    from modstore_server.strategic_portfolio import PortfolioError, _row

    if (
        data.get("active_cycle")
        or data.get("unknown_usage")
        or any(
            data["budget"].get(field, 0) > 0
            for field in ("reserved_tokens", "exploration_reserved_tokens")
        )
    ):
        return None
    settled = []
    for goal in data["goals"]:
        reflection_status = None
        if goal.get("retort_request_id"):
            from modstore_server.xiaoc_life_evolution import feedback

            owner = goal.get("evolution_owner_user_id", data["owner_user_id"])
            if type(owner) is not int:
                return None
            try:
                observed = feedback(session, goal, owner)
            except (LifePolicyError, PortfolioError, KeyError):
                return None
            if observed["metrics"].get("terminal_verified") is not True:
                return None
            reflection_status = observed["status"]
        if not (decision_id := goal.get("decision_id")):
            if reflection_status:
                settled.append((goal, reflection_status))
            continue
        try:
            row, proposal, state = _row(session, decision_id)
        except PortfolioError:
            return None  # Missing original evidence cannot release its authority.
        tasks = state.get("tasks", {})
        for task in tasks.values():
            calls = task.get("calls")
            if task.get("status") not in {"completed", "failed"} or not isinstance(calls, dict):
                return None
            if any(
                call.get("status") != "settled"
                or any(
                    type(call.get(field)) is not int or call[field] < 0
                    for field in ("actual_tokens", "accrued_cost_cents")
                )
                for call in calls.values()
            ):
                return None
        stopped = bool(
            row.status in {"rejected", "withdrawn"}
            or state.get("halted")
            or parse_time(proposal["limits"]["expires_at"]) <= utcnow()
        )
        selected = state.get("plan", {}).get("selected")
        if selected is None:
            selected = [item["opportunity_id"] for item in proposal["opportunities"]]
        if (
            row.status in {"approved", "executing"}
            and not stopped
            and any(key not in tasks for key in selected)
        ):
            return None
        status = "execution_verified"
        if row.status == "proposed" and not tasks and not stopped:
            status = "awaiting_approval"
        elif stopped or not tasks:
            status = "stopped"
        elif any(task["status"] == "failed" for task in tasks.values()):
            status = "failed"
        settled.append((goal, reflection_status or status))
    return settled


def update_settings(body: LifeUpdate, *, actor_user_id: int) -> dict[str, Any]:
    def change(data: dict[str, Any], session: Session) -> None:
        if not _active_principal(session, actor_user_id):
            raise LifePolicyError("需要有效的管理员身份")
        if data["revision"] != body.expected_revision:
            raise LifePolicyError("全企业自主设置已变动，请刷新后重试")
        previous_owner = data.get("owner_user_id")
        if body.policy is not None:
            policy = LifePolicy.model_validate({**data["policy"], **body.policy})
            expiry = policy.authorization_expires_at
            if expiry and not utcnow() < parse_time(expiry) <= utcnow() + timedelta(days=31):
                raise LifePolicyError("预算授权到期时间须在未来 31 天内")
            if previous_owner not in (None, actor_user_id):
                settled = _settled_owner_goals(data, session)
                if settled is None:
                    raise LifePolicyError("原授权任务或模型用量尚未结清，请先核对执行与用量回执")
                # Historical events remain; the active self hypothesis is not
                # transferred to another administrator's cognition context.
                data["self_model"] = {}
                data.pop("world_review", None)
                for goal, status in settled:
                    # Old approvals must not keep prioritizing the enterprise lane
                    # after its original owner and execution ledger are settled.
                    goal["status"] = status
                    if goal.get("retort_request_id"):
                        goal.setdefault("evolution_owner_user_id", previous_owner)
            if policy.retort_template_id:
                from modstore_server.xiaoc_life_evolution import reflection_template

                reflection_template(policy.retort_template_id, actor_user_id)
            data["policy"] = policy.model_dump()
            data["owner_user_id"] = actor_user_id
        for name in ("level", "paused", "mission"):
            if (value := getattr(body, name)) is not None:
                data[name] = value.strip() if isinstance(value, str) else value
        if not data["mission"]:
            raise LifePolicyError("企业使命不能为空")
        data["revision"] += 1
        data["next_wake_at"] = utcnow().isoformat()
        data["last_status"] = "idle"
        _event(
            session,
            f"policy:{data['revision']}",
            kind="policy",
            status="applied",
            summary=f"全企业小 C 自主模式更新为 L{data['level']}"
            + ("，自主活动已暂停" if data["paused"] else ""),
            evidence_refs=[f"admin:{actor_user_id}", f"policy:{data['revision']}"],
            details={
                "previous_owner_user_id": previous_owner,
                "owner_user_id": data["owner_user_id"],
            },
        )

    _mutate(change)
    return read_state()


def require_life_capability(minimum_level: int) -> None:
    if read_state()["level"] < minimum_level:
        raise LifePolicyError(f"当前全企业自主模式不允许此操作，需要 L{minimum_level} 或更高")


def claim_cycle(*, domain: str, reserve_tokens: int) -> dict[str, Any] | None:
    from modstore_server.strategic_remote_life import waiting_deadline

    if (
        domain not in MINIMUM_LEVEL
        or type(reserve_tokens) is not int
        or not 0 <= reserve_tokens <= 1_000_000
    ):
        raise LifePolicyError("invalid lifecycle domain or token reservation")

    def claim(data: dict[str, Any], session: Session) -> dict[str, Any] | None:
        now = utcnow()
        if data.get("active_cycle"):
            if waiting_deadline(data) <= now:
                data["unknown_usage"] = True
                data["last_status"] = "blocked"
            return None
        if data["paused"] or data["level"] < MINIMUM_LEVEL[domain] or _blockers(data, session):
            return None
        if data.get("next_wake_at") and parse_time(data["next_wake_at"]) > now:
            return None
        if data["budget"]["date"] != _day():
            data["budget"] = _budget()
        budget, policy = data["budget"], data["policy"]
        if budget["cycles"] >= policy["daily_cycle_limit"]:
            return None
        exploring = domain == "exploration"
        share = policy["daily_token_limit"] * policy["exploration_percent"] // 100
        lane_cap = share if exploring else policy["daily_token_limit"] - share
        lane_used = (
            budget["exploration_tokens"] + budget["exploration_reserved_tokens"]
            if exploring
            else budget["used_tokens"]
            + budget["reserved_tokens"]
            - budget["exploration_tokens"]
            - budget["exploration_reserved_tokens"]
        )
        reserved = min(reserve_tokens, max(0, lane_cap - lane_used))
        if reserve_tokens and reserved <= 0:
            return None
        from modstore_server.xiaoc_self_model import execution_scope

        cycle = {
            "execution_scope": execution_scope(data, now=now, owner_active=True),
            "cycle_id": uuid.uuid4().hex,
            "lease_token": uuid.uuid4().hex,
            "policy_revision": data["revision"],
            "owner_user_id": data["owner_user_id"],
            "domain": domain,
            "reserved_tokens": reserved,
            "outbound_journal_version": 1,
            "started_at": now.isoformat(),
            "deadline": min(
                now + timedelta(seconds=300), parse_time(policy["authorization_expires_at"])
            ).isoformat(),
        }
        data["active_cycle"] = cycle
        budget["cycles"] += 1
        budget["reserved_tokens"] += reserved
        if exploring:
            budget["exploration_reserved_tokens"] += reserved
        data["last_status"] = "thinking"
        data["next_wake_at"] = (
            now + timedelta(seconds=policy["wake_interval_seconds"])
        ).isoformat()
        return {**cycle, "state": {**copy.deepcopy(data), "self_authority_active": True}}

    return _mutate(claim)


def _claim_active(data: dict[str, Any], session: Session, claim: dict[str, Any]) -> bool:
    from modstore_server.strategic_remote_life import execution_deadline

    current = data.get("active_cycle") or {}
    return bool(
        all(
            current.get(key) == claim.get(key)
            for key in (
                "lease_token",
                "cycle_id",
                "owner_user_id",
                "domain",
                "reserved_tokens",
                "policy_revision",
            )
        )
        and current.get("lease_token")
        and current.get("policy_revision") == data["revision"]
        and execution_deadline(data, claim) > utcnow()
        and not data["paused"]
        and data["level"] >= MINIMUM_LEVEL[claim["domain"]]
        and not _blockers(data, session)
    )


def cycle_active(claim: dict[str, Any]) -> bool:
    with get_session_factory()() as session:
        row = session.get(XiaoCLifeState, IDENTITY_ID)
        return row is not None and _claim_active(json.loads(row.state_json), session, claim)


def _merge(
    items: list[dict[str, Any]], changes: list[dict[str, Any]], key: str, maximum: int
) -> list[dict[str, Any]]:
    values = {item[key]: item for item in items}
    for item in changes:
        if not isinstance(item, dict) or not item.get(key) or not item.get("evidence_refs"):
            raise LifePolicyError(
                "life learning requires an identity and actual evidence references"
            )
        previous = values.get(item[key], {})
        # Model-derived changes cannot replace a goal's execution binding/history.
        if (
            previous.get("decision_id")
            and item.get("decision_id", previous["decision_id"]) != previous["decision_id"]
        ):
            raise LifePolicyError("an existing goal cannot change its portfolio binding")
        for binding in ("retort_request_id", "evolution_source_sha256", "evolution_owner_user_id"):
            if previous.get(binding) and item.get(binding, previous[binding]) != previous[binding]:
                raise LifePolicyError(
                    "an existing goal cannot change its original evolution binding"
                )
        if item[key] not in values and len(values) >= maximum:
            continue
        values[item[key]] = {**previous, **item}
    return list(values.values())


def _advance_goal_cursor(
    data: dict[str, Any], claim: dict[str, Any], details: dict[str, Any] | None
) -> None:
    """Remember the runtime's original selection without changing its authority."""
    selection = (details or {}).get("portfolio_selection")
    if (
        not isinstance(selection, dict)
        or data["revision"] != claim["policy_revision"]
        or data.get("owner_user_id") != claim["owner_user_id"]
        or data["paused"]
    ):
        return
    if any(
        goal.get("id") == selection.get("goal_id")
        and goal.get("decision_id")
        and goal["decision_id"] == selection.get("decision_id")
        and goal.get("domain", "enterprise") == claim["domain"]
        for goal in data["goals"]
    ):
        data.setdefault("goal_cursors", {})[claim["domain"]] = selection["goal_id"]


def finish_cycle(
    claim: dict[str, Any],
    *,
    status: str,
    summary: str,
    evidence_refs: list[str],
    actual_tokens: int | None,
    model: str = "",
    goals: list[dict[str, Any]] | None = None,
    interests: list[dict[str, Any]] | None = None,
    self_model: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if actual_tokens is not None and (type(actual_tokens) is not int or actual_tokens < 0):
        raise LifePolicyError("actual model usage must be verified nonnegative integer tokens")

    def finish(data: dict[str, Any], session: Session) -> None:
        event_id = f"cycle:{claim['cycle_id']}"
        if session.get(XiaoCLifeEvent, event_id) is not None:
            return
        active = data.get("active_cycle") or {}
        if active.get("lease_token") != claim.get("lease_token") or active.get(
            "cycle_id"
        ) != claim.get("cycle_id"):
            raise LifePolicyError("lifecycle receipt does not own this run")
        budget = data["budget"]
        reserved = active["reserved_tokens"]
        # Late receipts still settle actual consumption, but cannot grant new learning.
        fresh = _claim_active(data, session, claim)
        if actual_tokens is None:
            data["unknown_usage"] = True
        else:
            budget["reserved_tokens"] -= reserved
            budget["used_tokens"] += actual_tokens
            if active["domain"] == "exploration":
                budget["exploration_reserved_tokens"] -= reserved
                budget["exploration_tokens"] += actual_tokens
            if actual_tokens > reserved:
                data["unknown_usage"] = True
        safe = fresh and actual_tokens is not None and actual_tokens <= reserved
        if fresh:
            _advance_goal_cursor(data, claim, details)
        if safe:
            data["goals"] = _merge(data["goals"], goals or [], "id", 100)
            data["interests"] = _merge(data["interests"], interests or [], "topic", 20)
            if self_model and self_model.get("evidence_refs"):
                data["self_model"] = {
                    **self_model,
                    "status": "hypothesis",
                    "owner_user_id": claim["owner_user_id"],
                    "assessment_event_id": event_id,
                }
        world_receipt: dict[str, Any] = {}
        observations = (details or {}).get("world_observations")
        if (
            safe
            and status == "completed"
            and active["domain"] == "reflection"
            and data["level"] >= 6
            and isinstance(observations, dict)
        ):
            from modstore_server.xiaoc_life_world import advance_review

            previous = data.get("world_review")
            try:
                next_review = advance_review(
                    previous, observations, owner=claim["owner_user_id"], now=utcnow()
                )
            except ValueError:
                world_receipt = {"world_review_error": "invalid_persisted_review"}
            else:
                if next_review != previous:
                    data["world_review"] = next_review
                    world_receipt = {"world_review_snapshot": next_review}
        final_status = "unknown" if actual_tokens is None else status if fresh else "policy_changed"
        _event(
            session,
            event_id,
            kind=active["domain"],
            status=final_status,
            summary=summary,
            evidence_refs=evidence_refs,
            actual_tokens=actual_tokens,
            model=model,
            details={
                **(details or {}),
                **world_receipt,
                "policy_revision": claim["policy_revision"],
                "execution_scope": active.get("execution_scope"),
                "reservation": reserved,
                "learning_applied": safe,
                "owner_user_id": claim["owner_user_id"],
                "steps": active.get("steps", []),
                "outbound_journal_version": active.get("outbound_journal_version"),
            },
        )
        data["active_cycle"] = None
        data["last_status"] = (
            "blocked" if data["unknown_usage"] or status in {"blocked", "failed"} else "waiting"
        )

    _mutate(finish)
    return read_state()


@contextlib.contextmanager
def life_execution_scope(claim: dict[str, Any]) -> Iterator[None]:
    if not cycle_active(claim):
        raise LifePolicyError("小 C 自主活动授权已改变")
    token = _CLAIM.set(claim)
    try:
        yield
    finally:
        _CLAIM.reset(token)


def require_current_life_call() -> None:
    claim = _CLAIM.get()
    if claim is not None and not cycle_active(claim):
        raise LifePolicyError("小 C 自主模式、预算或运行租约已改变")


def current_life_claim() -> dict[str, Any] | None:
    """Return only the durable lease identity, never the cognition snapshot."""
    claim = _CLAIM.get()
    if claim is None:
        return None
    require_current_life_call()
    return {
        key: claim[key]
        for key in (
            "cycle_id",
            "lease_token",
            "owner_user_id",
            "domain",
            "reserved_tokens",
            "policy_revision",
            "deadline",
        )
    }


def defer_cycle(
    claim: dict[str, Any],
    *,
    summary: str,
    evidence_refs: list[str],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A bound local worker keeps the original lease until its receipt or deadline."""

    def defer(data: dict[str, Any], session: Session) -> None:
        active = data.get("active_cycle") or {}
        if any(active.get(key) != claim.get(key) for key in ("cycle_id", "lease_token")):
            raise LifePolicyError("队列回执不属于当前运行")
        if not any(step.get("kind") == "portfolio" for step in active.get("steps", [])):
            raise LifePolicyError("没有原企业任务账本，不能延后结算")
        _advance_goal_cursor(data, claim, details)
        active["awaiting_worker"] = True
        data["last_status"] = "waiting"
        event_id = "waiting:" + claim["cycle_id"]
        if session.get(XiaoCLifeEvent, event_id) is None:
            _event(
                session,
                event_id,
                kind="execution",
                status="waiting",
                summary=summary,
                evidence_refs=evidence_refs,
                details=details,
            )

    _mutate(defer)
    return read_state()


def record_cycle_step(claim: dict[str, Any], *, kind: str, details: dict[str, Any]) -> None:
    """Journal existing execution identities before leaving the process."""
    from modstore_server.strategic_remote_life import execution_deadline, require_step

    require_step(kind, details)

    def record(data: dict[str, Any], _session: Session) -> None:
        active = data.get("active_cycle") or {}
        if active.get("cycle_id") != claim.get("cycle_id") or active.get(
            "lease_token"
        ) != claim.get("lease_token"):
            raise LifePolicyError("运行身份已改变，不能登记新的外部动作")
        if (
            active.get("policy_revision") != data["revision"]
            or data["paused"]
            or execution_deadline(data, claim) <= utcnow()
            or data["level"] < MINIMUM_LEVEL[active["domain"]]
            or _blockers(data, _session)
        ):
            raise LifePolicyError("运行授权已改变，不能登记新的外部动作")
        steps = active.setdefault("steps", [])
        step = {"kind": kind, **details}
        if step not in steps:
            if len(steps) >= 64:
                raise LifePolicyError("本轮外部动作数量达到上限")
            steps.append(step)

    _mutate(record)


def record_life_reservation(reservation: dict[str, Any]) -> None:
    claim = _CLAIM.get()
    if claim is not None:
        record_cycle_step(
            claim,
            kind="model",
            details={
                key: reservation[key]
                for key in ("request_id", "kind", "owner_user_id", "decision_id", "opportunity_id")
                if key in reservation and key != "kind"
            },
        )


def portfolio_life_guard(decision_id: str, proposal: dict[str, Any], state: dict[str, Any]) -> None:
    """Existing portfolio/model admission consults this only for life-owned work."""
    from modstore_server.strategic_remote_life import require_portfolio

    require_portfolio(proposal, decision_id)
    if not str(proposal.get("period", "")).startswith("xiaoc-life:"):
        return
    claim = _CLAIM.get()
    if claim is None or not cycle_active(claim):
        raise LifePolicyError("小 C 任务须由当前有效的生命循环认领，等待调度或恢复")
    snapshot = read_state()
    binding = next(
        (goal for goal in snapshot["goals"] if goal.get("decision_id") == decision_id), None
    )
    if binding is None or proposal["owner_user_id"] != claim["owner_user_id"]:
        raise LifePolicyError("小 C 任务身份或原预算主体不匹配")
    if snapshot["level"] < MINIMUM_LEVEL.get(binding.get("domain", "enterprise"), 6):
        raise LifePolicyError("当前自主模式不允许继续此类目标")
    # Each run advances one task; its pre-reserved allowance includes all model calls.
    active_tokens = sum(
        task["reservation"]["tokens"]
        for task in state.get("tasks", {}).values()
        if task.get("status") in {"running", "waiting"}
    )
    if active_tokens > claim["reserved_tokens"]:
        raise LifePolicyError("当前自主活动额度不足以覆盖已批准任务")


def require_life_task_capacity(proposal: dict[str, Any], tokens: int) -> None:
    from modstore_server.strategic_remote_life import require_new_task

    require_new_task()
    if not str(proposal.get("period", "")).startswith("xiaoc-life:"):
        return
    claim = _CLAIM.get()
    if claim is None or not cycle_active(claim) or tokens > claim["reserved_tokens"]:
        raise LifePolicyError("本轮已预留的自主额度不足以领取该企业任务")


def wake(*, actor_user_id: int, expected_revision: int) -> dict[str, Any]:
    def request(data: dict[str, Any], session: Session) -> None:
        if not _active_principal(session, actor_user_id) or data["revision"] != expected_revision:
            raise LifePolicyError("自主设置已改变或管理员身份失效")
        data["next_wake_at"] = utcnow().isoformat()

    _mutate(request)
    return read_state()
