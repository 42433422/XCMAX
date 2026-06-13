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

    return {
        "lookback_hours": hours,
        "pytest_failures": pytest_items,
        "runtime_anomalies": incident_items,
        "performance_signals": perf_items,
        "total_count": len(pytest_items) + len(incident_items) + len(perf_items),
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

    return "\n".join(lines).strip()


__all__ = [
    "collect_evolution_signals",
    "format_evolution_signals_for_prompt",
]
