"""Scoped conversation recall of complete, previously selected attachment groups."""

from __future__ import annotations

import io
from datetime import datetime
from zipfile import ZipFile

import pytest
from docx import Document

from app.application.agent_orchestrator import (
    get_agent_run_repository,
    set_agent_run_repository_for_tests,
)
from app.application.agent_orchestrator import attachment_inputs as inputs
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_runtime import goal_admission
from app.application.agent_runtime.conversation_attachments import (
    conversation_upload_context,
    recalled_attachment_view,
)
from app.application.agent_runtime.xiaox_runtime import _input_text
from app.application.ai_chat.chat_evidence import _prepare_history
from app.application.ai_chat.conversation_history import persist_chat_turn
from app.application.elt.service_uploads import UploadServiceMixin
from app.application.task_conversation_store import TaskConversationStore
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.domain.shared_services.conversation_service import ConversationService
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    goal_evidence_snapshot,
    runtime_file_evidence,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBinding
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def selection(trusted_actor, tmp_path, monkeypatch):
    actor = trusted_actor()
    store = TaskConversationStore()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    prior_repository = get_agent_run_repository()
    set_agent_run_repository_for_tests(repository)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr(goal_admission, "_context_evidence", lambda *_: [])
    context = {
        **actor.context,
        "local_user_id": actor.user_id,
        "session_id": "attachment-group",
        "conversation_id": "attachment-group",
        "_conversation_revision": 0,
    }

    def upload(name, raw):
        with tenant_scope(actor.tenant_id), get_db() as db:
            receipt = UploadServiceMixin().save_upload(
                db,
                owner_user_id=actor.user_id,
                file_name=name,
                content_type=None,
                stream=io.BytesIO(raw),
            )
        return receipt["upload_id"]

    def current(turn, **extra):
        run = AgentRun(
            str(actor.user_id), f"synthetic question {turn}", status="completed"
        )
        run.metadata.update(
            runtime_type="xiaox", runtime_context={**context, "turn_id": turn, **extra}
        )
        return run

    def freeze(run, **source):
        goal = build_goal_contract(run, **source)
        run.metadata.update(
            runtime_goal_contract=goal, runtime_goal_digest=goal["digest"]
        )
        repository.save(run)

    def record(run):
        with tenant_scope(actor.tenant_id):
            ack = persist_chat_turn(
                str(actor.user_id),
                run.message,
                run.metadata["runtime_context"],
                {
                    "success": True,
                    "response": "synthetic delivered answer",
                    "run_id": run.run_id,
                },
                store=ConversationService(),
            )
            assert ack["status"] == "saved"

    def next_turn():
        with tenant_scope(actor.tenant_id):
            history = _prepare_history(
                store, context, context["session_id"], actor.user_id
            )
        return current("follow-up", **history)

    try:
        yield actor, context, upload, current, freeze, record, next_turn
    finally:
        set_agent_run_repository_for_tests(prior_repository)


def _sample_document():
    out = io.BytesIO()
    document = Document()
    document.add_paragraph("ALPHA-VERIFIED-BODY")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "ALPHA-TABLE"
    document.save(out)
    return out.getvalue()


@pytest.mark.parametrize("invalidate", ["hash", "expiry"])
def test_explicit_previous_sql_selection_is_reopened_and_exposed_as_one_group(
    selection, trusted_actor, invalidate
):
    actor, context, upload, current, freeze, record, next_turn = selection
    raw = _sample_document()
    ids = [
        upload("first.docx", raw),
        upload("second.csv", b"label,value\nBETA-VERIFIED-BODY,4\n"),
    ]
    original = current("original")
    artifacts = inputs.resolve_attachment_inputs(
        {**context, "attachment_upload_ids": ids}
    )
    freeze(original, attachments=artifacts)
    record(original)
    run = next_turn()
    goal = goal_admission.prepare_runtime_goal(XiaoxBinding(run)).contract
    run.metadata.update(runtime_goal_contract=goal, runtime_goal_digest=goal["digest"])
    [catalogue] = goal["request"]["context_evidence"]
    assert "verified_read" not in catalogue
    group = catalogue["verified_reads"]
    assert [file["name"] for file in group] == ["first.docx", "second.csv"]
    assert len({file["upload_id"] for file in group}) == 2
    assert {file["source_run_id"] for file in group} == {original.run_id}
    assert all(file["coverage"]["truncated"] is False for file in group)
    assert recalled_attachment_view(run, run.metadata["runtime_context"]) == group
    assert (
        conversation_upload_context(
            run,
            run.metadata["runtime_context"],
            list(reversed(catalogue["entries"])),
        )
        is None
    )
    assert (
        recalled_attachment_view(
            run, {**run.metadata["runtime_context"], "tenant_id": actor.tenant_id + 1}
        )
        is None
    )
    assert (
        recalled_attachment_view(
            run, {**run.metadata["runtime_context"], "_conversation_revision": 1}
        )
        is None
    )

    other_actor = trusted_actor(tenant_id=actor.tenant_id)
    assert (
        recalled_attachment_view(
            run,
            {
                **run.metadata["runtime_context"],
                **other_actor.context,
                "local_user_id": other_actor.user_id,
            },
        )
        is None
    )

    ordinary_context = _input_text(run.message, [], None, goal=goal)
    verified_context = _input_text(
        run.message, [], None, goal=goal, recalled_attachment=group
    )
    assert all(
        marker not in ordinary_context
        for marker in ("ALPHA-VERIFIED-BODY", "BETA-VERIFIED-BODY")
    )
    assert all(
        marker in verified_context for marker in ("ALPHA-TABLE", "BETA-VERIFIED-BODY")
    )
    projected = runtime_file_evidence(
        goal, goal_evidence_snapshot(goal, [], "response")
    )
    assert set(projected) == {file["upload_id"] for file in group}
    assert [projected[file["upload_id"]]["sha256"] for file in group] == [
        artifact["metadata"]["sha256"] for artifact in artifacts
    ]

    # One stale member invalidates the whole frozen read; the directory is still discoverable.
    with tenant_scope(actor.tenant_id), get_db() as db:
        member = db.get(EltUpload, ids[-1])
        if invalidate == "hash":
            member.sha256 = "0" * 64
        else:
            member.expires_at = datetime(2000, 1, 1)
    assert recalled_attachment_view(run, run.metadata["runtime_context"]) is None
    ordinary_context = _input_text(
        run.message, [], None, goal=goal, recalled_attachment=None
    )
    assert "ALPHA-VERIFIED-BODY" not in ordinary_context
    assert "BETA-VERIFIED-BODY" not in ordinary_context
    retried = goal_admission.prepare_runtime_goal(XiaoxBinding(next_turn())).contract
    [remainder] = retried["request"]["context_evidence"]
    assert len(remainder["entries"]) == 1
    assert not {"verified_read", "verified_reads"} & remainder.keys()


