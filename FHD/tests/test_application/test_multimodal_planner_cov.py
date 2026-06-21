from __future__ import annotations

"""Coverage ramp tests for app.application.agent_orchestrator.multimodal_planner."""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Direct imports — Python 3.11 runtime, no exec_module workaround needed.
import app.application.agent_orchestrator.multimodal_planner as _planner
import app.application.agent_orchestrator.run_models as _run_models
import app.application.workflow.types as _workflow_types

AgentArtifact = _run_models.AgentArtifact
artifact_from_dict = _run_models.artifact_from_dict
PlanGraph = _workflow_types.PlanGraph

build_multimodal_autonomous_plan = _planner.build_multimodal_autonomous_plan
_collect_artifacts = _planner._collect_artifacts
_iter_attachment_payloads = _planner._iter_attachment_payloads
_artifact_from_attachment = _planner._artifact_from_attachment
_guess_attachment_artifact_type = _planner._guess_attachment_artifact_type
_resolve_dataset_id = _planner._resolve_dataset_id
_resolve_tenant_id = _planner._resolve_tenant_id
_resolve_query = _planner._resolve_query
_looks_like_excel_import_intent = _planner._looks_like_excel_import_intent
_has_document_export_artifact = _planner._has_document_export_artifact
_looks_like_document_export_intent = _planner._looks_like_document_export_intent
_resolve_document_output_format = _planner._resolve_document_output_format
_build_document_export_request = _planner._build_document_export_request
_artifact_text_preview = _planner._artifact_text_preview
_resolve_excel_import_records = _planner._resolve_excel_import_records
_coerce_record_list = _planner._coerce_record_list
_extract_excel_records_with_existing_parser = _planner._extract_excel_records_with_existing_parser
_coerce_bool = _planner._coerce_bool
_coerce_int = _planner._coerce_int

MOD = "app.application.agent_orchestrator.multimodal_planner"

# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _make_artifact(
    artifact_type: str = "pdf_document",
    name: str = "doc.pdf",
    uri: str = "/tmp/doc.pdf",
    source: str = "test",
    summary: str = "A summary",
    metadata: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
    fields: list | None = None,
    mime_type: str = "application/pdf",
) -> AgentArtifact:
    return AgentArtifact(
        artifact_type=artifact_type,
        name=name,
        uri=uri,
        source=source,
        summary=summary,
        metadata=metadata if metadata is not None else {},
        preview=preview if preview is not None else {},
        fields=fields if fields is not None else [],
        mime_type=mime_type,
    )


# ===========================================================================
# _coerce_bool
# ===========================================================================


class TestCoerceBool:
    def test_none_returns_default_true(self) -> None:
        assert _coerce_bool(None, default=True) is True

    def test_none_returns_default_false(self) -> None:
        assert _coerce_bool(None, default=False) is False

    def test_bool_true_passthrough(self) -> None:
        assert _coerce_bool(True, default=False) is True

    def test_bool_false_passthrough(self) -> None:
        assert _coerce_bool(False, default=True) is False

    @pytest.mark.parametrize("v", ["1", "true", "yes", "on", "TRUE", "YES"])
    def test_truthy_strings(self, v: str) -> None:
        assert _coerce_bool(v, default=False) is True

    @pytest.mark.parametrize("v", ["0", "false", "no", "off", "FALSE", "OFF"])
    def test_falsy_strings(self, v: str) -> None:
        assert _coerce_bool(v, default=True) is False

    def test_unknown_string_returns_default_true(self) -> None:
        assert _coerce_bool("maybe", default=True) is True

    def test_unknown_string_returns_default_false(self) -> None:
        assert _coerce_bool("maybe", default=False) is False


# ===========================================================================
# _coerce_int
# ===========================================================================


class TestCoerceInt:
    def test_valid_int(self) -> None:
        assert _coerce_int(7, default=0) == 7

    def test_valid_string_int(self) -> None:
        assert _coerce_int("42", default=0) == 42

    def test_none_returns_default(self) -> None:
        assert _coerce_int(None, default=5) == 5

    def test_non_numeric_string_returns_default(self) -> None:
        assert _coerce_int("abc", default=3) == 3

    def test_float_is_truncated(self) -> None:
        assert _coerce_int(3.9, default=0) == 3


# ===========================================================================
# _coerce_record_list
# ===========================================================================


