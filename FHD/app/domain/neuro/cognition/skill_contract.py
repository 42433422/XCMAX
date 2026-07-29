"""技能契约——把封闭意图表降级为 bootstrap，支持开放世界未命中路由。

两层表示：
- domain_skill：可扩展技能（发货/开单/对账…）
- procedure：由规划器组合；本模块负责技能匹配与新技能提案
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillContract:
    skill_id: str
    title: str
    bootstrap_intents: tuple[str, ...]
    required_slots: tuple[str, ...]
    optional_slots: tuple[str, ...]
    side_effects: tuple[str, ...]
    rollback: str
    keywords: tuple[str, ...]
    domain_adapters: tuple[str, ...]
    uses_causal_graph: str | None = None

    def missing_slots(self, slots: dict[str, Any] | None) -> list[str]:
        slots = slots or {}
        missing: list[str] = []
        for key in self.required_slots:
            val = slots.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(key)
        return missing


@dataclass
class SkillMatch:
    skill: SkillContract
    score: float
    reason: str
    via_bootstrap_intent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill.skill_id,
            "title": self.skill.title,
            "score": self.score,
            "reason": self.reason,
            "via_bootstrap_intent": self.via_bootstrap_intent,
            "required_slots": list(self.skill.required_slots),
            "side_effects": list(self.skill.side_effects),
            "domain_adapters": list(self.skill.domain_adapters),
            "uses_causal_graph": self.skill.uses_causal_graph,
        }


@dataclass
class SkillProposal:
    """开放世界未命中时的新技能提案（不直接改分类器）。"""

    proposed_skill_id: str
    title: str
    raw_input: str
    candidate_slots: list[str] = field(default_factory=list)
    rationale: str = ""
    status: str = "proposed"  # proposed | shadow | rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposed_skill_id": self.proposed_skill_id,
            "title": self.title,
            "raw_input": self.raw_input[:200],
            "candidate_slots": self.candidate_slots,
            "rationale": self.rationale,
            "status": self.status,
        }


def _default_skills_path() -> Path:
    return Path(__file__).resolve().parents[4] / "resources" / "neuro" / "skill_contracts.json"


def load_skill_contracts(path: Path | None = None) -> list[SkillContract]:
    skills_path = path or _default_skills_path()
    try:
        raw = json.loads(skills_path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        logger.debug("load_skill_contracts failed", exc_info=True)
        return []

    out: list[SkillContract] = []
    for item in raw.get("skills") or []:
        if not isinstance(item, dict) or not item.get("skill_id"):
            continue
        out.append(
            SkillContract(
                skill_id=str(item["skill_id"]),
                title=str(item.get("title") or item["skill_id"]),
                bootstrap_intents=tuple(str(x) for x in (item.get("bootstrap_intents") or [])),
                required_slots=tuple(str(x) for x in (item.get("required_slots") or [])),
                optional_slots=tuple(str(x) for x in (item.get("optional_slots") or [])),
                side_effects=tuple(str(x) for x in (item.get("side_effects") or [])),
                rollback=str(item.get("rollback") or "none"),
                keywords=tuple(str(x) for x in (item.get("keywords") or [])),
                domain_adapters=tuple(str(x) for x in (item.get("domain_adapters") or ["generic"])),
                uses_causal_graph=(
                    str(item["uses_causal_graph"]) if item.get("uses_causal_graph") else None
                ),
            )
        )
    return out


@lru_cache(maxsize=1)
def get_skill_registry() -> tuple[SkillContract, ...]:
    return tuple(load_skill_contracts())


def reset_skill_registry() -> None:
    get_skill_registry.cache_clear()


class SkillRouter:
    """意图 bootstrap + 关键词开放匹配；低置信产出技能提案。"""

    def __init__(
        self,
        skills: list[SkillContract] | None = None,
        *,
        min_score: float = 0.35,
    ) -> None:
        self._skills = list(skills) if skills is not None else list(get_skill_registry())
        self._min_score = min_score
        self._intent_index: dict[str, SkillContract] = {}
        for skill in self._skills:
            for intent in skill.bootstrap_intents:
                self._intent_index[intent] = skill

    def by_intent(self, intent: str | None) -> SkillContract | None:
        if not intent or intent in {"unk", "unknown", ""}:
            return None
        return self._intent_index.get(str(intent))

    def match(
        self,
        text: str,
        *,
        intent: str | None = None,
        domain: str = "generic",
        top_k: int = 3,
    ) -> list[SkillMatch]:
        text_norm = " ".join(str(text or "").strip().lower().split())
        matches: list[SkillMatch] = []

        bootstrap = self.by_intent(intent)
        if bootstrap and (domain in bootstrap.domain_adapters or not bootstrap.domain_adapters):
            matches.append(
                SkillMatch(
                    skill=bootstrap,
                    score=0.95,
                    reason="bootstrap_intent",
                    via_bootstrap_intent=intent,
                )
            )

        for skill in self._skills:
            if domain and skill.domain_adapters and domain not in skill.domain_adapters:
                continue
            if bootstrap and skill.skill_id == bootstrap.skill_id:
                continue
            score = self._keyword_score(text_norm, skill)
            if score >= self._min_score:
                matches.append(
                    SkillMatch(skill=skill, score=score, reason="keyword_overlap")
                )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[: max(1, top_k)]

    def route_open_world(
        self,
        text: str,
        *,
        intent: str | None = None,
        domain: str = "generic",
        confidence: float = 0.0,
    ) -> dict[str, Any]:
        """封闭意图未命中 / 低置信 → 候选技能或新技能提案。"""
        unclear = (not intent) or intent in {"unk", "unknown"} or confidence < 0.45
        matches = self.match(text, intent=None if unclear else intent, domain=domain)
        if matches and matches[0].score >= self._min_score and not (
            unclear and matches[0].reason == "bootstrap_intent" and confidence < 0.2
        ):
            top = matches[0]
            return {
                "status": "skill_candidate",
                "skill": top.to_dict(),
                "candidates": [m.to_dict() for m in matches],
                "proposal": None,
            }

        proposal = self.propose_skill(text)
        return {
            "status": "skill_proposal",
            "skill": None,
            "candidates": [m.to_dict() for m in matches],
            "proposal": proposal.to_dict(),
        }

    def propose_skill(self, text: str) -> SkillProposal:
        raw = " ".join(str(text or "").strip().split())
        slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", raw.lower())[:32].strip("_") or "open"
        slots = self._guess_slots(raw)
        return SkillProposal(
            proposed_skill_id=f"open.{slug}",
            title=f"开放技能：{raw[:40]}" if raw else "开放技能",
            raw_input=raw,
            candidate_slots=slots,
            rationale="classifier_miss_or_low_confidence",
            status="proposed",
        )

    def _keyword_score(self, text_norm: str, skill: SkillContract) -> float:
        if not text_norm or not skill.keywords:
            return 0.0
        hits = sum(1 for kw in skill.keywords if kw.lower() in text_norm)
        if hits <= 0:
            return 0.0
        return min(0.92, 0.25 + 0.22 * hits)

    def _guess_slots(self, text: str) -> list[str]:
        slots: list[str] = []
        if re.search(r"(单位|客户|公司)", text):
            slots.append("unit_name")
        if re.search(r"(订单|单号)", text):
            slots.append("order_no")
        if re.search(r"(电话|手机)", text):
            slots.append("contact_phone")
        if re.search(r"(\d+\s*桶|数量)", text):
            slots.append("quantity_tins")
        return slots


_router: SkillRouter | None = None


def get_skill_router() -> SkillRouter:
    global _router
    if _router is None:
        _router = SkillRouter()
    return _router


def reset_skill_router() -> None:
    global _router
    _router = None
    reset_skill_registry()
