"""Device-authenticated evidence; never overrides Para execution state."""

import hmac
import json
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlEvent, MacControlTask
from modstore_server.mac_control_store import digest, encoded

router = APIRouter(prefix="/api/internal/mac-control", tags=["mac-control-receipts"])


class DeviceProgress(BaseModel):
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    correlation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    device_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    subtask_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    progress: int = Field(default=0, ge=0, le=100)


@router.post("/receipts")
def receipt(body: DeviceProgress, authorization: str = Header(""), db: Session = Depends(get_db)):
    try:
        identities = json.loads(os.environ.get("MODSTORE_MAC_CONTROL_DEVICE_TOKENS", "{}"))
    except ValueError:
        identities = {}
    expected = identities.get(body.device_id, "")
    if not expected or not hmac.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(401, "设备服务身份无效")
    task = db.get(MacControlTask, body.correlation_id)
    if task is None or task.device_id != body.device_id:
        raise HTTPException(403, "设备与任务不匹配")
    if task.para_task_id and task.para_task_id != body.task_id:
        raise HTTPException(409, "Para 任务不匹配")
    payload = body.model_dump()
    existing = db.query(MacControlEvent).filter_by(event_key=body.event_id).first()
    if existing:
        if existing.payload_json != encoded(payload):
            raise HTTPException(409, "回执标识已用于其他内容")
        return {"accepted": True, "duplicate": True}
    if digest(body.model_dump(exclude={"event_id"})) != body.event_id:
        raise HTTPException(409, "回执摘要不匹配")
    stale = body.attempt_id != task.attempt_id
    db.add(
        MacControlEvent(
            event_key=body.event_id,
            task_id=task.id,
            attempt_id=body.attempt_id,
            state="late_device_evidence" if stale else "device_evidence",
            payload_json=encoded(payload),
            created_at=time.time(),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.query(MacControlEvent).filter_by(event_key=body.event_id).one()
        if prior.payload_json != encoded(payload):
            raise HTTPException(409, "回执冲突") from None
    return {"accepted": True, "stale_attempt": stale}
