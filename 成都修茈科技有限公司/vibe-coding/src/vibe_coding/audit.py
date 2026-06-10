"""Patch ledger for the standalone (code-layer only) build."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from ._internals import CodeSkill
from .runtime import JsonCodeSkillStore


@dataclass(slots=True)
class PatchRecord:
    skill_id: str
    layer: str
    version: int
    stage: str
    summary: str
    diff: dict[str, Any] = field(default_factory=dict)
    diagnosis: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PatchLedger:
    """History / evolution-chain / rollback over a :class:`JsonCodeSkillStore`."""

    def __init__(self, *, code_store: JsonCodeSkillStore):
        if code_store is None:
            raise ValueError("code_store is required")
        self.code_store = code_store

    def history(self, skill_id: str) -> list[PatchRecord]:
        if not self.code_store.has_code_skill(skill_id):
            return []
        records = list(self._code_history(skill_id))
        records.sort(key=lambda r: r.created_at)
        return records

    def evolution_chain(self, skill_id: str) -> list[dict[str, Any]]:
        if not self.code_store.has_code_skill(skill_id):
            raise KeyError(f"skill not found: {skill_id!r}")
        skill = self.code_store.get_code_skill(skill_id)
        return [
            {
                "version": v.version,
                "function_name": v.function_name,
                "source_run_id": v.source_run_id,
                "test_cases": len(v.test_cases),
                "active": v.version == skill.active_version,
                "created_at": v.created_at,
            }
            for v in sorted(skill.versions, key=lambda x: x.version)
        ]

    def rollback(self, skill_id: str, target_version: int) -> CodeSkill:
        skill = self.code_store.get_code_skill(skill_id)
        if not any(v.version == target_version for v in skill.versions):
            raise ValueError(f"version {target_version} not in skill {skill_id!r}")
        skill.active_version = int(target_version)
        self.code_store.save_code_skill(skill)
        return skill

    def report(self, skill_id: str | None = None) -> dict[str, Any]:
        skills = self.code_store.list_code_skills()
        if skill_id is not None:
            skills = [s for s in skills if s.skill_id == skill_id]
        rows: list[dict[str, Any]] = []
        for s in skills:
            history = self.history(s.skill_id)
            healed = sum(1 for r in history if r.stage in ("solidified", "dynamic", "healed"))
            failed = sum(1 for r in history if r.error)
            rows.append(
                {
                    "skill_id": s.skill_id,
                    "layer": "code",
                    "versions": len(s.versions),
                    "patches": len(history),
                    "healed": healed,
                    "failed": failed,
                    "active_version": s.active_version,
                }
            )
        return {
            "skills": rows,
            "totals": {
                "skills": len(rows),
                "patches": sum(r["patches"] for r in rows),
                "healed": sum(r["healed"] for r in rows),
                "failed": sum(r["failed"] for r in rows),
            },
        }

    def _code_history(self, skill_id: str) -> Iterable[PatchRecord]:
        for run in self.code_store.list_code_runs(skill_id):
            patch = run.get("patch") or {}
            diag = run.get("diagnosis") or {}
            yield PatchRecord(
                skill_id=skill_id,
                layer="code",
                version=int(patch.get("solidified_version") or 0),
                stage=str(run.get("stage") or ""),
                summary=str(patch.get("diff_summary") or patch.get("reason") or ""),
                diff={
                    "original_code": patch.get("original_code") or "",
                    "patched_code": patch.get("patched_code") or "",
                    "reasoning": patch.get("llm_reasoning") or "",
                },
                diagnosis=dict(diag) if isinstance(diag, dict) else {},
                error=str(run.get("error") or ""),
                created_at=str(run.get("started_at") or run.get("completed_at") or ""),
            )
