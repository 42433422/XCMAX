"""Second-wave behavior tests for
app.infrastructure.persistence.compat_db.product_queries.

Targets previously-uncovered branches of ``_load_products_list_impl_pg``:
- business-data-hidden short circuit (lines 36-37)
- get_sync_engine() raising a recoverable error (lines 42-43)
- env-var timeout parse failures for meta/count/data (51-52, 115-116, 168-169)
- statement_timeout reset failures inside ``finally`` (75-76, 127-128, 180-181)
- keyword + unit WHERE-clause assembly (90-100, 103-104)
- count query failure -> total None (121-122)
- data query timeout -> error hint, total coalesced to 0 (174-175, 183-185)
- per-row None coalescing of price/quantity/unit/is_active (195,197,199,201)
- total fallback to offset+len(rows) when count failed (204)

Everything external (sync engine, inspect) is mocked; the suite is offline,
deterministic and fast. patch sites are the *use* sites inside the module
under test.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.compat_db.product_queries import (
    _load_products_list_impl_pg,
)

MOD = "app.infrastructure.persistence.compat_db.product_queries"

# Full set of product columns so every optional-column branch is exercised
# and the SELECT projection uses real column names.
_ALL_COL_NAMES = [
    "id",
    "model_number",
    "name",
    "specification",
    "price",
    "quantity",
    "description",
    "category",
    "brand",
    "unit",
    "is_active",
    "created_at",
    "updated_at",
]


def _cols(names):
    return [{"name": n} for n in names]


def _ctx_conn():
    """A MagicMock connection usable as a context manager."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def _make_engine(connections):
    """Engine whose .connect() yields the given connections in order."""
    eng = MagicMock()
    eng.connect.side_effect = list(connections)
    return eng


def _insp_with(table_names, col_names):
    insp = MagicMock()
    insp.get_table_names.return_value = list(table_names)
    insp.get_columns.return_value = _cols(col_names)
    return insp


# ---------------------------------------------------------------------------
# business-data hidden short-circuit (lines 36-37)
# ---------------------------------------------------------------------------


def test_business_data_hidden_short_circuits():
    """When the business mod is not exposed, return the hidden reason and skip DB."""
    with (
        patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ),
        patch(
            "app.shell.mod_business_scope.business_data_hidden_reason",
            return_value="业务接口已关闭",
        ),
        patch(f"{MOD}.get_sync_engine") as mock_eng,
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)

    assert rows == []
    assert total == 0
    assert hint == "业务接口已关闭"
    # DB engine must never be touched when data is hidden.
    mock_eng.assert_not_called()


def test_business_scope_import_failure_is_suppressed_then_proceeds():
    """A recoverable error from the business-scope guard is swallowed (lines 38-39);
    flow continues to get_sync_engine(), which then fails recoverably (42-43)."""
    # ImportError is a RECOVERABLE_ERROR; simulate the guard import blowing up,
    # then get_sync_engine raising a recoverable error so we exit gracefully.
    with (
        patch(
            "app.shell.mod_business_scope.business_data_exposed",
            side_effect=ImportError("no scope"),
        ),
        patch(f"{MOD}.get_sync_engine", side_effect=RuntimeError("engine init failed")),
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)

    # The guard error was suppressed; the engine error produced the connection hint.
    assert rows == []
    assert total == 0
    assert hint is not None and "无法连接 PostgreSQL" in hint
    assert "engine init failed" in hint


# ---------------------------------------------------------------------------
# get_sync_engine() raising a recoverable error (lines 42-43)
# ---------------------------------------------------------------------------


def test_get_sync_engine_recoverable_error_returns_hint():
    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(f"{MOD}.get_sync_engine", side_effect=ConnectionError("db down")),
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)

    assert rows == []
    assert total == 0
    assert hint is not None
    assert "无法连接 PostgreSQL" in hint
    assert "db down" in hint


# ---------------------------------------------------------------------------
# env-var parse failures default the timeouts (51-52, 115-116, 168-169)
# and finally-block reset failures are suppressed (75-76, 127-128, 180-181)
# together with a fully successful keyword+unit query and row coalescing.
# ---------------------------------------------------------------------------


