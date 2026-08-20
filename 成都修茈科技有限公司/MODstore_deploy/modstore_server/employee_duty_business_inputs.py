"""Business-data resolvers for scheduled employee duty inputs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def enterprise_input(now: datetime):
    from modstore_server import employee_duty_input_resolver as core

    users, users_truncated = core._bounded(
        core._query_rows(
            "SELECT id, created_at FROM users WHERE is_enterprise = true ORDER BY id ASC LIMIT 501"
        )
    )
    transactions = core._query_rows(
        "SELECT user_id, txn_type, status, created_at FROM transactions "
        "WHERE user_id IN (SELECT id FROM users WHERE is_enterprise = true) "
        "AND lower(status) IN ('completed', 'success') "
        "ORDER BY id DESC LIMIT 10001"
    )
    purchases = core._query_rows(
        "SELECT user_id, amount, created_at FROM purchases "
        "WHERE user_id IN (SELECT id FROM users WHERE is_enterprise = true) "
        "ORDER BY id DESC LIMIT 10001"
    )
    llm_calls = core._query_rows(
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
            activity_days.update(core._activity_days(activity, cutoff=cutoff))
        features = []
        if any(
            str(row.get("status") or "").lower() in {"success", "completed"} for row in user_llm
        ):
            features.append("ai_chat")
        if user_transactions:
            features.append("billing_wallet")
        if user_purchases:
            features.append("modstore_purchase")
        paid_purchase = any(core._to_cents(row.get("amount")) > 0 for row in user_purchases)
        blockers = []
        if not activity_days:
            blockers.append("no_verified_30d_activity")
        if not paid_purchase:
            blockers.append("no_verified_paid_adoption")
        tenants.append(
            {
                "tenant_id": core._pseudonym("enterprise-tenant", user_id),
                "activated": core._as_datetime(user.get("created_at")) is not None,
                "active_days_30": min(30, len(activity_days)),
                "adopted_features": sorted(set(features)),
                "blocked_reasons": blockers,
                "value_milestones": ["paid_catalog_purchase"] if paid_purchase else [],
            }
        )
    return core.ResolvedDutyInput(
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


def payment_input(_now: datetime):
    from modstore_server import employee_duty_input_resolver as core

    orders, orders_truncated = core._bounded(
        core._query_rows("SELECT id, amount FROM purchases ORDER BY id DESC LIMIT 501")
    )
    payments, payments_truncated = core._bounded(
        core._query_rows(
            "SELECT id, amount FROM transactions "
            "WHERE txn_type = 'alipay_wallet' AND status = 'completed' AND amount >= 0 "
            "ORDER BY id DESC LIMIT 501"
        )
    )
    refunds, refunds_truncated = core._bounded(
        core._query_rows(
            "SELECT id, amount FROM transactions "
            "WHERE lower(txn_type) LIKE '%refund%' AND status = 'completed' "
            "ORDER BY id DESC LIMIT 501"
        )
    )
    ledger = {
        "orders": [
            {
                "id": core._pseudonym("purchase", row.get("id")),
                "amount_cents": core._to_cents(row.get("amount")),
            }
            for row in orders
        ],
        "payments": [
            {
                "id": core._pseudonym("payment", row.get("id")),
                "amount_cents": abs(core._to_cents(row.get("amount"))),
            }
            for row in payments
        ],
        "refunds": [
            {
                "id": core._pseudonym("refund", row.get("id")),
                "amount_cents": abs(core._to_cents(row.get("amount"))),
            }
            for row in refunds
        ],
    }
    return core.ResolvedDutyInput(
        input_data={"ledger": ledger},
        sources=("purchases", "transactions"),
        row_count=len(orders) + len(payments) + len(refunds),
        truncated=orders_truncated or payments_truncated or refunds_truncated,
    )


def llm_ops_input(now: datetime):
    from modstore_server import employee_duty_input_resolver as core

    cutoff = core._utc(now) - timedelta(hours=24)
    rows, truncated = core._bounded(
        core._query_rows(
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
    snapshot: dict[str, Any] = {
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
            "cli_assets": {"text_only": [], "product_capabilities_not_wired": []},
        },
    }
    return core.ResolvedDutyInput(
        input_data={"llm_ops_snapshot": snapshot},
        sources=("llm_call_logs", "platform_runtime_route", "duty_roster"),
        row_count=len(route_rows),
        truncated=truncated,
    )
