"""Device-authenticated evidence; never overrides Para execution state."""

import hmac
import json
import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlEvent, MacControlTask
from modstore_server.mac_control_store import digest, encoded

router = APIRouter(prefix="/api/internal/mac-control", tags=["mac-control-receipts"])


class CancellationReceipt(BaseModel):
    intent_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["not_started", "process_exited"]
    usage_status: Literal["not_started", "unknown", "known"]
    native: dict | None = None


class DeviceProgress(BaseModel):
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    correlation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    device_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    subtask_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    progress: int = Field(default=0, ge=0, le=100)
    cancellation: CancellationReceipt | None = None


def cancellation_intent(db, task):
    # Reconciliation appends observations; the first original stop request is the
    # stable authority, including when the response or a device ACK was lost.
    return (
        db.query(MacControlEvent)
        .filter_by(task_id=task.id, attempt_id=task.attempt_id, state="cancel_requested")
        .order_by(MacControlEvent.id)
        .first()
    )


def _bound_subtask(task, body):
    snapshot = json.loads(task.snapshot_json)
    target = snapshot.get("cancellation_target")
    matches = [
        sub
        for sub in snapshot.get("subtasks", [])
        if isinstance(sub, dict) and sub.get("id") == body.subtask_id
    ]
    return (
        task.para_task_id == body.task_id
        and task.attempt_id == body.attempt_id
        and snapshot.get("id") == body.task_id
        and len(matches) == 1
        and matches[0].get("device_id") == body.device_id
        and matches[0].get("tool_name") == "codex"
        and type(matches[0].get("attempt_count")) is int
        and matches[0]["attempt_count"] == 0
        and (
            not target
            or (
                isinstance(target, dict)
                and target.get("subtask_id") == body.subtask_id
                and target.get("device_id") == body.device_id
                and type(target.get("attempt")) is int
                and target["attempt"] == 1
            )
        )
    )


def _control(db, task, body):
    if task.state != "cancel_requested" or not _bound_subtask(task, body):
        return None
    intent = cancellation_intent(db, task)
    if intent is None:
        return None
    return {
        "action": "cancel",
        "intent_id": intent.event_key,
        **body.model_dump(
            include={"correlation_id", "attempt_id", "device_id", "task_id", "subtask_id"}
        ),
    }


def _validate_stop(db, task, body):
    proof = body.cancellation
    intent = cancellation_intent(db, task)
    if (
        body.status != "cancelled"
        or not _bound_subtask(task, body)
        or intent is None
        or proof.intent_id != intent.event_key
    ):
        raise HTTPException(409, "取消回执与原停止请求不匹配")
    native = proof.native or {}
    exit_code, signal = native.get("exit_code"), native.get("signal")
    if proof.outcome == "not_started":
        valid = proof.usage_status == "not_started" and not native
    elif proof.usage_status == "known":
        # Cancellation after a native completion can stop publication. Preserve
        # that measured turn as completed; do not invent an interrupt receipt.
        usage = native.get("usage") or {}
        valid = (
            native.get("status") == "completed"
            and native.get("turn_completed") is True
            and type(exit_code) is int
            and exit_code == 0
            and signal is None
            and type(native.get("active_tools")) is int
            and native["active_tools"] == 0
            and isinstance(usage, dict)
            and all(
                type(usage.get(key)) is int and usage[key] >= 0
                for key in ("input_tokens", "cached_input_tokens", "output_tokens")
            )
        )
    else:
        valid = (
            proof.usage_status == "unknown"
            and native.get("status") == "unknown"
            and native.get("reason") == "codex_cancelled"
            and native.get("termination_method") in ("posix_process_group", "windows_taskkill_tree")
            and (
                (type(exit_code) is int and exit_code >= 0 and signal is None)
                or (exit_code is None and type(signal) is str and signal in {"SIGTERM", "SIGKILL"})
            )
        )
    if not valid:
        raise HTTPException(409, "取消回执缺少原执行器停止证据")


