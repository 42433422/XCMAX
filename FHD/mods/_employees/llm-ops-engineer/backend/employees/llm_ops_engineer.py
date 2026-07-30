"""Deterministic LLM operations snapshot auditor; never probes or mutates."""

from __future__ import annotations

import re
from typing import Any

_HEALTHY = frozenset({"healthy", "ok", "available", "ready"})
_QUOTA_CLASSES = frozenset({"exact", "usage_only", "unknown"})
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    }
)
_SECRET_VALUE = re.compile(
    r"(?:sk|key|token|secret)[-_][A-Za-z0-9]{8,}",
    re.IGNORECASE,
)


def _text(value: Any, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _contains_sensitive_value(value: Any, *, key: str = "") -> bool:
    normalized_key = key.strip().lower()
    if normalized_key in _SENSITIVE_KEYS and isinstance(value, str) and value.strip():
        return True
    if isinstance(value, str):
        return bool(_SECRET_VALUE.search(value))
    if isinstance(value, dict):
        return any(
            _contains_sensitive_value(item, key=str(item_key)) for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_value(item) for item in value)
    return False


def _issue(issues: list[dict[str, str]], code: str, detail: str) -> None:
    issues.append({"code": code, "detail": detail})


def _health_matrix(
    providers: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for index, provider in enumerate(providers):
        provider_id = _text(provider.get("provider") or provider.get("id"))
        if not provider_id:
            provider_id = f"provider-{index + 1}"
            _issue(issues, "provider_identity_missing", "provider identity is required")
        health = _text(provider.get("health")).lower() or "unknown"
        key_configured = provider.get("key_configured") is True
        quota = provider.get("quota") if isinstance(provider.get("quota"), dict) else {}
        quota_class = _text(quota.get("classification")).lower() or "unknown"
        if quota_class not in _QUOTA_CLASSES:
            _issue(
                issues,
                "quota_classification_invalid",
                f"{provider_id} quota must be exact, usage_only, or unknown",
            )
            quota_class = "unknown"
        remaining = quota.get("remaining") if quota_class == "exact" else None
        if not key_configured:
            _issue(issues, "provider_key_unconfigured", f"{provider_id} has no configured key")
        if health not in _HEALTHY:
            _issue(issues, "provider_unhealthy", f"{provider_id} health is {health}")
        if quota_class == "exact":
            try:
                if float(remaining) <= 0:
                    _issue(
                        issues, "provider_quota_depleted", f"{provider_id} exact quota is depleted"
                    )
            except (TypeError, ValueError):
                _issue(
                    issues,
                    "exact_quota_remaining_invalid",
                    f"{provider_id} exact quota requires numeric remaining",
                )
                remaining = None
        matrix.append(
            {
                "provider": provider_id,
                "key_configured": key_configured,
                "health": health,
                "quota_classification": quota_class,
                "remaining": remaining,
                "latency_ms": provider.get("latency_ms"),
                "cost_per_million_tokens": provider.get("cost_per_million_tokens"),
            }
        )
    return matrix


def _route_issues(
    route: dict[str, Any],
    models: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    provider = _text(route.get("provider"))
    model = _text(route.get("model") or route.get("model_name"))
    selected = next(
        (
            item
            for item in models
            if _text(item.get("provider")) == provider
            and _text(item.get("name") or item.get("model")) == model
        ),
        None,
    )
    if not provider or not model:
        _issue(issues, "current_route_incomplete", "current route requires provider and model")
    elif selected is None:
        _issue(
            issues, "current_route_not_in_catalog", "current route is absent from supplied models"
        )
    else:
        if selected.get("runtime_selectable") is not True:
            _issue(
                issues,
                "current_route_not_runtime_selectable",
                "current route model is not runtime selectable",
            )
        if _text(selected.get("health")).lower() not in _HEALTHY:
            _issue(issues, "current_route_unhealthy", "current route model is not healthy")
    return {
        "provider": provider,
        "model": model,
        "catalog_match": selected is not None,
        "runtime_selectable": bool(selected and selected.get("runtime_selectable") is True),
        "health": _text((selected or {}).get("health")).lower() or "unknown",
    }


def _asset_summary(assets: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
    interfaces = sorted(
        {_text(item, 240) for item in assets.get("interfaces") or [] if _text(item, 240)}
    )
    by_category = assets.get("by_category") if isinstance(assets.get("by_category"), dict) else {}
    categories = {
        _text(name): len(values) if isinstance(values, list) else 0
        for name, values in by_category.items()
        if _text(name)
    }
    providers = sorted({_text(item) for item in assets.get("providers") or [] if _text(item)})
    cli_assets = assets.get("cli_assets") if isinstance(assets.get("cli_assets"), dict) else {}
    if not interfaces:
        _issue(issues, "asset_interfaces_missing", "assets.interfaces must not be empty")
    if not categories:
        _issue(issues, "asset_categories_missing", "assets.by_category must not be empty")
    return {
        "interfaces": interfaces,
        "category_counts": dict(sorted(categories.items())),
        "providers": providers,
        "cli_text_only": sorted(
            {_text(item) for item in cli_assets.get("text_only") or [] if _text(item)}
        ),
        "product_capabilities_not_wired": sorted(
            {
                _text(item, 240)
                for item in cli_assets.get("product_capabilities_not_wired") or []
                if _text(item, 240)
            }
        ),
    }


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("llm_ops_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
        missing_snapshot = True
    else:
        snapshot = dict(snapshot)
        missing_snapshot = False

    issues: list[dict[str, str]] = []
    if missing_snapshot:
        _issue(issues, "missing_llm_ops_snapshot", "llm_ops_snapshot is required")
    if snapshot.get("secrets_redacted") is not True:
        _issue(issues, "secret_redaction_unproven", "snapshot must attest secrets_redacted=true")
    if _contains_sensitive_value(snapshot):
        return {
            "ok": False,
            "status": "blocked",
            "summary": "LLM 运维快照包含疑似敏感凭据，已拒绝审计且未回显原值。",
            "health_matrix": [],
            "current_route": {},
            "asset_summary": {},
            "issues": [
                {
                    "code": "sensitive_value_blocked",
                    "detail": "snapshot contains a credential-like key or value",
                }
            ],
            "evidence": ["input_rejected_before_echo", "no_secret_output"],
            "read_only": True,
            "side_effects": [],
        }

    providers = _objects(snapshot.get("providers"))
    models = _objects(snapshot.get("models"))
    route = (
        dict(snapshot.get("current_route"))
        if isinstance(snapshot.get("current_route"), dict)
        else {}
    )
    assets = dict(snapshot.get("assets")) if isinstance(snapshot.get("assets"), dict) else {}
    if not providers:
        _issue(issues, "providers_missing", "providers health evidence is required")
    if not models:
        _issue(issues, "models_missing", "model catalog evidence is required")
    health_matrix = _health_matrix(providers, issues)
    route_summary = _route_issues(route, models, issues)
    asset_summary = _asset_summary(assets, issues)
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": (
            "LLM provider、模型路由、额度分类与 AI 资产快照均满足只读巡检契约。"
            if approved
            else "LLM 运维快照已完成只读审计，发现需要处理的健康或契约问题。"
        ),
        "health_matrix": health_matrix,
        "current_route": route_summary,
        "asset_summary": asset_summary,
        "issues": issues,
        "evidence": [
            "input.llm_ops_snapshot.providers",
            "input.llm_ops_snapshot.models",
            "input.llm_ops_snapshot.current_route",
            "input.llm_ops_snapshot.assets",
            "no_network_access",
            "no_secret_access",
            "no_route_mutation",
        ],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
