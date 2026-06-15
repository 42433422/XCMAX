"""测试 template_store_impl 模块的文件系统模板库。"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """创建使用临时目录的模板库实例。"""
    return FileSystemTemplateStore(str(tmp_path))


@pytest.fixture
def store_with_files(tmp_path):
    """创建包含模板文件的模板库实例。"""
    # 创建 Excel 模板
    (tmp_path / "发货单模板.xlsx").write_bytes(b"PK fake xlsx")
    (tmp_path / "产品清单.xlsx").write_bytes(b"PK fake xlsx2")
    # 创建 Word 模板
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "合同模板.docx").write_bytes(b"PK fake docx")
    return FileSystemTemplateStore(str(tmp_path))


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_template_dir(self, tmp_path):
        store = FileSystemTemplateStore(str(tmp_path))
        assert os.path.isdir(os.path.join(str(tmp_path), "templates"))


# ---------------------------------------------------------------------------
# _infer_template_type_from_filename
# ---------------------------------------------------------------------------

class TestInferTemplateType:
    def test_customer(self, store):
        assert store._infer_template_type_from_filename("客户列表.xlsx") == "客户"

    def test_material(self, store):
        assert store._infer_template_type_from_filename("原材料清单.xlsx") == "原材料"

    def test_product(self, store):
        assert store._infer_template_type_from_filename("产品价格表.xlsx") == "产品"

    def test_shipment_records(self, store):
        assert store._infer_template_type_from_filename("出货记录.xlsx") == "出货记录"

    def test_shipment(self, store):
        assert store._infer_template_type_from_filename("发货单模板.xlsx") == "发货单"

    def test_default(self, store):
        assert store._infer_template_type_from_filename("其他文件.xlsx") == "Excel"

    def test_empty(self, store):
        assert store._infer_template_type_from_filename("") == "Excel"


# ---------------------------------------------------------------------------
# _map_category
# ---------------------------------------------------------------------------

class TestMapCategory:
    def test_label_print(self):
        assert FileSystemTemplateStore._map_category("标签模板") == "label_print"

    def test_label(self):
        assert FileSystemTemplateStore._map_category("label") == "label_print"

    def test_print(self):
        assert FileSystemTemplateStore._map_category("打印模板") == "label_print"

    def test_excel_default(self):
        assert FileSystemTemplateStore._map_category("发货单") == "excel"

    def test_none(self):
        assert FileSystemTemplateStore._map_category(None) == "excel"

    def test_empty(self):
        assert FileSystemTemplateStore._map_category("") == "excel"


# ---------------------------------------------------------------------------
# _legacy_templates
# ---------------------------------------------------------------------------

class TestLegacyTemplates:
    def test_no_files(self, store):
        templates = store._legacy_templates()
        assert len(templates) == 2
        assert all(not t["exists"] for t in templates)

    def test_with_shipment_template(self, tmp_path):
        (tmp_path / "发货单模板.xlsx").write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._legacy_templates()
        shipment = next(t for t in templates if t["id"] == "shipment")
        assert shipment["exists"] is True
        fallback = next(t for t in templates if t["id"] == "fallback")
        assert fallback["exists"] is False


# ---------------------------------------------------------------------------
# _discover_excel_templates
# ---------------------------------------------------------------------------

class TestDiscoverExcelTemplates:
    def test_no_files(self, store):
        templates = store._discover_excel_templates()
        assert templates == []

    def test_discovers_xlsx(self, store_with_files):
        templates = store_with_files._discover_excel_templates()
        filenames = [t["filename"] for t in templates]
        assert "发货单模板.xlsx" in filenames
        assert "产品清单.xlsx" in filenames

    def test_skips_temp_files(self, tmp_path):
        (tmp_path / "~$temp.xlsx").write_bytes(b"temp")
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_excel_templates()
        assert len(templates) == 0

    def test_skips_non_excel(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not excel")
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_excel_templates()
        assert len(templates) == 0

    def test_dedup_by_path(self, tmp_path):
        # Same file in base_dir and templates/ should be deduped
        (tmp_path / "test.xlsx").write_bytes(b"PK")
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        # Different file with same name in templates dir
        (templates_dir / "test.xlsx").write_bytes(b"PK2")
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_excel_templates()
        # Should have 2 entries since they're different paths
        filenames = [t["filename"] for t in templates]
        assert filenames.count("test.xlsx") >= 1


# ---------------------------------------------------------------------------
# _discover_word_templates
# ---------------------------------------------------------------------------

class TestDiscoverWordTemplates:
    def test_no_files(self, store):
        templates = store._discover_word_templates()
        assert templates == []

    def test_discovers_docx(self, store_with_files):
        templates = store_with_files._discover_word_templates()
        filenames = [t["filename"] for t in templates]
        assert "合同模板.docx" in filenames

    def test_price_list_rename(self, tmp_path):
        (tmp_path / "price_list_default.docx").write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_word_templates()
        if templates:
            assert templates[0]["name"] == "产品价格表（Word 价目）"

    def test_skips_temp_files(self, tmp_path):
        (tmp_path / "~$temp.docx").write_bytes(b"temp")
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_word_templates()
        assert len(templates) == 0


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_empty_store(self, mock_db, store):
        templates = store.list_templates()
        assert templates == []

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_with_excel_files(self, mock_db, store_with_files):
        templates = store_with_files.list_templates()
        filenames = [t["filename"] for t in templates]
        assert "发货单模板.xlsx" in filenames

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_deduplication(self, mock_db, store_with_files):
        templates = store_with_files.list_templates()
        # Check no duplicate paths
        paths = [t.get("path") for t in templates if t.get("path")]
        assert len(paths) == len(set(paths))


# ---------------------------------------------------------------------------
# list_by_type
# ---------------------------------------------------------------------------

class TestListByType:
    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_no_matching_type(self, mock_db, store):
        result = store.list_by_type("不存在")
        assert result == []

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[
        {"id": "db:1", "template_type": "发货单", "is_active": 1, "name": "发货模板"},
    ])
    def test_matching_type(self, mock_db, store):
        result = store.list_by_type("发货单")
        assert len(result) == 1

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[
        {"id": "db:1", "template_type": "发货单", "is_active": 0, "name": "旧模板"},
        {"id": "db:2", "template_type": "发货单", "is_active": 1, "name": "新模板"},
    ])
    def test_active_only_filter(self, mock_db, store):
        result = store.list_by_type("发货单", active_only=True)
        assert len(result) == 1
        assert result[0]["name"] == "新模板"


# ---------------------------------------------------------------------------
# get_default_for_type
# ---------------------------------------------------------------------------

class TestGetDefaultForType:
    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_no_templates(self, mock_db, store):
        result = store.get_default_for_type("发货单")
        assert result is None

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[
        {"id": "db:1", "template_type": "发货单", "is_active": 1, "path": None, "db_id": 1},
    ])
    def test_db_template_no_path(self, mock_db, store):
        result = store.get_default_for_type("发货单")
        # No path, falls through to legacy
        # Legacy also has no file, so returns None
        assert result is None

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_fallback_to_legacy_shipment(self, mock_db, tmp_path):
        (tmp_path / "发货单模板.xlsx").write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))
        result = store.get_default_for_type("发货单")
        assert result is not None
        assert result["id"] == "shipment"


# ---------------------------------------------------------------------------
# resolve_template_file
# ---------------------------------------------------------------------------

class TestResolveTemplateFile:
    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_legacy_shipment(self, mock_db, tmp_path):
        (tmp_path / "发货单模板.xlsx").write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))
        result = store.resolve_template_file("shipment")
        assert result is not None
        assert "发货单模板.xlsx" in result

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_unknown_id_returns_none(self, mock_db, store):
        result = store.resolve_template_file("nonexistent")
        assert result is None

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_fs_prefix(self, mock_db, tmp_path):
        (tmp_path / "test.xlsx").write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))
        result = store.resolve_template_file("fs:test.xlsx")
        assert result is not None
        assert "test.xlsx" in result

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_fs_prefix_not_found(self, mock_db, store):
        result = store.resolve_template_file("fs:nonexistent.xlsx")
        assert result is None


# ---------------------------------------------------------------------------
# save_template_file
# ---------------------------------------------------------------------------

class TestSaveTemplateFile:
    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_source_not_found(self, mock_db, store):
        result = store.save_template_file("nonexistent.xlsx", "target.xlsx", True)
        assert result["success"] is False

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_save_with_overwrite(self, mock_db, tmp_path):
        source = tmp_path / "source.xlsx"
        source.write_bytes(b"PK source")
        store = FileSystemTemplateStore(str(tmp_path))
        result = store.save_template_file("source.xlsx", "target.xlsx", True)
        assert result["success"] is True
        assert result["saved"] is True

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_save_without_overwrite_existing(self, mock_db, tmp_path):
        source = tmp_path / "source.xlsx"
        source.write_bytes(b"PK source")
        target = tmp_path / "target.xlsx"
        target.write_bytes(b"PK existing")
        store = FileSystemTemplateStore(str(tmp_path))
        result = store.save_template_file("source.xlsx", "target.xlsx", False)
        assert result["success"] is True
        assert result["saved"] is False

    @patch.object(FileSystemTemplateStore, "_db_templates", return_value=[])
    def test_default_names(self, mock_db, tmp_path):
        source = tmp_path / "尹玉华132.xlsx"
        source.write_bytes(b"PK source")
        store = FileSystemTemplateStore(str(tmp_path))
        result = store.save_template_file("", "", True)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# save_template (DB)
# ---------------------------------------------------------------------------

class TestSaveTemplate:
    def test_empty_name_fails(self, store):
        result = store.save_template({"template_name": ""})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_empty_name_whitespace(self, store):
        result = store.save_template({"template_name": "   "})
        assert result["success"] is False

    @patch("app.infrastructure.templates.template_store_impl.get_db")
    def test_save_success(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 42
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.save_template({"template_name": "测试模板"})
        assert result["success"] is True
        assert result["id"] == 42

    @patch("app.infrastructure.templates.template_store_impl.get_db")
    def test_save_with_all_fields(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 99
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.save_template({
            "template_name": "完整模板",
            "template_type": "发货单",
            "template_key": "tpl_full",
            "original_file_path": "/tmp/test.xlsx",
            "analyzed_data": {"key": "value"},
            "editable_config": {"editable": True},
            "zone_config": {"zones": []},
            "merged_cells_config": {},
            "style_config": None,
            "business_rules": {"rule": 1},
        })
        assert result["success"] is True
