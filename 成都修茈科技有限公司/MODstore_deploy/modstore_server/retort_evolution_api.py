"""Native management surface for the persisted Retort improvement workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from modstore_server import retort_evolution as service
from modstore_server.api.deps import get_db, require_admin
from modstore_server.customer_service_tools import json_loads
from modstore_server.customer_ticket_github import configuration, github
from modstore_server.models import RetortEvolutionRun, User
from modstore_server.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(
    prefix="/api/retort-evolution", tags=["retort-evolution"], dependencies=[Depends(require_admin)]
)


def _templates():
    path = os.environ.get("MODSTORE_RETORT_PROTOCOLS", "")
    return json.loads(Path(path).read_text()) if path else {}


def _view(row):
    snapshot = json_loads(row.snapshot_json, {})
    status = row.status
    if (
        status == "completed"
        and snapshot.get("delivery", {}).get("status") != "deployment_verified"
    ):
        status = "branch_accepted"
    return {
        "id": row.id,
        "status": status,
        "protocol": json_loads(row.protocol_json, {}),
        "snapshot": snapshot,
        "effects": json_loads(row.effects_json, {}),
        "error": row.error,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _row(db, request_id):
    row = db.get(RetortEvolutionRun, str(request_id))
    if row is None:
        raise HTTPException(404, "改进任务不存在")
    return row


@router.get("")
def overview(
    db: Session = Depends(get_db), offset: int = Query(0, ge=0), limit: int = Query(8, ge=1, le=50)
):
    catalog = service.catalog()
    templates = _templates()
    config = configuration()
    query = db.query(RetortEvolutionRun)
    return {
        "items": [
            _view(row)
            for row in query.order_by(RetortEvolutionRun.updated_at.desc())
            .offset(offset)
            .limit(limit)
        ],
        "total": query.count(),
        "standard_version": catalog["standard_version"],
        "domains": [
            {
                "id": d["id"],
                "name": d["name"],
                "number": d["number"],
                "criteria": d["anchor_60"] + d["anchor_90"],
            }
            for d in catalog["domains"]
        ],
        "templates": [
            {"id": key, "name": value["name"], "criterion_ids": value["criterion_ids"]}
            for key, value in templates.items()
        ],
        "components": {"workflow": "LangGraph", "rsi": "GEPA", "executor": "GitHub Actions · Para"},
        "connections": {
            "checkpoint": bool(os.environ.get("MODSTORE_RETORT_CHECKPOINT_DSN")),
            "github": config["configured"],
            "employees": config["para_configured"],
            "protocols": bool(templates),
            "rsi": bool(os.environ.get("MODSTORE_RETORT_RSI_PROTOCOL")),
            "evidence": bool(os.environ.get("MODSTORE_RUNTIME_DIR"))
            and bool(
                os.environ.get("RETORT_ARTIFACT_MASTER_KEY")
                or os.environ.get("MODSTORE_LLM_MASTER_KEY")
            ),
        },
    }


class NewRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    template_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=12000)


def _advance(request_id, approval=None):
    # Persisted work remains resumable by APScheduler if this HTTP worker exits.
    try:
        service.advance_run(request_id, approval=approval)
    except RECOVERABLE_ERRORS as exc:
        import logging

        logging.getLogger(__name__).error(
            "Retort continuation incomplete: %s (%s)", request_id, type(exc).__name__
        )


@router.post("")
def create(body: NewRun, background: BackgroundTasks, user: User = Depends(require_admin)):
    template = _templates().get(body.template_id)
    if not template:
        raise HTTPException(422, "请选择已冻结的验收方案")
    config = configuration()
    source_sha = github("GET", f"/repos/{config['repository']}/commits/main")["sha"]
    request = {key: template[key] for key in ("criterion_ids", "checks", "container_image")}
    request.update(
        request_id=str(body.request_id),
        title=body.title,
        goal=body.goal,
        repository=config["repository"],
        source_sha=source_sha,
    )
    try:
        request_id = service.create_run(request, user.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    background.add_task(_advance, request_id)
    return {"id": request_id, "status": "created"}


@router.get("/{request_id}")
def detail(request_id: UUID, db: Session = Depends(get_db)):
    return _view(_row(db, request_id))


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool


@router.post("/{request_id}/decision")
def decide(request_id: UUID, body: Decision, user: User = Depends(require_admin)):
    # Approval is checkpointed synchronously before acknowledging it. The graph
    # pauses immediately after dispatch; expensive execution remains scheduled.
    try:
        return service.advance_run(
            str(request_id), approval={**body.model_dump(), "actor_id": user.id}
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{request_id}/resume")
def resume(request_id: UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    _row(db, request_id)
    background.add_task(_advance, str(request_id))
    return {"id": str(request_id), "status": "queued"}
