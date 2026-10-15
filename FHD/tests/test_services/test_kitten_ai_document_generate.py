"""测试 kitten_ai_document/generate 模块的文档生成功能。"""

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import pytest

from app.services.kitten_ai_document.generate import (
    _document_spec_timeout_sec,
    _extract_first_json_object,
    _strip_json_fence,
    build_docx_bytes,
    build_xlsx_bytes,
    generate_office_file,
)


@pytest.mark.parametrize("account", ["account-a", "account-b"])
def test_document_uses_scoped_authenticated_client(monkeypatch, account):
    from app.infrastructure.llm import client as llm

    fallback = object()
    monkeypatch.setattr(llm, "get_llm_client", lambda: fallback)
    monkeypatch.setattr("app.services.kitten_ai_document.generate.resolve_mode", lambda: "online")
    spec = {"title": account, "sections": [{"paragraphs": ["唯一标记", "文档内容读回"]}]}
    create = MagicMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(spec)))],
        )
    )
    authenticated = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    with llm.llm_client_scope(authenticated, f"{account}/model"):
        content, filename = generate_office_file("请生成文档", "docx")
        assert llm.get_openai_compatible_client() is authenticated
    assert filename == f"{account}.docx"
    assert create.call_args.kwargs["model"] == f"{account}/model"
    with ZipFile(BytesIO(content)) as archive:
        xml = archive.read("word/document.xml").decode()
        assert "唯一标记" in xml and "文档内容读回" in xml
    assert llm.get_openai_compatible_client() is fallback


# ---------------------------------------------------------------------------
# _strip_json_fence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('  ```json\n{"a": 1}\n```  ', '{"a": 1}'),
        ("", ""),
        ('```typescript\n{"a": 1}\n```', '{"a": 1}'),
    ],
)
def test_strip_json_fence(text, expected):
    assert _strip_json_fence(text) == expected


# ---------------------------------------------------------------------------
# _extract_first_json_object
# ---------------------------------------------------------------------------


class TestExtractFirstJsonObject:
    def test_simple_object(self):
        text = '{"key": "value"}'
        assert _extract_first_json_object(text) == '{"key": "value"}'

    def test_nested_object(self):
        text = '{"outer": {"inner": 1}}'
        assert _extract_first_json_object(text) == '{"outer": {"inner": 1}}'

    def test_with_surrounding_text(self):
        text = 'Here is the result: {"a": 1} and more'
        assert _extract_first_json_object(text) == '{"a": 1}'

    def test_with_string_containing_braces(self):
        text = '{"msg": "hello {world}"}'
        result = _extract_first_json_object(text)
        assert result == '{"msg": "hello {world}"}'

    def test_no_object(self):
        assert _extract_first_json_object("no json here") is None

    def test_empty_string(self):
        assert _extract_first_json_object("") is None

    def test_escaped_quotes_in_string(self):
        text = '{"key": "value with \\"quotes\\""}'
        result = _extract_first_json_object(text)
        assert result is not None
        assert '"key"' in result

    def test_multiple_objects_returns_first(self):
        text = '{"a": 1} some text {"b": 2}'
        result = _extract_first_json_object(text)
        assert result == '{"a": 1}'

    def test_array_not_matched(self):
        text = "[1, 2, 3]"
        assert _extract_first_json_object(text) is None

    def test_deeply_nested(self):
        text = '{"a": {"b": {"c": {"d": 1}}}}'
        result = _extract_first_json_object(text)
        assert result == '{"a": {"b": {"c": {"d": 1}}}}'

    def test_escaped_backslash_before_quote(self):
        text = '{"path": "C:\\\\Users\\\\test"}'
        result = _extract_first_json_object(text)
        assert result is not None


