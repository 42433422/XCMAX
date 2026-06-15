"""测试文档模板分析器模块。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import pytest

from app.services.document_templates.analyzer import (
    _cleanup_progress_tracking,
    _collect_docx_part_text,
    _extract_word_placeholder_fields,
    _j,
    _list_docx_xml_parts,
    _mark_progress_completed,
    _safe_remove,
    _update_progress,
    analyze_template_with_upload,
    analysis_progress,
    progress_lock,
)


class TestSafeRemove:
    """测试安全文件删除。"""

    def test_removes_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        _safe_remove(str(f))
        assert not f.exists()

    def test_no_error_on_nonexistent_file(self):
        _safe_remove("/nonexistent/path/file.txt")

    def test_no_error_on_empty_path(self):
        _safe_remove("")

    def test_no_error_on_none_path(self):
        _safe_remove(None)

    def test_no_error_on_directory(self, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        _safe_remove(str(d))
        assert d.exists()


class TestJ:
    """测试 JSON 响应辅助函数。"""

    def test_returns_json_response(self):
        result = _j({"success": True})
        assert result.status_code == 200

    def test_custom_status(self):
        result = _j({"success": False}, 400)
        assert result.status_code == 400

    def test_response_body_contains_data(self):
        result = _j({"key": "value"})
        body = result.body.decode("utf-8")
        data = json.loads(body)
        assert data["key"] == "value"


class TestProgressTracking:
    """测试进度追踪。"""

    def test_update_progress(self):
        task_id = "test-task-1"
        with progress_lock:
            analysis_progress[task_id] = {"percent": 0, "step": 1, "message": "start", "completed": False}

        _update_progress(task_id, 50, 2, "halfway")

        with progress_lock:
            assert analysis_progress[task_id]["percent"] == 50
            assert analysis_progress[task_id]["step"] == 2
            assert analysis_progress[task_id]["message"] == "halfway"
            del analysis_progress[task_id]

    def test_update_progress_nonexistent_task(self):
        _update_progress("nonexistent-task", 50, 2, "test")

    def test_mark_progress_completed(self):
        task_id = "test-task-2"
        with progress_lock:
            analysis_progress[task_id] = {"percent": 0, "step": 1, "message": "", "completed": False}

        _mark_progress_completed(task_id, 100, 3, "done")

        with progress_lock:
            assert analysis_progress[task_id]["completed"] is True
            assert analysis_progress[task_id]["percent"] == 100
            del analysis_progress[task_id]

    def test_cleanup_progress_tracking(self):
        task_id = "test-task-3"
        with progress_lock:
            analysis_progress[task_id] = {"percent": 50}

        _cleanup_progress_tracking(task_id)

        with progress_lock:
            assert task_id not in analysis_progress


class TestCollectDocxPartText:
    """测试 DOCX XML 文本提取。"""

    def test_extracts_text_from_simple_xml(self):
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = f'<w:document xmlns:w="{ns}"><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:document>'
        result = _collect_docx_part_text(xml.encode("utf-8"))
        assert "Hello" in result

    def test_returns_empty_on_invalid_xml(self):
        result = _collect_docx_part_text(b"not xml")
        assert result == ""

    def test_extracts_multiple_texts(self):
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = (
            f'<w:document xmlns:w="{ns}">'
            f'<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
            f'<w:p><w:r><w:t>World</w:t></w:r></w:p>'
            f"</w:document>"
        )
        result = _collect_docx_part_text(xml.encode("utf-8"))
        assert "Hello" in result
        assert "World" in result

    def test_handles_tail_text(self):
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = f'<w:document xmlns:w="{ns}"><w:p><w:r><w:t>Main</w:t>tail</w:r></w:p></w:document>'
        result = _collect_docx_part_text(xml.encode("utf-8"))
        assert "Main" in result

    def test_empty_document(self):
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = f'<w:document xmlns:w="{ns}"></w:document>'
        result = _collect_docx_part_text(xml.encode("utf-8"))
        assert result == ""


class TestListDocxXmlParts:
    """测试 DOCX XML 部件列表。"""

    def test_finds_document_xml(self):
        names = ["word/document.xml", "[Content_Types].xml"]
        result = _list_docx_xml_parts(names)
        assert "word/document.xml" in result

    def test_finds_header_and_footer(self):
        names = ["word/document.xml", "word/header1.xml", "word/footer1.xml"]
        result = _list_docx_xml_parts(names)
        assert "word/header1.xml" in result
        assert "word/footer1.xml" in result

    def test_excludes_non_word_parts(self):
        names = ["word/document.xml", "word/media/image1.png", "xl/workbook.xml"]
        result = _list_docx_xml_parts(names)
        assert "word/media/image1.png" not in result
        assert "xl/workbook.xml" not in result

    def test_ensures_document_xml_included_when_in_names(self):
        names = ["word/document.xml", "word/header1.xml"]
        result = _list_docx_xml_parts(names)
        assert "word/document.xml" in result

    def test_deduplication(self):
        names = ["word/document.xml", "word/document.xml"]
        result = _list_docx_xml_parts(names)
        assert result.count("word/document.xml") == 1


class TestExtractWordPlaceholderFields:
    """测试 Word 占位符提取。"""

    def _create_docx(self, text_content: str, tmp_path) -> str:
        """创建包含指定文本的 .docx 文件。"""
        docx_path = str(tmp_path / "test.docx")
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml_content = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<w:document xmlns:w="{ns}">'
            f"<w:p><w:r><w:t>{text_content}</w:t></w:r></w:p>"
            f"</w:document>"
        )

        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("word/document.xml", xml_content)
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')

        return docx_path

    def test_extracts_mustache_placeholders(self, tmp_path):
        docx_path = self._create_docx("Hello {{name}} and {{age}}", tmp_path)
        fields, tokens, text = _extract_word_placeholder_fields(docx_path)
        assert len(fields) >= 2
        labels = [f["label"] for f in fields]
        assert "name" in labels
        assert "age" in labels

    def test_extracts_dollar_placeholders(self, tmp_path):
        docx_path = self._create_docx("Price: ${price}", tmp_path)
        fields, tokens, text = _extract_word_placeholder_fields(docx_path)
        labels = [f["label"] for f in fields]
        assert "price" in labels

    def test_extracts_bracket_placeholders(self, tmp_path):
        docx_path = self._create_docx("Item [[item_name]]", tmp_path)
        fields, tokens, text = _extract_word_placeholder_fields(docx_path)
        labels = [f["label"] for f in fields]
        assert "item_name" in labels

    def test_extracts_jinja_placeholders(self, tmp_path):
        docx_path = self._create_docx("{% if show %}content{% endif %}", tmp_path)
        fields, tokens, text = _extract_word_placeholder_fields(docx_path)
        assert len(tokens) > 0

    def test_no_placeholders_returns_empty(self, tmp_path):
        docx_path = self._create_docx("Just plain text", tmp_path)
        fields, tokens, text = _extract_word_placeholder_fields(docx_path)
        assert len(fields) == 0
        assert len(tokens) == 0

    def test_fields_have_correct_structure(self, tmp_path):
        docx_path = self._create_docx("{{name}}", tmp_path)
        fields, _, _ = _extract_word_placeholder_fields(docx_path)
        assert len(fields) == 1
        assert fields[0]["label"] == "name"
        assert fields[0]["value"] == ""
        assert fields[0]["type"] == "dynamic"

    def test_deduplicates_tokens(self, tmp_path):
        docx_path = self._create_docx("{{name}} and {{name}}", tmp_path)
        fields, tokens, _ = _extract_word_placeholder_fields(docx_path)
        assert len(tokens) == 1

    def test_mixed_placeholder_types(self, tmp_path):
        docx_path = self._create_docx("{{name}} ${amount} [[code]]", tmp_path)
        fields, tokens, _ = _extract_word_placeholder_fields(docx_path)
        labels = [f["label"] for f in fields]
        assert "name" in labels
        assert "amount" in labels
        assert "code" in labels


class TestAnalyzeTemplateWithUpload:
    """测试模板分析主入口。"""

    def test_no_file_returns_400(self):
        result = analyze_template_with_upload(None, "test")
        assert result.status_code == 400
        data = result.get_json()
        assert data["success"] is False

    def test_empty_filename_returns_400(self):
        mock_file = MagicMock()
        mock_file.filename = ""
        result = analyze_template_with_upload(mock_file, "test")
        assert result.status_code == 400

    def test_unsupported_file_type_returns_400(self, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "test.pdf"
        mock_file.save = MagicMock()
        result = analyze_template_with_upload(mock_file, "test")
        assert result.status_code == 400

    def test_excel_file_routes_to_excel_analyzer(self, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "test.xlsx"
        mock_file.save = MagicMock()

        with patch(
            "app.services.document_templates.analyzer._analyze_excel_template"
        ) as mock_analyze:
            mock_analyze.return_value = _j({"success": True, "template_type": "excel"})
            result = analyze_template_with_upload(mock_file, "test")
            mock_analyze.assert_called_once()

    def test_docx_file_routes_to_word_analyzer(self, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "test.docx"
        mock_file.save = MagicMock()

        with patch(
            "app.services.document_templates.analyzer._analyze_word_template"
        ) as mock_analyze:
            mock_analyze.return_value = _j({"success": True, "template_type": "word"})
            result = analyze_template_with_upload(mock_file, "test")
            mock_analyze.assert_called_once()

    def test_image_file_routes_to_label_analyzer(self, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "test.png"
        mock_file.save = MagicMock()

        with patch(
            "app.services.document_templates.analyzer._analyze_label_template"
        ) as mock_analyze:
            mock_analyze.return_value = _j({"success": True, "template_type": "label"})
            result = analyze_template_with_upload(mock_file, "test")
            mock_analyze.assert_called_once()

    def test_recoverable_error_returns_500(self, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "test.xlsx"
        mock_file.save = MagicMock(side_effect=OSError("disk error"))

        result = analyze_template_with_upload(mock_file, "test")
        assert result.status_code == 500


class TestAnalyzeWordTemplate:
    """测试 Word 模板分析。"""

    def _create_docx(self, text_content: str, tmp_path) -> str:
        docx_path = str(tmp_path / "template.docx")
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml_content = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<w:document xmlns:w="{ns}">'
            f"<w:p><w:r><w:t>{text_content}</w:t></w:r></w:p>"
            f"</w:document>"
        )
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("word/document.xml", xml_content)
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')
        return docx_path

    def test_no_placeholders_returns_400(self, tmp_path):
        docx_path = self._create_docx("Just plain text", tmp_path)

        from app.services.document_templates.analyzer import _analyze_word_template

        result = _analyze_word_template(docx_path, "test", "plain.docx", "task-1")
        assert result.status_code == 400
        data = result.get_json()
        assert data["success"] is False

    def test_with_placeholders_returns_success(self, tmp_path):
        docx_path = self._create_docx("Dear {{name}}, price is ${{amount}}", tmp_path)

        from app.services.document_templates.analyzer import _analyze_word_template

        with patch(
            "app.services.document_templates.analyzer._validate_required_terms",
            return_value=(True, []),
        ):
            result = _analyze_word_template(docx_path, "test", "template.docx", "task-2")

        data = result.get_json()
        assert data["success"] is True
        assert data["template_type"] == "word"
        assert len(data["fields"]) >= 1

    def test_missing_required_terms_returns_400(self, tmp_path):
        docx_path = self._create_docx("{{name}}", tmp_path)

        from app.services.document_templates.analyzer import _analyze_word_template

        with patch(
            "app.services.document_templates.analyzer._validate_required_terms",
            return_value=(False, ["产品名称"]),
        ):
            result = _analyze_word_template(docx_path, "test", "template.docx", "task-3")

        assert result.status_code == 400
        data = result.get_json()
        assert data["success"] is False
        assert "missing_terms" in data

    def test_template_name_fallback_to_filename(self, tmp_path):
        docx_path = self._create_docx("{{name}}", tmp_path)

        from app.services.document_templates.analyzer import _analyze_word_template

        with patch(
            "app.services.document_templates.analyzer._validate_required_terms",
            return_value=(True, []),
        ):
            result = _analyze_word_template(docx_path, "", "my_template.docx", "task-4")

        data = result.get_json()
        assert data["success"] is True
        assert data["template_name"] == "my_template"


class TestAnalyzeExcelTemplate:
    """测试 Excel 模板分析。"""

    def test_excel_analysis_failure_returns_500(self, tmp_path):
        from app.services.document_templates.analyzer import _analyze_excel_template

        mock_skill_instance = MagicMock()
        mock_skill_instance.execute.return_value = {"success": False, "error": "parse error"}
        mock_skill_module = MagicMock()
        mock_skill_module.get_excel_analyzer_skill.return_value = mock_skill_instance

        with patch.dict("sys.modules", {
            "app.infrastructure.skills.excel_analyzer": mock_skill_module,
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer": mock_skill_module,
        }):
            result = _analyze_excel_template(
                str(tmp_path / "fake.xlsx"), "test", "fake.xlsx", "task-excel"
            )

        assert result.status_code == 500

    def test_excel_analysis_success(self, tmp_path):
        from app.services.document_templates.analyzer import _analyze_excel_template

        mock_skill_instance = MagicMock()
        mock_skill_instance.execute.return_value = {
            "success": True,
            "cells": {"A1": {"value": "产品名称", "purpose": "header"}},
            "editable_ranges": [],
            "merged_cells": [],
            "structure": {},
        }
        mock_skill_module = MagicMock()
        mock_skill_module.get_excel_analyzer_skill.return_value = mock_skill_instance

        with patch.dict("sys.modules", {
            "app.infrastructure.skills.excel_analyzer": mock_skill_module,
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer": mock_skill_module,
        }):
            with patch(
                "app.services.document_templates.analyzer._extract_structured_excel_preview",
                return_value={"fields": [{"label": "产品名称", "value": "", "type": "dynamic"}], "sample_rows": [], "sheet_name": "出货"},
            ):
                with patch(
                    "app.services.document_templates.analyzer._extract_excel_grid_preview",
                    return_value={},
                ):
                    with patch(
                        "app.services.document_templates.analyzer._validate_required_terms",
                        return_value=(True, []),
                    ):
                        result = _analyze_excel_template(
                            str(tmp_path / "fake.xlsx"), "test", "fake.xlsx", "task-excel2"
                        )

        data = result.get_json()
        assert data["success"] is True
        assert data["template_type"] == "excel"


class TestAnalyzeLabelTemplate:
    """测试标签模板分析。"""

    def test_label_analysis_failure_returns_500(self, tmp_path):
        from app.services.document_templates.analyzer import _analyze_label_template

        mock_skill_instance = MagicMock()
        mock_skill_instance.execute.return_value = {"success": False, "error": "OCR failed"}
        mock_skill_module = MagicMock()
        mock_skill_module.LabelTemplateGeneratorSkill.return_value = mock_skill_instance

        with patch.dict("sys.modules", {
            "app.services.skills": mock_skill_module,
            "app.services.skills.label_template_generator": mock_skill_module,
            "app.services.skills.label_template_generator.label_template_generator": mock_skill_module,
        }):
            result = _analyze_label_template(
                str(tmp_path / "fake.png"), "test", "fake.png", "task-label"
            )

        assert result.status_code == 500

    def test_label_analysis_success_with_fields(self, tmp_path):
        from app.services.document_templates.analyzer import _analyze_label_template

        mock_skill_instance = MagicMock()
        mock_skill_instance.execute.return_value = {
            "success": True,
            "analysis": {"size": {"width": 100, "height": 50}, "colors": {}},
            "ocr_result": {
                "fields": [
                    {"label": "品名", "value": "示例", "type": "fixed_label", "position": {}, "confidence": 0.9}
                ],
                "grid": {"rows": 2, "cols": 3},
            },
            "code": "class LabelGenerator",
        }
        mock_skill_module = MagicMock()
        mock_skill_module.LabelTemplateGeneratorSkill.return_value = mock_skill_instance

        with patch.dict("sys.modules", {
            "app.services.skills": mock_skill_module,
            "app.services.skills.label_template_generator": mock_skill_module,
            "app.services.skills.label_template_generator.label_template_generator": mock_skill_module,
        }):
            result = _analyze_label_template(
                str(tmp_path / "fake.png"), "test", "fake.png", "task-label2"
            )

        data = result.get_json()
        assert data["success"] is True
        assert data["template_type"] == "label"
        assert len(data["fields"]) >= 1

    def test_label_analysis_no_ocr_fields_uses_defaults(self, tmp_path):
        from app.services.document_templates.analyzer import _analyze_label_template

        mock_skill_instance = MagicMock()
        mock_skill_instance.execute.return_value = {
            "success": True,
            "analysis": {"size": {}, "colors": {}},
            "ocr_result": {},
            "code": "",
        }
        mock_skill_module = MagicMock()
        mock_skill_module.LabelTemplateGeneratorSkill.return_value = mock_skill_instance

        with patch.dict("sys.modules", {
            "app.services.skills": mock_skill_module,
            "app.services.skills.label_template_generator": mock_skill_module,
            "app.services.skills.label_template_generator.label_template_generator": mock_skill_module,
        }):
            result = _analyze_label_template(
                str(tmp_path / "fake.png"), "", "fake.png", "task-label3"
            )

        data = result.get_json()
        assert data["success"] is True
        assert len(data["fields"]) >= 1
