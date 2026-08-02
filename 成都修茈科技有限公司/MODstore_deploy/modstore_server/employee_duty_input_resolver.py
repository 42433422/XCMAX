"""Resolve reviewed employee duties against real, read-only platform data.

Scheduled employee contracts describe *what* a role must do, while deterministic
employee modules declare the concrete input schema.  Previously the scheduler
passed only the prose mission, so modules that correctly required ``facts``,
``deliveries`` or a billing ``ledger`` failed before doing any work.

This module is the narrow data-plane bridge between those two contracts.  It
reads only operational SSOTs, removes direct customer identifiers, bounds every
query, and writes a compact provenance receipt before execution.  An
authoritative empty result remains an explicit ``no_data`` observation; it is
never filled with fixtures or promoted to a business outcome.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

DEFAULT_RECEIPT_NAME = "employee_duty_input_receipts.jsonl"
_MAX_ROWS = 500


@dataclass(frozen=True)
class ResolvedDutyInput:
    input_data: dict[str, Any]
    sources: tuple[str, ...]
    row_count: int
    truncated: bool = False


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _runtime_dir() -> Path:
    raw = str(os.environ.get("MODSTORE_RUNTIME_DIR") or "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".xcmax" / "modstore-daily"


def receipt_path() -> Path:
    raw = str(os.environ.get("MODSTORE_DUTY_INPUT_RECEIPT_FILE") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / DEFAULT_RECEIPT_NAME


def _receipt_max_bytes() -> int:
    try:
        mib = int(str(os.environ.get("MODSTORE_DUTY_INPUT_RECEIPT_MAX_MIB") or "16"))
    except ValueError:
        mib = 16
    return max(1, min(mib, 1024)) * 1024**2


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pseudonym(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _append_receipt(record: Mapping[str, Any]) -> None:
    path = receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_fh:
        try:
            import fcntl

            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        size = path.stat().st_size if path.exists() else 0
        if size >= _receipt_max_bytes():
            archive = path.with_suffix(path.suffix + ".1")
            archive.unlink(missing_ok=True)
            path.replace(archive)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _query_rows(statement: str, parameters: Mapping[str, Any] | None = None) -> list[dict]:
    """Run one bounded read through the configured application database."""

    from sqlalchemy import text

    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    with sf() as session:
        rows = session.execute(text(statement), dict(parameters or {})).mappings().all()
    return [dict(row) for row in rows]


def _bounded(rows: Sequence[dict], limit: int = _MAX_ROWS) -> tuple[list[dict], bool]:
    return list(rows[:limit]), len(rows) > limit


def _to_cents(value: Any) -> int:
    try:
        decimal = Decimal(str(value or 0)) * Decimal("100")
    except (InvalidOperation, ValueError):
        return 0
    return int(decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _knowledge_input(_now: datetime) -> ResolvedDutyInput:
    rows, truncated = _bounded(
        _query_rows(
            "SELECT doc_id, size_bytes, chunk_count, created_at "
            "FROM knowledge_documents ORDER BY id DESC LIMIT 501"
        )
    )
    facts = []
    for row in rows:
        size = max(0, int(row.get("size_bytes") or 0))
        chunks = max(0, int(row.get("chunk_count") or 0))
        source_id = _pseudonym("knowledge-document", row.get("doc_id"))
        facts.append(
            {
                "statement": (
                    "知识索引持久化文档元数据："
                    f"size_bytes={size}, chunk_count={chunks}, "
                    f"created_at={str(row.get('created_at') or '')[:32]}"
                ),
                "source": f"database://knowledge_documents/{source_id}",
                "verified": True,
            }
        )
    return ResolvedDutyInput(
        input_data={"facts": facts},
        sources=("knowledge_documents",),
        row_count=len(rows),
        truncated=truncated,
    )


def _delivery_input(_now: datetime) -> ResolvedDutyInput:
    rows, truncated = _bounded(
        _query_rows(
            "SELECT receipt_id, customer_ref, source_employee_id, evidence_json, occurred_at "
            "FROM customer_value_receipts "
            "WHERE receipt_kind IN ('delivery', 'acceptance') "
            "AND verification_status = 'verified' "
            "ORDER BY id DESC LIMIT 501"
        )
    )
    deliveries = []
    for row in rows:
        try:
            evidence = json.loads(str(row.get("evidence_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence = {}
        evidence = evidence if isinstance(evidence, dict) else {}
        raw_sla = evidence.get("sla") if isinstance(evidence.get("sla"), dict) else {}
        delivery = {
            "partner_id": _pseudonym("customer", row.get("customer_ref") or row.get("receipt_id")),
            "delivery_receipt_id": str(row.get("receipt_id") or ""),
            "owner": str(row.get("source_employee_id") or "delivery-receipt-officer"),
            "sla_status": str(evidence.get("sla_status") or raw_sla.get("status") or ""),
            "observed_at": str(row.get("occurred_at") or "")[:32],
        }
        next_step = str(evidence.get("next_step") or raw_sla.get("next_step") or "").strip()
        if next_step:
            delivery["next_step"] = next_step[:500]
        deliveries.append(delivery)
    return ResolvedDutyInput(
        input_data={"deliveries": deliveries},
        sources=("customer_value_receipts",),
        row_count=len(rows),
        truncated=truncated,
    )


def _revenue_share_input(_now: datetime) -> ResolvedDutyInput:
    rows, truncated = _bounded(
        _query_rows(
            "SELECT order_id, author_id, gross, platform_fee_rate, net, status "
            "FROM author_earnings ORDER BY id DESC LIMIT 501"
        )
    )
    entries = []
    for row in rows:
        try:
            fee_rate = Decimal(str(row.get("platform_fee_rate") or 0))
        except InvalidOperation:
            fee_rate = Decimal("0")
        fee_rate = max(Decimal("0"), min(fee_rate, Decimal("1")))
        entries.append(
            {
                "partner_id": _pseudonym("author", row.get("author_id")),
                "gross_cents": _to_cents(row.get("gross")),
                "share_bps": int(
                    ((Decimal("1") - fee_rate) * Decimal("10000")).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                ),
                "recorded_share_cents": _to_cents(row.get("net")),
                "order_ref": _pseudonym("order", row.get("order_id")),
                "settlement_status": str(row.get("status") or "pending"),
            }
        )
    return ResolvedDutyInput(
        input_data={"entries": entries},
        sources=("author_earnings",),
        row_count=len(rows),
        truncated=truncated,
    )


def _quality_input(now: datetime) -> ResolvedDutyInput:
    from modstore_server.duty_workforce_contracts import (
        load_reviewed_duty_manifest,
        workforce_contract_map,
    )

    contracts = workforce_contract_map()
    candidates = sorted(contracts)
    if not candidates:
        raise RuntimeError("reviewed duty workforce is empty")
    employee_id = candidates[now.date().toordinal() % len(candidates)]
    manifest = load_reviewed_duty_manifest(employee_id)
    config = manifest.get("employee_config_v2") or {}
    actions = config.get("actions") if isinstance(config.get("actions"), dict) else {}
    direct = actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
    contract = contracts.get(employee_id) or {}
    capability = {
        "employee_id": employee_id,
        "manifest_version": str(manifest.get("version") or ""),
        "input_contract": (
            direct.get("input_schema") if isinstance(direct.get("input_schema"), dict) else {}
        ),
        "handlers": list(actions.get("handlers") or []),
        "acceptance": list(contract.get("acceptance") or []),
        "manifest_digest": _canonical_digest(manifest),
    }
    return ResolvedDutyInput(
        input_data={"capability": capability},
        sources=("reviewed_duty_manifest_ssot", "duty_employee_work_contracts"),
        row_count=1,
    )


def _filesystem_input(
    resolver: Callable[[datetime], tuple[dict[str, Any], tuple[str, ...], int, bool]],
    now: datetime,
) -> ResolvedDutyInput:
    input_data, sources, row_count, truncated = resolver(now)
    return ResolvedDutyInput(
        input_data=input_data,
        sources=sources,
        row_count=row_count,
        truncated=truncated,
    )


def _interview_input(now: datetime) -> ResolvedDutyInput:
    from modstore_server.employee_duty_filesystem_inputs import interview_input

    return _filesystem_input(interview_input, now)


def _pack_validator_input(now: datetime) -> ResolvedDutyInput:
    from modstore_server.employee_duty_filesystem_inputs import quality_validator_input

    return _filesystem_input(quality_validator_input, now)


def _architecture_input(now: datetime) -> ResolvedDutyInput:
    from modstore_server.employee_duty_filesystem_inputs import architecture_input

    return _filesystem_input(architecture_input, now)


def _activity_days(rows: Iterable[Mapping[str, Any]], *, cutoff: datetime) -> set[date]:
    days: set[date] = set()
    for row in rows:
        observed = _as_datetime(row.get("created_at"))
        if observed is not None and observed >= cutoff:
            days.add(observed.date())
    return days


def _enterprise_input(now: datetime) -> ResolvedDutyInput:
    users, users_truncated = _bounded(
        _query_rows(
            "SELECT id, created_at FROM users "
            "WHERE is_enterprise = true ORDER BY id ASC LIMIT 501"
        )
    )
    transactions = _query_rows(
        "SELECT user_id, txn_type, status, created_at FROM transactions "
        "WHERE user_id IN (SELECT id FROM users WHERE is_enterprise = true) "
        "AND lower(status) IN ('completed', 'success') "
        "ORDER BY id DESC LIMIT 10001"
    )
    purchases = _query_rows(
        "SELECT user_id, amount, created_at FROM purchases "
        "WHERE user_id IN (SELECT id FROM users WHERE is_enterprise = true) "
        "ORDER BY id DESC LIMIT 10001"
    )
    llm_calls = _query_rows(
        "SELECT user_id, status, created_at FROM llm_call_logs "
        "WHERE user_id IN (SELECT id FROM users WHERE is_enterprise = true) "
        "AND lower(status) IN ('completed', 'success') "
        "ORDER BY id DESC LIMIT 10001"
    )
    cutoff = now - timedelta(days=30)
    tenants = []
    for user in users:
        user_id = user.get("id")
        user_transactions = [row for row in transactions if row.get("user_id") == user_id]
        user_purchases = [row for row in purchases if row.get("user_id") == user_id]
        user_llm = [row for row in llm_calls if row.get("user_id") == user_id]
        activity_days = set()
        for activity in (user_transactions, user_purchases, user_llm):
            activity_days.update(_activity_days(activity, cutoff=cutoff))
        features = []
        if any(
            str(row.get("status") or "").lower() in {"success", "completed"} for row in user_llm
        ):
            features.append("ai_chat")
        if user_transactions:
            features.append("billing_wallet")
        if user_purchases:
            features.append("modstore_purchase")
        paid_purchase = any(_to_cents(row.get("amount")) > 0 for row in user_purchases)
        blockers = []
        if not activity_days:
            blockers.append("no_verified_30d_activity")
        if not paid_purchase:
            blockers.append("no_verified_paid_adoption")
        tenants.append(
            {
                "tenant_id": _pseudonym("enterprise-tenant", user_id),
                "activated": _as_datetime(user.get("created_at")) is not None,
                "active_days_30": min(30, len(activity_days)),
                "adopted_features": sorted(set(features)),
                "blocked_reasons": blockers,
                "value_milestones": ["paid_catalog_purchase"] if paid_purchase else [],
            }
        )
    return ResolvedDutyInput(
        input_data={"tenants": tenants},
        sources=("users", "transactions", "purchases", "llm_call_logs"),
        row_count=len(users),
        truncated=(
            users_truncated
            or len(transactions) > 10000
            or len(purchases) > 10000
            or len(llm_calls) > 10000
        ),
    )


def _payment_input(_now: datetime) -> ResolvedDutyInput:
    orders, orders_truncated = _bounded(
        _query_rows("SELECT id, amount FROM purchases ORDER BY id DESC LIMIT 501")
    )
    payments, payments_truncated = _bounded(
        _query_rows(
            "SELECT id, amount FROM transactions "
            "WHERE txn_type = 'alipay_wallet' AND status = 'completed' AND amount >= 0 "
            "ORDER BY id DESC LIMIT 501"
        )
    )
    refunds, refunds_truncated = _bounded(
        _query_rows(
            "SELECT id, amount FROM transactions "
            "WHERE lower(txn_type) LIKE '%refund%' AND status = 'completed' "
            "ORDER BY id DESC LIMIT 501"
        )
    )
    ledger = {
        "orders": [
            {
                "id": _pseudonym("purchase", row.get("id")),
                "amount_cents": _to_cents(row.get("amount")),
            }
            for row in orders
        ],
        "payments": [
            {
                "id": _pseudonym("payment", row.get("id")),
                "amount_cents": abs(_to_cents(row.get("amount"))),
            }
            for row in payments
        ],
        "refunds": [
            {
                "id": _pseudonym("refund", row.get("id")),
                "amount_cents": abs(_to_cents(row.get("amount"))),
            }
            for row in refunds
        ],
    }
    return ResolvedDutyInput(
        input_data={"ledger": ledger},
        sources=("purchases", "transactions"),
        row_count=len(orders) + len(payments) + len(refunds),
        truncated=orders_truncated or payments_truncated or refunds_truncated,
    )


def _legacy_archive_input(now: datetime) -> ResolvedDutyInput:
    """Audit the active immutable release as a bounded archive inventory row."""

    explicit = str(os.environ.get("MODSTORE_RELEASE_MANIFEST") or "").strip()
    if explicit:
        manifest_path = Path(explicit).expanduser()
    else:
        repo_root = str(os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
        if not repo_root:
            raise RuntimeError("immutable release manifest is not configured")
        manifest_path = Path(repo_root).expanduser() / ".xcmax-release.json"
    try:
        release = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("immutable release manifest is unavailable") from exc
    git_sha = str(release.get("git_sha") or "").strip().lower()
    if len(git_sha) != 40 or any(char not in "0123456789abcdef" for char in git_sha):
        raise RuntimeError("immutable release manifest has no valid git_sha")
    try:
        observed = datetime.fromtimestamp(manifest_path.stat().st_mtime, timezone.utc)
    except OSError as exc:
        raise RuntimeError("immutable release manifest cannot be inspected") from exc
    last_used_days = max(0.0, (_utc(now) - observed).total_seconds() / 86400)
    inventory = [
        {
            "path": f"releases/{git_sha}",
            "referenced_by": ["current"],
            "last_used_days": round(last_used_days, 4),
            "recovery_path": f"git:{git_sha}",
        }
    ]
    return ResolvedDutyInput(
        input_data={"inventory": inventory},
        sources=("immutable_release_manifest",),
        row_count=1,
    )


def _investor_portal_input(_now: datetime) -> ResolvedDutyInput:
    """Convert the public founder scorecard into a privacy-safe investor view."""

    state_root = Path(
        str(os.environ.get("XCMAX_PUBLIC_SITE_STATE_DIR") or "/var/lib/xcmax-public")
    ).expanduser()
    projection_path = state_root / "download-founder-autonomy.json"
    try:
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("public founder autonomy projection is unavailable") from exc
    dimensions = projection.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise RuntimeError("public founder autonomy projection has no dimensions")
    milestones: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for raw in dimensions[:32]:
        row = raw if isinstance(raw, dict) else {}
        dimension_id = str(row.get("id") or "").strip()
        try:
            progress = max(0.0, min(float(row.get("progress") or 0), 100.0))
        except (TypeError, ValueError):
            continue
        if not dimension_id:
            continue
        milestones.append(
            {
                "id": dimension_id,
                "status": "complete" if progress >= 100 else "in_progress",
                "progress_pct": round(progress, 2),
                "evidence_ref": f"public-founder-autonomy:{dimension_id}",
            }
        )
        remaining = max(0.0, 100.0 - progress)
        if remaining:
            risks.append(
                {
                    "id": f"gap-{dimension_id}",
                    "severity": "high" if remaining >= 50 else "medium",
                    "status": "open",
                    "mitigation": str(row.get("next_gap") or "补齐可验证运行证据")[:300],
                }
            )
    if not milestones:
        raise RuntimeError("public founder autonomy projection has no valid dimensions")
    return ResolvedDutyInput(
        input_data={"milestones": milestones, "risks": risks},
        sources=("public_founder_autonomy_projection",),
        row_count=len(milestones),
        truncated=len(dimensions) > 32,
    )


def _llm_ops_input(now: datetime) -> ResolvedDutyInput:
    """Build a secret-free LLM route snapshot from local production evidence."""

    cutoff = _utc(now) - timedelta(hours=24)
    rows, truncated = _bounded(
        _query_rows(
            "SELECT provider, model, status, total_tokens, created_at "
            "FROM llm_call_logs WHERE created_at >= :cutoff "
            "ORDER BY id DESC LIMIT 501",
            {"cutoff": cutoff.replace(tzinfo=None)},
        )
    )
    from modstore_server.duty_roster import all_planned_employee_ids
    from modstore_server.llm_key_resolver import platform_api_key
    from modstore_server.services.llm import resolve_platform_bench_llm

    provider, model = resolve_platform_bench_llm()
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    configured = bool(provider and platform_api_key(provider))
    route_rows = [
        row
        for row in rows
        if str(row.get("provider") or "").strip().lower() == provider
        and str(row.get("model") or "").strip() == model
    ]
    success_rows = [
        row
        for row in route_rows
        if str(row.get("status") or "").strip().lower() in {"success", "completed"}
    ]
    health = "healthy" if configured and success_rows else "unknown"
    snapshot = {
        "secrets_redacted": True,
        "providers": [
            {
                "provider": provider or "unresolved",
                "key_configured": configured,
                "health": health,
                "quota": {"classification": "usage_only"},
            }
        ],
        "models": [
            {
                "provider": provider,
                "name": model,
                "runtime_selectable": configured and bool(model),
                "health": health,
            }
        ],
        "current_route": {"provider": provider, "model": model},
        "assets": {
            "interfaces": ["platform_ai_employee_runtime", "llm_runtime_route"],
            "by_category": {
                "duty_employees": sorted(all_planned_employee_ids()),
                "runtime_models": [model] if model else [],
            },
            "providers": [provider] if provider else [],
            "cli_assets": {
                "text_only": [],
                "product_capabilities_not_wired": [],
            },
        },
    }
    return ResolvedDutyInput(
        input_data={"llm_ops_snapshot": snapshot},
        sources=("llm_call_logs", "platform_runtime_route", "duty_roster"),
        row_count=len(route_rows),
        truncated=truncated,
    )


_RESOLVERS: dict[str, Callable[[datetime], ResolvedDutyInput]] = {
    "doc-knowledge-curator": _knowledge_input,
    "ecosystem-delivery-reporter": _delivery_input,
    "ecosystem-investor-portal-officer": _investor_portal_input,
    "ecosystem-revenue-share-reconciler": _revenue_share_input,
    "employee-interview-assistant": _interview_input,
    "employee-pack-quality-interviewer": _quality_input,
    "enterprise-adoption-officer": _enterprise_input,
    "legacy-archive-curator": _legacy_archive_input,
    "llm-ops-engineer": _llm_ops_input,
    "payment-billing-reconciler": _payment_input,
    "quality-validator": _pack_validator_input,
    "top-architect": _architecture_input,
}


def resolve_employee_duty_input(
    employee_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return audited real input for a supported scheduled employee."""

    normalized = str(employee_id or "").strip()
    resolver = _RESOLVERS.get(normalized)
    if resolver is None:
        return None
    observed_at = _utc(now)
    resolved = resolver(observed_at)
    receipt = {
        "schema": "xcagi.employee_duty_input_receipt/v1",
        "employee_id": normalized,
        "status": "data" if resolved.row_count > 0 else "no_data",
        "row_count": max(0, int(resolved.row_count)),
        "sources": list(resolved.sources),
        "truncated": bool(resolved.truncated),
        "payload_digest": _canonical_digest(resolved.input_data),
        "observed_at": observed_at.isoformat(),
        "read_only": True,
        "contains_direct_customer_identifiers": False,
    }
    _append_receipt(receipt)
    input_data = dict(resolved.input_data)
    input_data["_duty_input_receipt"] = receipt
    return {"input_data": input_data, "receipt": receipt}


__all__ = [
    "ResolvedDutyInput",
    "receipt_path",
    "resolve_employee_duty_input",
]