def test_full_success_keyword_unit_bad_envs_and_reset_failures():
    """Drive the happy path with:
    - garbage timeout env vars (all three -> default branches),
    - keyword + unit filters (WHERE assembly),
    - SET statement_timeout TO 0 raising in every finally (suppressed),
    - rows with NULL price/quantity/unit/is_active (coalesced).
    """
    insp = _insp_with(["products"], _ALL_COL_NAMES)

    meta_conn = _ctx_conn()
    count_conn = _ctx_conn()
    data_conn = _ctx_conn()

    # meta_conn: timeout set ok, reset-to-0 raises (suppressed, lines 75-76)
    meta_conn.execute.side_effect = [
        MagicMock(),  # SET statement_timeout TO <ms>
        RuntimeError("reset boom"),  # SET statement_timeout TO 0 (finally)
    ]

    # count_conn: timeout set ok, count returns 7, reset raises (127-128)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 7
    count_conn.execute.side_effect = [
        MagicMock(),  # SET statement_timeout TO <ms>
        count_result,  # COUNT(*)
        RuntimeError("reset boom"),  # SET statement_timeout TO 0 (finally)
    ]

    # data_conn: timeout set ok, data returns rows with NULLs, reset raises (180-181)
    row_with_nulls = {
        "id": 1,
        "model_number": "M1",
        "name": "Paint",
        "specification": "20L",
        "price": None,
        "quantity": None,
        "description": "d",
        "category": "c",
        "brand": "b",
        "unit": None,
        "is_active": None,
        "created_at": None,
        "updated_at": None,
    }
    data_result = MagicMock()
    data_result.mappings.return_value.all.return_value = [row_with_nulls]
    data_conn.execute.side_effect = [
        MagicMock(),  # SET statement_timeout TO <ms>
        data_result,  # SELECT ... data
        RuntimeError("reset boom"),  # SET statement_timeout TO 0 (finally)
    ]

    eng = _make_engine([meta_conn, count_conn, data_conn])

    captured_where = {}

    def fake_append(where_parts, bind, col_names):
        captured_where["parts"] = list(where_parts)
        captured_where["bind"] = dict(bind)

    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(f"{MOD}.get_sync_engine", return_value=eng),
        patch(f"{MOD}.inspect", return_value=insp),
        patch(f"{MOD}.append_mod_scope_where", side_effect=fake_append),
        # Non-numeric env vars make int(...) raise ValueError (a RECOVERABLE_ERROR),
        # exercising the default-value except branches (51-52, 115-116, 168-169).
        patch.dict(
            "os.environ",
            {
                "FHD_PRODUCTS_META_TIMEOUT_MS": "not-a-number",
                "FHD_PRODUCTS_COUNT_TIMEOUT_MS": "not-a-number",
                "FHD_PRODUCTS_QUERY_TIMEOUT_MS": "not-a-number",
            },
            clear=False,
        ),
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, "paint", "桶")

    assert hint is None
    # count succeeded -> total is the COUNT(*) value
    assert total == 7
    assert len(rows) == 1
    r = rows[0]
    # None coalescing (lines 195,197,199,201)
    assert r["price"] == 0
    assert r["quantity"] == 0
    assert r["unit"] == ""
    assert r["is_active"] == 1

    # WHERE assembly captured: is_active guard + keyword OR-group + unit filter.
    parts = captured_where["parts"]
    bind = captured_where["bind"]
    assert any("is_active" in p for p in parts)
    assert any("ILIKE :kw" in p for p in parts)  # keyword OR-group (lines 90-100)
    assert "unit = :uunit" in parts  # unit filter (lines 103-104)
    assert bind.get("kw") == "%paint%"
    assert bind.get("uunit") == "桶"


# ---------------------------------------------------------------------------
# count query failure -> total None, then data succeeds -> total fallback (204)
# ---------------------------------------------------------------------------


def test_count_failure_then_total_fallback_to_offset_plus_len():
    """COUNT(*) raises recoverable error -> total None (121-122); data succeeds,
    so final total falls back to offset + len(rows) (line 204)."""
    insp = _insp_with(["products"], ["id", "model_number", "name"])

    meta_conn = _ctx_conn()
    meta_conn.execute.return_value = MagicMock()

    count_conn = _ctx_conn()
    # SET ok, then COUNT raises, then reset ok
    count_conn.execute.side_effect = [
        MagicMock(),  # SET
        RuntimeError("count timeout"),  # COUNT(*) -> total None
        MagicMock(),  # reset
    ]

    data_conn = _ctx_conn()
    data_result = MagicMock()
    data_result.mappings.return_value.all.return_value = [
        {"id": 5, "model_number": "X", "name": "N"},
        {"id": 6, "model_number": "Y", "name": "M"},
    ]
    data_conn.execute.side_effect = [
        MagicMock(),  # SET
        data_result,  # data
        MagicMock(),  # reset
    ]

    eng = _make_engine([meta_conn, count_conn, data_conn])

    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(f"{MOD}.get_sync_engine", return_value=eng),
        patch(f"{MOD}.inspect", return_value=insp),
        patch(f"{MOD}.append_mod_scope_where"),
    ):
        # page=2, per_page=10 -> offset = 10; 2 rows -> total fallback 12
        rows, total, hint = _load_products_list_impl_pg(2, 10, None, None)

    assert hint is None
    assert len(rows) == 2
    # missing optional columns are projected as defaults; price/quantity/unit/is_active
    # come from the SELECT aliases, not coalescing, but should still be present.
    assert total == 12  # offset(10) + len(rows)(2), since COUNT failed (line 204)


