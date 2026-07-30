"""规划软约束——把硬 SLA 阈值改成代价函数中的约束项。

阈值仍可作为默认先验，但选择路径时最小化：
  cost = w_latency * latency_penalty + w_risk * risk + w_cost * money - w_success * success_prior
Evolution 可提议调整权重，须 shadow 验证后晋升。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class SoftConstraints:
    """处理器/路径选择的软约束权重与 SLA 先验。"""

    sla_ms: dict[str, float] = field(
        default_factory=lambda: {
            "reflex": 1.0,
            "subconscious": 10.0,
            "conscious": 200.0,
        }
    )
    w_latency: float = 0.45
    w_risk: float = 0.35
    w_cost: float = 0.10
    w_success: float = 0.10
    # 各层先验风险 / 费用 / 成功率
    priors: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "reflex": {"risk": 0.15, "cost": 0.05, "success": 0.75},
            "subconscious": {"risk": 0.25, "cost": 0.15, "success": 0.70},
            "conscious": {"risk": 0.35, "cost": 0.55, "success": 0.82},
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sla_ms": dict(self.sla_ms),
            "w_latency": self.w_latency,
            "w_risk": self.w_risk,
            "w_cost": self.w_cost,
            "w_success": self.w_success,
            "priors": {k: dict(v) for k, v in self.priors.items()},
        }


def default_constraints() -> SoftConstraints:
    return SoftConstraints()


def _constraints_path() -> Path:
    override = (os.environ.get("XCAGI_SOFT_CONSTRAINTS_PATH") or "").strip()
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[4]
        / "resources"
        / "routing_policies"
        / "soft_constraints.json"
    )


def load_soft_constraints(path: Path | None = None) -> SoftConstraints:
    p = path or _constraints_path()
    base = default_constraints()
    if not p.is_file():
        return base
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        logger.debug("load_soft_constraints failed", exc_info=True)
        return base
    if not isinstance(raw, dict):
        return base
    if isinstance(raw.get("sla_ms"), dict):
        for k, v in raw["sla_ms"].items():
            try:
                base.sla_ms[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    for key in ("w_latency", "w_risk", "w_cost", "w_success"):
        if key in raw:
            try:
                setattr(base, key, float(raw[key]))
            except (TypeError, ValueError):
                pass
    if isinstance(raw.get("priors"), dict):
        for layer, vals in raw["priors"].items():
            if not isinstance(vals, dict):
                continue
            base.priors.setdefault(str(layer), {})
            for pk, pv in vals.items():
                try:
                    base.priors[str(layer)][str(pk)] = float(pv)
                except (TypeError, ValueError):
                    continue
    return base


def save_soft_constraints(constraints: SoftConstraints, path: Path | None = None) -> Path:
    p = path or _constraints_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(constraints.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p


@dataclass
class PathScore:
    processor: str
    cost: float
    breakdown: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "processor": self.processor,
            "cost": self.cost,
            "breakdown": dict(self.breakdown),
        }


def score_processor_path(
    processor: str,
    *,
    expected_latency_ms: float | None = None,
    constraints: SoftConstraints | None = None,
    risk_override: float | None = None,
) -> PathScore:
    """计算单路径代价；越小越好。"""
    c = constraints or load_soft_constraints()
    key = str(processor or "conscious").lower()
    prior = c.priors.get(key) or c.priors.get("conscious") or {}
    sla = float(c.sla_ms.get(key, 200.0))
    latency = float(expected_latency_ms if expected_latency_ms is not None else sla)
    latency_penalty = max(0.0, latency / max(sla, 1e-6) - 1.0) + min(
        1.0, latency / max(sla * 5, 1.0)
    )
    risk = float(risk_override if risk_override is not None else prior.get("risk", 0.3))
    money = float(prior.get("cost", 0.3))
    success = float(prior.get("success", 0.7))
    cost = (
        c.w_latency * latency_penalty + c.w_risk * risk + c.w_cost * money - c.w_success * success
    )
    return PathScore(
        processor=key,
        cost=round(cost, 6),
        breakdown={
            "latency_penalty": round(latency_penalty, 6),
            "risk": risk,
            "money": money,
            "success_prior": success,
            "sla_ms": sla,
            "expected_latency_ms": latency,
        },
    )


def select_processor_by_cost(
    candidates: list[str] | None = None,
    *,
    expected_latencies: dict[str, float] | None = None,
    constraints: SoftConstraints | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """在候选处理器中选代价最低者；prefer 仅作并列打破。"""
    c = constraints or load_soft_constraints()
    pool = candidates or ["reflex", "subconscious", "conscious"]
    scores = [
        score_processor_path(
            name,
            expected_latency_ms=(expected_latencies or {}).get(name),
            constraints=c,
        )
        for name in pool
    ]
    scores.sort(key=lambda s: (s.cost, 0 if s.processor == prefer else 1))
    best = scores[0]
    return {
        "selected": best.processor,
        "cost": best.cost,
        "scores": [s.to_dict() for s in scores],
        "constraints": c.to_dict(),
        "mode": "soft_constraint",
    }


def is_sla_hit_soft(
    processor: str,
    latency_ms: float,
    *,
    constraints: SoftConstraints | None = None,
    slack: float = 1.25,
) -> bool:
    """软 SLA：允许 slack 倍超出仍记为可接受（用于 reward，非硬杀）。"""
    c = constraints or load_soft_constraints()
    threshold = float(c.sla_ms.get(str(processor).lower(), 200.0)) * max(1.0, slack)
    return float(latency_ms) <= threshold