class TestCoerceRecordList:
    def test_non_list_string_returns_empty(self) -> None:
        assert _coerce_record_list("not-a-list") == []

    def test_non_list_int_returns_empty(self) -> None:
        assert _coerce_record_list(42) == []

    def test_none_returns_empty(self) -> None:
        assert _coerce_record_list(None) == []

    def test_list_of_dicts(self) -> None:
        assert _coerce_record_list([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_mixed_list_filters_non_dicts(self) -> None:
        assert _coerce_record_list([{"a": 1}, "x", 42, None, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_empty_list(self) -> None:
        assert _coerce_record_list([]) == []


# ===========================================================================
# _guess_attachment_artifact_type
# ===========================================================================


class TestGuessAttachmentArtifactType:
    def test_pdf_by_extension(self) -> None:
        assert _guess_attachment_artifact_type("file.pdf", "", "") == "pdf_document"

    def test_pdf_by_mime(self) -> None:
        assert _guess_attachment_artifact_type("", "application/pdf", "") == "pdf_document"

    def test_docx_by_extension(self) -> None:
        assert _guess_attachment_artifact_type("report.docx", "", "") == "office_document"

    def test_docx_by_mime_wordprocessingml(self) -> None:
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert _guess_attachment_artifact_type("", mime, "") == "office_document"

    @pytest.mark.parametrize("ext", [".txt", ".md", ".csv", ".json", ".log"])
    def test_text_extensions(self, ext: str) -> None:
        assert _guess_attachment_artifact_type(f"file{ext}", "", "") == "document_file"

    def test_text_mime(self) -> None:
        assert _guess_attachment_artifact_type("", "text/plain", "") == "document_file"

    def test_excel_xlsx_with_text(self) -> None:
        assert _guess_attachment_artifact_type("data.xlsx", "", "some text") == "excel_records"

    def test_excel_xlsx_without_text_returns_empty(self) -> None:
        assert _guess_attachment_artifact_type("data.xlsx", "", "") == ""

    def test_excel_xls_with_text(self) -> None:
        assert _guess_attachment_artifact_type("data.xls", "", "rows") == "excel_records"

    def test_excel_xlsm_with_text(self) -> None:
        assert _guess_attachment_artifact_type("data.xlsm", "", "data") == "excel_records"

    def test_excel_spreadsheetml_mime_with_text(self) -> None:
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert _guess_attachment_artifact_type("", mime, "text") == "excel_records"

    def test_excel_spreadsheetml_mime_without_text_empty(self) -> None:
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert _guess_attachment_artifact_type("", mime, "") == ""

    def test_image_mime_returns_ocr_text(self) -> None:
        assert _guess_attachment_artifact_type("", "image/png", "") == "ocr_text"

    def test_unknown_type_with_text_returns_ocr_text(self) -> None:
        assert _guess_attachment_artifact_type("", "", "some text") == "ocr_text"

    def test_no_match_returns_empty(self) -> None:
        assert _guess_attachment_artifact_type("", "", "") == ""


# ===========================================================================
# _iter_attachment_payloads
# ===========================================================================


class TestIterAttachmentPayloads:
    def test_empty_context(self) -> None:
        assert _iter_attachment_payloads({}) == []

    def test_dict_value_appended(self) -> None:
        ctx = {"multimodal_attachments": {"name": "x"}}
        assert _iter_attachment_payloads(ctx) == [{"name": "x"}]

    def test_list_of_dicts_extended(self) -> None:
        ctx = {"attachments": [{"a": 1}, {"b": 2}]}
        assert _iter_attachment_payloads(ctx) == [{"a": 1}, {"b": 2}]

    def test_list_with_non_dict_items_filtered(self) -> None:
        ctx = {"files": [{"c": 3}, "skip", 42]}
        assert _iter_attachment_payloads(ctx) == [{"c": 3}]

    def test_all_three_keys_combined(self) -> None:
        ctx = {
            "multimodal_attachments": {"a": 1},
            "attachments": [{"b": 2}],
            "files": [{"c": 3}],
        }
        assert _iter_attachment_payloads(ctx) == [{"a": 1}, {"b": 2}, {"c": 3}]

    def test_non_list_non_dict_value_ignored(self) -> None:
        ctx = {"attachments": "not-a-collection"}
        assert _iter_attachment_payloads(ctx) == []


# ===========================================================================
# _artifact_from_attachment
# ===========================================================================


class TestArtifactFromAttachment:
    def test_item_with_artifact_type_key(self) -> None:
        item = {"artifact_type": "pdf_document", "name": "x.pdf", "uri": "/x.pdf"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.artifact_type == "pdf_document"

    def test_type_artifact_with_artifact_type(self) -> None:
        item = {"type": "artifact", "artifact_type": "office_document", "name": "doc.docx"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.artifact_type == "office_document"

    def test_type_artifact_with_explicit_empty_type_returns_none(self) -> None:
        # artifact_from_dict returns empty artifact_type when both keys are absent/empty
        # Simulate this by using a blank artifact_type that makes artifact_from_dict return ""
        # The only way to get None returned is if artifact.artifact_type is falsy after artifact_from_dict
        # artifact_from_dict maps: artifact_type = str(data.get("artifact_type") or data.get("type") or "")
        # So {"artifact_type": ""} has type="" -> falls through to "" but "type" key not set -> ""
        item = {"artifact_type": "", "type": ""}
        # Neither artifact_type nor type=="artifact", so this won't enter the branch at all
        # Instead, it proceeds to the guessing path with empty file_path and no mime/text -> returns None
        result = _artifact_from_attachment(item)
        assert result is None

    def test_plain_pdf_item(self) -> None:
        item = {"file_path": "/docs/report.pdf", "name": "report.pdf"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.artifact_type == "pdf_document"
        assert result.name == "report.pdf"

    def test_unknown_attachment_returns_none(self) -> None:
        item = {"file_path": "/docs/binary.bin"}
        result = _artifact_from_attachment(item)
        assert result is None

    def test_fields_filtered_to_dicts(self) -> None:
        item = {
            "file_path": "/x.txt",
            "fields": [{"col": "a"}, "not-a-dict", {"col": "b"}],
        }
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.fields == [{"col": "a"}, {"col": "b"}]

    def test_non_list_fields_treated_as_empty(self) -> None:
        item = {"file_path": "/x.pdf", "fields": "not-a-list"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.fields == []

    def test_name_falls_back_to_path_basename(self) -> None:
        item = {"file_path": "/some/path/file.txt"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.name == "file.txt"

    def test_text_from_ocr_text_key(self) -> None:
        item = {"file_path": "", "mime_type": "image/jpeg", "ocr_text": "hello world"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.preview["text"] == "hello world"

    def test_summary_falls_back_to_message(self) -> None:
        item = {"file_path": "/a.txt", "message": "uploaded file"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.summary == "uploaded file"

    def test_uri_from_url_key(self) -> None:
        item = {"url": "http://example.com/file.pdf"}
        result = _artifact_from_attachment(item)
        assert result is not None
        assert result.uri == "http://example.com/file.pdf"


# ===========================================================================
# _collect_artifacts
# ===========================================================================


class TestCollectArtifacts:
    def test_import_error_from_chat_trace_falls_back_gracefully(self) -> None:
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "chat_trace" in name:
                raise ImportError("mocked chat_trace import")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = _collect_artifacts({})
        assert result == []

    def test_deduplication_removes_second_copy(self) -> None:
        art = _make_artifact()
        with patch.object(_planner, "_iter_attachment_payloads", return_value=[]):
            with patch.dict(
                "sys.modules",
                {
                    "app.application.agent_orchestrator.chat_trace": MagicMock(
                        _extract_artifacts=lambda ctx: [art, art]
                    )
                },
            ):
                result = _collect_artifacts({})
        assert len(result) == 1

    def test_artifacts_with_no_type_are_skipped(self) -> None:
        art_no_type = _make_artifact(artifact_type="")
        with patch.object(_planner, "_iter_attachment_payloads", return_value=[]):
            with patch.dict(
                "sys.modules",
                {
                    "app.application.agent_orchestrator.chat_trace": MagicMock(
                        _extract_artifacts=lambda ctx: [art_no_type]
                    )
                },
            ):
                result = _collect_artifacts({})
        assert result == []

    def test_attachment_payload_artifacts_added(self) -> None:
        item = {"file_path": "/x.pdf"}
        with patch.object(_planner, "_iter_attachment_payloads", return_value=[item]):
            with patch.dict(
                "sys.modules",
                {
                    "app.application.agent_orchestrator.chat_trace": MagicMock(
                        _extract_artifacts=lambda ctx: []
                    )
                },
            ):
                result = _collect_artifacts({})
        assert len(result) == 1
        assert result[0].artifact_type == "pdf_document"

    def test_none_artifact_from_attachment_not_added(self) -> None:
        item = {"file_path": "/x.bin"}  # no guessable type
        with patch.object(_planner, "_iter_attachment_payloads", return_value=[item]):
            with patch.dict(
                "sys.modules",
                {
                    "app.application.agent_orchestrator.chat_trace": MagicMock(
                        _extract_artifacts=lambda ctx: []
                    )
                },
            ):
                result = _collect_artifacts({})
        assert result == []


# ===========================================================================
# _resolve_dataset_id
# ===========================================================================


class TestResolveDatasetId:
    def test_context_dataset_id_wins(self) -> None:
        art = _make_artifact()
        assert _resolve_dataset_id("u1", {"dataset_id": "ds-42"}, [art]) == "ds-42"

    def test_rag_dataset_id_used(self) -> None:
        assert _resolve_dataset_id("u1", {"rag_dataset_id": "rag-ds"}, []) == "rag-ds"

    def test_knowledge_dataset_id_used(self) -> None:
        assert _resolve_dataset_id("u1", {"knowledge_dataset_id": "know-ds"}, []) == "know-ds"

    def test_target_dataset_id_used(self) -> None:
        assert _resolve_dataset_id("u1", {"target_dataset_id": "tgt-ds"}, []) == "tgt-ds"

    def test_artifact_metadata_dataset_id_fallback(self) -> None:
        art = _make_artifact(metadata={"dataset_id": "art-ds"})
        assert _resolve_dataset_id("u1", {}, [art]) == "art-ds"

    def test_user_id_fallback(self) -> None:
        art = _make_artifact(metadata={})
        assert _resolve_dataset_id("u99", {}, [art]) == "user_u99"

    def test_anonymous_fallback_when_no_user_id(self) -> None:
        assert _resolve_dataset_id("", {}, []) == "user_anonymous"


# ===========================================================================
# _resolve_tenant_id
# ===========================================================================


class TestResolveTenantId:
    def test_context_tenant_id_wins(self) -> None:
        assert _resolve_tenant_id("u1", {"tenant_id": "t-abc"}, []) == "t-abc"

    def test_tenantId_camel_case(self) -> None:
        assert _resolve_tenant_id("u1", {"tenantId": "t-xyz"}, []) == "t-xyz"

    def test_workspace_id(self) -> None:
        assert _resolve_tenant_id("u1", {"workspace_id": "ws-1"}, []) == "ws-1"

    def test_workspace_key(self) -> None:
        assert _resolve_tenant_id("u1", {"workspace": "ws-2"}, []) == "ws-2"

    def test_artifact_metadata_tenant_id_fallback(self) -> None:
        art = _make_artifact(metadata={"tenant_id": "art-tenant"})
        assert _resolve_tenant_id("u1", {}, [art]) == "art-tenant"

    def test_user_id_as_last_candidate(self) -> None:
        assert _resolve_tenant_id("user-42", {}, []) == "user-42"

    def test_anonymous_when_all_empty(self) -> None:
        assert _resolve_tenant_id("", {}, []) == "anonymous"


# ===========================================================================
# _resolve_query
# ===========================================================================


class TestResolveQuery:
    def test_context_dataset_query_wins(self) -> None:
        assert _resolve_query("msg", {"dataset_query": "ctx query"}, []) == "ctx query"

    def test_rag_query_key(self) -> None:
        assert _resolve_query("msg", {"rag_query": "rag q"}, []) == "rag q"

    def test_multimodal_query_key(self) -> None:
        assert _resolve_query("msg", {"multimodal_query": "mm q"}, []) == "mm q"

    def test_question_key(self) -> None:
        assert _resolve_query("msg", {"question": "q?"}, []) == "q?"

    def test_message_fallback(self) -> None:
        assert _resolve_query("my message", {}, []) == "my message"

    def test_artifact_names_fallback(self) -> None:
        art = _make_artifact(name="report.pdf")
        result = _resolve_query("", {}, [art])
        assert "report.pdf" in result

    def test_no_names_returns_generic_phrase(self) -> None:
        art = _make_artifact(name="")
        result = _resolve_query("", {}, [art])
        assert "attached artifacts" in result


# ===========================================================================
# _looks_like_excel_import_intent
# ===========================================================================


class TestLooksLikeExcelImportIntent:
    def test_context_excel_import_true(self) -> None:
        assert _looks_like_excel_import_intent("", {"excel_import": True}) is True

    def test_context_excel_import_to_db_true(self) -> None:
        assert _looks_like_excel_import_intent("", {"excel_import_to_db": True}) is True

    def test_empty_text_returns_false(self) -> None:
        assert _looks_like_excel_import_intent("", {}) is False

    def test_import_keyword_in_message(self) -> None:
        assert _looks_like_excel_import_intent("please import these records", {}) is True

    def test_chinese_daoru_shujuku(self) -> None:
        assert _looks_like_excel_import_intent("请导入数据库", {}) is True

    def test_chinese_ruku_marker(self) -> None:
        assert _looks_like_excel_import_intent("直接入库", {}) is True

    def test_no_match_returns_false(self) -> None:
        assert _looks_like_excel_import_intent("just a chat message", {}) is False

    def test_import_records_keyword(self) -> None:
        assert _looks_like_excel_import_intent("import_records from file", {}) is True

    def test_context_message_fallback_used(self) -> None:
        assert _looks_like_excel_import_intent("", {"message": "导入数据库"}) is True

    def test_xie_ru_shu_ju_ku(self) -> None:
        assert _looks_like_excel_import_intent("写入数据库", {}) is True


# ===========================================================================
# _has_document_export_artifact
# ===========================================================================


class TestHasDocumentExportArtifact:
    def test_pdf_document_type(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        assert _has_document_export_artifact([art]) is True

    def test_office_document_type(self) -> None:
        art = _make_artifact(artifact_type="office_document")
        assert _has_document_export_artifact([art]) is True

    def test_document_file_type(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        assert _has_document_export_artifact([art]) is True

    def test_unrelated_type_returns_false(self) -> None:
        art = _make_artifact(artifact_type="excel_records")
        assert _has_document_export_artifact([art]) is False

    def test_empty_list_returns_false(self) -> None:
        assert _has_document_export_artifact([]) is False


# ===========================================================================
# _looks_like_document_export_intent
# ===========================================================================


class TestLooksLikeDocumentExportIntent:
    def test_context_document_export_true(self) -> None:
        assert _looks_like_document_export_intent("", {"document_export": True}) is True

    def test_context_generate_document_true(self) -> None:
        assert _looks_like_document_export_intent("", {"generate_document": True}) is True

    def test_context_generate_office_document_true(self) -> None:
        assert _looks_like_document_export_intent("", {"generate_office_document": True}) is True

    def test_context_office_export_true(self) -> None:
        assert _looks_like_document_export_intent("", {"office_export": True}) is True

    def test_empty_text_returns_false(self) -> None:
        assert _looks_like_document_export_intent("", {}) is False

    def test_generate_and_report_matches(self) -> None:
        assert _looks_like_document_export_intent("generate a report", {}) is True

    def test_export_only_no_document_marker_returns_false(self) -> None:
        assert _looks_like_document_export_intent("please export the data", {}) is False

    def test_create_docx_matches(self) -> None:
        assert _looks_like_document_export_intent("create a docx file", {}) is True

    def test_export_to_spreadsheet_matches(self) -> None:
        assert _looks_like_document_export_intent("export to spreadsheet", {}) is True

    def test_context_message_fallback_used(self) -> None:
        assert _looks_like_document_export_intent("", {"message": "生成报告"}) is True

    def test_document_marker_only_returns_false(self) -> None:
        # "word" is document marker but no export marker
        assert _looks_like_document_export_intent("I have a word document here", {}) is False


# ===========================================================================
# _resolve_document_output_format
# ===========================================================================


class TestResolveDocumentOutputFormat:
    def test_context_output_format_docx(self) -> None:
        assert _resolve_document_output_format("", {"output_format": "docx"}) == "docx"

    def test_context_output_format_xlsx(self) -> None:
        assert _resolve_document_output_format("", {"output_format": "xlsx"}) == "xlsx"

    def test_document_output_format_key(self) -> None:
        assert _resolve_document_output_format("", {"document_output_format": "xlsx"}) == "xlsx"

    def test_unknown_format_falls_through(self) -> None:
        assert _resolve_document_output_format("", {"output_format": "pdf"}) == "docx"

    def test_message_contains_xlsx(self) -> None:
        assert _resolve_document_output_format("export as xlsx", {}) == "xlsx"

    def test_message_contains_excel(self) -> None:
        assert _resolve_document_output_format("make an excel", {}) == "xlsx"

    def test_message_contains_spreadsheet(self) -> None:
        assert _resolve_document_output_format("create a spreadsheet", {}) == "xlsx"

    def test_message_contains_biaoge(self) -> None:
        assert _resolve_document_output_format("请生成表格", {}) == "xlsx"

    def test_default_is_docx(self) -> None:
        assert _resolve_document_output_format("summarize the document", {}) == "docx"


# ===========================================================================
# _artifact_text_preview
# ===========================================================================


class TestArtifactTextPreview:
    def test_metadata_text_returned(self) -> None:
        art = _make_artifact(metadata={"text": "hello world"})
        assert _artifact_text_preview(art) == "hello world"

    def test_metadata_text_preview_used(self) -> None:
        art = _make_artifact(metadata={"text_preview": "preview text"})
        assert _artifact_text_preview(art) == "preview text"

    def test_metadata_ocr_text_used(self) -> None:
        art = _make_artifact(metadata={"ocr_text": "ocr content"})
        assert _artifact_text_preview(art) == "ocr content"

    def test_preview_text_used(self) -> None:
        art = _make_artifact(preview={"text": "preview body"})
        assert _artifact_text_preview(art) == "preview body"

    def test_preview_text_preview_key_used(self) -> None:
        art = _make_artifact(preview={"text_preview": "ptp"})
        assert _artifact_text_preview(art) == "ptp"

    def test_empty_returns_empty_string(self) -> None:
        art = _make_artifact()
        assert _artifact_text_preview(art) == ""

    def test_preview_not_dict_treated_as_empty(self) -> None:
        art = _make_artifact()
        art.preview = "string"  # type: ignore[assignment]
        assert _artifact_text_preview(art) == ""

    def test_metadata_not_dict_treated_as_empty(self) -> None:
        art = _make_artifact()
        art.metadata = "string"  # type: ignore[assignment]
        assert _artifact_text_preview(art) == ""

    def test_whitespace_collapsed(self) -> None:
        art = _make_artifact(metadata={"text": "  hello   world  "})
        assert _artifact_text_preview(art) == "hello world"


# ===========================================================================
# _build_document_export_request
# ===========================================================================


class TestBuildDocumentExportRequest:
    def test_explicit_context_document_request(self) -> None:
        result = _build_document_export_request("", {"document_request": "custom req"}, [])
        assert result == "custom req"

    def test_office_document_request_key(self) -> None:
        result = _build_document_export_request("", {"office_document_request": "off req"}, [])
        assert result == "off req"

    def test_generate_document_request_key(self) -> None:
        result = _build_document_export_request("", {"generate_document_request": "gen req"}, [])
        assert result == "gen req"

    def test_message_used_when_no_explicit(self) -> None:
        assert _build_document_export_request("use this", {}, []) == "use this"

    def test_default_request_when_empty(self) -> None:
        result = _build_document_export_request("", {}, [])
        assert "结构化文档" in result

    def test_evidence_lines_built_from_document_artifacts(self) -> None:
        art = _make_artifact(
            artifact_type="pdf_document",
            name="report.pdf",
            summary="Key findings",
            metadata={"text": "evidence text"},
        )
        result = _build_document_export_request("generate report", {}, [art])
        assert "report.pdf" in result
        assert "evidence text" in result

    def test_non_document_artifacts_skipped_in_evidence(self) -> None:
        art = _make_artifact(artifact_type="excel_records", name="data.xlsx")
        result = _build_document_export_request("generate", {}, [art])
        assert "data.xlsx" not in result

    def test_no_evidence_lines_returns_request_only(self) -> None:
        assert _build_document_export_request("just a message", {}, []) == "just a message"

    def test_uri_used_when_name_empty(self) -> None:
        art = _make_artifact(artifact_type="pdf_document", name="", uri="/path/to/file.pdf")
        result = _build_document_export_request("req", {}, [art])
        assert "/path/to/file.pdf" in result

    def test_summary_appended(self) -> None:
        art = _make_artifact(artifact_type="office_document", summary="contract details")
        result = _build_document_export_request("req", {}, [art])
        assert "contract details" in result

    def test_text_preview_included_in_evidence(self) -> None:
        art = _make_artifact(artifact_type="document_file", preview={"text": "preview words"})
        result = _build_document_export_request("req", {}, [art])
        assert "preview words" in result

    def test_artifact_with_no_name_or_uri_uses_index_label(self) -> None:
        art = _make_artifact(artifact_type="pdf_document", name="", uri="")
        result = _build_document_export_request("req", {}, [art])
        assert "artifact-1" in result


# ===========================================================================
# _resolve_excel_import_records
# ===========================================================================


class TestResolveExcelImportRecords:
    def test_context_excel_import_records_used(self) -> None:
        records = [{"row": 1}, {"row": 2}]
        result = _resolve_excel_import_records({"excel_import_records": records}, [], "")
        assert result == records

    def test_context_import_records_used(self) -> None:
        records = [{"r": 1}]
        result = _resolve_excel_import_records({"import_records": records}, [], "")
        assert result == records

    def test_excel_analysis_candidate_tried(self) -> None:
        ctx = {"excel_analysis": {"sheet": "Sheet1"}}
        with patch.object(
            _planner, "_extract_excel_records_with_existing_parser", return_value=[{"a": 1}]
        ) as mock_fn:
            result = _resolve_excel_import_records(ctx, [], "msg")
        assert result == [{"a": 1}]
        mock_fn.assert_called_once()

    def test_excel_artifact_with_preview_data_tried(self) -> None:
        art = _make_artifact(
            artifact_type="excel_records",
            name="data.xlsx",
            preview={"preview_data": {"col": "A"}, "record_count": 5},
        )
        with patch.object(
            _planner, "_extract_excel_records_with_existing_parser", return_value=[{"b": 2}]
        ):
            result = _resolve_excel_import_records({}, [art], "")
        assert result == [{"b": 2}]

    def test_excel_artifact_without_preview_data_skipped(self) -> None:
        art = _make_artifact(artifact_type="excel_records", preview={})
        with patch.object(_planner, "_extract_excel_records_with_existing_parser", return_value=[]):
            result = _resolve_excel_import_records({}, [art], "")
        assert result == []

    def test_non_excel_artifact_ignored(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        result = _resolve_excel_import_records({}, [art], "")
        assert result == []

    def test_returns_empty_when_nothing_found(self) -> None:
        assert _resolve_excel_import_records({}, [], "") == []

    def test_excel_file_artifact_type_accepted(self) -> None:
        art = _make_artifact(artifact_type="excel_file", preview={"preview_data": {"col": "B"}})
        with patch.object(
            _planner, "_extract_excel_records_with_existing_parser", return_value=[{"c": 3}]
        ):
            result = _resolve_excel_import_records({}, [art], "")
        assert result == [{"c": 3}]

    def test_excel_analysis_not_dict_is_ignored(self) -> None:
        ctx = {"excel_analysis": "not-a-dict"}
        result = _resolve_excel_import_records(ctx, [], "")
        assert result == []


# ===========================================================================
# _extract_excel_records_with_existing_parser
# ===========================================================================


class TestExtractExcelRecordsWithExistingParser:
    """_extract_excel_records_with_existing_parser does `from app.application import get_ai_chat_app_service`
    at call time inside a try/except block.  app.application is a MagicMock stub, so we patch
    its `get_ai_chat_app_service` attribute directly via patch.object.
    """

    _APP_APP_MOD = sys.modules["app.application"]

    def test_import_error_returns_empty(self) -> None:
        # Temporarily remove the stub so the `from app.application import ...` raises ImportError.
        saved = sys.modules.pop("app.application")
        try:
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        finally:
            sys.modules["app.application"] = saved
        assert result == []

    def test_extractor_not_callable_returns_empty(self) -> None:
        mock_service = MagicMock()
        mock_service._extract_excel_import_records = "not-callable"
        with patch.object(self._APP_APP_MOD, "get_ai_chat_app_service", return_value=mock_service):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == []

    def test_extractor_none_returns_empty(self) -> None:
        mock_service = MagicMock()
        mock_service._extract_excel_import_records = None
        with patch.object(self._APP_APP_MOD, "get_ai_chat_app_service", return_value=mock_service):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == []

    def test_extractor_returns_error_string_returns_empty(self) -> None:
        mock_service = MagicMock()
        mock_service._extract_excel_import_records.return_value = ([], "parse error")
        with patch.object(self._APP_APP_MOD, "get_ai_chat_app_service", return_value=mock_service):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == []

    def test_extractor_returns_valid_records(self) -> None:
        mock_service = MagicMock()
        mock_service._extract_excel_import_records.return_value = ([{"row": 1}], None)
        with patch.object(self._APP_APP_MOD, "get_ai_chat_app_service", return_value=mock_service):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == [{"row": 1}]

    def test_attribute_error_returns_empty(self) -> None:
        with patch.object(
            self._APP_APP_MOD, "get_ai_chat_app_service", side_effect=AttributeError("no attr")
        ):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == []

    def test_type_error_returns_empty(self) -> None:
        with patch.object(
            self._APP_APP_MOD, "get_ai_chat_app_service", side_effect=TypeError("type error")
        ):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == []

    def test_value_error_returns_empty(self) -> None:
        with patch.object(
            self._APP_APP_MOD, "get_ai_chat_app_service", side_effect=ValueError("val error")
        ):
            result = _extract_excel_records_with_existing_parser({}, {}, "")
        assert result == []


# ===========================================================================
# build_multimodal_autonomous_plan  (top-level planner)
# ===========================================================================


class TestBuildMultimodalAutonomousPlan:
    """All tests mock _collect_artifacts to supply controlled artifacts."""

    def _patch_collect(self, artifacts):
        return patch.object(_planner, "_collect_artifacts", return_value=artifacts)

    def test_no_artifacts_returns_none(self) -> None:
        with self._patch_collect([]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="hello", runtime_context={}
            )
        assert result is None

    def test_none_runtime_context_treated_as_empty(self) -> None:
        with self._patch_collect([]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="hello", runtime_context=None
            )
        assert result is None

    def test_default_rag_plan_returned(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="what is this", runtime_context={}
            )
        assert result is not None
        assert result.intent == "multimodal_artifact_rag"
        assert result.risk_level == "low"

    def test_excel_import_plan_returned(self) -> None:
        art = _make_artifact(artifact_type="excel_records")
        ctx = {"excel_import": True, "excel_import_records": [{"row": 1}]}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="import records", runtime_context=ctx
            )
        assert result is not None
        assert result.intent == "multimodal_excel_import_to_db"
        assert result.risk_level == "medium"

    def test_document_export_plan_returned(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        ctx = {"document_export": True}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="generate report", runtime_context=ctx
            )
        assert result is not None
        assert result.intent == "multimodal_document_export"

    def test_version_added_to_rag_params_when_present(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context={"dataset_version": "v2"}
            )
        assert result is not None
        assert result.nodes[0].params.get("version") == "v2"

    def test_version_not_added_when_empty(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context={}
            )
        assert result is not None
        assert "version" not in result.nodes[0].params

    def test_metadata_filter_added_when_non_empty_dict(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        ctx = {"metadata_filter": {"tag": "vip"}}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context=ctx
            )
        assert result is not None
        assert result.nodes[0].params.get("metadata_filter") == {"tag": "vip"}

    def test_metadata_filter_not_added_when_empty_dict(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context={"metadata_filter": {}}
            )
        assert result is not None
        assert "metadata_filter" not in result.nodes[0].params

    def test_metadata_filter_not_added_when_not_dict(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context={"metadata_filter": "not-a-dict"}
            )
        assert result is not None
        assert "metadata_filter" not in result.nodes[0].params

    def test_top_k_clamped_to_1_minimum(self) -> None:
        # _coerce_int("-5") = -5 -> max(1, min(-5, 20)) = 1
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context={"dataset_top_k": "-5"}
            )
        assert result is not None
        assert result.nodes[0].params["top_k"] == 1

    def test_top_k_clamped_to_20_maximum(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context={"dataset_top_k": 99}
            )
        assert result is not None
        assert result.nodes[0].params["top_k"] == 20

    def test_artifact_metadata_enriched(self) -> None:
        art = _make_artifact(artifact_type="document_file", metadata={})
        ctx = {"dataset_id": "ds-99"}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context=ctx
            )
        assert result is not None
        assert art.metadata["dataset_id"] == "ds-99"
        assert art.metadata["multimodal_autonomous"] is True

    def test_excel_plan_node_structure(self) -> None:
        art = _make_artifact(artifact_type="excel_records")
        ctx = {"excel_import": True, "excel_import_records": [{"k": "v"}]}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="import", runtime_context=ctx
            )
        assert result is not None
        node = result.nodes[0]
        assert node.tool_id == "excel_import"
        assert node.action == "import_records"
        assert node.risk == "medium"
        assert node.idempotent is False

    def test_excel_import_records_in_node_params(self) -> None:
        records = [{"name": "Alice"}, {"name": "Bob"}]
        art = _make_artifact(artifact_type="excel_records")
        ctx = {"excel_import": True, "excel_import_records": records}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="import", runtime_context=ctx
            )
        assert result is not None
        assert result.nodes[0].params["records"] == records

    def test_document_export_node_structure(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        ctx = {"document_export": True}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="generate word report", runtime_context=ctx
            )
        assert result is not None
        node = result.nodes[0]
        assert node.tool_id == "generate_office_document"
        assert node.action == "execute"

    def test_document_export_output_format_xlsx_in_metadata(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        ctx = {"document_export": True, "output_format": "xlsx"}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="generate spreadsheet", runtime_context=ctx
            )
        assert result is not None
        assert result.metadata["document_export"]["output_format"] == "xlsx"

    def test_doc_export_requires_user_confirmation_in_metadata(self) -> None:
        art = _make_artifact(artifact_type="pdf_document")
        ctx = {"document_export": True}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="generate word report", runtime_context=ctx
            )
        assert result is not None
        assert result.metadata["document_export"]["requires_user_confirmation"] is True

    def test_rag_coerces_include_answer_and_rerank(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        ctx = {"include_answer": "false", "rerank": "true"}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="query", runtime_context=ctx
            )
        assert result is not None
        params = result.nodes[0].params
        assert params["include_answer"] is False
        assert params["rerank"] is True

    def test_plan_id_prefix_rag(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(user_id="u1", message="q", runtime_context={})
        assert result is not None
        assert result.plan_id.startswith("plan_multimodal_")

    def test_plan_id_prefix_excel(self) -> None:
        art = _make_artifact(artifact_type="excel_records")
        ctx = {"excel_import": True, "excel_import_records": [{"x": 1}]}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="import", runtime_context=ctx
            )
        assert result is not None
        assert result.plan_id.startswith("plan_multimodal_excel_")

    def test_plan_id_prefix_doc_export(self) -> None:
        art = _make_artifact(artifact_type="office_document")
        ctx = {"generate_document": True}
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="generate word report", runtime_context=ctx
            )
        assert result is not None
        assert result.plan_id.startswith("plan_multimodal_doc_export_")

    def test_rag_version_from_version_key(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="q", runtime_context={"version": "v3"}
            )
        assert result is not None
        assert result.nodes[0].params.get("version") == "v3"

    def test_rag_top_k_from_rag_top_k_key(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(
                user_id="u1", message="q", runtime_context={"rag_top_k": "8"}
            )
        assert result is not None
        assert result.nodes[0].params["top_k"] == 8

    def test_artifact_types_in_rag_metadata(self) -> None:
        art = _make_artifact(artifact_type="document_file")
        with self._patch_collect([art]):
            result = build_multimodal_autonomous_plan(user_id="u1", message="q", runtime_context={})
        assert result is not None
        assert "document_file" in result.metadata["artifact_types"]
