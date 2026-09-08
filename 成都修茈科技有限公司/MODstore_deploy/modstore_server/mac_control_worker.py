"""Recover accepted Para work before retrying; never infer delivery from execution."""

from __future__ import annotations

import json
import os
import time
import uuid

from sqlalchemy.exc import IntegrityError

from modstore_server.db.base import get_session_factory
from modstore_server.db.mac_control import (
    MacControlObservation,
    MacControlSyncLease,
    MacControlTask,
)
from modstore_server.mac_control_store import TERMINAL, acquire, encoded, transition
from modstore_server.mac_control_transport import (
    ParaClient,
    ParaUnavailable,
    choose_device,
    device_view,
    execution_view,
)


def enabled() -> bool:
    return os.environ.get("MODSTORE_MAC_CONTROL_ENABLED") == "1"


def observe(db, client, now):
    observation = db.get(MacControlObservation, "para")
    if observation is None:
        observation = MacControlObservation(id="para")
        db.add(observation)
    observation.checked_at = now
    try:
        devices = client.devices()
        observation.payload_json = encoded([device_view(row, now) for row in devices])
        observation.observed_at, observation.error = now, ""
        db.commit()
        return devices
    except ParaUnavailable as exc:
        observation.error = str(exc)
        db.commit()
        return None


def reconcile(db, task, client):
    if not task.para_task_id:
        marker = f"[xcmax:{task.id}:{task.attempt_id}]"
        found = [t for t in client.tasks() if str(t.get("title", "")).startswith(marker)]
        if len(found) != 1:
            transition(
                db,
                task,
                "reconciling",
                "dispatch_outcome_unknown_no_automatic_resubmit",
            )
            return
        task.para_task_id = found[0]["id"]
        db.commit()
    raw = client.task(task.para_task_id)
    status = raw.get("status")
    state = {
        "completed": "execution_completed",
        "merged": "execution_completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(status, "running")
    if task.state == "cancel_requested" and state == "running":
        state = "cancel_requested"
    transition(db, task, state, snapshot=execution_view(raw))


def process(db, task, client, devices):
    if task.attempt_id or task.para_task_id:
        reconcile(db, task, client)
        return
    if task.state == "cancel_requested":
        transition(db, task, "cancelled", "cancelled_before_dispatch")
        return
    request = json.loads(task.request_json)
    from modstore_server.mac_control_facts import context_facts
    from modstore_server.mac_control_preflight import prepare_windows_probe

    prepare_windows_probe(db, client, devices, request)
    device, reason = choose_device(devices, request, time.time())
    if not device:
        transition(db, task, "waiting_device", reason)
        return
    # The DB claim is held throughout the bounded network call. Other tasks
    # targeting this device wait, including when the acceptance result is unknown.
    busy = (
        db.query(MacControlTask)
        .filter(
            MacControlTask.id != task.id,
            MacControlTask.device_id == device["id"],
            MacControlTask.state.notin_(TERMINAL),
        )
        .first()
    )
    if busy:
        transition(db, task, "waiting_device", "workspace_reserved")
        return
    facts = context_facts(db, request)
    task.device_id, task.attempt_id = device["id"], uuid.uuid4().hex
    transition(db, task, "dispatching")  # commit before network mutation
    marker = f"[xcmax:{task.id}:{task.attempt_id}]"
    context = {
        "task_id": task.id,
        "request": request,
        "facts": facts,
        "devices": [device_view(d, time.time()) for d in devices],
    }
    payload = {
        "device_id": task.device_id,
        "tool_name": request.get("tool", "codex"),
        "title": f"{marker} {request['message'][:120]}",
        "prompt": (
            "你是 XCMAX 的 Mac 主控执行助手。以下是已授权请求和来源上下文。"
            "仅在隔离工作区工作，先核实事实；执行到现有审批点，禁止绕过审批、"
            "自动合并、生产发布、对外发送消息或改变客户授权。"
            "结果须区分代码、测试、主线、发布和客户验收，缺少证据明确标记。\n" + encoded(context)
        ),
        "repo_url": os.environ.get("MODSTORE_PARA_REPO_URL", ""),
        "branch": request.get("source_sha") or "main",
        "max_attempts": 1,
        "report_only": request.get("mode", "review") == "review",
        "auto_merge": False,
    }
    if not payload["repo_url"]:
        transition(db, task, "failed", "repo_url_not_configured")
        return
    raw = client.submit(payload)
    if not raw.get("id"):
        raise ParaUnavailable("dispatch_response_missing_id")
    task.para_task_id = raw["id"]
    transition(db, task, "running", snapshot=execution_view(raw))


def run_mac_control_sync():
    if not enabled():
        return {"enabled": False}
    factory = get_session_factory()
    owner = uuid.uuid4().hex
    with factory() as db:
        if db.get(MacControlSyncLease, "dispatcher") is None:
            try:
                db.add(MacControlSyncLease(id="dispatcher", owner="", until=0))
                db.commit()
            except IntegrityError:
                db.rollback()
        claimed = (
            db.query(MacControlSyncLease)
            .filter(
                MacControlSyncLease.id == "dispatcher",
                MacControlSyncLease.until < time.time(),
            )
            .update({"owner": owner, "until": time.time() + 300})
        )
        db.commit()
        if not claimed:
            return {"enabled": True, "busy": True}
    try:
        return _sync(factory)
    finally:
        with factory() as db:
            db.query(MacControlSyncLease).filter_by(id="dispatcher", owner=owner).update(
                {"until": 0}
            )
            db.commit()


def _sync(factory):
    try:
        client = ParaClient()
    except ParaUnavailable as exc:
        with factory() as db:
            row = db.get(MacControlObservation, "para") or MacControlObservation(id="para")
            row.checked_at, row.error = time.time(), str(exc)
            db.add(row)
            db.commit()
        return {"enabled": True, "available": False}
    try:
        with factory() as db:
            devices = observe(db, client, time.time())
            if devices is None:
                return {"enabled": True, "available": False}
            ids = [
                r.id
                for r in db.query(MacControlTask)
                .filter(
                    MacControlTask.state.notin_(TERMINAL),
                )
                .order_by(MacControlTask.updated_at)
                .limit(5)
            ]
            for task_id in ids:
                task = acquire(db, task_id)
                if task is None:
                    continue
                try:
                    process(db, task, client, devices)
                except ParaUnavailable:
                    transition(
                        db,
                        task,
                        "reconciling" if task.attempt_id else "waiting_device",
                        "para_unreachable_or_result_pending",
                    )
                finally:
                    task.lease_until = 0
                    db.commit()
        return {"enabled": True, "available": True}
    finally:
        client.close()
