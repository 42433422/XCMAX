"""Phase-D：员工向老板的双向问答回路。

Phase-C 遗留：enqueue_uncertain_item 单向写 jsonl 文件，员工不等回答继续干。
Phase-D 升级：ask_human_blocking 写 DB + 推送 + 阻塞轮询等回答 + 超时降级。

真实员工类比：员工走到老板工位问问题，站着等回答，超时了才自己走开继续干。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def queue_path() -> Path:
    raw = (os.environ.get("MODSTORE_AUTONOMOUS_UNCERTAINTY_QUEUE") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / "autonomous_uncertainty_queue.jsonl"


def _fingerprint(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _recent_fingerprints(limit: int = 300) -> set[str]:
    path = queue_path()
    if not path.exists():
        return set()
    rows: List[str] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(line)
    except OSError:
        return set()
    out = set()
    for line in rows[-limit:]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        fp = str(data.get("fingerprint") or "").strip()
        if fp:
            out.add(fp)
    return out


def enqueue_uncertain_item(
    *,
    context: Dict[str, Any],
    decision: Dict[str, Any],
    reason: str,
    source: str = "self_maintenance_loop",
) -> Dict[str, Any]:
    """Append a deduplicated uncertainty item (Phase-C 遗留，向后兼容).

    Phase-D 推荐改用 ask_human_blocking() 实现双向问答。
    """

    if (
        os.environ.get("MODSTORE_AUTONOMOUS_UNCERTAINTY_QUEUE_ENABLED") or "1"
    ).strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {"queued": False, "reason": "disabled"}
    item = {
        "context": context,
        "decision": decision,
        "reason": reason,
        "schema_version": 1,
        "source": source,
        "ts": time.time(),
    }
    item["fingerprint"] = _fingerprint(
        {
            "branch": context.get("branch"),
            "reason": reason,
            "run_id": context.get("run_id"),
            "task_id": context.get("para_task_id"),
        }
    )
    if item["fingerprint"] in _recent_fingerprints():
        return {"fingerprint": item["fingerprint"], "queued": False, "reason": "duplicate"}
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return {"fingerprint": item["fingerprint"], "path": str(path), "queued": True}


# ──────────────────────────────────────────────────────────────────────────────
# Phase-D：双向问答回路
# ──────────────────────────────────────────────────────────────────────────────


def _enabled() -> bool:
    """Phase-D 双向问答是否启用。环境变量 MODSTORE_ASK_HUMAN_BLOCKING_ENABLED。"""
    return (os.environ.get("MODSTORE_ASK_HUMAN_BLOCKING_ENABLED") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _default_timeout_seconds() -> int:
    """默认阻塞等回答的超时秒数。环境变量 MODSTORE_ASK_HUMAN_TIMEOUT_SECONDS。"""
    try:
        return int(os.environ.get("MODSTORE_ASK_HUMAN_TIMEOUT_SECONDS") or "300")
    except ValueError:
        return 300


def _default_poll_interval_seconds() -> int:
    """轮询 DB 检查回答的间隔秒数。环境变量 MODSTORE_ASK_HUMAN_POLL_INTERVAL。"""
    try:
        return int(os.environ.get("MODSTORE_ASK_HUMAN_POLL_INTERVAL") or "5")
    except ValueError:
        return 5


def ask_human_blocking(
    *,
    employee_id: str,
    user_id: int,
    question: str,
    task: str = "",
    context: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[int] = None,
    poll_interval_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """员工向老板提问并阻塞等回答（Phase-D 核心）。

    流程：
    1. 写 PendingHumanQuestion 行（status=pending, expires_at=now+timeout）
    2. 推送站内通知给老板
    3. 轮询 DB 检查 status 是否变成 answered
    4. 超时则标记 expired，返回 expired 状态

    返回:
        - {"status": "answered", "answer": "...", "question_id": N}
        - {"status": "expired", "reason": "timeout", "question_id": N}
        - {"status": "disabled", "reason": "Phase-D disabled by env"}
        - {"status": "duplicate", "reason": "same question pending", "question_id": N}

    真实员工类比：走到老板工位问问题，站着等回答，超时了才自己走开。
    """
    if not _enabled():
        return {"status": "disabled", "reason": "Phase-D disabled by env"}

    # 延迟 import 避免循环依赖
    from modstore_server.models import PendingHumanQuestion, get_session_factory

    timeout = timeout_seconds if timeout_seconds is not None else _default_timeout_seconds()
    poll = poll_interval_seconds if poll_interval_seconds is not None else _default_poll_interval_seconds()
    poll = max(1, poll)

    fp = _fingerprint(
        {
            "employee_id": employee_id,
            "task": task,
            "question": question,
            "user_id": user_id,
        }
    )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=timeout)

    sf = get_session_factory()
    with sf() as session:
        # 去重：同 fingerprint 已有 pending 问题则复用
        existing = (
            session.query(PendingHumanQuestion)
            .filter(PendingHumanQuestion.fingerprint == fp)
            .filter(PendingHumanQuestion.status == "pending")
            .first()
        )
        if existing:
            question_id = existing.id
            # 等回答时复用 existing 的 expires_at（取较晚的）
            if existing.expires_at and existing.expires_at > expires:
                expires = existing.expires_at
        else:
            row = PendingHumanQuestion(
                user_id=user_id,
                employee_id=employee_id,
                task=task,
                question=question,
                context_json=json.dumps(context or {}, ensure_ascii=False, default=str),
                status="pending",
                asked_at=now,
                expires_at=expires,
                fingerprint=fp,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            question_id = row.id

        # 推送通知给老板（延迟 import 避免循环依赖）
        try:
            from modstore_server.notification_service import notify_human_question

            notify_human_question(
                user_id=user_id,
                question_id=question_id,
                employee_id=employee_id,
                question=question,
                task=task,
            )
        except Exception as exc:  # 推送失败不阻塞问答
            print(f"[ask_human_blocking] notify failed: {exc}", flush=True)

    # 轮询等回答
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        with sf() as session:
            row = (
                session.query(PendingHumanQuestion)
                .filter(PendingHumanQuestion.id == question_id)
                .first()
            )
            if not row:
                return {"status": "error", "reason": "question row vanished", "question_id": question_id}
            if row.status == "answered":
                return {
                    "status": "answered",
                    "answer": row.answer or "",
                    "question_id": question_id,
                    "answered_at": row.answered_at.isoformat() if row.answered_at else None,
                }

    # 超时降级
    with sf() as session:
        row = (
            session.query(PendingHumanQuestion)
            .filter(PendingHumanQuestion.id == question_id)
            .first()
        )
        if row and row.status == "pending":
            row.status = "expired"
            session.commit()
    return {
        "status": "expired",
        "reason": f"timeout after {timeout}s",
        "question_id": question_id,
    }


def list_pending_questions(
    *,
    user_id: Optional[int] = None,
    include_expired: bool = False,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列出 pending（或含 expired/answered）的问题。供 API 端点调用。"""
    from modstore_server.models import PendingHumanQuestion, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        q = session.query(PendingHumanQuestion)
        if user_id is not None:
            q = q.filter(PendingHumanQuestion.user_id == user_id)
        if not include_expired:
            q = q.filter(PendingHumanQuestion.status == "pending")
        else:
            q = q.order_by(PendingHumanQuestion.created_at.desc())
        q = q.order_by(PendingHumanQuestion.asked_at.desc()).limit(limit)
        rows = q.all()
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "employee_id": r.employee_id,
                "task": r.task,
                "question": r.question,
                "context": _safe_json(r.context_json),
                "status": r.status,
                "answer": r.answer,
                "asked_at": r.asked_at.isoformat() if r.asked_at else None,
                "answered_at": r.answered_at.isoformat() if r.answered_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in rows
        ]


def answer_pending_question(
    *,
    question_id: int,
    answer: str,
    answered_by_user_id: int,
) -> Dict[str, Any]:
    """老板回答 pending 问题。供 API 端点调用。"""
    from modstore_server.models import PendingHumanQuestion, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(PendingHumanQuestion)
            .filter(PendingHumanQuestion.id == question_id)
            .first()
        )
        if not row:
            return {"ok": False, "reason": "not_found"}
        if row.status != "pending":
            return {"ok": False, "reason": f"already_{row.status}", "current_status": row.status}
        row.status = "answered"
        row.answer = answer
        row.answered_by_user_id = answered_by_user_id
        row.answered_at = datetime.now(timezone.utc)
        session.commit()
        return {
            "ok": True,
            "question_id": question_id,
            "employee_id": row.employee_id,
            "status": "answered",
        }


def _safe_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text) if text else {}
    except Exception:
        return {}


__all__ = [
    "enqueue_uncertain_item",
    "queue_path",
    "ask_human_blocking",
    "list_pending_questions",
    "answer_pending_question",
]