# ---------------------------------------------------------------------------
# _document_spec_timeout_sec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 180.0), ("60", 60.0), ("5", 15.0), ("999", 600.0), ("not_a_number", 180.0)],
)
def test_document_spec_timeout(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("FHD_DOCUMENT_SPEC_TIMEOUT_SEC", raising=False)
    else:
        monkeypatch.setenv("FHD_DOCUMENT_SPEC_TIMEOUT_SEC", value)
    assert _document_spec_timeout_sec() == expected


# ---------------------------------------------------------------------------
# build_docx_bytes
# ---------------------------------------------------------------------------


class TestBuildDocxBytes:
    @pytest.fixture
    def sample_spec(self):
        return {
            "title": "测试合同",
            "sections": [
                {
                    "heading": "一、合同双方",
                    "paragraphs": ["甲方：测试公司", "乙方：测试客户"],
                },
                {
                    "heading": "二、服务内容",
                    "paragraphs": ["提供AI服务"],
                },
            ],
            "tables": [
                {
                    "title": "费用明细",
                    "headers": ["项目", "金额"],
                    "rows": [["服务费", "10000"]],
                }
            ],
            "signatures": ["甲方（盖章）：________________"],
        }

    def test_builds_valid_docx(self, sample_spec):
        data, filename = build_docx_bytes(sample_spec)
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert filename.endswith(".docx")
        assert "测试合同" in filename

    def test_empty_spec(self):
        spec = {}
        data, filename = build_docx_bytes(spec)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_spec_with_no_sections(self):
        spec = {"title": "空文档"}
        data, filename = build_docx_bytes(spec)
        assert isinstance(data, bytes)

    def test_spec_with_empty_sections(self):
        spec = {"title": "测试", "sections": []}
        data, filename = build_docx_bytes(spec)
        assert isinstance(data, bytes)

    def test_spec_with_non_dict_section_skipped(self):
        spec = {
            "title": "测试",
            "sections": ["not a dict", {"heading": "有效", "paragraphs": ["ok"]}],
        }
        data, filename = build_docx_bytes(spec)
        assert isinstance(data, bytes)

    def test_spec_with_no_tables(self):
        spec = {"title": "测试", "sections": [], "tables": []}
        data, filename = build_docx_bytes(spec)
        assert isinstance(data, bytes)

    def test_spec_with_non_dict_table_skipped(self):
        spec = {"title": "测试", "tables": ["not a dict"]}
        data, filename = build_docx_bytes(spec)
        assert isinstance(data, bytes)

    def test_filename_sanitization(self):
        spec = {"title": "test/file\\name"}
        data, filename = build_docx_bytes(spec)
        assert "/" not in filename
        assert "\\" not in filename

    def test_long_title_truncated(self):
        spec = {"title": "A" * 100}
        data, filename = build_docx_bytes(spec)
        assert len(filename) < 60


# ---------------------------------------------------------------------------
# build_xlsx_bytes
# ---------------------------------------------------------------------------


class TestBuildXlsxBytes:
    @pytest.fixture
    def sample_spec(self):
        return {
            "title": "报价表",
            "sheets": [
                {
                    "name": "产品报价",
                    "headers": ["产品", "单价", "数量"],
                    "rows": [["产品A", 100, 5], ["产品B", 200, 3]],
                    "column_widths": [20, 12, 10],
                }
            ],
        }

    def test_builds_valid_xlsx(self, sample_spec):
        data, filename = build_xlsx_bytes(sample_spec)
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert filename.endswith(".xlsx")
        assert "报价表" in filename

    def test_empty_spec(self):
        spec = {}
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_no_sheets(self):
        spec = {"title": "测试", "sheets": []}
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_non_dict_sheet_skipped(self):
        spec = {
            "title": "测试",
            "sheets": ["not a dict", {"name": "Sheet1", "headers": ["A"], "rows": [["1"]]}],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_multiple_sheets(self):
        spec = {
            "title": "多Sheet",
            "sheets": [
                {"name": "Sheet1", "headers": ["A"], "rows": [["1"]]},
                {"name": "Sheet2", "headers": ["B"], "rows": [["2"]]},
            ],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_sheet_with_no_headers(self):
        spec = {
            "title": "测试",
            "sheets": [{"name": "Sheet1", "rows": [["1", "2"]]}],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_sheet_with_column_widths(self):
        spec = {
            "title": "测试",
            "sheets": [
                {
                    "name": "Sheet1",
                    "headers": ["A", "B"],
                    "rows": [["1", "2"]],
                    "column_widths": [15, 20],
                }
            ],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_invalid_column_widths_ignored(self):
        spec = {
            "title": "测试",
            "sheets": [
                {
                    "name": "Sheet1",
                    "headers": ["A"],
                    "rows": [["1"]],
                    "column_widths": ["invalid"],
                }
            ],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_long_sheet_name_truncated(self):
        spec = {
            "title": "测试",
            "sheets": [{"name": "A" * 50, "headers": ["A"], "rows": [["1"]]}],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)

    def test_non_list_rows_skipped(self):
        spec = {
            "title": "测试",
            "sheets": [{"name": "Sheet1", "headers": ["A"], "rows": ["not a list", ["1"]]}],
        }
        data, filename = build_xlsx_bytes(spec)
        assert isinstance(data, bytes)
