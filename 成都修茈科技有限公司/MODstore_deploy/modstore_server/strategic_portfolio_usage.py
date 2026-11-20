"""Persisted per-call reservations for approved strategic employee execution.

ContextVars follow the repository's copy_context thread handoffs. Input bytes
provide a deliberately conservative text-token bound. Missing upstream usage
retains the reservation and stops additional spending instead of becoming zero.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Iterator, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from modstore_server.db.db_base import get_session_factory
from modstore_server.strategic_portfolio import (
    PortfolioError,
    _date,
    _json,
    digest,
    mutate_portfolio,
    require_active_portfolio_owner,
    require_authorization,
)

_SCOPE: contextvars.ContextVar[tuple[str, str, str] | None] = contextvars.ContextVar(
    "strategy_portfolio", default=None
)
_PLANNING: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "strategy_planning", default=None
)
_CALL: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "strategy_model_reservation", default=None
)


@contextlib.contextmanager
def platform_call_reservation(reservation: dict[str, Any] | None) -> Iterator[None]:
    token = _CALL.set({**reservation, "used": False} if reservation else None)
    try:
        yield
    finally:
        _CALL.reset(token)


def require_call_reservation() -> None:
    if scope_active() and _CALL.get() is None:
        raise PortfolioError("budgeted model route requires a persisted per-call reservation")


async def dispatch_budgeted(
    invoke: Callable[..., Awaitable[dict[str, Any]]], provider: str, kwargs: dict[str, Any]
) -> dict[str, Any]:
    """One admission point covers direct pipelines as well as the platform facade."""
    if not scope_active():
        return await invoke(provider, **kwargs)
    if _SCOPE.get() is not None:
        remaining_execution_seconds()
    if (planning := _PLANNING.get()) is not None:
        require_active_portfolio_owner(planning["owner_user_id"])
    from modstore_server.llm_chat_proxy import _normalize_openai_base, normalize_model
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        platform_api_key,
        platform_base_url,
    )

    platform_key = platform_api_key(provider)
    if not platform_key or not hmac.compare_digest(
        str(platform_key), str(kwargs.get("api_key") or "")
    ):
        raise PortfolioError("strategic model call requires the approved platform credential")
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS and _normalize_openai_base(
        provider, kwargs.get("base_url"), platform_key
    ) != _normalize_openai_base(provider, platform_base_url(provider), platform_key):
        raise PortfolioError("strategic model call cannot change the platform endpoint")
    kwargs["model"] = normalize_model(provider, kwargs["model"], kwargs.get("base_url"))
    active = _CALL.get()
    if active is not None:
        if active["used"] or (active["provider"], active["model"]) != (provider, kwargs["model"]):
            raise PortfolioError("model reservation already consumed or route mismatch")
        active["used"] = True
        return await invoke(provider, **kwargs)
    reservation = prepare_platform_call(
        provider, kwargs["model"], kwargs["messages"], kwargs.get("max_tokens")
    )
    assert reservation is not None
    kwargs["max_tokens"] = reservation["max_tokens"]
    result = None
    try:
        with platform_call_reservation(reservation):
            active = _CALL.get()
            assert active is not None
            active["used"] = True
            result = await asyncio.wait_for(
                invoke(provider, **kwargs), timeout=reservation["timeout_seconds"]
            )
    finally:
        # Cancellation and programming errors retain the hold and propagate.
        complete_platform_call(reservation, result)
    return result


@contextlib.contextmanager
def portfolio_usage_scope(
    decision_id: str, opportunity_id: str, lease_token: str
) -> Iterator[None]:
    token = _SCOPE.set((decision_id, opportunity_id, lease_token))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def scope_active() -> bool:
    return _SCOPE.get() is not None or _PLANNING.get() is not None


def remaining_execution_seconds() -> float | None:
    """Stop at operation boundaries; a running synchronous tool is not preemptible."""
    scope = _SCOPE.get()
    if scope is None:
        return None
    decision_id, opportunity_id, lease_token = scope

    def check(row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any) -> float:
        require_authorization(row, proposal, state)
        task = state.get("tasks", {}).get(opportunity_id, {})
        if task.get("status") != "running" or task.get("lease_token") != lease_token:
            raise PortfolioError("strategic execution lease is not active")
        remaining = (
            min(_date(task["deadline"]), _date(proposal["limits"]["expires_at"]))
            - datetime.now(UTC)
        ).total_seconds()
        if remaining <= 0:
            raise PortfolioError("strategic execution deadline expired")
        return remaining

    return mutate_portfolio(decision_id, check)


def unmetered_delegate_block(
    handler: str, payload: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """No remote model credentials are granted before a budget-capable adapter exists."""
    if _SCOPE.get() is None and not (payload or {}).get("strategic_execution_binding"):
        return None
    return {
        "handler": handler,
        "ok": False,
        "accepted": False,
        "queued": False,
        "status": "blocked_strategy_budget_adapter",
        "error": "Remote worker requires a model gateway with per-call reservation and verified usage receipts",
    }


def bind_portfolio_worker(receipt_id: str, *, owner_user_id: int) -> dict[str, Any]:
    """A trusted local queue persists this binding, then returns its queue receipt."""
    scope = _SCOPE.get()
    if scope is None or not receipt_id or len(receipt_id) > 160:
        raise PortfolioError("worker binding requires an active strategy lease and queue identity")
    decision_id, opportunity_id, lease_token = scope
    binding_id = uuid.uuid4().hex

    def bind(
        row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any
    ) -> dict[str, Any]:
        require_authorization(row, proposal, state)
        task = state.get("tasks", {}).get(opportunity_id, {})
        if (
            task.get("lease_token") != lease_token
            or task.get("status") != "running"
            or task.get("worker_binding")
        ):
            raise PortfolioError("worker binding already owned or lease invalid")
        binding = {
            "decision_id": decision_id,
            "opportunity_id": opportunity_id,
            "lease_token": lease_token,
            "owner_user_id": owner_user_id,
            "proposal_sha256": proposal["proposal_sha256"],
            "receipt_id": receipt_id,
            "binding_id": binding_id,
        }
        task["worker_binding"] = binding
        return binding

    return mutate_portfolio(decision_id, bind, owner_user_id=owner_user_id)


@contextlib.contextmanager
def portfolio_worker_scope(
    binding: dict[str, Any], *, owner_user_id: int
) -> Iterator[dict[str, Any]]:
    """Restore a durable local queue lease once, including the platform model scope."""
    from modstore_server.platform_llm_scope import platform_llm_scope

    def claim(row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any):
        require_authorization(row, proposal, state)
        task = state.get("tasks", {}).get(binding.get("opportunity_id"), {})
        if (
            task.get("worker_binding") != binding
            or task.get("status") != "waiting"
            or binding.get("owner_user_id") != owner_user_id
        ):
            raise PortfolioError("worker receipt identity or owner mismatch; no replay allowed")
        if _date(task["deadline"]) <= datetime.now(UTC):
            raise PortfolioError("worker execution deadline expired")
        task["status"] = "running"
        opportunity = next(
            item
            for item in proposal["opportunities"]
            if item["opportunity_id"] == binding["opportunity_id"]
        )
        return {
            **opportunity,
            **binding,
            "deadline": task["deadline"],
            "started_at": task["started_at"],
        }

    task = mutate_portfolio(binding["decision_id"], claim, owner_user_id=owner_user_id)
    with (
        platform_llm_scope(),
        portfolio_usage_scope(
            binding["decision_id"], binding["opportunity_id"], binding["lease_token"]
        ),
    ):
        yield task


async def planning_admission(provider: str, model: str) -> dict[str, Any] | None:
    """Use existing prepaid platform headroom, never the unapproved proposal budget."""
    from modstore_server.llm_quota_monitor import platform_quota_snapshot

    snapshot = await platform_quota_snapshot(
        live_probe=False,
        isolated_http=True,
        catalog={"providers": [{"provider": provider, "configured": True}]},
    )
    for row in snapshot.get("providers", []):
        applicable = [
            resource
            for resource in row.get("resources", [])
            if resource.get("resource") in {"general", model}
        ]
        if (
            row.get("provider") == provider
            and row.get("visibility") == "exact"
            and row.get("state") == "healthy"
            and applicable
            and all(
                type(item.get("remaining_percent")) is int and item["remaining_percent"] >= 20
                for item in applicable
            )
        ):
            return {
                "provider": provider,
                "model": model,
                "source": row.get("source"),
                "checked_at": snapshot.get("checked_at"),
                "remaining_percent": min(item["remaining_percent"] for item in applicable),
                "budget_source": "existing_platform_subscription_quota",
                "max_calls": 1,
                "max_total_tokens": 32768,
                "max_output_tokens": 1600,
            }
    return None


@contextlib.contextmanager
def planning_usage_scope(owner_user_id: int, admission: dict[str, Any]) -> Iterator[dict[str, Any]]:
    context = {"owner_user_id": owner_user_id, "admission": admission, "receipts": []}
    token = _PLANNING.set(context)
    try:
        yield context
    finally:
        _PLANNING.reset(token)


def _reserve_planning(
    context: dict[str, Any], provider: str, model: str, prompt_bound: int, output_bound: int
) -> dict[str, Any]:
    from modstore_server.db.llm_chat import LlmClientRequest

    admission = context["admission"]
    if (provider, model) != (admission["provider"], admission["model"]) or context["receipts"]:
        raise PortfolioError("planning route or single-call quota exhausted")
    output_bound = min(output_bound, admission["max_output_tokens"])
    if prompt_bound + output_bound > admission["max_total_tokens"]:
        raise PortfolioError("planning context exceeds platform task token budget")
    record = {
        "kind": "strategic_planning",
        "request_id": "strategy-discovery-" + uuid.uuid4().hex,
        "owner_user_id": context["owner_user_id"],
        "admission": admission,
        "reserved_tokens": prompt_bound + output_bound,
        "status": "pending",
    }
    record_sha = digest(record)
    with get_session_factory()() as session:
        require_active_portfolio_owner(context["owner_user_id"], session)
        unresolved = session.execute(
            select(LlmClientRequest.id)
            .where(
                LlmClientRequest.user_id == context["owner_user_id"],
                LlmClientRequest.client_request_id.startswith("strategy-discovery-"),
                LlmClientRequest.state.in_(("processing", "unknown")),
            )
            .limit(1)
        ).first()
        if unresolved:
            raise PortfolioError("previous planning usage requires reconciliation")
        slot = session.execute(
            select(LlmClientRequest).where(
                LlmClientRequest.user_id == context["owner_user_id"],
                LlmClientRequest.client_request_id == "strategy-planning-slot",
            )
        ).scalar_one_or_none()
        if slot is None:
            session.add(
                LlmClientRequest(
                    user_id=context["owner_user_id"],
                    client_request_id="strategy-planning-slot",
                    request_sha256=record_sha,
                    state="processing",
                    done_json=_json(record),
                )
            )
        else:
            changed = cast(
                CursorResult[Any],
                session.execute(
                    update(LlmClientRequest)
                    .where(
                        LlmClientRequest.id == slot.id,
                        LlmClientRequest.state == "completed",
                    )
                    .values(state="processing", request_sha256=record_sha, done_json=_json(record))
                ),
            ).rowcount
            if changed != 1:
                raise PortfolioError("previous planning usage requires reconciliation")
        session.add(
            LlmClientRequest(
                user_id=context["owner_user_id"],
                client_request_id=record["request_id"],
                request_sha256=record_sha,
                state="processing",
                done_json=_json(record),
            )
        )
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise PortfolioError("another planning call owns the account quota slot") from exc
    context["receipts"].append(record)
    return {
        **record,
        "provider": provider,
        "model": model,
        "max_tokens": output_bound,
        "timeout_seconds": 45,
    }


def _settle_planning(reservation: dict[str, Any], result: dict[str, Any] | None) -> None:
    from modstore_server.db.llm_chat import LlmCallLog, LlmClientRequest

    values = (result or {}).get("usage") or {}
    prompt = (
        values.get("prompt_tokens", values.get("input_tokens"))
        if isinstance(values, dict)
        else None
    )
    completion = (
        values.get("completion_tokens", values.get("output_tokens"))
        if isinstance(values, dict)
        else None
    )
    known = (
        type(prompt) is int
        and type(completion) is int
        and prompt >= 0
        and completion >= 0
        and not (result or {}).get("_fallback_used")
        and not (result or {}).get("usage_estimated")
        and values.get("estimated") is not True
    )
    admission = reservation["admission"]
    known = known and (result or {}).get("provider") in (None, "", admission["provider"])
    known = known and (result or {}).get("model") in (None, "", admission["model"])
    total = cast(int, prompt) + cast(int, completion) if known else None
    exceeded = total is not None and total > reservation["reserved_tokens"]
    report = {
        **reservation,
        "status": "exceeded" if exceeded else "settled" if known else "unknown",
        "actual_tokens": total,
        "supplier_cost_cents": None,
        "cost_basis": "existing_subscription_usage_not_supplier_invoice",
    }
    with get_session_factory()() as session:
        row = session.execute(
            select(LlmClientRequest).where(
                LlmClientRequest.client_request_id == reservation["request_id"],
                LlmClientRequest.user_id == reservation["owner_user_id"],
            )
        ).scalar_one()
        if row.state != "processing":
            return
        final_state = "completed" if known and not exceeded else "unknown"
        changed = cast(
            CursorResult[Any],
            session.execute(
                update(LlmClientRequest)
                .where(
                    LlmClientRequest.id == row.id,
                    LlmClientRequest.state == "processing",
                )
                .values(state=final_state, done_json=_json(report))
            ),
        ).rowcount
        if changed != 1:
            session.rollback()
            return
        session.execute(
            update(LlmClientRequest)
            .where(
                LlmClientRequest.user_id == reservation["owner_user_id"],
                LlmClientRequest.client_request_id == "strategy-planning-slot",
                LlmClientRequest.request_sha256 == row.request_sha256,
                LlmClientRequest.state == "processing",
            )
            .values(state=final_state, done_json=_json(report))
        )
        session.add(
            LlmCallLog(
                user_id=reservation["owner_user_id"],
                provider=admission["provider"],
                model=admission["model"],
                status="strategy_planning" if known else "strategy_planning_unknown",
                prompt_tokens=prompt if known else 0,
                completion_tokens=completion if known else 0,
                total_tokens=total or 0,
                estimated=not known,
                error="" if known else "Upstream usage absent; reservation retained",
                hold_no=reservation["request_id"][-64:],
            )
        )
        session.commit()
    context = _PLANNING.get()
    if context is not None:
        context["receipts"][:] = [report]


def _cost(prompt: int, completion: int, tariff: dict[str, Any]) -> int:
    numerator = (
        prompt * tariff["input_cents_per_million"] + completion * tariff["output_cents_per_million"]
    )
    return int((numerator + 999_999) // 1_000_000)


def prepare_platform_call(
    provider: str, model: str, messages: list[dict[str, Any]], max_tokens: int | None
) -> dict[str, Any] | None:
    scope = _SCOPE.get()
    planning = _PLANNING.get()
    if scope is None and planning is None:
        return None
    if any(not isinstance(item.get("content", ""), str) for item in messages):
        raise PortfolioError("strategic budget requires text-only model input")
    # Text chat only. This bounds tokenization and protocol framing without
    # introducing a second tokenizer or network-dependent registry.
    prompt_bound = len(_json(messages).encode("utf-8")) * 4 + 256
    output_bound = max_tokens if type(max_tokens) is int and max_tokens > 0 else 1024
    if scope is None:
        assert planning is not None
        return _reserve_planning(planning, provider, model, prompt_bound, output_bound)
    decision_id, opportunity_id, lease_token = scope
    request_id = uuid.uuid4().hex

    def reserve(
        row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any
    ) -> dict[str, Any]:
        require_authorization(row, proposal, state)
        task = state.get("tasks", {}).get(opportunity_id, {})
        if task.get("status") != "running" or task.get("lease_token") != lease_token:
            raise PortfolioError("strategic execution lease is no longer valid")
        if _date(task["deadline"]) <= datetime.now(UTC):
            raise PortfolioError("strategic task compute deadline exceeded")
        tariff = next(
            (
                item
                for item in proposal["limits"]["tariffs"]
                if (item["provider"], item["model"]) == (provider, model)
            ),
            None,
        )
        if tariff is None:
            raise PortfolioError("model route lacks an approved tariff")
        calls = task.setdefault("calls", {})
        # Settled calls consume actual usage; unresolved calls keep full holds.
        used_tokens = sum(
            item.get("actual_tokens", item["reserved_tokens"]) for item in calls.values()
        )
        used_cost = sum(
            item.get("accrued_cost_cents", item["reserved_cost_cents"]) for item in calls.values()
        )
        remaining_tokens = task["reservation"]["tokens"] - used_tokens
        bounded_output = min(output_bound, remaining_tokens - prompt_bound)
        if bounded_output <= 0:
            raise PortfolioError("strategic task token budget exhausted")
        cost = _cost(prompt_bound, bounded_output, tariff)
        if used_cost + cost > task["reservation"]["cost_cents"]:
            raise PortfolioError("strategic task monetary budget exhausted")
        total_cost = sum(
            call.get("accrued_cost_cents", call["reserved_cost_cents"])
            for item in state["tasks"].values()
            for call in item.get("calls", {}).values()
        )
        latest = (state.get("reviews") or [{}])[-1]
        revenue = latest.get("business", {}).get("revenue_cents")
        credited = (
            revenue
            if type(revenue) is int and latest.get("business", {}).get("status") == "verified"
            else 0
        )
        if total_cost + cost - credited > proposal["limits"]["stop_loss_cents"]:
            raise PortfolioError("strategic stop loss budget exhausted")
        calls[request_id] = {
            "status": "pending",
            "provider": provider,
            "model": model,
            "reserved_tokens": prompt_bound + bounded_output,
            "reserved_cost_cents": cost,
            "tariff": tariff,
            "created_at": datetime.now(UTC).isoformat(),
        }
        return {
            "provider": provider,
            "model": model,
            "decision_id": decision_id,
            "opportunity_id": opportunity_id,
            "lease_token": lease_token,
            "request_id": request_id,
            "max_tokens": bounded_output,
            "timeout_seconds": max(
                0.01,
                (
                    min(_date(task["deadline"]), _date(proposal["limits"]["expires_at"]))
                    - datetime.now(UTC)
                ).total_seconds(),
            ),
        }

    return mutate_portfolio(decision_id, reserve)


def complete_platform_call(
    reservation: dict[str, Any] | None, result: dict[str, Any] | None
) -> None:
    if reservation is None:
        return
    if reservation.get("kind") == "strategic_planning":
        _settle_planning(reservation, result)
        return

    def settle(_row: Any, _proposal: dict[str, Any], state: dict[str, Any], _session: Any) -> None:
        task = state.get("tasks", {}).get(reservation["opportunity_id"], {})
        call = task.get("calls", {}).get(reservation["request_id"])
        if call is None or task.get("lease_token") != reservation["lease_token"]:
            raise PortfolioError("strategic usage reservation missing")
        if call["status"] != "pending":
            return
        usage = (result or {}).get("usage") or {}
        prompt = (
            usage.get("prompt_tokens", usage.get("input_tokens"))
            if isinstance(usage, dict)
            else None
        )
        completion = (
            usage.get("completion_tokens", usage.get("output_tokens"))
            if isinstance(usage, dict)
            else None
        )
        verified = (
            type(prompt) is int and type(completion) is int and prompt >= 0 and completion >= 0
        )
        verified = verified and not (result or {}).get("_fallback_used")
        verified = (
            verified
            and usage.get("estimated") is not True
            and (result or {}).get("usage_estimated") is not True
        )
        verified = verified and ((result or {}).get("provider") in (None, "", call["provider"]))
        verified = verified and ((result or {}).get("model") in (None, "", call["model"]))
        if not verified:
            call["status"] = "unknown"
            state.update(halted=True, stop_reason="upstream_usage_unknown")
        else:
            prompt, completion = cast(int, prompt), cast(int, completion)
            cost = _cost(prompt, completion, call["tariff"])
            call.update(
                status="settled",
                actual_tokens=prompt + completion,
                prompt_tokens=prompt,
                completion_tokens=completion,
                accrued_cost_cents=cost,
                cost_basis="approved_tariff_accrual",
            )
            if prompt + completion > call["reserved_tokens"] or cost > call["reserved_cost_cents"]:
                state.update(halted=True, stop_reason="upstream_usage_exceeded_reservation")
        call["completed_at"] = datetime.now(UTC).isoformat()

    mutate_portfolio(reservation["decision_id"], settle)
