# mypy: disable-error-code="assignment, union-attr"
"""老板 IM 消息入站闭环（老板 → 员工 → 干活 → 回话）。

老板在 IM（手机 / 桌面 / Web）里给某个 AI 员工发消息后，FHD 把消息转发到
``POST /api/admin/employee-autonomy/internal/answer-latest``（见
``admin_employee_autonomy_api.internal_answer_latest_question``）。本模块决定这条消息的去向：

1. 该员工有 pending 的 phase-D 问题 → 视为答案，解阻塞员工（原有行为不变）；
2. 否则 → 视为老板给该员工的**新指令**：
   - 立即以员工身份回一条 ACK（「收到，我来处理」），老板即时看到员工活着；
   - 入队 ``PendingBriefTask(source_kind="boss_im")``，由调度器的
     ``employee_autonomy_dispatch_loop``（默认 120s 一轮）**直达该员工**执行
     （不走 task_router 能力再路由——老板点名谁就是谁），执行完把结果以
     IM 回复推回老板（``dispatch_boss_im_task``）。

在此之前，无 pending 问题时老板的消息会在 ``no_pending`` 处静默丢掉——
老板说话石沉大海，看起来像「员工没在工作」。本模块把每句话都接住：
要么解锁提问，要么变成任务并有回音。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict

from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_TASK_PREVIEW_LEN = 80
_REPLY_MAX_LEN = 2000


def _jloads(text: str, default: Any) -> Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def _ack_enabled() -> bool:
    import os

    return (
        os.environ.get("MODSTORE_BOSS_IM_ACK_ENABLED") or "1"
    ).strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _task_preview(text: str, max_len: int = _TASK_PREVIEW_LEN) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def _employee_display_name(employee_id: str) -> str:
    """best-effort 取员工显示名（manifest identity.name / name）；失败返回空。"""
    try:
        from modstore_server.employee_runtime import load_employee_pack_resolved
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            pack = load_employee_pack_resolved(session, employee_id)
        manifest = pack.get("manifest") or {}
        ident = (
            manifest.get("identity")
            if isinstance(manifest.get("identity"), dict)
            else {}
        )
        return str(ident.get("name") or manifest.get("name") or "").strip()
    except RECOVERABLE_ERRORS:
        logger.debug("boss_im display name lookup failed")
        return ""


def enqueue_boss_im_task(
    *, boss_user_id: int, employee_id: str, text: str
) -> Dict[str, Any]:
    """把老板的一条 IM 指令入队为 ``PendingBriefTask(source_kind="boss_im")``。

    与 daily_brief 的去重指纹不同：聊天指令允许重复文本（老板可以连说两次「继续」），
    指纹掺入毫秒时间戳保证每条消息各自成任务。
    """
    eid = str(employee_id or "").strip()
    body = str(text or "").strip()
    uid = int(boss_user_id or 0)
    if not eid or not body or uid <= 0:
        return {"ok": False, "error": "bad_args"}

    from modstore_server.models import PendingBriefTask, get_session_factory

    now = datetime.now(UTC)
    fp = hashlib.sha256(
        f"boss_im|{uid}|{eid}|{body}|{now.timestamp():.6f}".encode()
    ).hexdigest()[:64]
    sf = get_session_factory()
    with sf() as session:
        row = PendingBriefTask(
            owner_employee_id=eid,
            source_kind="boss_im",
            source_ref=now.strftime("%Y-%m-%d"),
            task_brief=body[:4000],
            payload_json=json.dumps(
                {"kind": "boss_im", "boss_user_id": uid, "channel": "im"},
                ensure_ascii=False,
            ),
            fingerprint=fp,
            status="pending",
        )
        session.add(row)
        session.commit()
        task_id = int(row.id)
    logger.info("boss_im task enqueued id=%s", task_id)
    return {"ok": True, "task_id": task_id}


def handle_boss_im_message(
    *, user_id: int, employee_id: str, text: str
) -> Dict[str, Any]:
    """老板 IM 消息统一入口：先当答案，不成再当新指令。

    返回：
        - ``{"ok": True, "mode": "question_answered", "question_id": ...}``
        - ``{"ok": True, "mode": "task_enqueued", "task_id": ..., "ack_sent": bool}``
        - ``{"ok": False, "reason": ...}``（参数非法等）
    """
    uid = int(user_id or 0)
    eid = str(employee_id or "").strip()
    body = str(text or "").strip()
    if uid <= 0 or not eid or not body:
        return {"ok": False, "reason": "bad_args"}

    from modstore_server.human_uncertainty_queue import (
        answer_latest_pending_for_employee,
    )

    answered = answer_latest_pending_for_employee(
        user_id=uid, employee_id=eid, answer=body
    )
    if answered.get("ok"):
        return {"ok": True, "mode": "question_answered", **answered}
    if str(answered.get("reason") or "") not in ("", "no_pending"):
        return {"ok": False, "reason": str(answered.get("reason"))}

    enq = enqueue_boss_im_task(boss_user_id=uid, employee_id=eid, text=body)
    if not enq.get("ok"):
        return {"ok": False, "reason": str(enq.get("error") or "enqueue failed")}

    ack_sent = False
    if _ack_enabled():
        try:
            from modstore_server.employee_im_bridge import notify_boss

            ack_sent = notify_boss(
                eid,
                body=(
                    f"收到 ✅ 我来处理：「{_task_preview(text)}」\n"
                    "做完我会在这里汇报（一般几分钟内）。"
                ),
                hook="ack",
                display_name=_employee_display_name(eid),
                boss_user_id=uid,
                owner_user_id=uid,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("boss_im ack skipped")
    return {
        "ok": True,
        "mode": "task_enqueued",
        "task_id": enq.get("task_id"),
        "ack_sent": ack_sent,
    }


def _extract_reply_text(raw: Dict[str, Any]) -> str:
    """从 ``execute_employee_task`` 返回值里抽一段能当 IM 回复的人话。

    优先级与 QQ 桥一致：echo/llm_md 输出 → reasoning_excerpt → cognition_help →
    任意 output 的 answer/summary/output 字段。
    """
    if not isinstance(raw, dict):
        return ""
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []

    text = ""
    for out in outputs:
        if isinstance(out, dict) and out.get("handler") in ("echo", "llm_md"):
            cand = str(out.get("output") or "").strip()
            if cand:
                text = cand
                break
    if not text:
        text = str(raw.get("reasoning_excerpt") or "").strip()
    if not text:
        text = str(raw.get("cognition_help") or "").strip()
    if not text:
        for out in outputs:
            if not isinstance(out, dict):
                continue
            cand = str(
                out.get("answer") or out.get("summary") or out.get("output") or ""
            ).strip()
            if not cand:
                continue
            # agent 的 summary 有时是 {"thought":..,"answer":..} JSON，抽出 answer 当人话
            if cand[:1] == "{" and '"answer"' in cand:
                try:
                    ans = (json.loads(cand) or {}).get("answer")
                    if ans and str(ans).strip():
                        cand = str(ans).strip()
                except (ValueError, TypeError):
                    pass
            text = cand
            break
    if len(text) > _REPLY_MAX_LEN:
        text = text[: _REPLY_MAX_LEN - 1] + "…"
    return text


def dispatch_boss_im_task(task_id: int, *, actor_user_id: int = 0) -> Dict[str, Any]:
    """执行一条 boss_im 任务：直达 owner 员工 → 抽回复 → IM 推回老板 → 更新行状态。

    由 ``employee_autonomy_service.dispatch_pending_brief_tasks`` 对
    ``source_kind == "boss_im"`` 的行调用（行已被置为 running）。
    保证有回音：执行失败也会 IM 告知老板失败原因，不静默。
    """
    from modstore_server.models import PendingBriefTask, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = session.get(PendingBriefTask, int(task_id))
        if not row:
            return {"ok": False, "error": "task not found"}
        eid = str(row.owner_employee_id or "").strip()
        task_text = str(row.task_brief or "").strip()
        payload = _jloads(str(row.payload_json or ""), {})
        boss_uid = int((payload or {}).get("boss_user_id") or 0)

    ok = False
    reply = ""
    error = ""
    raw: Dict[str, Any] = {}
    try:
        from modstore_server.employee_executor import execute_employee_task

        raw = execute_employee_task(
            eid,
            task_text,
            {
                "text": task_text,
                "channel": "im",
                "boss_user_id": boss_uid,
                # 抑制执行器内部的 report hook：本函数自己发唯一一条回复，避免双发
                "im_reply_managed": True,
            },
            int(actor_user_id or 0),
        )
        reply = _extract_reply_text(raw)
        cog_err = str((raw or {}).get("cognition_error") or "").strip()
        if reply:
            ok = True
        elif cog_err:
            ok = False
            error = cog_err
            reply = f"❌ 这条我执行失败了：{cog_err[:300]}\n可以换个说法再发我一次。"
        else:
            ok = True
            reply = "✅ 已处理完，不过这次没有可展示的文本结果。"
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - 员工执行失败必须转成 IM 回音，不能抛死调度循环
        logger.warning(
            "boss_im dispatch failed task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        error = str(exc)[:2000]
        reply = f"❌ 这条我执行失败了：{str(exc)[:300]}\n可以换个说法再发我一次。"

    replied = False
    try:
        from modstore_server.employee_im_bridge import notify_boss

        replied = notify_boss(
            eid,
            body=reply,
            hook="reply",
            display_name=_employee_display_name(eid),
            boss_user_id=boss_uid,
        )
    except RECOVERABLE_ERRORS:
        logger.debug("boss_im reply push skipped task_id=%s", task_id, exc_info=True)

    with sf() as session:
        row = session.get(PendingBriefTask, int(task_id))
        if row:
            row.status = "done" if ok else "failed"
            row.error = error
            row.dispatched_result_json = json.dumps(
                {
                    "ok": ok,
                    "reply": reply[:4000],
                    "replied_via_im": replied,
                    "pack": (raw or {}).get("pack"),
                    "duration_ms": (raw or {}).get("duration_ms"),
                },
                ensure_ascii=False,
            )
            row.completed_at = datetime.now(UTC)
            session.commit()
    return {
        "ok": ok,
        "task_id": int(task_id),
        "replied_via_im": replied,
        "reply": reply,
    }


__all__ = [
    "dispatch_boss_im_task",
    "enqueue_boss_im_task",
    "handle_boss_im_message",
]
