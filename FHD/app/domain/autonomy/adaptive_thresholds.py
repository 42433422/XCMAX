"""自适应自治阈值——硬常量降级为带安全下限的软约束。

例：CRASH_THRESHOLD 不再写死 3，而是 floor≤value≤ceiling，
可由反思引擎/在线学习提议调整，但不得低于安全下限。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdaptiveThreshold:
    name: str
    value: float
    floor: float
    ceiling: float
    unit: str = ""
    source: str = "default"

    def clamped(self) -> AdaptiveThreshold:
        v = min(self.ceiling, max(self.floor, self.value))
        return AdaptiveThreshold(
            name=self.name,
            value=v,
            floor=self.floor,
            ceiling=self.ceiling,
            unit=self.unit,
            source=self.source,
        )


_DEFAULTS: dict[str, AdaptiveThreshold] = {
    "crash_threshold": AdaptiveThreshold(
        name="crash_threshold",
        value=3,
        floor=2,
        ceiling=5,
        unit="count_per_window",
        source="default",
    ),
    "crash_window_ms": AdaptiveThreshold(
        name="crash_window_ms",
        value=5 * 60 * 1000,
        floor=60_000,
        ceiling=30 * 60 * 1000,
        unit="ms",
        source="default",
    ),
    "disk_clean_threshold": AdaptiveThreshold(
        name="disk_clean_threshold",
        value=70,
        floor=60,
        ceiling=90,
        unit="percent",
        source="default",
    ),
    "restart_count_cap": AdaptiveThreshold(
        name="restart_count_cap",
        value=3,
        floor=2,
        ceiling=6,
        unit="count",
        source="default",
    ),
}


def _path() -> Path:
    override = (os.environ.get("XCAGI_ADAPTIVE_THRESHOLDS_PATH") or "").strip()
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[3]
        / "resources"
        / "autonomy"
        / "adaptive_thresholds.json"
    )


def load_adaptive_thresholds(path: Path | None = None) -> dict[str, AdaptiveThreshold]:
    out = dict(_DEFAULTS)
    p = path or _path()
    if not p.is_file():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        logger.debug("load adaptive thresholds failed", exc_info=True)
        return out
    if not isinstance(raw, dict):
        return out
    items = raw.get("thresholds") if isinstance(raw.get("thresholds"), dict) else raw
    for name, base in _DEFAULTS.items():
        item = items.get(name) if isinstance(items, dict) else None
        if not isinstance(item, dict):
            continue
        try:
            thr = AdaptiveThreshold(
                name=name,
                value=float(item.get("value", base.value)),
                floor=float(item.get("floor", base.floor)),
                ceiling=float(item.get("ceiling", base.ceiling)),
                unit=str(item.get("unit") or base.unit),
                source=str(item.get("source") or "file"),
            ).clamped()
            out[name] = thr
        except (TypeError, ValueError):
            continue
    return out


def get_threshold(name: str, *, path: Path | None = None) -> AdaptiveThreshold:
    return load_adaptive_thresholds(path).get(name) or _DEFAULTS.get(
        name,
        AdaptiveThreshold(name=name, value=0, floor=0, ceiling=0),
    )


def propose_threshold_update(
    name: str,
    new_value: float,
    *,
    reason: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """写入提议（不直接生效）；生效需 shadow→canary→promote。"""
    current = get_threshold(name, path=path)
    proposed = AdaptiveThreshold(
        name=name,
        value=float(new_value),
        floor=current.floor,
        ceiling=current.ceiling,
        unit=current.unit,
        source="proposed",
    ).clamped()
    return {
        "name": name,
        "current": current.value,
        "proposed": proposed.value,
        "floor": proposed.floor,
        "ceiling": proposed.ceiling,
        "reason": str(reason or "")[:300],
        "requires_promotion": True,
        "clamped": proposed.value != float(new_value),
    }


def save_thresholds(
    thresholds: dict[str, AdaptiveThreshold],
    path: Path | None = None,
) -> Path:
    p = path or _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0.0",
        "thresholds": {
            name: {
                "value": t.value,
                "floor": t.floor,
                "ceiling": t.ceiling,
                "unit": t.unit,
                "source": t.source,
            }
            for name, t in thresholds.items()
        },
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
