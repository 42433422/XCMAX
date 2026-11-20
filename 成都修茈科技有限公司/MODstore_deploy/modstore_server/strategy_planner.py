"""战略规划器：按现有模型资产、仓库信号、18 域状态自主生成赌注。

输入三份证据，输出可结算的赌注（交给 ``strategy_bets`` 登记）：
1. 模型资产：``llm_runtime_route.platform_model_catalog``（拿不到则标 unknown）
2. 仓库信号：``evolution_signal_collector.aggregate_signals``
3. 18 域：``MODSTORE_DOMAIN_AUDIT_PATH`` 指向的结构化审计 JSON

缺证据时不会编造：对应分区标 ``unknown``，并在提案理由里保留证据缺口。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server import evolution_ledger, strategy_bets

UTC = timezone.utc
MAX_NEW_BETS = 1
DEFAULT_ENVELOPE = {
    "proposals": 6,
    "tokens": 800000,
    "ci_minutes": 480,
    "human_hours": 16,
}
_REQUIRED_FIELDS = (
    "title",
    "hypothesis",
    "metric_id",
    "threshold",
    "direction",
    "window_days",
    "kill_criteria",
    "expected_value",
    "effort",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _digest(payload: Any) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect_context() -> Dict[str, Any]:
    strategy_bets.apply_evidence_defaults()
    return {
        "assets": _model_assets(),
        "repo": _repo_signals(),
        "domains": _domain_status(),
        "active_bets": [bet["bet_id"] for bet in strategy_bets.active_bets()],
        "envelope": _envelope(),
        "built_at": _now().isoformat(),
    }


def _model_assets() -> Dict[str, Any]:
    """读取平台模型资产；不触发刷新，失败即 unknown。"""
    try:
        from modstore_server.llm_runtime_route import platform_model_catalog

        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False
        if loop_running:
            return {"status": "unknown", "reason": "event_loop_active"}
        catalog = asyncio.run(platform_model_catalog(refresh=False))
    except Exception:
        return {"status": "unknown", "reason": "catalog_unavailable"}
    providers = [row for row in (catalog or {}).get("providers") or [] if isinstance(row, dict)]
    configured = [row for row in providers if row.get("configured")]
    return {
        "status": "ok" if providers else "unknown",
        "provider_count": len(providers),
        "configured_provider_count": len(configured),
        "model_count": sum(int(row.get("model_count") or 0) for row in configured),
    }


def _repo_signals() -> Dict[str, Any]:
    try:
        from modstore_server.evolution_signal_collector import aggregate_signals

        signals = aggregate_signals()
    except Exception:
        return {"status": "unknown", "signals": {}}
    if not isinstance(signals, dict):
        return {"status": "unknown", "signals": {}}
    return {"status": "ok", "signals": signals}


def _domain_status() -> Dict[str, Any]:
    """读取结构化 18 域审计；没有文件就如实标 unknown，不假装已评级。"""
    raw = os.environ.get("MODSTORE_DOMAIN_AUDIT_PATH", "").strip()
    if not raw:
        return {"status": "unknown", "reason": "audit_path_not_set", "domains": []}
    path = Path(raw)
    if not path.is_file():
        return {"status": "unknown", "reason": "audit_file_missing", "domains": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "unknown", "reason": "audit_file_invalid", "domains": []}
    domains = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(domains, list):
        return {"status": "unknown", "reason": "audit_schema_invalid", "domains": []}
    normalized = []
    for row in domains:
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "domain_id": str(row.get("domain_id") or ""),
                "status": str(row.get("status") or "UNRATED").upper(),
                "score": row.get("score"),
                "evidence": str(row.get("evidence") or ""),
            }
        )
    rated = [row for row in normalized if row["status"] != "UNRATED"]
    return {
        "status": "ok" if rated else "unrated",
        "domain_count": len(normalized),
        "rated_count": len(rated),
        "domains": normalized,
    }


def _envelope() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for key, default in DEFAULT_ENVELOPE.items():
        env_key = f"MODSTORE_STRATEGY_WEEKLY_{key.upper()}"
        try:
            value = int(os.environ.get(env_key, str(default)))
        except ValueError:
            value = default
        out[key] = max(1, value)
    return out


def build_prompt(context: Dict[str, Any]) -> str:
    return (
        "你是产品战略负责人。根据下面的证据，提出 1-3 个可结算的产品赌注。\n"
        "规则：\n"
        "1) 只能使用 metric_id ∈ "
        f"{sorted(list(strategy_bets.METRIC_SOURCES) + [strategy_bets.REVENUE_METRIC, strategy_bets.DOMAIN_METRIC])}\n"
        "2) 每个赌注必须有可证伪的假设、明确阈值、窗口 1-365 天、至少一条 kill 条件\n"
        "3) direction 只能是 max（越高越好）或 min（越低越好）\n"
        "4) expected_value 和 effort 各取 1-5 的整数\n"
        "5) 证据不足的分区不要编造结论，在 rationale 里写明缺口\n"
        "6) 不要重复已有的活跃赌注\n"
        "只输出 JSON 数组，不要解释，不要 Markdown 代码块。\n\n"
        f"证据：\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    )


def parse_plan(text: str) -> List[Dict[str, Any]]:
    if not isinstance(text, str):
        return []
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def validate_candidate(candidate: Dict[str, Any]) -> Optional[str]:
    """返回拒绝原因；None 表示通过。"""
    for field in _REQUIRED_FIELDS:
        if field not in candidate:
            return f"missing_{field}"
    supported = set(strategy_bets.METRIC_SOURCES) | {
        strategy_bets.REVENUE_METRIC,
        strategy_bets.DOMAIN_METRIC,
    }
    if candidate["metric_id"] not in supported:
        return "unsupported_metric"
    if candidate.get("direction") not in strategy_bets.DIRECTIONS:
        return "invalid_direction"
    threshold = candidate.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return "invalid_threshold"
    window = candidate.get("window_days")
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 365:
        return "invalid_window"
    if not isinstance(candidate.get("kill_criteria"), list) or not candidate["kill_criteria"]:
        return "invalid_kill_criteria"
    for field in ("expected_value", "effort"):
        value = candidate.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            return f"invalid_{field}"
    return None


def rank_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid = [row for row in candidates if validate_candidate(row) is None]

    def score(row: Dict[str, Any]) -> float:
        return row["expected_value"] / max(1, row["effort"])

    return sorted(valid, key=score, reverse=True)


def fit_envelope(
    candidates: List[Dict[str, Any]], envelope: Dict[str, int], active: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """按剩余信封过滤；每个候选按默认预算折算，超出即跳过。"""
    used = {key: 0 for key in DEFAULT_ENVELOPE}
    for bet in active:
        for key in DEFAULT_ENVELOPE:
            used[key] += int((bet.get("budget") or {}).get(key, 0))
    kept: List[Dict[str, Any]] = []
    for row in candidates:
        share = {key: max(1, int(envelope[key] // max(1, len(candidates)))) for key in envelope}
        if any(used[key] + share[key] > envelope[key] for key in envelope):
            continue
        kept.append({**row, "budget": share})
        for key in envelope:
            used[key] += share[key]
    return kept


def _new_bet_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:24]
    suffix = _digest(title)[:8]
    date = _now().strftime("%Y%m%d")
    return f"bet-{slug or 'plan'}-{suffix}-{date}"


FALLBACK_TARGETS = (
    (strategy_bets.DOMAIN_METRIC, 0.5, "max", "18 域证据评级覆盖率"),
    ("intent_accuracy", 0.85, "max", "意图识别准确率"),
    ("slo_availability", 0.99, "max", "SLO 可用性"),
    ("slo_error_rate", 0.01, "min", "SLO 错误率"),
    ("legacy_ratio", 0.25, "min", "遗留功能使用占比"),
)


def fallback_candidates(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """无 LLM 时按真实缺口规则生成候选；没有缺口就返回空，不硬凑。"""
    rows: List[Dict[str, Any]] = []
    for metric_id, threshold, direction, label in FALLBACK_TARGETS:
        value = strategy_bets.read_metric(metric_id)
        if value is None:
            continue
        if direction == "max":
            gap = (threshold - value) / max(threshold, 1e-9)
        else:
            gap = (value - threshold) / max(threshold, 1e-9)
        if gap <= 0.02:
            continue
        window = 30 if metric_id == strategy_bets.DOMAIN_METRIC else 14
        rows.append(
            {
                "title": f"提升{label}",
                "hypothesis": f"{label} 当前 {value:.4f}，目标 {threshold}，缺口可被本轮改造收敛",
                "metric_id": metric_id,
                "threshold": threshold,
                "direction": direction,
                "window_days": window,
                "kill_criteria": [f"{window} 天内{label}没有改善就停止投入"],
                "expected_value": min(5, 3 + int(round(gap * 4))),
                "effort": 3,
                "rationale": f"规则触发：归一化缺口 {gap:.4f}；证据状态 "
                f"assets={context['assets'].get('status')} "
                f"repo={context['repo'].get('status')} "
                f"domains={context['domains'].get('status')}",
            }
        )
    return rows


def plan_strategy(*, dry_run: bool = False) -> Dict[str, Any]:
    context = collect_context()
    context_sha = _digest(context)

    try:
        from modstore_server.employee_pack_proposal import _call_llm

        raw = _call_llm(build_prompt(context))
    except Exception:
        raw = {}
    text = ""
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("content") or "")
        if not text and isinstance(raw.get("choices"), list) and raw["choices"]:
            message = raw["choices"][0].get("message") or {}
            text = str(message.get("content") or "")
    candidates = parse_plan(text)
    source = "llm"
    if not candidates:
        candidates = fallback_candidates(context)
        source = "deterministic_fallback"

    ranked = rank_candidates(candidates)
    kept = fit_envelope(ranked, context["envelope"], [])
    chosen = kept[: max(1, int(os.environ.get("MODSTORE_STRATEGY_MAX_NEW_BETS", MAX_NEW_BETS)))]

    registered: List[str] = []
    rejected = [
        {"title": row.get("title", ""), "reason": validate_candidate(row)}
        for row in candidates
        if validate_candidate(row)
    ]
    if not dry_run:
        for row in chosen:
            bet = strategy_bets.register_bet(
                bet_id=_new_bet_id(str(row["title"])),
                title=str(row["title"]),
                hypothesis=str(row["hypothesis"]),
                metric_id=str(row["metric_id"]),
                threshold=float(row["threshold"]),
                direction=str(row["direction"]),
                window_days=int(row["window_days"]),
                kill_criteria=[str(item) for item in row["kill_criteria"]],
                budget=row["budget"],
                scope="global",
            )
            registered.append(bet["bet_id"])
        evolution_ledger.append_event(
            {
                "event_type": "strategy_plan_generated",
                "context_sha256": context_sha,
                "candidates": len(candidates),
                "chosen": registered,
                "rejected": rejected,
                "final_status": "success" if registered else "needs_human",
            }
        )
    return {
        "ok": True,
        "source": source,
        "dry_run": dry_run,
        "context_sha256": context_sha,
        "candidates": len(candidates),
        "kept": [row.get("title", "") for row in kept],
        "registered": registered,
        "rejected": rejected,
        "evidence": {
            "assets": context["assets"].get("status"),
            "repo": context["repo"].get("status"),
            "domains": context["domains"].get("status"),
        },
    }


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="自主战略规划器")
    parser.add_argument("command", choices=["plan", "context"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = collect_context() if args.command == "context" else plan_strategy(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
