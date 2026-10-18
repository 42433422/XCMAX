"""终极员工分诊介入：可查看、可改分类/改派；无介入自动继续；账号类不误进修代码。"""

from __future__ import annotations

from modstore_server.customer_ticket_triage import (
    CODE_FIX_TOOLS,
    ULTIMATE_TOOLS,
    apply_para_triage,
    apply_triage_intervention,
    build_triage_snapshot,
    guard_code_fix_tool,
    stamp_intake_triage,
)
from modstore_server.duty_workforce_contracts import enrich_customer_ticket_publish_payload


def test_account_intent_needs_ultimate_and_blocks_code_fix():
    snap = build_triage_snapshot({"intent": "account_support", "ticket_id": 40})
    assert snap["triage_lane"] == "ultimate_review"
    assert snap["allow_code_fix"] is False
    assert snap["needs_ultimate_review"] is True
    assert "codex" in snap["code_fix_tools_blocked"]


def test_product_issue_allows_code_fix_unless_intervened():
    snap = build_triage_snapshot({"intent": "product_issue"})
    assert snap["triage_lane"] == "product_defect"
    assert snap["allow_code_fix"] is True
    blocked = apply_triage_intervention(
        {"intent": "product_issue"},
        {
            "intent": "account_support",
            "allow_code_fix": False,
            "by": "grok_bot",
            "note": "实为账号",
        },
    )
    assert blocked["intent"] == "account_support"
    assert blocked["triage"]["allow_code_fix"] is False
    assert blocked["triage_intervention"]["by"] == "grok_bot"


def test_intervention_can_reassign_tool_and_device():
    out = apply_triage_intervention(
        {"intent": "general", "ticket_id": 1},
        {"tool_name": "dolt", "device_id": "dolt-cloud", "note": "改派确认"},
    )
    assert out["tool_name"] == "dolt" and out["device_id"] == "dolt-cloud"
    assert out["triage"]["intervention_applied"] is True


def test_no_intervention_auto_continues_without_drop():
    out = apply_triage_intervention(
        {"intent": "account_support", "ticket_id": 7, "summary": "余额"}
    )
    assert out["ticket_id"] == 7 and out["summary"] == "余额"
    assert out["triage"]["intervention_applied"] is False
    assert out["triage_lane"] == "ultimate_review"


def test_guard_rewrites_codex_to_ultimate_not_silent_drop():
    tool, reason = guard_code_fix_tool("codex", allow=False, fallback_ultimate="dolt")
    assert tool == "dolt" and "triage_blocked_code_fix" in reason
    tool2, reason2 = guard_code_fix_tool("grok_bot", allow=False)
    assert tool2 == "grok_bot" and reason2 == ""
    assert ULTIMATE_TOOLS and CODE_FIX_TOOLS.isdisjoint(ULTIMATE_TOOLS)


def test_para_triage_blocks_code_tool_on_account_ticket():
    out = apply_para_triage(
        {
            "event_type": "ops.intake.customer_ticket",
            "intent": "account_support",
            "tool_name": "codex",
            "device_id": "mac-local",
        }
    )
    assert out["tool_name"] == "grok_bot"
    assert out["triage"]["allow_code_fix"] is False
    assert "guard" in out["triage"]
    assert out.get("report_only") is True


def test_enrich_publish_stamps_triage_snapshot():
    body = enrich_customer_ticket_publish_payload(
        {
            "ticket_id": 40,
            "ticket_no": "CS1",
            "user_id": 1,
            "summary": "账号余额不对请提交工单",
            "intent": "account_support",
            "source": "customer_ticket",
        }
    )
    assert body["triage"]["triage_lane"] == "ultimate_review"
    assert body["triage"]["allow_code_fix"] is False
    assert body["requests"] and body["ticket"]
    # 介入写入后 enrich 再应用
    body2 = stamp_intake_triage(
        {
            **body,
            "triage_intervention": {
                "intent": "product_issue",
                "allow_code_fix": True,
                "by": "dolt",
            },
        }
    )
    assert body2["intent"] == "product_issue"
    assert body2["triage"]["allow_code_fix"] is True


def test_para_triage_reads_nested_incident_intent_and_keeps_unknown():
    nested = {
        "event_type": "ops.intake.customer_ticket",
        "incident": {"intent": "product_issue", "ticket_id": 40},
        "tool_name": "codex",
    }
    out = apply_para_triage(nested)
    assert out["tool_name"] == "codex" and out["triage"]["allow_code_fix"] is True
    unknown = {"event_type": "ops.intake.customer_ticket", "tool_name": "codex"}
    assert apply_para_triage(unknown)["tool_name"] == "codex"
    acct = apply_para_triage({**nested, "incident": {"intent": "account_support"}})
    assert acct["tool_name"] == "grok_bot"