def test_older_group_and_multiple_origins_stay_as_directory_only(selection):
    _, context, upload, current, freeze, record, next_turn = selection
    ids = [
        upload(name, b"key,value\nvalue,5\n")
        for name in ("one.csv", "two.csv", "three.csv")
    ]
    older = current("original")
    freeze(
        older,
        attachments=inputs.resolve_attachment_inputs(
            {**context, "attachment_upload_ids": ids[:2]}
        ),
    )
    record(older)
    unrelated = current("unrelated")
    freeze(unrelated)
    record(unrelated)
    run = next_turn()
    [directory] = goal_admission.prepare_runtime_goal(XiaoxBinding(run)).contract[
        "request"
    ]["context_evidence"]
    assert len(directory["entries"]) == 2 and "verified_reads" not in directory

    fresh = current("fresh")
    freeze(
        fresh,
        attachments=inputs.resolve_attachment_inputs(
            {**context, "attachment_upload_ids": ids[2:]}
        ),
    )
    record(fresh)
    run = next_turn()
    [directory] = goal_admission.prepare_runtime_goal(XiaoxBinding(run)).contract[
        "request"
    ]["context_evidence"]
    assert len(directory["entries"]) == 3
    assert not {"verified_read", "verified_reads"} & directory.keys()


@pytest.mark.parametrize("metric", ["file_bytes", "package_bytes", "text_bytes"])
def test_total_inline_budget_applies_to_the_entire_selection(
    selection, monkeypatch, metric
):
    _, context, upload, *_ = selection
    document = _sample_document()
    ids = [upload(name, document) for name in ("first.docx", "second.docx")]
    with ZipFile(io.BytesIO(document)) as zipped:
        expanded = sum(info.file_size for info in zipped.infolist())
    decode = inputs._decode(document, ".docx", inline_context=True)[0].encode("utf-8")
    one = {
        "file_bytes": len(document),
        "package_bytes": expanded,
        "text_bytes": len(decode),
    }
    budget_type = inputs._InlineReadBudget
    monkeypatch.setattr(
        inputs,
        "_InlineReadBudget",
        lambda: budget_type(**{metric: 2 * one[metric] - 1}),
    )
    assert inputs.resolve_attachment_inputs(
        {**context, "attachment_upload_ids": ids[:1]}, inline_context=True
    )
    if metric == "package_bytes":
        with pytest.raises(inputs.AttachmentInputError):
            inputs.resolve_attachment_inputs(
                {**context, "attachment_upload_ids": ids}, inline_context=True
            )
    else:
        assert (
            inputs.resolve_attachment_inputs(
                {**context, "attachment_upload_ids": ids}, inline_context=True
            )
            == []
        )


def test_active_explicit_selection_uses_creation_order_even_if_old_run_is_updated(
    selection,
):
    _, context, upload, current, freeze, record, next_turn = selection
    ids = [upload(name, b"name,count\nfixture,2\n") for name in ("one.csv", "two.csv")]
    artifacts = inputs.resolve_attachment_inputs(
        {**context, "attachment_upload_ids": ids}
    )
    earlier = current("earlier")
    freeze(earlier, attachments=artifacts)
    record(earlier)
    active = current("active")
    freeze(active, attachments=artifacts)
    record(active)
    earlier.updated_at = "2099-01-01T00:00:00"
    freeze(earlier, attachments=artifacts)
    source = next_turn()
    [directory] = goal_admission.prepare_runtime_goal(XiaoxBinding(source)).contract[
        "request"
    ]["context_evidence"]
    assert [view["source_run_id"] for view in directory["verified_reads"]] == [
        active.run_id,
        active.run_id,
    ]
