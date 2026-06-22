"""自进化信号采集：CI 失败 / 运行异常 / 性能退化 → 每日 work unit 事实源。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _lookback_hours() -> int:
    try:
        return max(
            1, min(int(os.environ.get("MODSTORE_EVOLUTION_SIGNAL_LOOKBACK_HOURS", "24")), 168)
        )
    except ValueError:
        return 24


def _repo_root() -> Path:
    try:
        from modstore_server.daily_digest import _repo_root

        return Path(_repo_root())
    except Exception:
        return Path(os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()


def _collect_pytest_failures(*, root: Path, limit: int = 12) -> List[Dict[str, str]]:
    """读取 pytest lastfailed 缓存。"""
    try:
        from modstore_server.daily_digest import _pytest_lastfailed_snippet

        raw = _pytest_lastfailed_snippet(root, limit=4000)
        if not raw or "无（" in raw:
            return []
        items: List[Dict[str, str]] = []
        try:
            data = json.loads(raw.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">"))
            if isinstance(data, dict):
                for nodeid in list(data.keys())[:limit]:
                    items.append({"kind": "pytest", "nodeid": str(nodeid)})
        except json.JSONDecodeError:
            for line in raw.splitlines()[:limit]:
                line = line.strip()
                if line:
                    items.append({"kind": "pytest", "nodeid": line[:240]})
        return items
    except Exception:
        logger.debug("collect pytest failures failed", exc_info=True)
        return []


def _collect_runtime_anomalies(*, lookback_hours: int, limit: int = 20) -> List[Dict[str, str]]:
    """近窗口 incident_bus 入库事件。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        from modstore_server.models import IncidentEvent, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(IncidentEvent)
                .filter(IncidentEvent.created_at >= cutoff)
                .order_by(IncidentEvent.id.desc())
                .limit(limit)
                .all()
            )
        out: List[Dict[str, str]] = []
        for r in rows:
            et = str(getattr(r, "event_type", "") or "")
            src = str(getattr(r, "source", "") or "")
            if et or src:
                out.append(
                    {
                        "kind": "incident",
                        "event_type": et[:120],
                        "source": src[:80],
                    }
                )
        return out
    except Exception:
        logger.debug("collect runtime anomalies failed", exc_info=True)
        return []


def _collect_performance_signals() -> List[Dict[str, str]]:
    """post_deploy_smoke 最近一次结果。"""
    try:
        from modstore_server.post_deploy_smoke import load_last_smoke_result

        last = load_last_smoke_result()
        if not last:
            return []
        ok = bool(last.get("ok"))
        probes = last.get("probes") if isinstance(last.get("probes"), list) else []
        slow: List[str] = []
        for p in probes:
            if not isinstance(p, dict):
                continue
            ms = p.get("elapsed_ms")
            name = str(p.get("name") or "")
            try:
                if ms is not None and float(ms) > 3000:
                    slow.append(f"{name}:{ms}ms")
            except (TypeError, ValueError):
                pass
        items: List[Dict[str, str]] = []
        if not ok:
            items.append(
                {
                    "kind": "performance",
                    "signal": "post_deploy_smoke_failed",
                    "detail": str(last.get("error") or last.get("reason") or "smoke not ok")[:240],
                }
            )
        for s in slow[:5]:
            items.append({"kind": "performance", "signal": "slow_probe", "detail": s})
        return items
    except Exception:
        logger.debug("collect performance signals failed", exc_info=True)
        return []


