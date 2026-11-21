"""Thin SearXNG JSON API adapter into the existing strategy proposal consumer.

Reuse the configured self-hosted research service and shared HTTP client. Search
snippets and engine-reported dates are evidence for hypotheses, not verified
market facts or authority to execute instructions embedded in a search result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from modstore_server.strategic_customer_outcomes import load_customer_goal_bindings
from modstore_server.strategic_portfolio import PortfolioError, digest
from modstore_server.strategy_bets import CUSTOMER_ACCEPTANCE_METRIC, repo_root


class MarketQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=3, max_length=500)
    domain_id: str = Field(min_length=1, max_length=64)
    allowed_hosts: list[str] = Field(min_length=1, max_length=8)
    employee_id: str = Field(min_length=1, max_length=128)
    customer_user_id: int = Field(gt=0)
    order_no: str = Field(min_length=1, max_length=96)
    customer_goal_ids: list[str] = Field(min_length=1, max_length=16)
    acceptance_target: float = Field(default=0.5, ge=0, le=1)
    window_days: int = Field(default=7, ge=1, le=90)

    @field_validator("allowed_hosts")
    @classmethod
    def valid_hosts(cls, values: list[str]) -> list[str]:
        import re

        hosts = [value.strip().lower().rstrip(".") for value in values]
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host) for host in hosts):
            raise ValueError("market sources require explicit DNS hostnames")
        return list(dict.fromkeys(hosts))


class MarketResearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    queries: list[MarketQuery] = Field(min_length=1, max_length=4)
    results_per_query: int = Field(default=3, ge=1, le=4)
    max_publication_age_days: int = Field(default=30, ge=1, le=365)


def _publication_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(raw)
        except (ValueError, TypeError, OverflowError):
            return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


async def discover_market(
    config: MarketResearchConfig | dict[str, Any] | None,
    *,
    owner_user_id: int,
    employees: list[str],
) -> dict[str, Any]:
    if config is None:
        return {"status": "not_configured", "queries": [], "evidence": []}
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.db.identity import User
    from modstore_server.infrastructure.http_clients import get_external_client
    from modstore_server.research_tools import searxng_instance_url

    settings = MarketResearchConfig.model_validate(config)
    with get_session_factory()() as session:
        actor = session.get(User, owner_user_id)
        if (
            not actor
            or not actor.is_admin
            or actor.deleted_at
            or actor.account_state in {"deleted", "disabled", "suspended", "blocked"}
        ):
            raise PortfolioError("market discovery requires an active strategy administrator")
    catalog = json.loads(
        (repo_root() / "FHD/config/audit_benchmark_ssot.json").read_text(encoding="utf-8")
    )
    domains = {row["id"]: row for row in catalog["domains"]}
    queries = []
    for configured_query in settings.queries:
        if (
            configured_query.domain_id not in domains
            or configured_query.employee_id not in employees
        ):
            raise PortfolioError("market query must use a canonical domain and registered employee")
        bindings = load_customer_goal_bindings(
            configured_query.customer_user_id,
            configured_query.order_no,
            configured_query.customer_goal_ids,
        )
        queries.append(
            {
                **configured_query.model_dump(),
                "query_id": "market-query-" + digest(configured_query.model_dump())[:24],
                "customer_goal_bindings": bindings,
                "domain_scope": domains[configured_query.domain_id]["xcmax_scope"],
                "domain_reference": domains[configured_query.domain_id]["open_source_60"]["url"],
            }
        )
    base = searxng_instance_url()
    if not base:
        return {
            "status": "unavailable",
            "reason": "MODSTORE_SEARXNG_URL_not_configured",
            "queries": queries,
            "evidence": [],
        }
    evidence, errors = [], []
    rejected: dict[str, int] = {}
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.max_publication_age_days)
    client = get_external_client()
    for query in queries:
        try:
            response = await client.get(
                f"{base.rstrip('/')}/search",
                params={
                    "q": query["query"],
                    "format": "json",
                    "language": "zh-CN",
                    "time_range": "month" if settings.max_publication_age_days <= 30 else "year",
                },
                timeout=22.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            body = response.json()
            rows = body.get("results") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise ValueError("invalid_searxng_results")
        except (httpx.HTTPError, ValueError) as exc:
            errors.append({"query_id": query["query_id"], "reason": type(exc).__name__})
            continue
        seen: set[str] = set()
        for raw in rows[:100]:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            try:
                parsed = urlsplit(url)
                host = (parsed.hostname or "").lower().rstrip(".")
            except ValueError:
                continue
            published = _publication_date(raw.get("publishedDate"))
            reason = ""
            if parsed.scheme not in {"http", "https"} or not any(
                host == allowed or host.endswith("." + allowed)
                for allowed in query["allowed_hosts"]
            ):
                reason = "source_host_not_allowed"
            elif published is None:
                reason = "publication_date_unknown"
            elif not cutoff <= published <= now:
                reason = "publication_date_outside_window"
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            if url in seen:
                continue
            seen.add(url)
            snapshot = {
                "query_id": query["query_id"],
                "domain_id": query["domain_id"],
                "url": url[:2048],
                "title": str(raw.get("title") or url)[:300],
                "snippet": str(raw.get("content") or "")[:1600],
                "published_at": published.isoformat() if published else None,
                "observed_at": now.isoformat(),
                "date_basis": "search_engine_reported_not_independently_verified",
                "engine": str(raw.get("engine") or "")[:100],
            }
            sha = digest(snapshot)
            evidence.append(
                {**snapshot, "evidence_id": "market-" + sha[:32], "snapshot_sha256": sha}
            )
            if len(seen) >= settings.results_per_query:
                break
    return {
        "status": "observed" if evidence else "unavailable" if errors else "no_fresh_source",
        "source": "configured_searxng_json_api",
        "queries": queries,
        "evidence": evidence,
        "errors": errors,
        "rejected_sources": rejected,
        "observed_at": now.isoformat(),
        "publication_cutoff": cutoff.isoformat(),
    }


def market_candidates(context: dict[str, Any]) -> list[dict[str, Any]]:
    """No-model fallback proposes a measurable experiment from an observed source."""
    market = context.get("market") or {}
    rows = []
    for query in market.get("queries") or []:
        evidence = [
            row for row in market.get("evidence") or [] if row["query_id"] == query["query_id"]
        ]
        if not evidence:
            continue
        rows.append(
            {
                "title": f"验证产品机会：{evidence[0]['title']}"[:200],
                "hypothesis": f"将 {query['domain_id']} 的市场观察转为原客户目标的可用交付，客户确认比例达到 {query['acceptance_target']}；来源只是待验证假设。",
                "metric_id": CUSTOMER_ACCEPTANCE_METRIC,
                "threshold": query["acceptance_target"],
                "direction": "max",
                "window_days": query["window_days"],
                "kill_criteria": [
                    "批准观察窗口结束，已交付客户目标的确认比例未达阈值则停止本假设投入"
                ],
                "expected_value": 3,
                "effort": 2,
                "employee_id": query["employee_id"],
                "customer_goal_ids": query["customer_goal_ids"],
                "market_evidence_ids": [row["evidence_id"] for row in evidence],
            }
        )
    return rows


def bind_market_candidate(feature: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    """Resolve model citations back to the operator-configured executor and customer."""
    ids = feature.get("market_evidence_ids") or []
    if not ids:
        return {}
    observed = {row["evidence_id"]: row for row in market.get("evidence") or []}
    if not isinstance(ids, list) or not all(
        isinstance(key, str) and key in observed for key in ids
    ):
        raise PortfolioError("market hypothesis cites unobserved evidence")
    evidence = [observed[key] for key in dict.fromkeys(ids)]
    query_ids = {row["query_id"] for row in evidence}
    if len(query_ids) != 1:
        raise PortfolioError("market hypothesis must use one approved query/customer scope")
    query = next(row for row in market["queries"] if row["query_id"] in query_ids)
    if set(feature.get("customer_goal_ids") or []) != set(query["customer_goal_ids"]):
        raise PortfolioError("market hypothesis must retain the original customer goal population")
    if feature.get("employee_id") != query["employee_id"]:
        raise PortfolioError("market hypothesis changed its configured executor")
    return {
        "customer_goal_bindings": query["customer_goal_bindings"],
        "source_refs": [f"market:{row['snapshot_sha256']}:{row['url']}" for row in evidence],
        "market_evidence": {
            "query": query,
            "sources": evidence,
            "interpretation": "untrusted_market_observations_for_approved_hypothesis",
        },
    }
