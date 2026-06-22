"""SLA 实测采集器 — 写入 jsonl 供离线分析。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.neuro_bus.sla_controller import SLALevel


def _default_measurements_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    d = root / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sla_measurements.jsonl"


def _collect_enabled() -> bool:
    return os.environ.get("XCAGI_NEURO_BUS_SLA_COLLECT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class SLACollector:
    """SLA 实测采集器。默认关闭，XCAGI_NEURO_BUS_SLA_COLLECT=1 启用。"""

    def __init__(self) -> None:
        self._path = Path(
            os.environ.get(
                "XCAGI_SLA_MEASUREMENTS_PATH",
                str(_default_measurements_path()),
            )
        )
        self._enabled = _collect_enabled()

    def record(
        self,
        level: SLALevel,
        operation: str,
        latency_ms: float,
        sla_target_ms: float,
        sla_hit: bool,
    ) -> None:
        """记录一次 SLA 测量。"""
        if not self._enabled:
            return
        row = {
            "ts": time.time(),
            "level": level.value,
            "operation": operation,
            "latency_ms": latency_ms,
            "sla_target_ms": sla_target_ms,
            "sla_hit": sla_hit,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
