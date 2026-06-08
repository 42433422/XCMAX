"""REST API for ESkill registry and debug runs."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.eskill_runtime import default_eskill_runtime
from modstore_server.infrastructure.db import get_db
from modstore_server.models import ESkill, ESkillRun, ESkillVersion, User

router = APIRouter(prefix="/api/eskills", tags=["eskills"])


class CreateESkillBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    domain: str = Field("", max_length=2000)
    description: str = Field("", max_length=4000)
    static_logic: Dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "template_transform",
            "template": "${value}",
            "output_var": "eskill_result",
        }
    )
    trigger_policy: Dict[str, Any] = Field(default_factory=dict)
    quality_gate: Dict[str, Any] = Field(default_factory=dict)


class RunESkillBody(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)
    logic_overrides: Dict[str, Any] = Field(default_factory=dict)
    trigger_policy: Dict[str, Any] = Field(default_factory=dict)
    quality_gate: Dict[str, Any] = Field(default_factory=dict)
    force_dynamic: bool = False
    solidify: bool = True


def _loads(raw: str | None) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _skill_to_dict(skill: ESkill, version: Optional[ESkillVersion] = None) -> Dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "domain": skill.domain or "",
        "description": skill.description or "",
        "active_version": skill.active_version,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        "active": {
            "version": version.version if version else skill.active_version,
            "static_logic": _loads(version.static_logic_json) if version else {},
            "trigger_policy": _loads(version.trigger_policy_json) if version else {},
            "quality_gate": _loads(version.quality_gate_json) if version else {},
        },
    }


@router.get("")
@router.get("/")
async def list_eskills(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(ESkill).filter(ESkill.user_id == user.id).order_by(ESkill.updated_at.desc()).all()
    )
    versions = {
        (v.eskill_id, v.version): v
        for v in db.query(ESkillVersion)
        .filter(ESkillVersion.eskill_id.in_([s.id for s in rows] or [0]))
        .all()
    }
    return [_skill_to_dict(skill, versions.get((skill.id, skill.active_version))) for skill in rows]


@router.post("")
@router.post("/")
async def create_eskill(
    body: CreateESkillBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    skill = ESkill(
        user_id=user.id,
        name=body.name.strip(),
        domain=body.domain.strip(),
        description=body.description.strip(),
        active_version=1,
    )
    db.add(skill)
    try:
        db.flush()
        version = ESkillVersion(
            eskill_id=skill.id,
            version=1,
            static_logic_json=_dumps(body.static_logic),
            trigger_policy_json=_dumps(body.trigger_policy),
            quality_gate_json=_dumps(body.quality_gate),
            note="initial",
        )
        db.add(version)
        db.commit()
        db.refresh(skill)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(400, f"创建 ESkill 失败: {exc}") from exc
    return _skill_to_dict(skill, version)


@router.get("/{eskill_id}")
async def get_eskill(
    eskill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    skill = db.query(ESkill).filter(ESkill.id == eskill_id, ESkill.user_id == user.id).first()
    if not skill:
        raise HTTPException(404, "ESkill 不存在")
    versions = (
        db.query(ESkillVersion)
        .filter(ESkillVersion.eskill_id == skill.id)
        .order_by(ESkillVersion.version.desc())
        .all()
    )
    runs = (
        db.query(ESkillRun)
        .filter(ESkillRun.eskill_id == skill.id)
        .order_by(ESkillRun.id.desc())
        .limit(20)
        .all()
    )
    active = next((v for v in versions if v.version == skill.active_version), None)
    data = _skill_to_dict(skill, active)
    data["versions"] = [
        {
            "id": v.id,
            "version": v.version,
            "static_logic": _loads(v.static_logic_json),
            "trigger_policy": _loads(v.trigger_policy_json),
            "quality_gate": _loads(v.quality_gate_json),
            "source_run_id": v.source_run_id,
            "note": v.note or "",
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]
    data["runs"] = [
        {
            "id": r.id,
            "stage": r.stage,
            "output": _loads(r.output_json),
            "patch": _loads(r.patch_json),
            "error": r.error_message or "",
            "duration_ms": r.duration_ms,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]
    return data


@router.post("/{eskill_id}/run")
async def run_eskill(
    eskill_id: int,
    body: RunESkillBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    try:
        return default_eskill_runtime.run(
            db,
            eskill_id=eskill_id,
            user_id=user.id,
            input_data=body.input_data,
            logic_overrides=body.logic_overrides,
            trigger_policy_override=body.trigger_policy,
            quality_gate_override=body.quality_gate,
            force_dynamic=body.force_dynamic,
            solidify=body.solidify,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
