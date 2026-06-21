from __future__ import annotations

"""Branch-coverage tests for app.infrastructure.persistence.product_repository_impl."""

import math
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.product_repository_impl import (
    TRIVIAL_MEASURE_UNITS,
    SQLAlchemyProductRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(**kw):
    p = MagicMock()
    p.__dict__ = {
        "id": kw.get("id", 1),
        "name": kw.get("name", "产品A"),
        "model_number": kw.get("model_number", "M-001"),
        "specification": kw.get("specification", "10x20"),
        "price": kw.get("price", 9.9),
        "quantity": kw.get("quantity", 10),
        "description": kw.get("description", "desc"),
        "category": kw.get("category", "cat"),
        "brand": kw.get("brand", "brand"),
        "unit": kw.get("unit", "个"),
        "is_active": kw.get("is_active", 1),
        "created_at": kw.get("created_at"),
        "updated_at": kw.get("updated_at"),
        "_sa_instance_state": MagicMock(),
    }
    return p


@contextmanager
def _db_ctx(db_mock):
    yield db_mock


@pytest.fixture
def repo():
    return SQLAlchemyProductRepository()


# ---------------------------------------------------------------------------
# _api_scalar
# ---------------------------------------------------------------------------

class TestApiScalar:
    def test_none_returns_none(self, repo):
        assert repo._api_scalar(None) is None

    def test_float_nan_returns_none(self, repo):
        assert repo._api_scalar(float("nan")) is None

    def test_string_nan_returns_none(self, repo):
        assert repo._api_scalar("nan") is None

    def test_string_none_returns_none(self, repo):
        assert repo._api_scalar("none") is None

    def test_string_nat_returns_none(self, repo):
        assert repo._api_scalar("NaT") is None

    def test_string_na_returns_none(self, repo):
        assert repo._api_scalar("<NA>") is None

    def test_string_null_returns_none(self, repo):
        assert repo._api_scalar("null") is None

    def test_normal_string_stripped(self, repo):
        assert repo._api_scalar("  hello  ") == "hello"

    def test_value_nan_via_float_returns_none(self, repo):
        # non-float but float(x) == nan — tricky to trigger but cover ValueError path
        result = repo._api_scalar(True)
        assert result is True  # bool can float() fine, 1.0 != nan so returns as-is

    def test_regular_int(self, repo):
        assert repo._api_scalar(42) == 42

    def test_regular_float(self, repo):
        assert repo._api_scalar(3.14) == 3.14


# ---------------------------------------------------------------------------
# find_all — missing branches
# ---------------------------------------------------------------------------

class TestFindAllBranches:
    def _make_db(self, has_products_table=True, has_bind=True, products=None):
        # Use a simple object so __dict__ assignment works cleanly
        class _FakeDB:
            def __init__(self):
                self.bind = MagicMock() if has_bind else None

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        db = _FakeDB()

        # Override __dict__ via spec trick: we only set bind/no-bind
        if not has_bind:
            db.bind = None

        mock_insp = MagicMock()
        if has_products_table:
            mock_insp.get_table_names.return_value = ["products"]
        else:
            mock_insp.get_table_names.return_value = []

        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.offset.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.all.return_value = products or []

        db.query = MagicMock(return_value=query_mock)
        return db, mock_insp

    def test_find_all_no_products_table(self, repo):
        """Branch: 'products' not in table_names -> return empty."""
        db, mock_insp = self._make_db(has_products_table=False, has_bind=True)
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all()
        assert result["success"] is True
        assert result["data"] == []
        assert result["total"] == 0

    def test_find_all_empty_db_dict(self, repo):
        """Branch: db.__dict__ == {} (no bind key) -> table_names = []."""
        class _EmptyDB:
            # __dict__ will only have __class__ etc, no 'bind'
            def __enter__(self): return self
            def __exit__(self, *a): pass

        db = _EmptyDB()
        db.query = MagicMock()

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
        ):
            result = repo.find_all()
        assert result["success"] is True
        assert result["data"] == []

    def test_find_all_bind_none_fallback(self, repo):
        """Branch: bind is None (falsy) -> table_names = ['products']."""
        class _NoneBindDB:
            bind = None
            def __enter__(self): return self
            def __exit__(self, *a): pass

        db = _NoneBindDB()
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.offset.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.all.return_value = []
        db.query = MagicMock(return_value=query_mock)

        with patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)):
            result = repo.find_all()
        assert result["success"] is True

    def test_find_all_with_unit_name(self, repo):
        """Branch: unit_name is set -> filter applied."""
        db, mock_insp = self._make_db()
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all(unit_name="个")
        assert result["success"] is True

    def test_find_all_with_model_number(self, repo):
        """Branch: model_number set -> normalized filter."""
        db, mock_insp = self._make_db()
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all(model_number="M-001 A")
        assert result["success"] is True

    def test_find_all_with_model_number_empty_after_strip(self, repo):
        """Branch: model_token becomes empty string after normalize -> no filter."""
        db, mock_insp = self._make_db()
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all(model_number="- -")
        assert result["success"] is True

    def test_find_all_keyword_single_segment(self, repo):
        """Branch: keyword -> 1 segment path."""
        db, mock_insp = self._make_db()
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all(keyword="apple")
        assert result["success"] is True

    def test_find_all_keyword_multiple_segments(self, repo):
        """Branch: keyword -> multiple segments path."""
        db, mock_insp = self._make_db()
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all(keyword="苹果 apple 001")
        assert result["success"] is True

    def test_find_all_keyword_no_segments_uses_fallback(self, repo):
        """Branch: keyword has no alphanum/CJK segments -> uses keyword_text itself."""
        db, mock_insp = self._make_db()
        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=mock_insp),
        ):
            result = repo.find_all(keyword="   ")
        assert result["success"] is True

    def test_find_all_exception_returns_failure(self, repo):
        """Branch: outer exception -> return failure dict."""
        with patch("app.infrastructure.persistence.product_repository_impl.get_db", side_effect=RuntimeError("db down")):
            result = repo.find_all()
        assert result["success"] is False

    def test_find_all_has_get_table_names_on_bind(self, repo):
        """Branch: bind has get_table_names attribute (not inspect fallback)."""
        bind = MagicMock()
        bind.get_table_names = MagicMock(return_value=["products"])

        class _GetTableNamesDB:
            def __init__(self):
                self.bind = bind
            def __enter__(self): return self
            def __exit__(self, *a): pass

        db = _GetTableNamesDB()
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.offset.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.all.return_value = []
        db.query = MagicMock(return_value=query_mock)

        with patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)):
            result = repo.find_all()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# find_product_units — missing branches
