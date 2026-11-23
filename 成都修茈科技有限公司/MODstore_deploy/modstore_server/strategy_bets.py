"""Hypothesis evidence adapted from PR #3396 (a0cf41c3), with one SQL control plane.

The original metric adapters and threshold semantics remain reusable. Historical
JSONL is read-only; approvals, actual usage and outcome snapshots live exclusively
in StrategicDecision/StrategicActionItem through strategic_portfolio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modstore_server import evolution_ledger

UTC = UTC
BET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
DEFAULT_BUDGET: Dict[str, int] = {
    "proposals": 4,
    "tokens": 400000,
    "ci_minutes": 240,
    "human_hours": 8,
}
DIRECTIONS = {"max", "min"}

# 只读已有报告，不新增采集；具体取值见 ``read_metric``。
METRIC_SOURCES: Dict[str, str] = {
    "slo_availability": "SLO-API-01",
    "slo_error_rate": "SLO-API-03",
    "intent_accuracy": "FHD/metrics/intent_benchmark_latest.json",
    "legacy_ratio": "FHD/metrics/legacy-usage-168h.json",
}
REVENUE_METRIC = "revenue_monthly"
CUSTOMER_ACCEPTANCE_METRIC = "customer_acceptance_ratio"
DOMAIN_METRIC = "domain_rated_ratio"
DEFAULT_DOMAIN_AUDIT = "FHD/config/domain_audit.json"

REGISTERED = "strategy_bet_registered"
SPEND = "strategy_bet_spend"
OUTCOME = "strategy_outcome"


class BetHypothesis(BaseModel):
    """An approved, falsifiable target; no model-generated spending authority."""

    model_config = ConfigDict(extra="forbid", strict=True)
    hypothesis: str = Field(min_length=1, max_length=2000)
    metric_id: str = Field(min_length=1, max_length=64)
    threshold: float = Field(allow_inf_nan=False)
    direction: str
    window_days: int = Field(ge=1, le=365)
    kill_criteria: list[str] = Field(min_length=1, max_length=16)
    kill_on_miss: bool = True

    @model_validator(mode="after")
    def valid_metric(self):
        if (
            self.metric_id
            not in {*METRIC_SOURCES, REVENUE_METRIC, DOMAIN_METRIC, CUSTOMER_ACCEPTANCE_METRIC}
            or self.direction not in DIRECTIONS
        ):
            raise ValueError("unsupported strategy metric or direction")
        if self.metric_id == CUSTOMER_ACCEPTANCE_METRIC and not 0 <= self.threshold <= 1:
            raise ValueError("customer acceptance threshold must be between zero and one")
        return self


class BudgetExceeded(ValueError):
    """赌注预算不足；调用方必须放弃本次动作，而不是绕过。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _positive_int(budget: Dict[str, Any], key: str) -> int:
    raw = budget.get(key, DEFAULT_BUDGET[key])
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"预算字段 {key} 必须是正整数")
    return raw


def register_bet(**_kwargs: Any) -> Dict[str, Any]:
    """Legacy writes cannot create an executable budget or a second ledger."""
    raise ValueError("Use strategic_portfolio.create_portfolio_proposal and authenticated approval")


def _bets() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for event in evolution_ledger.list_events(event_type=REGISTERED):
        bet = event.get("bet") or {}
        if bet.get("bet_id"):
            out[bet["bet_id"]] = bet
    return out


def _spend_totals() -> Dict[str, Dict[str, int]]:
    totals: Dict[str, Dict[str, int]] = {}
    for event in evolution_ledger.list_events(event_type=SPEND):
        bet_id = event.get("bet_id")
        if not bet_id:
            continue
        bucket = totals.setdefault(bet_id, dict.fromkeys(DEFAULT_BUDGET, 0))
        for key in DEFAULT_BUDGET:
            bucket[key] += int(event.get(key) or 0)
    return totals


def _outcomes() -> Dict[str, Dict[str, Any]]:
    return {
        event["bet_id"]: event
        for event in evolution_ledger.list_events(event_type=OUTCOME)
        if event.get("bet_id")
    }


def bet_state(bet_id: str) -> Dict[str, Any]:
    bet = _bets().get(bet_id)
    if not bet:
        raise ValueError(f"未登记的赌注: {bet_id}")
    spent = _spend_totals().get(bet_id, dict.fromkeys(DEFAULT_BUDGET, 0))
    remaining = {key: int(bet["budget"][key]) - int(spent.get(key, 0)) for key in DEFAULT_BUDGET}
    review_at = _parse(bet.get("review_at"))
    return {
        "bet": bet,
        "spent": spent,
        "remaining": remaining,
        "review_due": bool(review_at and review_at <= _now()),
        "outcome": _outcomes().get(bet_id),
    }


