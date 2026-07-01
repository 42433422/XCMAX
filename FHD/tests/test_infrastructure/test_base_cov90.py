"""Behavioural tests for app.infrastructure.persistence.compat_db.base.

Targets previously-uncovered branches:
- _validate_order_clause: bare valid column (continue), bare invalid column,
  ASC/DESC with disallowed column.
- _insp_table_exists: has_table success / has_table raising / get_table_names
  fallback / get_table_names raising.
- _customer_pg_engine_insp: engine + inspector tuple.
- _product_parse_id: bool input.
- _product_parse_quantity: empty-string short-circuit.
- _product_parse_is_active: None / bool / int-float / unrecognised string.
- _business_mod_json_block: exposed True/False and import/raise fallback.
- _customers_write_raise / _products_write_raise: missing-table 503,
  HTTPException re-raise, RECOVERABLE_ERRORS -> 503 wrap.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.persistence.compat_db.base import (
    _business_mod_json_block,
    _customer_pg_engine_insp,
    _customers_write_raise,
    _insp_table_exists,
    _product_parse_id,
    _product_parse_is_active,
    _product_parse_quantity,
    _products_write_raise,
    _validate_order_clause,
)

BASE = "app.infrastructure.persistence.compat_db.base"


# ---------------------------------------------------------------------------
# _validate_order_clause  (lines 138-141, 145)
# ---------------------------------------------------------------------------


class TestValidateOrderClause:
    def test_bare_valid_column_no_direction(self):
        # m fails (no ASC/DESC), m2 matches, column allowed -> continue branch (140-141).
        assert _validate_order_clause("name") == '"name"'

    def test_bare_quoted_valid_column(self):
        assert _validate_order_clause('"created_at"') == '"created_at"'

    def test_bare_invalid_column_raises(self):
        # m2 matches but column not allowed -> falls through to raise (142).
        with pytest.raises(ValueError, match="invalid ORDER BY token"):
            _validate_order_clause("not_a_real_column")

    def test_garbage_token_raises(self):
        # m2 does not match (contains a space / operator) -> raise.
        with pytest.raises(ValueError, match="invalid ORDER BY token"):
            _validate_order_clause("DROP TABLE")

    def test_ascdesc_with_disallowed_column_raises(self):
        # m matches ASC/DESC form but column not allowed and != id (line 144-145).
        with pytest.raises(ValueError, match="ORDER BY column not allowed"):
            _validate_order_clause("evil_col ASC")

    def test_ascdesc_id_is_allowed(self):
        # id passes the `col_name != "id"` guard even though it is in the column set.
        assert _validate_order_clause("id DESC") == '"id" DESC'

    def test_multi_token_mixed_valid(self):
        result = _validate_order_clause("name ASC, created_at DESC")
        assert result == '"name" ASC, "created_at" DESC'


# ---------------------------------------------------------------------------
# _insp_table_exists  (lines 157-162)
# ---------------------------------------------------------------------------


class TestInspTableExists:
    def test_has_table_returns_true(self):
        insp = MagicMock()
        insp.has_table.return_value = True
        assert _insp_table_exists(insp, "customers") is True
        insp.has_table.assert_called_once_with("customers")

    def test_has_table_returns_false(self):
        insp = MagicMock()
        insp.has_table.return_value = False
        assert _insp_table_exists(insp, "customers") is False

    def test_has_table_raises_then_fallback_get_table_names(self):
        # has_table raises a recoverable error -> falls to get_table_names (157-160).
        insp = MagicMock()
        insp.has_table.side_effect = RuntimeError("boom")
        insp.get_table_names.return_value = ["customers", "products"]
        assert _insp_table_exists(insp, "products") is True

    def test_has_table_raises_then_fallback_missing(self):
        insp = MagicMock()
        insp.has_table.side_effect = RuntimeError("boom")
        insp.get_table_names.return_value = ["customers"]
        assert _insp_table_exists(insp, "products") is False

    def test_no_has_table_uses_get_table_names(self):
        # has_table not callable -> straight to get_table_names path.
        insp = MagicMock()
        insp.has_table = None
        insp.get_table_names.return_value = ["sessions"]
        assert _insp_table_exists(insp, "sessions") is True

    def test_get_table_names_raises_returns_false(self):
        # both has_table missing and get_table_names raising -> False (161-162).
        insp = MagicMock()
        insp.has_table = None
        insp.get_table_names.side_effect = RuntimeError("db down")
        assert _insp_table_exists(insp, "sessions") is False


# ---------------------------------------------------------------------------
# _customer_pg_engine_insp  (lines 182, 184-185)
# ---------------------------------------------------------------------------


class TestCustomerPgEngineInsp:
    def test_returns_engine_and_inspector(self):
        fake_engine = MagicMock(name="engine")
        fake_insp = MagicMock(name="inspector")
        with (
            patch(f"{BASE}.get_sync_engine", return_value=fake_engine) as m_eng,
            patch("sqlalchemy.inspect", return_value=fake_insp) as m_insp,
        ):
            eng, insp = _customer_pg_engine_insp()
        assert eng is fake_engine
        assert insp is fake_insp
        m_eng.assert_called_once_with()
        m_insp.assert_called_once_with(fake_engine)


# ---------------------------------------------------------------------------
# _product_parse_id  (line 205) and other small parsers
# ---------------------------------------------------------------------------


class TestProductParseId:
    def test_bool_true_returns_none(self):
        # isinstance(raw, bool) branch at line 204-205.
        assert _product_parse_id(True) is None

    def test_bool_false_returns_none_early(self):
        # raw is False -> line 202-203.
        assert _product_parse_id(False) is None

    def test_positive_int(self):
        assert _product_parse_id(7) == 7

    def test_zero_int_returns_none(self):
        assert _product_parse_id(0) is None

    def test_numeric_string(self):
        assert _product_parse_id("  12 ") == 12

    def test_non_numeric_string_returns_none(self):
        assert _product_parse_id("abc") is None


class TestProductParseQuantity:
    def test_empty_string_short_circuit(self):
        # line 216-217.
        assert _product_parse_quantity("") == 0

    def test_none_returns_zero(self):
        assert _product_parse_quantity(None) == 0

    def test_float_string_truncates(self):
        assert _product_parse_quantity("3.9") == 3

    def test_garbage_returns_zero(self):
        assert _product_parse_quantity("xx") == 0


class TestProductParseIsActive:
    def test_none_returns_none(self):
        # line 225-226.
        assert _product_parse_is_active(None) is None

    def test_bool_passthrough(self):
        # line 227-228.
        assert _product_parse_is_active(True) is True
        assert _product_parse_is_active(False) is False

    def test_int_nonzero_true(self):
        # line 229-230.
        assert _product_parse_is_active(5) is True

    def test_int_zero_false(self):
        assert _product_parse_is_active(0) is True or _product_parse_is_active(0) is False
        # int(0) != 0 is False -> returns False
        assert _product_parse_is_active(0) is False

    def test_float_nonzero_true(self):
        assert _product_parse_is_active(2.5) is True

    def test_string_false_tokens(self):
        for tok in ("0", "false", "no", "off"):
            assert _product_parse_is_active(tok) is False

    def test_string_true_tokens(self):
        for tok in ("1", "true", "yes", "on"):
            assert _product_parse_is_active(tok) is True

    def test_unrecognised_string_returns_none(self):
        # line 236: nothing matched.
        assert _product_parse_is_active("maybe") is None


# ---------------------------------------------------------------------------
# _business_mod_json_block  (lines 240-241, 243-245, 249-250)
# ---------------------------------------------------------------------------


class TestBusinessModJsonBlock:
    def test_exposed_returns_none(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value=None,
            ),
        ):
            assert _business_mod_json_block() is None

    def test_hidden_returns_block_with_reason(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=False),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value="自定义原因",
            ),
        ):
            block = _business_mod_json_block()
        assert block == {"success": False, "message": "自定义原因"}

    def test_hidden_falls_back_to_default_message(self):
        # business_data_hidden_reason returns None -> default Chinese message (line 247).
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=False),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value=None,
            ),
        ):
            block = _business_mod_json_block()
        assert block is not None
        assert block["success"] is False
        assert "扩展 Mod 未就绪" in block["message"]

    def test_recoverable_error_returns_none(self):
        # business_data_exposed raising a recoverable error -> except -> None (249-250).
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            side_effect=RuntimeError("scope down"),
        ):
            assert _business_mod_json_block() is None


# ---------------------------------------------------------------------------
# _customers_write_raise  (lines 254-256, 258-261, 265-268)
# ---------------------------------------------------------------------------


class TestCustomersWriteRaise:
    def test_success_when_table_present(self):
        req = MagicMock()
        fake_insp = MagicMock()
        fake_insp.get_table_names.return_value = ["purchase_units", "customers"]
        with (
            patch(f"{BASE}.verify_db_write_token_header") as m_verify,
            patch(f"{BASE}.get_sync_engine", return_value=MagicMock()),
            patch("sqlalchemy.inspect", return_value=fake_insp),
        ):
            # Returns None (no raise) when purchase_units exists.
            assert _customers_write_raise(req) is None
        m_verify.assert_called_once_with(req)

    def test_missing_purchase_units_raises_503(self):
        req = MagicMock()
        fake_insp = MagicMock()
        fake_insp.get_table_names.return_value = ["customers"]
        with (
            patch(f"{BASE}.verify_db_write_token_header"),
            patch(f"{BASE}.get_sync_engine", return_value=MagicMock()),
            patch("sqlalchemy.inspect", return_value=fake_insp),
        ):
            with pytest.raises(HTTPException) as exc:
                _customers_write_raise(req)
        assert exc.value.status_code == 503
        assert "purchase_units" in exc.value.detail

    def test_http_exception_from_inner_reraised(self):
        # An HTTPException raised inside try (e.g. by inspect) must propagate unchanged.
        req = MagicMock()
        inner = HTTPException(status_code=418, detail="teapot")
        with (
            patch(f"{BASE}.verify_db_write_token_header"),
            patch(f"{BASE}.get_sync_engine", side_effect=inner),
        ):
            with pytest.raises(HTTPException) as exc:
                _customers_write_raise(req)
        assert exc.value.status_code == 418
        assert exc.value.detail == "teapot"

    def test_recoverable_error_wrapped_503(self):
        # get_sync_engine raising RECOVERABLE_ERRORS -> wrapped 503 (265-268).
        req = MagicMock()
        with (
            patch(f"{BASE}.verify_db_write_token_header"),
            patch(f"{BASE}.get_sync_engine", side_effect=RuntimeError("no engine")),
        ):
            with pytest.raises(HTTPException) as exc:
                _customers_write_raise(req)
        assert exc.value.status_code == 503
        assert "无法校验" in exc.value.detail

    def test_verify_token_error_propagates(self):
        # verify_db_write_token_header runs before the try block; its HTTPException
        # (e.g. 401) is not caught here.
        req = MagicMock()
        with patch(
            f"{BASE}.verify_db_write_token_header",
            side_effect=HTTPException(status_code=401, detail="no token"),
        ):
            with pytest.raises(HTTPException) as exc:
                _customers_write_raise(req)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# _products_write_raise  (lines 275-277, 279-282, 286-289)
# ---------------------------------------------------------------------------


class TestProductsWriteRaise:
    def test_success_when_table_present(self):
        req = MagicMock()
        fake_insp = MagicMock()
        fake_insp.get_table_names.return_value = ["products", "customers"]
        with (
            patch(f"{BASE}.verify_db_write_token_header") as m_verify,
            patch(f"{BASE}.get_sync_engine", return_value=MagicMock()),
            patch("sqlalchemy.inspect", return_value=fake_insp),
        ):
            assert _products_write_raise(req) is None
        m_verify.assert_called_once_with(req)

    def test_missing_products_raises_503(self):
        req = MagicMock()
        fake_insp = MagicMock()
        fake_insp.get_table_names.return_value = ["customers"]
        with (
            patch(f"{BASE}.verify_db_write_token_header"),
            patch(f"{BASE}.get_sync_engine", return_value=MagicMock()),
            patch("sqlalchemy.inspect", return_value=fake_insp),
        ):
            with pytest.raises(HTTPException) as exc:
                _products_write_raise(req)
        assert exc.value.status_code == 503
        assert "products" in exc.value.detail

    def test_http_exception_from_inner_reraised(self):
        req = MagicMock()
        inner = HTTPException(status_code=409, detail="conflict")
        with (
            patch(f"{BASE}.verify_db_write_token_header"),
            patch(f"{BASE}.get_sync_engine", side_effect=inner),
        ):
            with pytest.raises(HTTPException) as exc:
                _products_write_raise(req)
        assert exc.value.status_code == 409

    def test_recoverable_error_wrapped_503(self):
        req = MagicMock()
        with (
            patch(f"{BASE}.verify_db_write_token_header"),
            patch(f"{BASE}.get_sync_engine", side_effect=OSError("disk")),
        ):
            with pytest.raises(HTTPException) as exc:
                _products_write_raise(req)
        assert exc.value.status_code == 503
        assert "无法校验" in exc.value.detail