# ---------------------------------------------------------------------------

class TestFindProductUnits:
    def test_purchase_units_authoritative_returns_early(self, repo):
        """Branch: purchase_units table found -> return ordered without products fallback."""
        cs = MagicMock()
        bind = MagicMock()
        cs.get_bind.return_value = bind
        tinsp = MagicMock()
        tinsp.get_table_names.return_value = ["purchase_units"]
        cs.query.return_value.filter.return_value.filter.return_value.distinct.return_value.all.return_value = [("个",), ("套",)]

        with (
            patch("app.application.customer_app_service.get_customers_session", return_value=cs),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=tinsp),
        ):
            # Also patch inside the function's import resolution
            import app.application.customer_app_service as _cs_mod
            orig = getattr(_cs_mod, "get_customers_session", None)
            try:
                _cs_mod.get_customers_session = lambda: cs
                result = repo.find_product_units()
            finally:
                if orig is not None:
                    _cs_mod.get_customers_session = orig
        assert isinstance(result, list)

    def test_fallback_to_products_unit(self, repo):
        """Branch: no purchase_units -> falls back to products.unit."""
        class _FakeDB:
            def __init__(self):
                self.bind = MagicMock()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        db = _FakeDB()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        db.query = MagicMock()
        db.query.return_value.distinct.return_value.all.return_value = [("箱",), ("米",), ("个",), ("专属包装",)]

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_customers_session", side_effect=Exception("nope"), create=True),
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=insp),
        ):
            result = repo.find_product_units()
        # trivial units (箱, 米, 个) filtered out; non-trivial kept
        assert "箱" not in result
        assert "专属包装" in result

    def test_add_label_trivial_unit_skipped(self, repo):
        """Branch: from_products=True + trivial measure unit -> skip."""
        class _FakeDB:
            def __init__(self):
                self.bind = MagicMock()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        db = _FakeDB()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        db.query = MagicMock()
        db.query.return_value.distinct.return_value.all.return_value = [("千克",), ("独家包装",)]

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=insp),
        ):
            result = repo.find_product_units()
        assert "千克" not in result
        assert "独家包装" in result


