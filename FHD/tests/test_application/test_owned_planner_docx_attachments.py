"""Authenticated Word attachments, table locations and bounded package previews."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.db.models.elt import EltUpload
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.owned_attachments import owned as owned


def _docx_bytes(document):
    import io

    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_chat_word_upload_binds_the_original_table_to_the_authenticated_turn(
    trusted_actor, monkeypatch, tmp_path
):
    import json

    from docx import Document
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import set_agent_run_repository_for_tests
    from app.application.agent_orchestrator.attachment_inputs import (
        AttachmentInputError,
        resolve_attachment_context,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.agent_runtime import goal_admission
    from app.application.agent_runtime.conversation_attachments import (
        EVIDENCE_SOURCE,
        recalled_attachment_view,
    )
    from app.application.agent_runtime.xiaox_runtime import _input_text
    from app.application.ai_chat.conversation_history import restore_runtime_history_files
    from app.application.task_conversation_store import TaskConversationStore
    from app.db.session import get_db
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
    from app.fastapi_routes.platform_shell_routes import router
    from app.infrastructure.xiaox.binding import XiaoxBinding, XiaoxBindingError, XiaoxBindingStore
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setattr(goal_admission, "_context_evidence", lambda *_: [])
    owner = trusted_actor()
    same_tenant = trusted_actor(tenant_id=owner.tenant_id)
    other_tenant = trusted_actor(tenant_id=owner.tenant_id + 1)
    document = Document()
    document.add_paragraph("对账单示例")
    document.add_table(rows=1, cols=2).rows[0].cells[1].text = "120.50"
    raw = _docx_bytes(document)
    form = {
        "file": (
            "对账单.docx",
            raw,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    path = "/api/platform-shell/chat-office-file-upload?attachment_only=true"
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as anonymous:
        assert anonymous.post(path, files=form).status_code == 401
    with TestClient(app, headers=owner.headers) as authenticated:
        assert (
            authenticated.post(path, files={"file": ("arbitrary.txt", b"data")}).status_code == 400
        )
        response = authenticated.post(path, files=form)
        assert response.status_code == 200, response.text
        unused = authenticated.post(path, files=form).json()["data"]["upload_id"]
    receipt = response.json()["data"]
    assert receipt.keys() == {"upload_id", "filename"}
    assert receipt["filename"] == "对账单.docx"
    assert not (tmp_path / "workspace").exists()
    attachments = {"attachment_upload_ids": [receipt["upload_id"]]}
    context, (artifact,) = resolve_attachment_context({**owner.context, **attachments})
    [verified] = context["file_context"]["verified_uploads"]
    assert verified["text"] == "对账单示例\n[表格 1 行 1 列 2] 120.50"
    assert artifact["source"] == "owned_elt_upload" and artifact["uri"] == ""
    assert artifact["metadata"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert artifact["metadata"]["skip_dataset_ingest"] is True
    for principal in (same_tenant, other_tenant):
        with pytest.raises(AttachmentInputError, match="附件不属于当前账户"):
            resolve_attachment_context({**principal.context, **attachments})

    repository = SQLAlchemyAgentRunRepository(session_factory=owner.factory)
    conversations = TaskConversationStore()
    book_chat, unrelated_chat = "book-chat", "unrelated-chat"
    with tenant_scope(owner.tenant_id):
        for session in (book_chat, unrelated_chat):
            conversations.save_message(
                session_id=session, user_id=owner.user_id, role="user", content="test"
            )

    def chat_context(session, turn_id):
        return {
            **owner.context,
            "_conversation_revision": 0,
            "session_id": session,
            "conversation_id": session,
            "local_user_id": owner.user_id,
            "turn_id": turn_id,
            "execution_autonomy_level": 1,
        }

    parent = AgentRun(str(owner.user_id), "读取附件", status="running")
    parent.metadata.update(
        runtime_type="xiaox", runtime_context=chat_context(book_chat, "original-turn")
    )
    contract = build_goal_contract(parent, attachments=[artifact])
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)
    bridge = XiaoxToolBridge(
        store,
        AgentOrchestrator(
            repository=repository,
            tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
        ),
    )
    set_agent_run_repository_for_tests(repository)
    try:
        selection = {"tool_id": "conversation_history", "action": "read_attachment"}
        discovery = bridge.invoke(grant.mcp_token, "capability_search", {"query": "docx 附件"})
        assert any(row["action"] == selection["action"] for row in discovery["capabilities"])
        spec = bridge.invoke(grant.mcp_token, "capability_describe", selection)["capability"]
        assert spec["read_only"] is True
        for requested in (receipt["upload_id"], unused):
            found = bridge.invoke(
                grant.mcp_token,
                "execute_action",
                {
                    **selection,
                    "params": {"upload_id": requested},
                    "call_id": requested,
                    "schema_digest": spec["schema_digest"],
                },
            )
            if requested == unused:
                assert found["status"] == "failed" and not found["verified"]
                assert "120.50" not in str(found)
            else:
                assert found["status"] == "completed" and found["verified"] is True, found
                [verified_step] = found["verification"]["steps"]
                assert verified_step["status"] == "verified"
                [tool] = found["tool_calls"]
                assert tool["output"]["data"]["text"] == verified["text"]
                assert tool["output"]["data"]["sha256"] == artifact["metadata"]["sha256"]

        def next_turn(session, fresh=False):
            current = AgentRun(str(owner.user_id), "查询另一个表格单元", status="running")
            current.metadata.update(
                runtime_type="xiaox", runtime_context=chat_context(session, current.run_id)
            )
            if fresh:
                current.metadata["_xiaox_input_data"] = attachments
            frozen = goal_admission.prepare_runtime_goal(XiaoxBinding(current)).contract
            current.metadata.update(
                runtime_goal_contract=frozen, runtime_goal_digest=frozen["digest"]
            )
            repository.save(current)
            return current, store.create(current.run_id).mcp_token, frozen["request"]

        continuation, token, followup = next_turn(book_chat)
        assert not followup["attachments"]
        [catalogue] = followup["context_evidence"]
        [entry] = catalogue["entries"]
        assert catalogue["source"] == EVIDENCE_SOURCE and entry["source_run_id"] == parent.run_id
        reference = entry["upload_id"]
        assert catalogue["verified_read"] == {
            **entry,
            "sha256": artifact["metadata"]["sha256"],
            **artifact["preview"],
        }

        conversation_context = continuation.metadata["runtime_context"]
        bound = continuation.metadata["runtime_goal_contract"]
        recalled_view = recalled_attachment_view(continuation, conversation_context)
        assert recalled_view == catalogue["verified_read"]
        assert "120.50" not in _input_text(continuation.message, [], None, goal=bound)
        assert "120.50" in _input_text(
            continuation.message, [], None, goal=bound, recalled_attachment=recalled_view
        )
        assert (
            recalled_attachment_view(continuation, chat_context(unrelated_chat, "cross-chat"))
            is None
        )
        assert (
            recalled_attachment_view(
                continuation,
                {
                    **conversation_context,
                    **other_tenant.context,
                },
            )
            is None
        )

        def read(token, value, call_id):
            return bridge.invoke(
                token,
                "execute_action",
                {
                    **selection,
                    "params": {"upload_id": value},
                    "call_id": call_id,
                    "schema_digest": spec["schema_digest"],
                },
            )

        recalled = read(token, reference, "recall-verified")
        assert recalled["status"] == "completed" and recalled["verified"], recalled
        assert recalled["tool_calls"][0]["output"]["data"]["text"] == verified["text"]
        assert read(token, receipt["upload_id"], "bare-id")["status"] == "failed"

        binding = {
            "run_id": parent.run_id,
            "turn_id": "original-turn",
            "recall_bound": True,
            "conversation_id": book_chat,
        }
        page = {
            "messages": [
                {
                    "role": "user",
                    "metadata": json.dumps({"business_harness": binding, "summary": binding}),
                }
            ]
        }
        restore_runtime_history_files(page, {**parent.metadata["runtime_context"], "mod_id": ""})
        files = json.loads(page["messages"][0]["metadata"])["ui"]["inputAttachments"]
        assert files == [{"name": receipt["filename"], "reference": reference}]

        _, other_token, other = next_turn(unrelated_chat)
        assert not other["context_evidence"]
        with pytest.raises(XiaoxBindingError, match="未获授权"):
            read(other_token, reference, "different-session")
        _, fresh_token, fresh = next_turn(book_chat, fresh=True)
        assert fresh["attachments"] and not fresh["context_evidence"]
        assert read(fresh_token, reference, "old-after-current-selection")["status"] == "failed"

        # A second real selection leaves the catalogue available without guessing a file.
        alternate = AgentRun(str(owner.user_id), "另一个附件", status="running")
        alternate.metadata.update(
            runtime_type="xiaox", runtime_context=chat_context(book_chat, "second-turn")
        )
        _, artifacts = resolve_attachment_context(
            {**owner.context, "attachment_upload_ids": [unused]}
        )
        alternate_contract = build_goal_contract(alternate, attachments=artifacts)
        alternate.metadata.update(
            runtime_goal_contract=alternate_contract,
            runtime_goal_digest=alternate_contract["digest"],
        )
        repository.save(alternate)
        _, _, ambiguous = next_turn(book_chat)
        [ambiguous_catalogue] = ambiguous["context_evidence"]
        assert len(ambiguous_catalogue["entries"]) == 2
        assert "verified_read" not in ambiguous_catalogue

        with tenant_scope(owner.tenant_id), get_db() as db:
            original = db.get(EltUpload, receipt["upload_id"])
            original.sha256 = "0" * 64
        assert recalled_attachment_view(continuation, conversation_context) is None
        with tenant_scope(owner.tenant_id), get_db() as db:
            original = db.get(EltUpload, receipt["upload_id"])
            original.sha256 = artifact["metadata"]["sha256"]
            original.expires_at = datetime(2000, 1, 1)
        assert recalled_attachment_view(continuation, conversation_context) is None
        assert read(token, reference, "expired-after-selection")["status"] == "failed"
        with tenant_scope(owner.tenant_id):
            conversations.delete_session(session_id=book_chat, user_id=owner.user_id)
        with pytest.raises(XiaoxBindingError, match="会话"):
            read(token, reference, "after-delete")
    finally:
        set_agent_run_repository_for_tests(None)


def test_docx_preview_keeps_body_order_and_cell_coordinates():
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    document.add_paragraph("Introduction")
    table = document.add_table(rows=3, cols=4)
    table.cell(0, 0).text = "SKU | Item"
    table.cell(0, 2).merge(table.cell(0, 3)).text = "Quoted price"
    table.cell(1, 0).merge(table.cell(2, 0)).text = "Paint"
    table.cell(1, 2).text = "0"
    table.cell(2, 2).text = "120"
    row = table.rows[2]._tr
    row.remove(row.tc_lst[0])
    before = OxmlElement("w:gridBefore")
    before.set(qn("w:val"), "1")
    row.get_or_add_trPr().append(before)
    document.add_paragraph("Terms")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Net 30"

    text, coverage = _decode(_docx_bytes(document), ".docx")
    assert text.splitlines() == [
        "Introduction",
        "[表格 1 行 1 列 1] SKU | Item",
        "[表格 1 行 1 列 3] Quoted price",
        "[表格 1 行 2 列 1] Paint",
        "[表格 1 行 2 列 3] 0",
        "[表格 1 行 3 列 3] 120",
        "Terms",
        "[表格 2 行 1 列 1] Net 30",
    ]
    assert coverage["scope"] == "paragraphs_and_tables"
    assert coverage["truncated"] is False


def test_docx_preview_marks_nested_table_omission_without_misattribution():
    from docx import Document

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    outer = document.add_table(rows=1, cols=1).cell(0, 0)
    outer.text = "parent cell"
    outer.add_table(rows=1, cols=1).cell(0, 0).text = "nested only"

    text, coverage = _decode(_docx_bytes(document), ".docx")
    assert text.strip() == "[表格 1 行 1 列 1] parent cell"
    assert coverage["truncated"] is True


def test_docx_preview_reports_omitted_content_control():
    from docx import Document
    from docx.oxml import OxmlElement

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    document.add_paragraph("visible")
    wrapped = document.add_paragraph("wrapped content")._p
    control = OxmlElement("w:sdt")
    content = OxmlElement("w:sdtContent")
    control.append(content)
    wrapped.addprevious(control)
    content.append(wrapped)

    text, coverage = _decode(_docx_bytes(document), ".docx")
    assert text == "visible"
    assert coverage["truncated"] is True


def test_inline_docx_distinguishes_footnote_reference_from_package_template():
    from docx import Document
    from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import OxmlElement

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    paragraph = document.add_paragraph("Relevant body")
    footnotes = Part(
        PackURI("/word/footnotes.xml"),
        CONTENT_TYPE.WML_FOOTNOTES,
        b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        document.part.package,
    )
    document.part.relate_to(footnotes, RELATIONSHIP_TYPE.FOOTNOTES)
    raw = _docx_bytes(document)
    before = _decode(raw, ".docx")
    assert _decode(raw, ".docx", inline_context=True) == before

    paragraph.add_run()._r.append(OxmlElement("w:footnoteReference"))
    raw = _docx_bytes(document)
    assert _decode(raw, ".docx") == before
    assert _decode(raw, ".docx", inline_context=True)[1]["truncated"] is True


def test_docx_preview_rejects_oversized_expanded_package():
    import io
    from zipfile import ZIP_DEFLATED, ZipFile

    from docx import Document

    from app.application.agent_orchestrator.attachment_inputs import AttachmentInputError, _decode

    stream = io.BytesIO(_docx_bytes(Document()))
    with ZipFile(stream, "a", ZIP_DEFLATED) as archive:
        archive.writestr("word/unused.bin", b"\0" * (32 * 1024 * 1024))

    with pytest.raises(AttachmentInputError, match="体积过大"):
        _decode(stream.getvalue(), ".docx")


@pytest.mark.parametrize("scenario", ["ok", "broken", "large", "partial"])
def test_owned_docx_preview_uses_only_verified_upload(monkeypatch, scenario):
    import io
    from contextlib import nullcontext
    from unittest.mock import Mock

    from docx import Document

    from app.application.agent_orchestrator import attachment_inputs

    document = Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "quoted value"
    if scenario == "partial":
        cell.add_table(rows=1, cols=1)
    raw = b"not a DOCX" if scenario == "broken" else _docx_bytes(document)
    row = SimpleNamespace(
        id="owned-file",
        file_name="quote.docx",
        suffix=".docx",
        storage_path="pinned-file",
        size_bytes=len(raw) if scenario != "large" else attachment_inputs._CONTEXT_FILE_BYTES + 1,
        sha256=hashlib.sha256(raw).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = row
    opened = Mock(return_value=io.BytesIO(raw))
    monkeypatch.setattr(attachment_inputs, "get_db", lambda: nullcontext(db))
    monkeypatch.setattr(attachment_inputs, "tenant_scope", lambda _: nullcontext())
    monkeypatch.setattr(attachment_inputs, "validate_actor_context", lambda _: None)
    monkeypatch.setattr(attachment_inputs, "open_elt_input_file", opened)
    context = {
        "user_id": 7,
        "tenant_id": 13,
        "attachment_upload_ids": [row.id],
        "file_context": {"verified_uploads": [{"text": "untrusted fallback"}]},
    }

    if scenario == "large":
        assert attachment_inputs.resolve_attachment_inputs(context, inline_context=True) == []
        opened.assert_not_called()
        return
    if scenario == "partial":
        assert attachment_inputs.resolve_attachment_inputs(context, inline_context=True) == []
    elif scenario == "broken":
        with pytest.raises(attachment_inputs.AttachmentInputError, match="解析失败"):
            attachment_inputs.resolve_attachment_context(context)
    else:
        resolved, (artifact,) = attachment_inputs.resolve_attachment_context(context)
        assert artifact["source"] == "owned_elt_upload"
        assert artifact["metadata"]["upload_id"] == row.id
        assert artifact["preview"]["text"].strip() == "[表格 1 行 1 列 1] quoted value"
        assert resolved["file_context"] == {
            "verified_uploads": [
                {"name": row.file_name, "upload_id": row.id, **artifact["preview"]}
            ]
        }
    opened.assert_called_once_with(row.storage_path, owner_user_id=7)
