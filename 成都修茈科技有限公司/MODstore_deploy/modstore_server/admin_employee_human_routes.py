# mypy: disable-error-code="arg-type, union-attr"
"""Human-question bridge and employee scorecard routes."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from fastapi import Body, Depends, HTTPException, Query, Request

from modstore_server.api.deps import require_admin
from modstore_server.models import User

router = sys.modules["modstore_server.admin_employee_autonomy_api"].router


# ──────────────────────────────────────────────────────────────────────────────
# Phase-D：员工向老板的双向问答回路
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/questions")
def list_pending_human_questions(
    include_history: bool = Query(False, description="true 则包含 answered/expired 历史"),
    limit: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """老板查看员工问自己的问题（pending 或历史）。

    GET /api/admin/employee-autonomy/questions?include_history=false
    """
    from modstore_server.human_uncertainty_queue import list_pending_questions
    from modstore_server.retort_clarification_gate import (
        get_clarification,
        list_clarifications,
    )

    items = list_pending_questions(
        user_id=_admin_user.id,
        include_expired=include_history,
        limit=limit,
    )
    # Enrich Phase-D mirrored Retort items with structured questions / countdown.
    for item in items:
        if not isinstance(item, dict):
            continue
        ctx = item.get("context") if isinstance(item.get("context"), dict) else {}
        if str(ctx.get("kind") or "") != "retort_clarification":
            continue
        sid = str(ctx.get("session_id") or "").strip()
        detail = get_clarification(sid) if sid else None
        if not detail:
            continue
        item["questions"] = detail.get("questions") or []
        item["seconds_remaining"] = detail.get("seconds_remaining")
        item["urgency"] = detail.get("urgency")
        item["blocking_question_ids"] = detail.get("blocking_question_ids") or []
        item["source"] = "retort_clarification_gate"

    # Merge open Retort clarifications that may not yet have a Phase-D mirror.
    clar = list_clarifications(include_terminal=include_history, limit=limit)
    seen_sessions = {
        str((item.get("context") or {}).get("session_id") or "")
        for item in items
        if isinstance(item, dict)
    }
    for row in clar.get("items") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("session_id") or "")
        if not sid or sid in seen_sessions:
            continue
        if not include_history and row.get("status") != "open":
            continue
        questions = row.get("questions") if isinstance(row.get("questions"), list) else []
        primary = ""
        for q in questions:
            if isinstance(q, dict) and str(q.get("question") or "").strip():
                primary = str(q.get("question") or "").strip()
                break
        items.append(
            {
                "id": f"retort:{sid}",
                "user_id": _admin_user.id,
                "employee_id": "retort-clarification",
                "task": str(row.get("source") or "retort_clarification"),
                "question": primary or "Retort 需要确认战略意图",
                "questions": questions,
                "blocking_question_ids": row.get("blocking_question_ids") or [],
                "seconds_remaining": row.get("seconds_remaining"),
                "urgency": row.get("urgency") or "none",
                "context": {
                    "kind": "retort_clarification",
                    "session_id": sid,
                    "subject": row.get("subject"),
                    "change_request_id": row.get("change_request_id"),
                },
                "status": (
                    "pending" if row.get("status") == "open" else str(row.get("status") or "")
                ),
                "answer": "",
                "asked_at": row.get("created_at"),
                "answered_at": row.get("answered_at"),
                "expires_at": row.get("expires_at"),
                "source": "retort_clarification_gate",
            }
        )
        seen_sessions.add(sid)

    # Pending Retort first, then soon-to-expire.
    def _sort_key(item: Dict[str, Any]) -> tuple:
        is_retort = 0 if str(item.get("employee_id") or "") == "retort-clarification" else 1
        remaining = item.get("seconds_remaining")
        remaining_key = int(remaining) if isinstance(remaining, int) else 10**9
        return (is_retort, remaining_key, str(item.get("asked_at") or ""))

    items = sorted([item for item in items if isinstance(item, dict)], key=_sort_key)
    return {
        "items": items[:limit],
        "count": min(len(items), limit),
        "retort_open_count": int(clar.get("open_count") or 0),
        "retort_critical_count": int(clar.get("critical_count") or 0),
        "retort_healthy": bool(clar.get("healthy")),
    }


@router.post("/questions/{question_id}/answer")
def answer_human_question(
    question_id: str,
    body: Dict[str, Any] = Body(...),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """老板回答员工的问题。

    POST /api/admin/employee-autonomy/questions/{id}/answer
    body: {"answer": "去这么做..."}
    ``question_id`` 可为数字，或合成 id ``retort:<session_id>``。
    """
    from modstore_server.human_uncertainty_queue import answer_pending_question

    raw_answers = (body or {}).get("answers")
    answer = str((body or {}).get("answer") or "").strip()
    if not answer and not isinstance(raw_answers, (dict, list)):
        raise HTTPException(400, "answer or answers is required")

    payload_answers: Any = raw_answers if isinstance(raw_answers, (dict, list)) else answer
    raw_id = str(question_id or "").strip()
    if raw_id.startswith("retort:"):
        from modstore_server.retort_clarification_gate import answer_clarification

        session_id = raw_id.split(":", 1)[1].strip()
        out = answer_clarification(
            session_id,
            answers=payload_answers,
            answered_by=f"user:{_admin_user.id}",
        )
        if not out.get("ok"):
            raise HTTPException(409, str(out.get("error") or "answer failed"))
        return {
            "ok": True,
            "question_id": raw_id,
            "employee_id": "retort-clarification",
            "status": "answered",
            "retort_clarification": out,
        }

    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "invalid question_id") from exc

    # Phase-D mirrored Retort rows may carry structured answers.
    if isinstance(raw_answers, (dict, list)):
        from modstore_server.human_uncertainty_queue import list_pending_questions
        from modstore_server.retort_clarification_gate import answer_clarification

        matched = next(
            (
                item
                for item in list_pending_questions(
                    user_id=_admin_user.id, include_expired=True, limit=200
                )
                if int(item.get("id") or 0) == numeric_id
            ),
            None,
        )
        ctx = (matched or {}).get("context") if isinstance(matched, dict) else {}
        sid = str((ctx or {}).get("session_id") or "").strip()
        if sid and str((ctx or {}).get("kind") or "") == "retort_clarification":
            bridged = answer_clarification(
                sid,
                answers=payload_answers,
                answered_by=f"user:{_admin_user.id}",
            )
            if not bridged.get("ok"):
                raise HTTPException(409, str(bridged.get("error") or "answer failed"))
            # Also close the Phase-D row with a concise summary.
            summary = answer or json.dumps(raw_answers, ensure_ascii=False)[:1000]
            out = answer_pending_question(
                question_id=numeric_id,
                answer=summary,
                answered_by_user_id=_admin_user.id,
            )
            out["retort_clarification"] = bridged
            if not out.get("ok"):
                # Session already answered; treat as success if bridge ok.
                return {
                    "ok": True,
                    "question_id": numeric_id,
                    "employee_id": "retort-clarification",
                    "status": "answered",
                    "retort_clarification": bridged,
                }
            return out

    out = answer_pending_question(
        question_id=numeric_id,
        answer=answer or json.dumps(raw_answers, ensure_ascii=False)[:1000],
        answered_by_user_id=_admin_user.id,
    )
    if not out.get("ok"):
        raise HTTPException(409, str(out.get("reason") or "answer failed"))
    return out


@router.post("/internal/answer-latest")
def internal_answer_latest_question(
    request: Request,
    body: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """内部端点：老板在员工 IM 聊天页发的消息统一入站（回答问题 / 转新指令）。

    供 FHD 在「老板于员工 IM 聊天页直接回复」时经 ``X-Internal-Api-Key`` 调用，无需 question_id。
    POST body: ``{user_id, employee_id, answer}``。

    - 员工有 pending phase-D 问题 → 视为答案解阻塞（原有行为）；
    - 否则 → 视为老板新指令：入队 boss_im 任务 + 员工即时 ACK，执行完 IM 回音
      （见 ``boss_im_inbound.handle_boss_im_message``，不再静默丢消息）。
    """
    import os

    expected = (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    provided = (request.headers.get("X-Internal-Api-Key") or "").strip()
    if not expected or provided != expected:
        raise HTTPException(401, "unauthorized")
    try:
        user_id = int((body or {}).get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    employee_id = str((body or {}).get("employee_id") or "").strip()
    answer = str((body or {}).get("answer") or "").strip()
    if user_id <= 0 or not employee_id or not answer:
        raise HTTPException(400, "user_id/employee_id/answer required")
    from modstore_server.boss_im_inbound import handle_boss_im_message

    return handle_boss_im_message(user_id=user_id, employee_id=employee_id, text=answer)


@router.get("/questions/stats")
def human_questions_stats(
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """老板查看问题统计（pending/answered/expired 数量）。

    GET /api/admin/employee-autonomy/questions/stats
    """
    from sqlalchemy import func

    from modstore_server.models import PendingHumanQuestion, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(PendingHumanQuestion.status, func.count(PendingHumanQuestion.id))
            .filter(PendingHumanQuestion.user_id == _admin_user.id)
            .group_by(PendingHumanQuestion.status)
            .all()
        )
        counts = {status: cnt for status, cnt in rows}
    return {
        "pending": counts.get("pending", 0),
        "answered": counts.get("answered", 0),
        "expired": counts.get("expired", 0),
        "total": sum(counts.values()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 员工成绩单（10 项成熟度要求第 8 项 — 会承担结果）
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/scorecard/{employee_id}")
def get_employee_scorecard_api(
    employee_id: str,
    days: int = Query(7, ge=1, le=90, description="回看多少天"),
    human_friendly: bool = Query(False, description="true 则返回人话文本，否则返回 JSON"),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """单个员工的成绩单 — 任务数/成功率/失败原因/处理时长/最近任务。

    GET /api/admin/employee-autonomy/scorecard/{employee_id}?days=7&human_friendly=false
    """
    from modstore_server.employee_scorecard import (
        build_human_friendly_scorecard_text,
        get_employee_scorecard,
    )

    if human_friendly:
        return {
            "ok": True,
            "employee_id": employee_id,
            "text": build_human_friendly_scorecard_text(employee_id, days=days),
        }
    return get_employee_scorecard(employee_id, days=days)


@router.get("/scorecard")
def list_employee_scorecards_api(
    days: int = Query(7, ge=1, le=90),
    sort_by: str = Query(
        "total_tasks",
        description="total_tasks|success_rate|avg_duration_ms|failure_count|total_llm_tokens",
    ),
    top_n: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """全部员工成绩汇总（按 sort_by 排序）。

    GET /api/admin/employee-autonomy/scorecard?days=7&sort_by=total_tasks&top_n=50

    用于老板「一览谁在干活、谁在拖后腿」。
    """
    from modstore_server.employee_scorecard import list_all_employee_scorecards

    return list_all_employee_scorecards(days=days, sort_by=sort_by, top_n=top_n)
