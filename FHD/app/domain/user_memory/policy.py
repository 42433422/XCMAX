"""Candidate source governance and stable normalization, independent of storage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from app.domain.user_memory.records import UserMemory


@dataclass(frozen=True)
class PolicyPorts:
    types: Callable[[], Collection[str]]
    statuses: Callable[[], Collection[str]]
    blocked_sources: Callable[[], Collection[str]]
    trusted_sources: Callable[[], Collection[str]]
    observed_sources: Callable[[], Collection[str]]


class MemoryPolicy:
    def __init__(self, ports: PolicyPorts) -> None:
        self.ports = ports

    def normalize_type(self, memory_type: str) -> str:
        normalized = str(memory_type or "").strip().lower()
        aliases = {
            "pref": "preference",
            "preference_memory": "preference",
            "entity_memory": "entity",
            "episodic_memory": "episodic",
            "task": "episodic",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in self.ports.types():
            raise ValueError(f"unsupported memory_type: {memory_type}")
        return normalized

    def normalize_status(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized not in self.ports.statuses():
            raise ValueError(f"unsupported memory status: {status}")
        return normalized

    def fingerprint(self, memory_type: str, key: str, value: Any) -> str:
        raw = json.dumps(
            {"memory_type": memory_type, "key": key, "value": value},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def govern_candidate(
        self, *, source: str, confidence: float, evidence: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        normalized_source = str(source or "agent_observation").strip().lower()
        normalized_source = normalized_source.replace(" ", "_")[:80] or "agent_observation"
        flags: list[str] = []
        source_policy = "requires_confirmation"
        source_trust = "observed"
        try:
            effective_confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            effective_confidence = 0.5
            flags.append("invalid_confidence_defaulted")
        evidence_items = [
            dict(item) for item in list(evidence or []) if isinstance(item, dict) and item
        ][:10]
        evidence_required = False
        if normalized_source in self.ports.blocked_sources():
            source_policy = "blocked"
            source_trust = "blocked"
            flags.append("blocked_source")
            effective_confidence = min(effective_confidence, 0.0)
        elif normalized_source in self.ports.trusted_sources():
            source_policy = "trusted_pending"
            source_trust = "trusted_user"
        elif normalized_source in self.ports.observed_sources():
            source_policy = "observed_pending"
            source_trust = "observed"
            evidence_required = True
        else:
            source_policy = "needs_evidence"
            source_trust = "unverified"
            evidence_required = True
            flags.append("unknown_source")
        if evidence_required and (not evidence_items):
            flags.append("missing_evidence")
            effective_confidence = min(effective_confidence, 0.35)
        return {
            "source": normalized_source,
            "source_policy": source_policy,
            "source_trust": source_trust,
            "source_evidence_required": evidence_required,
            "requires_user_confirmation": True,
            "auto_confirm_allowed": False,
            "eligible_for_planner": False,
            "governance_flags": flags,
            "confidence": effective_confidence,
            "evidence": evidence_items,
        }

    def find_record(self, memory: UserMemory, memory_id: str) -> tuple[int, dict[str, Any] | None]:
        for idx, record in enumerate(memory.memory_v2_records):
            if str(record.get("memory_id") or "") == str(memory_id or ""):
                return (idx, record)
        return (-1, None)


def is_scoped_memory_owner(user_id: str) -> bool:
    return str(user_id or "").startswith(
        ("personal-memory:v1:", "enterprise-memory:v1:", "global-preference:v1:")
    )


def is_erp_bound_memory(record: Any) -> bool:
    """Claims tied to ERP must not enter unscoped vector or legacy recall."""
    if not isinstance(record, dict):
        return False
    if record.get("source") == "erp_authority":
        return True
    evidence = record.get("evidence")
    return isinstance(evidence, list) and any(
        isinstance(item, dict) and item.get("kind") == "erp_fact_reference_v1" for item in evidence
    )


def is_recallable_memory(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and record.get("status") == "active"
        and record.get("eligible_for_planner") is True
        and record.get("source_policy") != "blocked"
    )


def memory_statement(record: dict[str, Any]) -> str:
    value = record.get("value")
    if isinstance(value, dict) and value.get("statement"):
        return str(value["statement"])
    rendered = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    )
    return f"{record.get('key') or '记忆'}：{rendered}"
