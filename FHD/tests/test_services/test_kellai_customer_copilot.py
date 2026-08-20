# mypy: disable-error-code="index"
from __future__ import annotations

import json

import pytest

from app.services import kellai_customer_copilot as copilot


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path):
    path = tmp_path / "kellai-copilot-drafts.json"
    monkeypatch.setattr(copilot, "_store_path", lambda: path)
    return path


@pytest.mark.asyncio
async def test_generate_draft_persists_only_derived_output_and_audits(
    monkeypatch: pytest.MonkeyPatch,
    isolated_store,
) -> None:
    from app.infrastructure.llm import invoke

    async def fake_completion(*_args, **_kwargs):
        return {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "客户询问交期，尚未获得确认。",
                                "intent": "交期咨询",
                                "risk_level": "high",
                                "next_action": "先核实真实交期",
                                "reply_draft": "您好，我正在核实交付计划，确认后回复您。",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
        }

    audits: list[tuple[str, dict]] = []
    monkeypatch.setattr(invoke, "chat_completion_openai_format", fake_completion)
    monkeypatch.setattr(
        copilot,
        "_audit",
        lambda *, actor, action, payload: audits.append((action, payload)),
    )

    draft = await copilot.generate_draft(
        customer_id=7,
        customer={"stage_label": "意向客户", "channel_sources": ["wework"]},
        messages=[
            {
                "id": "m-sensitive",
                "direction": "inbound",
                "content": "这是只应发送给模型、不能写入草稿存储的原始客户消息",
                "created_at": "2026-07-15T10:00:00Z",
            }
        ],
        actor=8,
    )

    assert draft["status"] == "pending_approval"
    assert draft["risk_level"] == "high"
    assert draft["model"] == "test-model"
    persisted = isolated_store.read_text(encoding="utf-8")
    assert "不能写入草稿存储的原始客户消息" not in persisted
    assert isolated_store.stat().st_mode & 0o777 == 0o600
    assert audits == [
        (
            "kellai.copilot_draft.generated",
            {
                "draft_id": draft["draft_id"],
                "customer_id": 7,
                "risk_level": "high",
                "status": "pending_approval",
                "evidence_count": 1,
            },
        )
    ]


@pytest.mark.asyncio
async def test_draft_requires_real_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(copilot.KellaiCopilotError, match="真实会话"):
        await copilot.generate_draft(
            customer_id=7,
            customer={},
            messages=[],
        )


@pytest.mark.asyncio
async def test_approval_is_terminal_and_latest_draft_survives_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.llm import invoke

    async def fake_completion(*_args, **_kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"摘要","intent":"咨询","risk_level":"low",'
                            '"next_action":"核实","reply_draft":"草稿"}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(invoke, "chat_completion_openai_format", fake_completion)
    monkeypatch.setattr(copilot, "_audit", lambda **_kwargs: None)
    generated = await copilot.generate_draft(
        customer_id=9,
        customer={},
        messages=[{"id": "m1", "direction": "inbound", "content": "你好"}],
    )

    approved = copilot.decide_draft(
        draft_id=generated["draft_id"],
        decision="approve",
        actor=3,
    )
    assert approved["status"] == "approved_for_manual_send"
    assert copilot.latest_draft(9)["draft_id"] == generated["draft_id"]

    with pytest.raises(copilot.KellaiCopilotError, match="不能重复变更"):
        copilot.decide_draft(
            draft_id=generated["draft_id"],
            decision="reject",
            actor=3,
        )


@pytest.mark.asyncio
async def test_follow_up_task_is_idempotent_audited_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.llm import invoke

    prompts: list[list[dict]] = []

    async def fake_completion(messages, **_kwargs):
        prompts.append(messages)
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"摘要","intent":"交期确认","risk_level":"high",'
                            '"next_action":"在八小时内核实交期并回访",'
                            '"reply_draft":"我先核实交期。"}'
                        )
                    }
                }
            ]
        }

    audits: list[tuple[str, dict]] = []
    monkeypatch.setattr(invoke, "chat_completion_openai_format", fake_completion)
    monkeypatch.setattr(
        copilot,
        "_audit",
        lambda *, actor, action, payload: audits.append((action, payload)),
    )
    draft = await copilot.generate_draft(
        customer_id=11,
        customer={},
        messages=[{"id": "m1", "direction": "inbound", "content": "交期是什么时候"}],
        actor=5,
    )
    audits.clear()

    first = copilot.create_follow_up_task(draft_id=draft["draft_id"], actor=5)
    retried = copilot.create_follow_up_task(draft_id=draft["draft_id"], actor=5)

    assert first["task_id"] == retried["task_id"]
    assert first["status"] == "open"
    assert first["priority"] == "high"
    assert first["description"] == "在八小时内核实交期并回访"
    assert [task["task_id"] for task in copilot.list_follow_up_tasks(11)] == [first["task_id"]]
    assert [action for action, _payload in audits] == ["kellai.follow_up_task.created"]

    completed = copilot.decide_follow_up_task(
        task_id=first["task_id"],
        decision="complete",
        actor=5,
        outcome_result="success",
    )
    repeated = copilot.decide_follow_up_task(
        task_id=first["task_id"],
        decision="complete",
        actor=5,
        outcome_result="success",
    )
    assert completed["status"] == "completed"
    assert repeated["completed_at"] == completed["completed_at"]
    assert [action for action, _payload in audits] == [
        "kellai.follow_up_task.created",
        "kellai.follow_up_task.completed",
    ]

    with pytest.raises(copilot.KellaiCopilotError, match="已经结束"):
        copilot.decide_follow_up_task(
            task_id=first["task_id"],
            decision="cancel",
            actor=5,
        )

    await copilot.generate_draft(
        customer_id=11,
        customer={},
        messages=[{"id": "m2", "direction": "inbound", "content": "还有进展吗"}],
        actor=5,
    )
    next_context = json.loads(prompts[-1][1]["content"])["customer_context"]
    assert next_context["recent_follow_up_outcomes"] == [
        {
            "previous_action": "在八小时内核实交期并回访",
            "outcome": "success",
        }
    ]
    assert copilot.follow_up_metrics(11) == {
        "total": 1,
        "open": 0,
        "completed": 1,
        "failed": 0,
        "cancelled": 0,
        "outcomes": {"success": 1, "no_result": 0, "failed": 0},
        "success_rate": 1.0,
    }


def test_purge_removes_all_derived_customer_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    isolated_store,
) -> None:
    isolated_store.write_text(
        json.dumps(
            {
                "version": 2,
                "drafts": {"draft-1": {"draft_id": "draft-1", "customer_id": 7}},
                "follow_up_tasks": {"task-1": {"task_id": "task-1", "customer_id": 7}},
            }
        ),
        encoding="utf-8",
    )
    audits: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        copilot,
        "_audit",
        lambda *, actor, action, payload: audits.append((action, payload)),
    )

    result = copilot.purge_all(actor=8)

    assert result == {"drafts_deleted": 1, "tasks_deleted": 1}
    assert not isolated_store.exists()
    assert copilot.latest_draft(7) is None
    assert copilot.list_follow_up_tasks(7) == []
    assert audits == [
        (
            "kellai.customer_artifacts.purged",
            {"drafts_deleted": 1, "tasks_deleted": 1},
        )
    ]
