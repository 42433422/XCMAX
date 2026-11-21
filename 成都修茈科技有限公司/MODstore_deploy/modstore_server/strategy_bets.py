"""策略赌注账本：预注册、预算信封、到期结果判定。

复用 ``evolution_ledger``（append-only JSONL）与 ``StrategicDecision``（战略库），
不新增表、不新增存储。所有状态都可由 ledger 重算，进程重启不丢。

闭环：注册（含预注册阈值）→ 预算扣减 → 到期回读指标 → hit/miss/inconclusive
→ 写回战略决策执行结果，供事后审计复算。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from modstore_server import evolution_ledger

UTC = timezone.utc
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
DOMAIN_METRIC = "domain_rated_ratio"
DEFAULT_DOMAIN_AUDIT = "FHD/config/domain_audit.json"

REGISTERED = "strategy_bet_registered"
SPEND = "strategy_bet_spend"
OUTCOME = "strategy_outcome"


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


def register_bet(
    *,
    bet_id: str,
    title: str,
    hypothesis: str,
    metric_id: str,
    threshold: float,
    direction: str,
    window_days: int,
    kill_criteria: List[str],
    budget: Optional[Dict[str, int]] = None,
    scope: str = "global",
) -> Dict[str, Any]:
    """登记一个赌注（幂等）。返回账本里的预注册记录。"""
    if not BET_ID_RE.match(bet_id or ""):
        raise ValueError("bet_id 必须为 3-64 位小写字母/数字/._-")
    if metric_id not in METRIC_SOURCES and metric_id not in {REVENUE_METRIC, DOMAIN_METRIC}:
        raise ValueError(f"未支持的 metric_id: {metric_id}")
    if direction not in DIRECTIONS:
        raise ValueError("direction 只能是 max 或 min")
    if isinstance(window_days, bool) or not isinstance(window_days, int):
        raise ValueError("window_days 必须是整数")
    if not 1 <= window_days <= 365:
        raise ValueError("window_days 必须在 1-365 之间")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold 必须是数字")
    if not title.strip() or not hypothesis.strip():
        raise ValueError("title 和 hypothesis 不能为空")
    if not kill_criteria:
        raise ValueError("kill_criteria 不能为空")

    budget_in = budget or {}
    envelope = {key: _positive_int(budget_in, key) for key in DEFAULT_BUDGET}
    registered_at = _now()
    payload: Dict[str, Any] = {
        "bet_id": bet_id,
        "title": title.strip(),
        "hypothesis": hypothesis.strip(),
        "metric_id": metric_id,
        "threshold": float(threshold),
        "direction": direction,
        "window_days": window_days,
        "kill_criteria": [str(item) for item in kill_criteria],
        "budget": envelope,
        "scope": scope,
        "registered_at": _iso(registered_at),
        "review_at": _iso(registered_at + timedelta(days=window_days)),
    }
    payload["payload_sha256"] = _digest(payload)

    for event in evolution_ledger.list_events(event_type=REGISTERED):
        existing = event.get("bet") or {}
        if existing.get("bet_id") == bet_id:
            return existing

    evolution_ledger.append_event({"event_type": REGISTERED, "bet": payload})
    _sync_decision(payload)
    return payload


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
        bucket = totals.setdefault(bet_id, {key: 0 for key in DEFAULT_BUDGET})
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
    spent = _spend_totals().get(bet_id, {key: 0 for key in DEFAULT_BUDGET})
    remaining = {
        key: int(bet["budget"][key]) - int(spent.get(key, 0)) for key in DEFAULT_BUDGET
    }
    review_at = _parse(bet.get("review_at"))
    return {
        "bet": bet,
        "spent": spent,
        "remaining": remaining,
        "review_due": bool(review_at and review_at <= _now()),
        "outcome": _outcomes().get(bet_id),
    }


def record_spend(
    bet_id: str,
    *,
    proposals: int = 0,
    tokens: int = 0,
    ci_minutes: int = 0,
    human_hours: int = 0,
    source: str = "",
) -> Dict[str, Any]:
    """扣减预算；不足则抛 ``BudgetExceeded``，调用方不得继续执行。"""
    state = bet_state(bet_id)
    delta = {
        "proposals": proposals,
        "tokens": tokens,
        "ci_minutes": ci_minutes,
        "human_hours": human_hours,
    }
    for key, amount in delta.items():
        if amount < 0:
            raise ValueError("预算扣减不能为负")
        if amount > state["remaining"][key]:
            raise BudgetExceeded(f"赌注 {bet_id} 的 {key} 预算不足")
    event = {
        "event_type": SPEND,
        "bet_id": bet_id,
        "payload_sha256": state["bet"]["payload_sha256"],
        "source": source,
        **delta,
    }
    evolution_ledger.append_event(event)
    return bet_state(bet_id)


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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _revenue_monthly() -> Optional[float]:
    """过去 30 天已开票金额；数据库不可用返回 None（判定为 inconclusive）。"""
    try:
        from sqlalchemy import func
        from modstore_server.db.billing import Invoice
        from modstore_server.db.db_base import get_session_factory

        with get_session_factory()() as db:
            total = (
                db.query(func.coalesce(func.sum(Invoice.amount), 0))
                .filter(Invoice.issued_at >= _now() - timedelta(days=30))
                .scalar()
            )
        return float(total or 0)
    except Exception:
        return None


def read_metric(metric_id: str) -> Optional[float]:
    apply_evidence_defaults()
    if metric_id == REVENUE_METRIC:
        return _revenue_monthly()
    if metric_id in {"slo_availability", "slo_error_rate"}:
        report = _read_json_report("MODSTORE_SLO_REPORT_PATH")
        if not report:
            return None
        reading = (report.get("readings") or {}).get(METRIC_SOURCES[metric_id]) or {}
        return _number(reading.get("reading_numeric"))
    if metric_id == "intent_accuracy":
        report = _read_json_report("MODSTORE_INTENT_REPORT_PATH")
        if not report:
            return None
        direct = _number(report.get("accuracy"))
        if direct is not None:
            return direct
        counts = ((report.get("rule") or {}).get("counts") or {})
        correct = sum(int((row or {}).get("correct") or 0) for row in counts.values())
        total = sum(int((row or {}).get("total") or 0) for row in counts.values())
        return correct / total if total else None
    if metric_id == "legacy_ratio":
        report = _read_json_report("MODSTORE_LEGACY_REPORT_PATH")
        return _number((report or {}).get("legacy_ratio"))
    if metric_id == DOMAIN_METRIC:
        report = _read_json_report("MODSTORE_DOMAIN_AUDIT_PATH")
        domains = (report or {}).get("domains") or []
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
    if value is None:
        return "inconclusive"
    if direction == "max":
        return "hit" if value >= threshold else "miss"
    return "hit" if value <= threshold else "miss"


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
    """对到期且未判定的赌注回读指标并落结论；只读已有数据源。"""
    moment = now or _now()
    outcomes = _outcomes()
    reviewed: List[Dict[str, Any]] = []
    for bet in _bets().values():
        bet_id = bet["bet_id"]
        if bet_id in outcomes:
            continue
        review_at = _parse(bet.get("review_at"))
        if not review_at or review_at > moment:
            continue
        value = read_metric(bet["metric_id"])
        verdict = judge(bet["metric_id"], value, bet["threshold"], bet["direction"])
        event = {
            "event_type": OUTCOME,
            "bet_id": bet_id,
            "payload_sha256": bet["payload_sha256"],
            "metric_id": bet["metric_id"],
            "value": value,
            "threshold": bet["threshold"],
            "direction": bet["direction"],
            "verdict": verdict,
            "reason": "evidence_missing" if value is None else "",
            "reviewed_at": _iso(moment),
            "final_status": verdict,
        }
        evolution_ledger.append_event(event)
        _sync_outcome(bet, event)
        reviewed.append(event)
    return reviewed


def _sync_decision(payload: Dict[str, Any]) -> None:
    """把赌注登记到战略库；数据库不可用时只留 ledger。"""
    try:
        from modstore_server.db.db_base import get_session_factory
        from modstore_server.db.strategic import StrategicDecision

        review_at = _parse(payload.get("review_at"))
        with get_session_factory()() as db:
            existing = (
                db.query(StrategicDecision)
                .filter_by(decision_id=payload["bet_id"])
                .first()
            )
            if existing:
                return
            db.add(
                StrategicDecision(
                    decision_id=payload["bet_id"],
                    title=payload["title"],
                    rationale=payload["hypothesis"],
                    proposed_by="evolution-strategy",
                    decision_type="strategy_bet",
                    scope=payload["scope"],
                    status="proposed",
                    decision_payload_json=_canonical(payload),
                    review_at=review_at.replace(tzinfo=None) if review_at else None,
                )
            )
            db.commit()
    except Exception:
        return


def _sync_outcome(bet: Dict[str, Any], event: Dict[str, Any]) -> None:
    try:
        from modstore_server.db.db_base import get_session_factory
        from modstore_server.db.strategic import StrategicDecision

        with get_session_factory()() as db:
            row = (
                db.query(StrategicDecision)
                .filter_by(decision_id=bet["bet_id"])
                .first()
            )
            if not row:
                return
            row.status = "reviewed"
            row.execution_result_json = _canonical(event)
            db.commit()
    except Exception:
        return


def audit_outcomes() -> Dict[str, int]:
    """独立复算已落结论的事件；不采信当初的判定，只看当前数据源。"""
    verified = mismatched = 0
    bets = _bets()
    for event in evolution_ledger.list_events(event_type=OUTCOME):
        if (event.get("owner_audit") or {}).get("audited"):
            continue
        bet = bets.get(event.get("bet_id"))
        if not bet:
            continue
        recomputed = judge(
            bet["metric_id"], read_metric(bet["metric_id"]), bet["threshold"], bet["direction"]
        )
        verdict = "verified" if recomputed == event.get("verdict") else "mismatch"
        if evolution_ledger.mark_audited(event["event_id"], verdict):
            if verdict == "verified":
                verified += 1
            else:
                mismatched += 1
    return {"verified": verified, "mismatched": mismatched}


def run_review() -> Dict[str, Any]:
    reviewed = review_due()
    audit = audit_outcomes()
    return {
        "ok": True,
        "reviewed": len(reviewed),
        "verdicts": [{"bet_id": item["bet_id"], "verdict": item["verdict"]} for item in reviewed],
        "audit": audit,
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