# ---------------------------------------------------------------------------
# data query timeout -> error hint, total coalesced to 0 (174-175, 183-185)
# ---------------------------------------------------------------------------


def test_data_query_timeout_returns_hint_and_total_zero():
    """Data SELECT raises recoverable error AND count already failed (total None):
    the timeout hint is returned and total is coalesced to 0 (lines 183-184)."""
    insp = _insp_with(["products"], ["id", "model_number", "name"])

    meta_conn = _ctx_conn()
    meta_conn.execute.return_value = MagicMock()

    count_conn = _ctx_conn()
    count_conn.execute.side_effect = [
        MagicMock(),  # SET
        RuntimeError("count boom"),  # COUNT -> total None
        MagicMock(),  # reset
    ]

    data_conn = _ctx_conn()
    data_conn.execute.side_effect = [
        MagicMock(),  # SET
        TimeoutError("data query timeout"),  # data -> data_query_err set (174-175)
        MagicMock(),  # reset
    ]

    eng = _make_engine([meta_conn, count_conn, data_conn])

    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(f"{MOD}.get_sync_engine", return_value=eng),
        patch(f"{MOD}.inspect", return_value=insp),
        patch(f"{MOD}.append_mod_scope_where"),
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)

    assert rows == []
    assert total == 0  # total None -> coalesced to 0 (line 184)
    assert hint is not None
    assert "列表查询超时" in hint


def test_data_query_timeout_keeps_known_total():
    """When COUNT succeeded but data SELECT times out, the hint is returned with the
    previously-known total preserved (data_query_err branch without total-coalesce)."""
    insp = _insp_with(["products"], ["id", "model_number", "name"])

    meta_conn = _ctx_conn()
    meta_conn.execute.return_value = MagicMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 42
    count_conn = _ctx_conn()
    count_conn.execute.side_effect = [
        MagicMock(),  # SET
        count_result,  # COUNT -> 42
        MagicMock(),  # reset
    ]

    data_conn = _ctx_conn()
    data_conn.execute.side_effect = [
        MagicMock(),  # SET
        TimeoutError("data timeout"),  # data -> err
        MagicMock(),  # reset
    ]

    eng = _make_engine([meta_conn, count_conn, data_conn])

    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(f"{MOD}.get_sync_engine", return_value=eng),
        patch(f"{MOD}.inspect", return_value=insp),
        patch(f"{MOD}.append_mod_scope_where"),
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)

    assert rows == []
    assert total == 42  # preserved known total
    assert hint is not None
    assert "列表查询超时" in hint


# ---------------------------------------------------------------------------
# meta-timeout reset failure isolated (lines 75-76) without int patching,
# verifying success path with minimal columns + ORDER BY created_at branch.
# ---------------------------------------------------------------------------


def test_order_by_created_at_branch_and_meta_reset_suppressed(monkeypatch):
    """FHD_PRODUCTS_ORDER_BY_CREATED_AT=1 with created_at present selects the
    created_at ORDER BY; meta reset-to-0 raises and is suppressed."""
    monkeypatch.setenv("FHD_PRODUCTS_ORDER_BY_CREATED_AT", "1")

    insp = _insp_with(["products"], ["id", "model_number", "name", "created_at"])

    meta_conn = _ctx_conn()
    meta_conn.execute.side_effect = [
        MagicMock(),  # SET
        RuntimeError("reset boom"),  # reset -> suppressed (75-76)
    ]

    count_result = MagicMock()
    count_result.scalar_one.return_value = 3
    count_conn = _ctx_conn()
    count_conn.execute.side_effect = [
        MagicMock(),  # SET
        count_result,  # COUNT
        MagicMock(),  # reset
    ]

    captured_sql = {}
    data_result = MagicMock()
    data_result.mappings.return_value.all.return_value = []
    data_conn = _ctx_conn()

    def data_exec(stmt, *a, **k):
        captured_sql.setdefault("calls", []).append(str(stmt))
        if "SELECT" in str(stmt).upper() and "FROM PRODUCTS" in str(stmt).upper():
            return data_result
        return MagicMock()

    data_conn.execute.side_effect = data_exec

    eng = _make_engine([meta_conn, count_conn, data_conn])

    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(f"{MOD}.get_sync_engine", return_value=eng),
        patch(f"{MOD}.inspect", return_value=insp),
        patch(f"{MOD}.append_mod_scope_where"),
    ):
        rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)

    assert hint is None
    assert total == 3
    assert rows == []
    joined = " ".join(captured_sql.get("calls", []))
    assert "created_at DESC NULLS LAST" in joined


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