def _collect_loop_memory_signals(limit: int = 12) -> List[Dict[str, str]]:
    """Read real self-maintenance loop memory and expose unresolved risks."""

    try:
        from modstore_server.self_maintenance_policy import load_loop_memory

        memory = load_loop_memory()
    except Exception:
        logger.debug("collect loop memory signals failed", exc_info=True)
        return []
    if not isinstance(memory, dict) or not memory:
        return []

    signals: List[Dict[str, str]] = []
    parse_error = str(memory.get("_parse_error") or "").strip()
    if parse_error:
        signals.append(
            {
                "kind": "loop_memory",
                "signal": "loop_memory_parse_error",
                "detail": parse_error[:240],
            }
        )

    last_decision = memory.get("last_policy_decision")
    if isinstance(last_decision, dict):
        action = str(last_decision.get("action") or "")
        reason = str(last_decision.get("reason") or "")
        if action or reason:
            signals.append(
                {
                    "kind": "loop_memory",
                    "signal": "last_policy_decision",
                    "action": action,
                    "reason": reason,
                    "run_id": str(memory.get("last_run", {}).get("run_id") or ""),
                    "completed_at": str(memory.get("last_run", {}).get("completed_at") or ""),
                }
            )

    open_items = memory.get("open_items")
    if isinstance(open_items, list):
        for item in open_items[-limit:]:
            if not isinstance(item, dict):
                continue
            signals.append(
                {
                    "kind": "loop_memory",
                    "signal": str(item.get("kind") or "open_item"),
                    "action": str(item.get("action") or ""),
                    "reason": str(item.get("reason") or ""),
                    "run_id": str(item.get("run_id") or ""),
                    "task_id": str(item.get("task_id") or item.get("para_task_id") or ""),
                    "branch": str(item.get("branch") or ""),
                    "created_at": str(item.get("created_at") or ""),
                    "detail": json.dumps(item, ensure_ascii=False, sort_keys=True)[:360],
                }
            )

    recent_runs = memory.get("recent_runs")
    if isinstance(recent_runs, list):
        for item in recent_runs[-5:]:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "")
            status = str(item.get("status") or "")
            if action not in {"await_human_strategy_approval", "stop"} and status not in {
                "failed",
                "completed_waiting_human_strategy",
            }:
                continue
            signals.append(
                {
                    "kind": "loop_memory",
                    "signal": "recent_run_risk",
                    "action": action,
                    "status": status,
                    "run_id": str(item.get("run_id") or ""),
                    "branch": str(item.get("branch") or ""),
                    "completed_at": str(item.get("completed_at") or ""),
                    "detail": json.dumps(item, ensure_ascii=False, sort_keys=True)[:360],
                }
            )

    return signals[:limit]


def collect_evolution_signals(
    *,
    lookback_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """汇总三类事实信号，供 vibe 预备 prompt 注入。"""
    hours = int(lookback_hours or _lookback_hours())
    root = _repo_root()
    pytest_items = _collect_pytest_failures(root=root)
    incident_items = _collect_runtime_anomalies(lookback_hours=hours)
    perf_items = _collect_performance_signals()
    loop_memory_items = _collect_loop_memory_signals()

    return {
        "lookback_hours": hours,
        "loop_memory_signals": loop_memory_items,
        "pytest_failures": pytest_items,
        "runtime_anomalies": incident_items,
        "performance_signals": perf_items,
        "total_count": len(pytest_items)
        + len(incident_items)
        + len(perf_items)
        + len(loop_memory_items),
    }


def format_evolution_signals_for_prompt(signals: Dict[str, Any]) -> str:
    """渲染为 vibe 预备 LLM user content 段落。"""
    if not signals or int(signals.get("total_count") or 0) <= 0:
        return "（近 24h 无 CI/异常/性能事实信号；可辅以截图分析）"

    lines = [
        f"采集窗口：近 {signals.get('lookback_hours', 24)} 小时",
        "优先级：以下事实信号 **高于** 三端截图分析；补丁清单须优先覆盖 pytest 失败与线上异常。",
        "",
    ]
    pf = signals.get("pytest_failures") or []
    if pf:
        lines.append("### CI / pytest 失败")
        for it in pf[:10]:
            lines.append(f"- `{it.get('nodeid', '')}`")
        lines.append("")

    ra = signals.get("runtime_anomalies") or []
    if ra:
        lines.append("### 运行时异常（incident_bus）")
        for it in ra[:10]:
            lines.append(f"- {it.get('event_type', '?')} ← {it.get('source', '?')}")
        lines.append("")

    ps = signals.get("performance_signals") or []
    if ps:
        lines.append("### 性能 / 部署探针")
        for it in ps[:8]:
            lines.append(f"- {it.get('signal', '?')}: {it.get('detail', '')}")
        lines.append("")

    lm = signals.get("loop_memory_signals") or []
    if lm:
        lines.append("### 自维护 loop 记忆")
        for it in lm[:12]:
            timestamp = it.get("created_at") or it.get("completed_at") or "no-ts"
            reason = it.get("reason") or it.get("status") or it.get("detail") or ""
            run_id = it.get("run_id") or ""
            branch = it.get("branch") or ""
            lines.append(
                f"- {timestamp} `{it.get('signal', '?')}` run={run_id} branch={branch}: {reason}"
            )
        lines.append("")

    return "\n".join(lines).strip()


__all__ = [
    "collect_evolution_signals",
    "format_evolution_signals_for_prompt",
]
