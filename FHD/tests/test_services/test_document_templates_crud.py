"""Tests for app.services.document_templates.crud — comprehensive coverage."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.document_templates.crud import (
    _build_template_payload_from_row,
    _j,
    _normalize_db_template_id,
    create_template_with_payload,
    update_template_with_payload,
)


# ========================= _normalize_db_template_id =====================


class TestNormalizeDbTemplateId:
    def test_plain_int(self):
        assert _normalize_db_template_id("42") == 42

    def test_db_prefix(self):
        assert _normalize_db_template_id("db:42") == 42

    def test_db_prefix_with_spaces(self):
        assert _normalize_db_template_id("db: 42") == 42

    def test_int_input(self):
        assert _normalize_db_template_id(42) == 42

    def test_non_numeric(self):
        assert _normalize_db_template_id("abc") is None

    def test_empty(self):
        assert _normalize_db_template_id("") is None

    def test_none(self):
        assert _normalize_db_template_id(None) is None

    def test_whitespace(self):
        assert _normalize_db_template_id("  ") is None

    def test_float_string(self):
        assert _normalize_db_template_id("3.14") is None

    def test_negative(self):
        assert _normalize_db_template_id("-1") is None


# ========================= _j =====================


class TestJ:
    """Test _j helper function."""

    def test_returns_json_response(self):
        result = _j({"success": True})
        assert result.status_code == 200
        data = result.get_json()
        assert data["success"] is True

    def test_custom_status(self):
        result = _j({"error": "bad"}, 400)
        assert result.status_code == 400
        data = result.get_json()
        assert data["error"] == "bad"


# ========================= _ensure_template_tables_ready =====================


class TestEnsureTemplateTablesReady:
    """Test _ensure_template_tables_ready helper."""

    def test_calls_init_template_tables(self):
        with patch("app.db.init_db.init_template_tables") as mock_init:
            from app.services.document_templates.crud import _ensure_template_tables_ready
            _ensure_template_tables_ready()
            mock_init.assert_called_once()

    def test_handles_error_gracefully(self):
        with patch("app.db.init_db.init_template_tables", side_effect=RuntimeError("db error")):
            from app.services.document_templates.crud import _ensure_template_tables_ready
            # Should not raise
            _ensure_template_tables_ready()


# ========================= _build_template_payload_from_row =====================


class TestBuildTemplatePayloadFromRow:
    """Test _build_template_payload_from_row helper."""

    def test_basic_row(self):
        row = MagicMock()
        row.id = 1
        row.template_name = "测试模板"
        row.template_type = "出货明细"
        row.original_file_path = "/path/to/file.xlsx"
        row.analyzed_data = json.dumps({
            "business_scope": "orders",
            "category": "excel",
            "fields": [{"label": "产品型号", "name": "model"}],
            "preview_data": {"sample": "data"},
            "source": "upload",
        })
        row.business_rules = json.dumps({
            "business_scope": "orders",
            "source": "upload",
        })
        row.editable_config = json.dumps([{"label": "产品型号", "name": "model"}])

        result = _build_template_payload_from_row(row)
        assert result["id"] == "db:1"
        assert result["db_id"] == 1
        assert result["name"] == "测试模板"
        assert result["template_type"] == "出货明细"
        assert result["business_scope"] == "orders"
        assert result["category"] == "excel"
        assert result["source"] == "upload"
        assert result["file_path"] == "/path/to/file.xlsx"
        assert len(result["fields"]) == 1
        assert result["preview_data"]["sample"] == "data"

    def test_row_with_empty_analyzed_data(self):
        row = MagicMock()
        row.id = 2
        row.template_name = "空模板"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = None
        row.business_rules = None
        row.editable_config = None

        result = _build_template_payload_from_row(row)
        assert result["id"] == "db:2"
        assert result["fields"] == []
        assert result["preview_data"] == {}
        assert result["category"] == "excel"  # default

    def test_row_with_invalid_category_defaults_to_excel(self):
        row = MagicMock()
        row.id = 3
        row.template_name = "无效分类"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = json.dumps({"category": "pdf"})
        row.business_rules = json.dumps({})
        row.editable_config = None

        result = _build_template_payload_from_row(row)
        assert result["category"] == "excel"

    def test_row_with_word_category(self):
        row = MagicMock()
        row.id = 4
        row.template_name = "Word模板"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = json.dumps({"category": "word"})
        row.business_rules = json.dumps({})
        row.editable_config = None

        result = _build_template_payload_from_row(row)
        assert result["category"] == "word"

    def test_business_scope_from_analyzed_data(self):
        row = MagicMock()
        row.id = 5
        row.template_name = "模板"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = json.dumps({"business_scope": "customers"})
        row.business_rules = json.dumps({})
        row.editable_config = None

        result = _build_template_payload_from_row(row)
        assert result["business_scope"] == "customers"

    def test_business_scope_from_business_rules_takes_priority(self):
        row = MagicMock()
        row.id = 6
        row.template_name = "模板"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = json.dumps({"business_scope": "orders"})
        row.business_rules = json.dumps({"business_scope": "customers"})
        row.editable_config = None

        result = _build_template_payload_from_row(row)
        assert result["business_scope"] == "customers"

    def test_fields_from_editable_config_fallback(self):
        row = MagicMock()
        row.id = 7
        row.template_name = "模板"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = json.dumps({})
        row.business_rules = json.dumps({})
        row.editable_config = json.dumps([{"label": "字段A"}])

        result = _build_template_payload_from_row(row)
        assert len(result["fields"]) == 1
        assert result["fields"][0]["label"] == "字段A"

    def test_source_from_business_rules(self):
        row = MagicMock()
        row.id = 8
        row.template_name = "模板"
        row.template_type = ""
        row.original_file_path = None
        row.analyzed_data = json.dumps({"source": "upload"})
        row.business_rules = json.dumps({"source": "generated"})
        row.editable_config = None

        result = _build_template_payload_from_row(row)
        assert result["source"] == "generated"


# ========================= create_template_with_payload =====================


class TestCreateTemplateWithPayload:
    """Test create_template_with_payload function."""

    def test_none_payload_uses_empty_dict(self):
        with patch(
            "app.services.document_templates.crud._create_template_with_payload_inner"
        ) as mock_inner:
            mock_inner.return_value = MagicMock()
            create_template_with_payload(None)
            mock_inner.assert_called_once_with({})

    def test_empty_name_returns_400(self):
        result = create_template_with_payload({"name": ""})
        data = result.get_json()
        assert data["success"] is False
        assert "模板名称不能为空" in data["message"]

    def test_none_name_returns_400(self):
        result = create_template_with_payload({})
        data = result.get_json()
        assert data["success"] is False

    def test_whitespace_name_returns_400(self):
        result = create_template_with_payload({"name": "   "})
        data = result.get_json()
        assert data["success"] is False

    def test_successful_create(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 42
        mock_db.execute.return_value = mock_result
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = create_template_with_payload({
                "name": "测试模板",
                "template_type": "出货明细",
                "business_scope": "orders",
                "fields": [{"label": "产品型号"}],
                "preview_data": {"sample": "data"},
            })

        data = result.get_json()
        assert data["success"] is True
        assert data["template"]["name"] == "测试模板"
        assert data["template"]["db_id"] == 42

    def test_create_with_default_type(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = create_template_with_payload({"name": "默认类型模板"})

        data = result.get_json()
        assert data["success"] is True
        assert data["template"]["template_type"] == "Excel"

    def test_create_with_invalid_category_defaults_excel(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = create_template_with_payload({
                "name": "无效分类",
                "category": "pdf",
            })

        data = result.get_json()
        assert data["success"] is True
        assert data["template"]["category"] == "excel"

    def test_create_with_word_category(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = create_template_with_payload({
                "name": "Word模板",
                "category": "word",
            })

        data = result.get_json()
        assert data["success"] is True
        assert data["template"]["category"] == "word"

    def test_create_with_scope_validation_failure(self):
        """Business scope with missing required terms should fail."""
        with patch("app.db.init_db.init_template_tables"), \
             patch(
                "app.services.document_templates.crud._validate_required_terms",
                return_value=(False, ["产品型号", "数量"]),
            ):
            result = create_template_with_payload({
                "name": "不合规模板",
                "business_scope": "orders",
            })

        data = result.get_json()
        assert data["success"] is False
        assert "必填字段未匹配" in data["message"]
        assert result.status_code == 400

    def test_create_with_db_error_returns_500(self):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db connection failed")), \
             patch("app.db.init_db.init_template_tables"):
            result = create_template_with_payload({"name": "测试"})

        data = result.get_json()
        assert data["success"] is False
        assert result.status_code == 500

    def test_create_uses_template_name_key(self):
        """Both 'name' and 'template_name' should work."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = create_template_with_payload({"template_name": "通过template_name"})

        data = result.get_json()
        assert data["success"] is True
        assert data["template"]["name"] == "通过template_name"

    def test_create_usage_log_failure_does_not_fail(self):
        """Template usage log failure should not affect create result."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 1
        mock_db.execute.side_effect = [mock_result, RuntimeError("log table missing")]
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = create_template_with_payload({"name": "日志失败模板"})

        data = result.get_json()
        assert data["success"] is True


# ========================= update_template_with_payload =====================


class TestUpdateTemplateWithPayload:
    """Test update_template_with_payload function."""

    def test_none_payload_uses_empty_dict(self):
        with patch(
            "app.services.document_templates.crud._update_template_with_payload_inner"
        ) as mock_inner:
            mock_inner.return_value = MagicMock()
            update_template_with_payload(None)
            mock_inner.assert_called_once_with({})

    def test_invalid_id_returns_400(self):
        result = update_template_with_payload({"id": "abc"})
        data = result.get_json()
        assert data["success"] is False
        assert "模板 id 无效" in data["message"]

    def test_none_id_returns_400(self):
        result = update_template_with_payload({"id": None})
        data = result.get_json()
        assert data["success"] is False

    def test_empty_id_returns_400(self):
        result = update_template_with_payload({"id": ""})
        data = result.get_json()
        assert data["success"] is False

    def test_template_not_found_returns_404(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({"id": "db:999"})

        data = result.get_json()
        assert data["success"] is False
        assert "模板不存在" in data["message"]
        assert result.status_code == 404

    def test_successful_update_name(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "旧名"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders", "category": "excel"})
        mock_row.business_rules = json.dumps({"business_scope": "orders", "source": "db"})
        mock_row.editable_config = json.dumps([])

        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=mock_row)),  # SELECT
            MagicMock(),  # UPDATE
            MagicMock(),  # usage log
            MagicMock(fetchone=MagicMock(return_value=mock_row)),  # refreshed SELECT
        ]
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "name": "新名",
            })

        data = result.get_json()
        assert data["success"] is True
        assert "模板更新成功" in data["message"]

    def test_scope_mismatch_with_enforce_returns_400(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders"})
        mock_row.business_rules = json.dumps({"business_scope": "orders"})

        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = mock_row

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "business_scope": "customers",
                "enforce_scope_match": True,
            })

        data = result.get_json()
        assert data["success"] is False
        assert "同业务范围" in data["message"]
        assert result.status_code == 400

    def test_scope_validation_failure_returns_400(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders"})
        mock_row.business_rules = json.dumps({"business_scope": "orders"})

        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = mock_row

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch(
                "app.services.document_templates.crud._validate_required_terms",
                return_value=(False, ["产品型号"]),
            ):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "business_scope": "orders",
            })

        data = result.get_json()
        assert data["success"] is False
        assert "必填字段未匹配" in data["message"]

    def test_update_with_db_error_returns_500(self):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db error")), \
             patch("app.db.init_db.init_template_tables"):
            result = update_template_with_payload({"id": "db:1"})

        data = result.get_json()
        assert data["success"] is False
        assert result.status_code == 500

    def test_update_with_fields(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders", "category": "excel"})
        mock_row.business_rules = json.dumps({"business_scope": "orders", "source": "db"})
        mock_row.editable_config = json.dumps([])

        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
            MagicMock(),  # UPDATE
            MagicMock(),  # usage log
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
        ]
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "fields": [{"label": "新产品型号", "name": "new_model"}],
            })

        data = result.get_json()
        assert data["success"] is True

    def test_update_with_preview_data_merges(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({
            "business_scope": "orders",
            "category": "excel",
            "preview_data": {"old_key": "old_val"},
        })
        mock_row.business_rules = json.dumps({"business_scope": "orders", "source": "db"})
        mock_row.editable_config = json.dumps([])

        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
            MagicMock(),
            MagicMock(),
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
        ]
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "preview_data": {"new_key": "new_val"},
            })

        data = result.get_json()
        assert data["success"] is True

    def test_update_with_file_path(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders", "category": "excel"})
        mock_row.business_rules = json.dumps({"business_scope": "orders", "source": "db"})
        mock_row.editable_config = json.dumps([])

        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
            MagicMock(),
            MagicMock(),
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
        ]
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "file_path": "/new/path.xlsx",
            })

        data = result.get_json()
        assert data["success"] is True

    def test_update_usage_log_failure_does_not_fail(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders", "category": "excel"})
        mock_row.business_rules = json.dumps({"business_scope": "orders", "source": "db"})
        mock_row.editable_config = json.dumps([])

        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=mock_row)),
            MagicMock(),  # UPDATE
            RuntimeError("log table missing"),  # usage log fails
            MagicMock(fetchone=MagicMock(return_value=mock_row)),  # refreshed SELECT
        ]
        mock_db.commit = MagicMock()

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"), \
             patch("app.services.document_templates.crud._validate_required_terms", return_value=(True, [])):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "name": "更新名",
            })

        data = result.get_json()
        assert data["success"] is True

    def test_update_with_replace_mode_enforces_scope(self):
        """replace_mode=True should enforce scope match."""
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_name = "模板"
        mock_row.template_type = "出货明细"
        mock_row.original_file_path = None
        mock_row.analyzed_data = json.dumps({"business_scope": "orders"})
        mock_row.business_rules = json.dumps({"business_scope": "orders"})

        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = mock_row

        with patch("app.db.session.get_db") as mock_get_db, \
             patch("app.db.init_db.init_template_tables"):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = update_template_with_payload({
                "id": "db:1",
                "business_scope": "customers",
                "replace_mode": True,
            })

        data = result.get_json()
        assert data["success"] is False
        assert result.status_code == 400