# ---------------------------------------------------------------------------
# export_to_excel — missing branches
# ---------------------------------------------------------------------------

class TestExportToExcel:
    def _make_fake_db(self, table_names, products=None):
        class _FakeDB:
            def __init__(self):
                self.bind = MagicMock()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        db = _FakeDB()
        db.query = MagicMock()
        q = db.query.return_value
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = products or []
        return db, table_names

    def test_no_products_table(self, repo, tmp_path):
        """Branch: products not in table -> return failure."""
        db, tnames = self._make_fake_db([])
        insp = MagicMock()
        insp.get_table_names.return_value = tnames

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=insp),
        ):
            result = repo.export_to_excel()
        assert result["success"] is False
        assert result["file_path"] is None

    def test_export_with_unit_and_keyword(self, repo, tmp_path):
        """Branch: unit_name and keyword filters applied, no template."""
        prod = MagicMock()
        prod.model_number = "M-001"
        prod.name = "TestProd"
        prod.price = 10.0

        db, _ = self._make_fake_db(["products"], products=[prod])
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=insp),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
        ):
            result = repo.export_to_excel(unit_name="个", keyword="Test")
        assert result["success"] is True
        assert result["count"] == 1

    def test_export_with_template_id_found(self, repo, tmp_path):
        """Branch: template_id given and template found with valid path."""
        from openpyxl import Workbook

        fake_tmpl = tmp_path / "template.xlsx"
        wb_t = Workbook()
        wb_t.save(str(fake_tmpl))

        db, _ = self._make_fake_db(["products"], products=[])
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]

        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {
            "templates": [{"id": "42", "path": str(fake_tmpl), "file_path": None}]
        }

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=insp),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=mock_svc),
            patch("app.utils.template_export_utils.fill_workbook_from_template", return_value=Workbook()),
        ):
            result = repo.export_to_excel(template_id="42")
        assert result["success"] is True

    def test_export_with_template_id_not_found(self, repo, tmp_path):
        """Branch: template_id given but no matching template -> use default workbook."""
        db, _ = self._make_fake_db(["products"], products=[])
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]

        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"templates": []}

        with (
            patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)),
            patch("app.infrastructure.persistence.product_repository_impl.inspect", return_value=insp),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=mock_svc),
        ):
            result = repo.export_to_excel(template_id="99")
        assert result["success"] is True

    def test_export_exception_returns_failure(self, repo):
        """Branch: exception during export -> failure dict."""
        with patch("app.infrastructure.persistence.product_repository_impl.get_db", side_effect=OSError("disk error")):
            result = repo.export_to_excel()
        assert result["success"] is False
        assert result["file_path"] is None


# ---------------------------------------------------------------------------
# batch_create — missing branches
# ---------------------------------------------------------------------------

class TestBatchCreate:
    def test_empty_list(self, repo):
        result = repo.batch_create([])
        assert result["success"] is False

    def test_partial_failure_no_name(self, repo):
        """Branch: product_name missing -> failed_products list."""
        db = MagicMock()
        db.bulk_insert_mappings.return_value = None
        db.commit.return_value = None

        with patch("app.infrastructure.persistence.product_repository_impl.get_db", return_value=_db_ctx(db)):
            result = repo.batch_create([{"name": ""}, {"name": "ValidProd"}])
        assert result["failed_count"] >= 1
