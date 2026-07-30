"""自我反思——允许改配置与策略，禁止运行时改代码架构。

反思环：critique → patch proposal → shadow → canary → promote
可反思对象白名单：路由策略、技能描述、槽位 schema、阈值、prompt 模板、注意力权重。
禁止：处理器拓扑、权限边界、支付/库存副作用代码。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# 可反思 / 可自动晋升对象
REFLECT_WHITELIST = frozenset(
    {
        "routing_policy",
        "skill_description",
        "slot_schema",
        "soft_constraints",
        "prompt_template",
        "attention_weights",
    }
)

# 明确禁止自改（只能出 RFC/issue）
REFLECT_DENYLIST = frozenset(
    {
        "processor_topology",
        "permission_boundary",
        "payment_side_effect",
        "inventory_side_effect",
        "source_code",
        "cognitive_architecture",
    }
)

_STAGE_ORDER = ("proposed", "shadow", "canary", "promoted", "rejected")


@dataclass
class ReflectionPatch:
    patch_id: str
    target: str
    critique: str
    proposal: dict[str, Any]
    stage: str = "proposed"
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "target": self.target,
            "critique": self.critique,
            "proposal": dict(self.proposal),
            "stage": self.stage,
            "evidence": dict(self.evidence),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "whitelisted": self.target in REFLECT_WHITELIST,
            "denied": self.target in REFLECT_DENYLIST,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _ledger_path() -> Path:
    override = (os.environ.get("XCAGI_REFLECTION_LEDGER") or "").strip()
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[4]
        / "resources"
        / "routing_policies"
        / "reflection_ledger.jsonl"
    )


def is_reflectable(target: str) -> bool:
    t = str(target or "").strip()
    if t in REFLECT_DENYLIST:
        return False
    return t in REFLECT_WHITELIST


class SelfReflectionEngine:
    """白名单自我反思引擎。"""

    def critique_and_propose(
        self,
        *,
        target: str,
        critique: str,
        proposal: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ReflectionPatch:
        now = _utc_now()
        target_key = str(target or "").strip()
        if target_key in REFLECT_DENYLIST or not is_reflectable(target_key):
            patch = ReflectionPatch(
                patch_id=uuid.uuid4().hex[:12],
                target=target_key,
                critique=str(critique or "")[:500],
                proposal={
                    "action": "rfc_only",
                    "reason": "target_not_whitelisted",
                    "human_gate": True,
                    **(proposal or {}),
                },
                stage="rejected",
                evidence=dict(evidence or {}),
                created_at=now,
                updated_at=now,
            )
            self._append(patch)
            return patch

        patch = ReflectionPatch(
            patch_id=uuid.uuid4().hex[:12],
            target=target_key,
            critique=str(critique or "")[:500],
            proposal=dict(proposal or {}),
            stage="proposed",
            evidence=dict(evidence or {}),
            created_at=now,
            updated_at=now,
        )
        self._append(patch)
        return patch

    def advance(
        self,
        patch_id: str,
        *,
        to_stage: str,
        evidence: dict[str, Any] | None = None,
    ) -> ReflectionPatch | None:
        """推进阶段：proposed→shadow→canary→promoted（或 rejected）。"""
        to_stage = str(to_stage or "").strip()
        if to_stage not in _STAGE_ORDER:
            return None
        existing = self.get_patch(patch_id)
        if existing is None:
            return None
        if existing.target in REFLECT_DENYLIST or not is_reflectable(existing.target):
            existing.stage = "rejected"
            existing.updated_at = _utc_now()
            existing.evidence = {**existing.evidence, **(evidence or {}), "blocked": True}
            self._append(existing)
            return existing

        # 禁止跳级晋升（rejected 除外）
        if to_stage != "rejected":
            cur_idx = _STAGE_ORDER.index(existing.stage) if existing.stage in _STAGE_ORDER else 0
            new_idx = _STAGE_ORDER.index(to_stage)
            if new_idx > cur_idx + 1:
                return None

        existing.stage = to_stage
        existing.updated_at = _utc_now()
        if evidence:
            existing.evidence = {**existing.evidence, **evidence}
        self._append(existing)

        if to_stage == "promoted":
            self._apply_promotion(existing)
        return existing

    def reflect_on_routing_mistake(
        self,
        *,
        selected: str,
        better: str,
        reason: str,
        metrics: dict[str, Any] | None = None,
    ) -> ReflectionPatch:
        """典型反思：为何选错层/错技能。"""
        return self.critique_and_propose(
            target="routing_policy",
            critique=f"选了 {selected}，更优应为 {better}：{reason}",
            proposal={
                "action": "bias_processor",
                "from": selected,
                "to": better,
                "delta": 0.05,
            },
            evidence=dict(metrics or {}),
        )

    def get_patch(self, patch_id: str) -> ReflectionPatch | None:
        path = _ledger_path()
        if not path.is_file():
            return None
        latest: ReflectionPatch | None = None
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("patch_id") != patch_id:
                        continue
                    latest = ReflectionPatch(
                        patch_id=str(rec.get("patch_id")),
                        target=str(rec.get("target") or ""),
                        critique=str(rec.get("critique") or ""),
                        proposal=dict(rec.get("proposal") or {}),
                        stage=str(rec.get("stage") or "proposed"),
                        evidence=dict(rec.get("evidence") or {}),
                        created_at=str(rec.get("created_at") or ""),
                        updated_at=str(rec.get("updated_at") or ""),
                    )
        except RECOVERABLE_ERRORS:
            logger.debug("get_patch failed", exc_info=True)
            return None
        return latest

    def _append(self, patch: ReflectionPatch) -> None:
        path = _ledger_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            rec = patch.to_dict()
            rec["ts_unix"] = time.time()
            with _lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except RECOVERABLE_ERRORS:
            logger.debug("reflection ledger append failed", exc_info=True)

    def _apply_promotion(self, patch: ReflectionPatch) -> None:
        """晋升时仅改白名单配置；架构变更不自动 merge。"""
        if patch.target == "soft_constraints":
            try:
                from app.domain.neuro.cognition.plan_constraints import (
                    load_soft_constraints,
                    save_soft_constraints,
                )

                c = load_soft_constraints()
                prop = patch.proposal or {}
                for key in ("w_latency", "w_risk", "w_cost", "w_success"):
                    if key in prop:
                        setattr(c, key, float(prop[key]))
                if isinstance(prop.get("sla_ms"), dict):
                    for k, v in prop["sla_ms"].items():
                        c.sla_ms[str(k)] = float(v)
                save_soft_constraints(c)
                logger.info("promoted soft_constraints patch %s", patch.patch_id)
            except RECOVERABLE_ERRORS:
                logger.debug("soft_constraints promotion failed", exc_info=True)
            return
        # 其他白名单目标：只记账，由运维/CI 消费 proposal
        logger.info(
            "reflection patch %s promoted for target=%s (ledger-only apply)",
            patch.patch_id,
            patch.target,
        )


_engine: SelfReflectionEngine | None = None


def get_self_reflection_engine() -> SelfReflectionEngine:
    global _engine
    if _engine is None:
        _engine = SelfReflectionEngine()
    return _engine


def reset_self_reflection_engine() -> None:
    global _engine
    _engine = None
