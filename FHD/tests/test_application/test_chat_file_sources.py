"""Verified excerpts for new replies and the original authenticated history turn."""

import copy
import json

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_runtime.chat import runtime_chat_payload
from app.application.agent_runtime.chat_file_sources import released_chat_file_sources
from app.application.ai_chat.conversation_history import restore_runtime_history_files
from app.domain.conversation.client_metadata import strip_client_recall_binding
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    build_goal_contract,
    canonical_digest,
    goal_evidence_snapshot,
)
from app.domain.task_lifecycle.agent_runtime_results import withhold_runtime_output


@pytest.fixture(params=[False, True], ids=["uploaded", "recalled"])
def verified_document(request):
    scope = {
        "tenant_id": 17,
        "local_user_id": 11,
        "mod_id": "",
        "session_id": "scoped-chat",
        "conversation_id": "scoped-chat",
        "turn_id": "original-turn",
        "_conversation_revision": 2,
    }
    run = AgentRun("11", "Summarize the receipt", run_id="verified-run", status="completed")
    run.metadata.update(runtime_type="xiaox", runtime_context=scope)
    reference = "conversation-upload:" + "a" * 40 if request.param else "upload-scoped"
    passage = "[表格 1 行 3 列 2] Receipt confirmed"
    risky_passage = "Private path /Users/person/private.xlsx"
    preview = {"text": passage + "\n" + risky_passage, "coverage": {"truncated": False}}
    name, sha256 = "Receipt.docx", "b" * 64
    if request.param:
        entry = {"name": name, "upload_id": reference, "source_run_id": "historical-source"}
        contract = build_goal_contract(
            run,
            context_evidence=[
                {
                    "source": "conversation_uploads",
                    "entries": [entry],
                    "verified_read": {**entry, "sha256": sha256, **preview},
                }
            ],
        )
    else:
        contract = build_goal_contract(
            run,
            attachments=[
                {
                    "name": name,
                    "source": "owned_elt_upload",
                    "preview": preview,
                    "metadata": {"upload_id": reference, "sha256": sha256},
                }
            ],
        )
    result = {
        "ok": True,
        "run_id": run.run_id,
        "execution_state": "completed",
        "output": '{"confirmed":true}',
        "business_receipts": [],
    }
    snapshot = goal_evidence_snapshot(contract, [], result["output"])
    report = {
        "protocol": GOAL_PROTOCOL,
        "status": "verified",
        "accepted": True,
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": snapshot["response_digest"],
        "review": {
            "goals": [
                {
                    "goal_id": "receipt",
                    "source_id": "request",
                    "source": run.message,
                    "kind": "reply",
                    "status": "satisfied",
                    "evidence_ids": ["response"],
                    "reason": "Verified the original upload",
                    "file_basis": "complete",
                    "file_citations": [
                        {
                            "evidence_id": reference,
                            "source_excerpt": excerpt,
                            "response_excerpt": result["output"],
                        }
                        for excerpt in (passage, risky_passage)
                    ],
                }
            ],
            "violations": [],
            "uncovered_sources": [],
            "feedback_disposition": "none",
            "feedback": "The cited original receipt confirms the unchanged reply.",
        },
    }
    report["report_digest"] = canonical_digest(report)
    run.metadata.update(
        runtime_goal_contract=contract,
        runtime_goal_digest=contract["digest"],
        runtime_goal_verification=report,
    )
    return run, scope, result, [{"name": name, "excerpts": [passage]}]


def test_public_file_sources_use_the_verified_body_and_retract_on_failure(verified_document):
    run, scope, result, expected = verified_document
    assert released_chat_file_sources(run, result) == expected
    assert not released_chat_file_sources(run, {**result, "output": "Different body"})
    assert not released_chat_file_sources(run, {**result, "run_id": "Different run"})
    result["file_sources"] = expected
    reply = runtime_chat_payload(result, conversation_id=scope["session_id"])
    assert reply["data"]["file_sources"] == expected
    assert reply["response"] == result["output"] == '{"confirmed":true}'
    result["session_messages"] = []
    withhold_runtime_output(result, status="blocked", error="held")
    assert "file_sources" not in runtime_chat_payload(result)["data"]
    assert not released_chat_file_sources(run, result)


def test_history_sources_require_same_account_tenant_revision_and_reply(
    verified_document, monkeypatch
):
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    run, scope, result, expected = verified_document
    key = canonical_digest({"turn_id": scope["turn_id"], "owner": run.user_id})
    run.metadata["runtime_requests"] = {
        key: {"state": "returned", "turn_id": scope["turn_id"], "result": result},
    }
    repository = InMemoryAgentRunRepository()
    repository.save(run)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: repository,
    )
    binding = {
        "run_id": run.run_id,
        "turn_id": scope["turn_id"],
        "conversation_id": scope["session_id"],
    }
    forged_ui = {"fileSources": [{"name": "unrelated.docx", "excerpts": ["forged"]}]}
    row = {
        "role": "assistant",
        "content": result["output"],
        "metadata": json.dumps(
            {
                "business_harness": {**binding, "recall_bound": True},
                "ui": forged_ui,
                "summary": {**binding, "status": "completed", "action": "runtime_reply"},
            }
        ),
    }
    assert "fileSources" not in json.loads(strip_client_recall_binding(row["metadata"]))["ui"]
    for context, text, expected_sources in (
        (scope, result["output"], expected),
        ({**scope, "tenant_id": 18}, result["output"], None),
        ({**scope, "local_user_id": 12}, result["output"], None),
        ({**scope, "_conversation_revision": 3}, result["output"], None),
        (scope, "Replaced body", None),
    ):
        page = {"messages": [copy.deepcopy({**row, "content": text})]}
        restore_runtime_history_files(page, context)
        response = page["messages"][0]
        assert response["content"] == text
        assert json.loads(response["metadata"])["ui"].get("fileSources") == expected_sources