def record_spend(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
    raise BudgetExceeded("Usage must be reserved and settled by strategic_portfolio_usage")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def apply_evidence_defaults() -> None:
    """缺环境变量时回落到仓库内已有的报告；显式配置仍然优先。"""
    root = repo_root()
    metrics = root / "FHD" / "metrics"
    slo_candidates = sorted(metrics.glob("slo-measured-*.json"))
    defaults = {
        "MODSTORE_SLO_REPORT_PATH": slo_candidates[-1] if slo_candidates else None,
        "MODSTORE_INTENT_REPORT_PATH": metrics / "intent_benchmark_latest.json",
        "MODSTORE_LEGACY_REPORT_PATH": metrics / "legacy-usage-168h.json",
        "MODSTORE_DOMAIN_AUDIT_PATH": root / DEFAULT_DOMAIN_AUDIT,
    }
    for key, value in defaults.items():
        if value is not None and not os.environ.get(key):
            os.environ[key] = str(value)


def _read_json_report(env_var: str) -> Optional[Dict[str, Any]]:
    raw = os.environ.get(env_var, "")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _revenue_monthly() -> Optional[float]:
    # Global invoices are neither collected revenue nor attributable business outcomes.
    # Portfolio review supplies its authoritative, goal-linked payment outcome.
    return None


def read_metric(metric_id: str) -> Optional[float]:
    apply_evidence_defaults()
    if metric_id == REVENUE_METRIC:
        return _revenue_monthly()
    env_var = {
        "slo_availability": "MODSTORE_SLO_REPORT_PATH",
        "slo_error_rate": "MODSTORE_SLO_REPORT_PATH",
        "intent_accuracy": "MODSTORE_INTENT_REPORT_PATH",
        "legacy_ratio": "MODSTORE_LEGACY_REPORT_PATH",
        DOMAIN_METRIC: "MODSTORE_DOMAIN_AUDIT_PATH",
    }.get(metric_id, "")
    return _metric_from_report(metric_id, _read_json_report(env_var) or {})


def _metric_from_report(metric_id: str, report: Dict[str, Any]) -> Optional[float]:
    """Evaluate the exact evidence snapshot whose hash is frozen in SQL."""
    if metric_id in {"slo_availability", "slo_error_rate"}:
        reading = (report.get("readings") or {}).get(METRIC_SOURCES[metric_id]) or {}
        return _number(reading.get("reading_numeric"))
    if metric_id == "intent_accuracy":
        direct = _number(report.get("accuracy"))
        if direct is not None:
            return direct
        counts = (report.get("rule") or {}).get("counts") or {}
        correct = sum(int((row or {}).get("correct") or 0) for row in counts.values())
        total = sum(int((row or {}).get("total") or 0) for row in counts.values())
        return correct / total if total else None
    if metric_id == "legacy_ratio":
        return _number(report.get("legacy_ratio"))
    if metric_id == DOMAIN_METRIC:
        domains = report.get("domains") or []
        if not isinstance(domains, list) or not domains:
            return None
        rated = [
            row
            for row in domains
            if isinstance(row, dict) and str(row.get("status") or "").upper() != "UNRATED"
        ]
        return len(rated) / len(domains)
    return None


def judge(metric_id: str, value: Optional[float], threshold: float, direction: str) -> str:
    """hit / miss / inconclusive（缺证据不算失败，也不算通过）。"""
    if _number(value) is None or _number(threshold) is None or direction not in DIRECTIONS:
        return "inconclusive"
    assert value is not None
    if direction == "max":
        return "hit" if value >= threshold else "miss"
    return "hit" if value <= threshold else "miss"


def capture_metric(
    metric_id: str, *, start: datetime, end: datetime, business: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Read only in-window source evidence; preserve the exact bytes' identity."""
    if metric_id == CUSTOMER_ACCEPTANCE_METRIC:
        outcome = business or {}
        ratio = _number(outcome.get("acceptance_ratio"))
        if outcome.get("status") == "verified" and ratio is not None and 0 <= ratio <= 1:
            return {
                "value": ratio,
                "source": outcome.get("source"),
                "evidence_sha256": outcome.get("evidence_sha256"),
                "accepted_goals": outcome.get("accepted_goals"),
                "target_goals": outcome.get("target_goals"),
                "basis": "approved_goals_with_completed_artifact_and_customer_acceptance",
            }
        return {"value": None, "reason": "customer_delivery_evidence_unavailable"}
    if metric_id == REVENUE_METRIC:
        outcome = business or {}
        cents = outcome.get("revenue_cents")
        if outcome.get("status") == "verified" and type(cents) is int:
            return {
                "value": cents / 100,
                "source": outcome.get("source"),
                "evidence_sha256": outcome.get("order_refs_sha256"),
                "basis": "attributed_verified_payments_in_approved_window",
            }
        return {"value": None, "reason": "attributed_payment_evidence_unavailable"}
    apply_evidence_defaults()
    env_var = {
        "slo_availability": "MODSTORE_SLO_REPORT_PATH",
        "slo_error_rate": "MODSTORE_SLO_REPORT_PATH",
        "intent_accuracy": "MODSTORE_INTENT_REPORT_PATH",
        "legacy_ratio": "MODSTORE_LEGACY_REPORT_PATH",
        DOMAIN_METRIC: "MODSTORE_DOMAIN_AUDIT_PATH",
    }.get(metric_id, "")
    path = Path(os.environ.get(env_var, ""))
    try:
        raw = path.read_bytes()
        report = json.loads(raw)
    except (OSError, ValueError):
        return {"value": None, "reason": "metric_source_unavailable"}
    if not isinstance(report, dict):
        return {"value": None, "reason": "metric_source_invalid"}
    observed_at = _parse(
        report.get("generated_at") or report.get("measured_at") or report.get("built_at")
    )
    if observed_at is None or not start <= observed_at <= end:
        return {
            "value": None,
            "reason": "metric_source_outside_observation_window",
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {
        "value": _metric_from_report(metric_id, report),
        "source": str(path),
        "observed_at": _iso(observed_at),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
    }


def review_hypotheses(
    proposal: Dict[str, Any],
    state: Dict[str, Any],
    business_by_op: Dict[str, Any],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Store immutable metric snapshots in the existing SQL portfolio transaction."""
    moment = now or _now()
    outcomes = state.setdefault("hypothesis_outcomes", {})
    results = []
    for item in proposal["opportunities"]:
        raw = item.get("hypothesis")
        task = state.get("tasks", {}).get(item["opportunity_id"])
        if not raw or not task:
            continue
        key = item["opportunity_id"]
        if key in outcomes:
            results.append(outcomes[key])
            continue
        target = BetHypothesis.model_validate(raw)
        start = _parse(task["started_at"])
        assert start is not None
        end = start + timedelta(days=target.window_days)
        if moment < end or task["status"] not in {"completed", "failed"}:
            results.append({"opportunity_id": key, "verdict": "pending", "review_at": _iso(end)})
            continue
        evidence = capture_metric(
            target.metric_id, start=start, end=end, business=business_by_op.get(key)
        )
        verdict = judge(target.metric_id, evidence.get("value"), target.threshold, target.direction)
        snapshot = {
            "opportunity_id": key,
            "hypothesis": target.model_dump(),
            "evidence": evidence,
            "verdict": verdict,
            "window_start": _iso(start),
            "window_end": _iso(end),
            "reviewed_at": _iso(moment),
        }
        snapshot["snapshot_sha256"] = _digest(snapshot)
        outcomes[key] = snapshot
        results.append(snapshot)
        if verdict == "miss" and target.kill_on_miss:
            state.update(halted=True, stop_reason=f"hypothesis_missed:{key}")
    return results


def active_bets(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    moment = now or _now()
    outcomes = _outcomes()
    totals = _spend_totals()
    active: List[Dict[str, Any]] = []
    for bet in _bets().values():
        if bet["bet_id"] in outcomes:
            continue
        review_at = _parse(bet.get("review_at"))
        if review_at and review_at <= moment:
            continue
        spent = totals.get(bet["bet_id"], {})
        if any(int(spent.get(key, 0)) >= int(bet["budget"][key]) for key in DEFAULT_BUDGET):
            continue
        active.append(bet)
    return sorted(active, key=lambda item: str(item.get("review_at") or ""))


def active_bet_id() -> str:
    active = active_bets()
    return active[0]["bet_id"] if active else ""


def review_due(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Read the imported ledger; execution and review writes belong to SQL portfolios."""
    return list(_outcomes().values())


def audit_outcomes() -> Dict[str, int]:
    """Verify the recorded threshold calculation without reading a later time window."""
    bets = _bets()
    valid = sum(
        event.get("verdict")
        == judge(
            bets[key]["metric_id"],
            event.get("value"),
            bets[key]["threshold"],
            bets[key]["direction"],
        )
        for key, event in _outcomes().items()
        if key in bets
    )
    return {"calculation_verified": valid, "source_evidence_verified": 0}


def run_review() -> Dict[str, Any]:
    return {
        "ok": True,
        "legacy_read_only": True,
        "outcomes": review_due(),
        "audit": audit_outcomes(),
    }


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="策略赌注账本")
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--file", required=True, help="预注册 JSON 文件")

    sub.add_parser("active-bet-id")
    sub.add_parser("review-due")

    state = sub.add_parser("state")
    state.add_argument("--bet-id", required=True)

    spend = sub.add_parser("spend")
    spend.add_argument("--bet-id", required=True)
    spend.add_argument("--proposals", type=int, default=0)
    spend.add_argument("--tokens", type=int, default=0)
    spend.add_argument("--ci-minutes", type=int, default=0)
    spend.add_argument("--human-hours", type=int, default=0)
    spend.add_argument("--source", default="")

    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
            result = register_bet(**payload)
        elif args.command == "active-bet-id":
            print(active_bet_id())
            return 0
        elif args.command == "state":
            result = bet_state(args.bet_id)
        elif args.command == "spend":
            result = record_spend(
                args.bet_id,
                proposals=args.proposals,
                tokens=args.tokens,
                ci_minutes=args.ci_minutes,
                human_hours=args.human_hours,
                source=args.source,
            )
        else:
            result = run_review()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"strategy_bets: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
