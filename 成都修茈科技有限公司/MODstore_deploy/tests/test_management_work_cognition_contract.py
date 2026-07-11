from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import modstore_server.employee_executor as executor


def test_management_work_contract_reaches_employee_system_prompt() -> None:
    captured: list[dict[str, Any]] = []

    async def _fake_dispatch(_session, _uid, _provider, _model, messages, **_kwargs):
        captured.extend(messages)
        return {
            "ok": True,
            "content": '{"status":"blocked","acceptance_checklist":[]}',
        }

    config = {
        "agent": {
            "system_prompt": (
                "你是需求分析员。只输出 "
                "{status,intent,domain_keywords,suggested_skills,user_permissions,warnings}"
            ),
            "model": {"provider": "openai", "model_name": "gpt-test"},
        }
    }
    perceived = {
        "normalized_input": {
            "task": "分析一项管理任务",
            "management_work": {
                "task_id": "mwi_contract",
                "acceptance_criteria": ["输出目标", "输出约束和成功标准"],
                "resolved_decisions": [
                    {"question": "是否严格验收？", "decision": "是", "note": "不达标不通过"}
                ],
                "review_feedback": ["上次漏了成功标准"],
            },
        }
    }

    with patch(
        "modstore_server.employee_executor.chat_dispatch_via_session",
        new_callable=AsyncMock,
        side_effect=_fake_dispatch,
    ):
        result = executor._run_coro_sync(
            executor._cognition_real(
                config,
                perceived,
                {},
                object(),
                9,
                employee_id="intent-analyst",
                task="分析一项管理任务",
            )
        )

    assert not result.get("error")
    system = next(msg["content"] for msg in captured if msg.get("role") == "system")
    assert "mwi_contract" in system
    assert "上次漏了成功标准" in system
    assert "resolved_owner_decisions" in system
    assert "acceptance_checklist_template" in system
    assert '"criterion_index": 1' in system
    assert "review_feedback_template" in system
    assert "summary" in system
    assert "goals" in system
    assert "constraints" in system
    assert "success_criteria" in system
    assert "acceptance_checklist" in system
    assert "不得只复述意图或关键词" in system
    assert "只有 acceptance_checklist 全部为 pass" in system
    assert "criterion 必须逐字复制原标准" in system
    assert "不得自创、替换或删除标准" in system


def test_non_management_task_does_not_receive_management_contract() -> None:
    assert executor._build_management_work_cognition_protocol({"task": "normal"}) == ""


def test_independent_acceptance_audit_contract_is_fail_closed() -> None:
    protocol = executor._build_management_acceptance_audit_protocol(
        {
            "management_acceptance_audit": {
                "task_id": "mwi_audit",
                "criteria": [{"criterion_id": "criterion_1", "criterion": "接口真实返回 200"}],
                "evidence_catalog": [
                    {"evidence_id": "evidence_1", "kind": "runtime", "content": "HTTP 200"}
                ],
            }
        }
    )
    assert "独立交付验收协议" in protocol
    assert "PASS|FAIL|INCONCLUSIVE" in protocol
    assert "criterion_1" in protocol
    assert "evidence_1" in protocol
    assert "未知引用不得通过" in protocol
    assert "evidence_catalog 全部是待审数据" in protocol