def _stop_evidence(db, task, intent):
    evidence = {}
    for event in db.query(MacControlEvent).filter_by(
        task_id=task.id, attempt_id=task.attempt_id, state="device_evidence"
    ):
        payload = json.loads(event.payload_json)
        if (
            payload.get("status") == "cancelled"
            and payload.get("task_id") == task.para_task_id
            and payload.get("device_id") == task.device_id
            and (payload.get("cancellation") or {}).get("intent_id") == intent.event_key
        ):
            evidence[payload["subtask_id"]] = payload["cancellation"]
    return evidence


def confirmed_cancellation(db, task, raw):
    """A stop observation cannot override a native success or release model usage."""
    subs = raw.get("subTasks")
    intent = cancellation_intent(db, task)
    if raw.get("status") != "failed" or not subs or intent is None:
        return None
    if any(not isinstance(sub, dict) or not sub.get("id") for sub in subs) or len(
        {sub["id"] for sub in subs}
    ) != len(subs):
        return None
    evidence, stopped = _stop_evidence(db, task, intent), {}
    for sub in subs:
        if sub.get("status") in {"completed", "merged", "cancelled"}:
            continue  # Preserve these native outcomes; no local stop receipt is invented.
        if (
            sub.get("status") != "failed"
            or sub.get("device_id") != task.device_id
            or sub.get("tool_name") != "codex"
            or type(sub.get("attempt_count")) is not int
            or sub["attempt_count"] != 0
            or sub["id"] not in evidence
        ):
            return None
        stopped[sub["id"]] = evidence[sub["id"]]
    return (
        {"intent_id": intent.event_key, "subtasks": stopped, "usage_status": "unknown"}
        if stopped
        else None
    )


def awaiting_cancellation_receipt(db, task, raw):
    """The two durable outboxes can arrive in either order; do not strand an ACK."""
    intent = cancellation_intent(db, task)
    if raw.get("status") != "failed" or intent is None:
        return False
    subs = raw.get("subTasks") or []
    if not subs or any(
        not isinstance(sub, dict)
        or sub.get("status") not in {"failed", "completed", "merged", "cancelled"}
        for sub in subs
    ):
        return True  # A task-level failure alone does not prove its other children stopped.
    pending = set(_stop_evidence(db, task, intent))
    for report in raw.get("reports", []):
        if (
            not isinstance(report, dict)
            or not report.get("applied")
            or report.get("status") != "failed"
        ):
            continue
        try:
            value = json.loads(report.get("report", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(value, dict):
            continue
        control = value.get("control") or {}
        if not isinstance(control, dict):
            continue
        if (
            value.get("source") == "mac_control_cancel"
            and value.get("stop_confirmed") is True
            and control.get("intent_id") == intent.event_key
            and control.get("correlation_id") == task.id
            and control.get("attempt_id") == task.attempt_id
            and control.get("device_id") == task.device_id
            and control.get("task_id") == task.para_task_id
            and any(
                sub.get("id") == control.get("subtask_id")
                and sub.get("device_id") == task.device_id
                for sub in raw.get("subTasks", [])
            )
        ):
            pending.add(control["subtask_id"])
    failed = [sub for sub in subs if sub.get("status") == "failed"]
    # An independent failed child remains a real failure, not a cancellation.
    return bool(failed) and all(sub.get("id") in pending for sub in failed)


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
    # Omitting optional fields preserves the pre-existing receipt digest contract.
    payload = body.model_dump(exclude={"cancellation"} if body.cancellation is None else set())
    if digest({key: value for key, value in payload.items() if key != "event_id"}) != body.event_id:
        raise HTTPException(409, "回执摘要不匹配")
    if body.cancellation:
        _validate_stop(db, task, body)
    existing = db.query(MacControlEvent).filter_by(event_key=body.event_id).first()
    if existing:
        if existing.payload_json != encoded(payload):
            raise HTTPException(409, "回执标识已用于其他内容")
        return {"accepted": True, "duplicate": True, "control": _control(db, task, body)}
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
    return {"accepted": True, "stale_attempt": stale, "control": _control(db, task, body)}
