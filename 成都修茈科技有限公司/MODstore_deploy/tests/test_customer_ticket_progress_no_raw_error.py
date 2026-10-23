"""#2389：员工进度回写客户工单时，报错原文/路径/工具名不进客户消息，只留内部审计与动作。"""

from __future__ import annotations

import json
import re
import uuid

import pytest

from tests.test_customer_service_api import _make_user

pytest.importorskip("fastapi")

LEAK = "Cursor Agent 失败: Command failed: git clone --depth 1 https://github.com/o/r.git /Users/a/XCMAX-runtime"
LEAK_RE = re.compile(r"/Users/|git clone|Cursor Agent|Command failed|github\.com|Traceback")


def _rows(ok: bool) -> list[dict]:
    out = {
        "cause": LEAK,
        "summary": f"已改 /Users/a/x.py {LEAK}",
        "error": LEAK,
        "output_error": LEAK,
    }
    rows = [
        {"role": r, "ok": ok, "status": "success" if ok else "handler_failed"}
        for r in ("scout", "fix", "verify")
    ]
    rows[0]["handler_outputs"] = {"outputs": [out], "poll_error": f"Traceback: {LEAK}"}
    return rows


@pytest.mark.parametrize("team_ok", [False, True])
def test_progress_never_writes_raw_error_into_customer_message(client, team_ok):
    from modstore_server import models_cs as cs
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.models import get_session_factory

    owner = _make_user(f"cs_2389_{uuid.uuid4().hex[:8]}")
    with get_session_factory()() as db:
        session = cs.CustomerServiceSession(user_id=owner.id)
        db.add(session)
        db.flush()
        ticket = cs.CustomerServiceTicket(
            user_id=owner.id, session_id=session.id, ticket_no=f"T2389-{uuid.uuid4().hex}",
            intent="product_issue", status="processing", summary="更新日志看不到 1.0.0.6",
        )  # fmt: skip
        db.add(ticket)
        db.flush()
        out = apply_customer_ticket_incident_progress(
            db, ticket_id=ticket.id, event_id=2389, team_ok=team_ok, team_rows=_rows(team_ok)
        )
        db.commit()
        assert out["ok"] is True
        msg = db.get(cs.CustomerServiceMessage, out["message_id"])
        assert not LEAK_RE.search(msg.content) and not LEAK_RE.search(msg.payload_json)
        assert "排查" in msg.content and "下一步" in msg.content
        assert "内部问题" in msg.content and out["team_ok"] is False
        db.refresh(ticket)
        reports = json.loads(ticket.evidence_json)["employee_reports"]
        assert reports and not LEAK_RE.search(json.dumps(reports, ensure_ascii=False))
        # 内部明细仍完整留给管理端排查：动作结果与审计 detail 里有报错原文。
        action = db.get(cs.CustomerServiceAction, out["action_id"])
        assert "git clone" in json.loads(action.result_json)["progress"]
        audit = (
            db.query(cs.CustomerServiceAuditLog)
            .filter_by(ticket_id=ticket.id, event_type="employee_progress")
            .one()
        )
        assert "git clone" in json.loads(audit.detail_json)["progress"]
