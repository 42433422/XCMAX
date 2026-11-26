from __future__ import annotations

"""Branch-coverage tests for app.infrastructure.persistence.compat_db.writes.

Each test targets one or more of the missing branches listed in the coverage
report.  All DB / HTTP / engine dependencies are mocked
no real database is
touched.
"""

import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

MODULE = "app.infrastructure.persistence.compat_db.writes"


def _make_conn(rows=None, rowcount=1):
    """Return a mock connection whose execute returns a useful result."""
    conn = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    result.first.return_value = rows[0] if rows else None
    result.scalar_one.return_value = rows[0] if rows else 99
    result.mappings.return_value.first.return_value = rows[0] if rows else None
    conn.execute.return_value = result
    return conn


@contextmanager
def _ctx_conn(conn):
    """Simulate eng.connect() / eng.begin() context managers."""
    yield conn


def _eng_with_conn(conn):
    """Return a mock engine that returns *conn* from both begin() and connect()."""
    eng = MagicMock()
    eng.begin.return_value = _ctx_conn(conn)
    eng.connect.return_value = _ctx_conn(conn)
    return eng


# ---------------------------------------------------------------------------
# 1. _purchase_units_delete_by_norm_unit_pg – lines 70-72
#    Branch: "unit_name" NOT in cols → return 0 immediately
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. _purchase_units_delete_by_id_pg – lines 116-118
#    Branch: "id" NOT in cols → return 0 immediately
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. _customer_pg_insert – lines 234-235
#    Branch: duplicate record found → raise 400
# ---------------------------------------------------------------------------


def test_customer_pg_insert_duplicate_raises_400():
    """Line 234-235: dup row found → HTTPException 400."""
    conn = _make_conn(rows=[{"id": 1}])  # dup found
    eng = _eng_with_conn(conn)
    insp = MagicMock()
    insp.get_columns.return_value = [
        {"name": "unit_name"},
        {"name": "id"},
    ]
    with (
        patch(f"{MODULE}._customer_pg_engine_insp", return_value=(eng, insp)),
        patch(f"{MODULE}.scoped_mod_id", return_value=None),
        patch(f"{MODULE}.append_mod_scope_where"),
        patch(f"{MODULE}._pg_purchase_unit_active_sql", return_value="is_active = true"),
        patch(
            f"{MODULE}._sql_select_from_where", return_value="SELECT id FROM purchase_units WHERE …"
        ),
        patch(f"{MODULE}.utc_now_naive", return_value=MagicMock()),
    ):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert

        with pytest.raises(HTTPException) as exc:
            _customer_pg_insert("ExistingName", "cp", "ph", "addr")
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. _customer_pg_insert – lines 244-245
#    Branch: "xcagi_mod_id" in pu_cols AND mid is set → append to col_pairs
# ---------------------------------------------------------------------------


def test_customer_pg_insert_xcagi_mod_id_appended():
    """Line 244-245: xcagi_mod_id column exists and mid is truthy."""
    new_id = 77
    conn = MagicMock()
    # First call (dup check) returns no dup; second builds insert
    no_dup = MagicMock()
    no_dup.first.return_value = None
    insert_result = MagicMock()
    insert_result.scalar_one.return_value = new_id
    conn.execute.side_effect = [no_dup, insert_result]

    eng = MagicMock()
    eng.connect.return_value = _ctx_conn(conn)

    insp = MagicMock()
    insp.get_columns.return_value = [
        {"name": "unit_name"},
        {"name": "id"},
        {"name": "xcagi_mod_id"},
    ]
    fetch_result = {"id": new_id, "customer_name": "TestCo"}

    with (
        patch(f"{MODULE}._customer_pg_engine_insp", return_value=(eng, insp)),
        patch(f"{MODULE}.scoped_mod_id", return_value="mod-abc"),
        patch(f"{MODULE}.append_mod_scope_where"),
        patch(f"{MODULE}._pg_purchase_unit_active_sql", return_value="is_active = true"),
        patch(f"{MODULE}._sql_select_from_where", return_value="SELECT …"),
        patch(f"{MODULE}._sql_insert_returning", return_value="INSERT …"),
        patch(f"{MODULE}.utc_now_naive", return_value=MagicMock()),
        patch(f"{MODULE}._customer_pg_fetch_by_id", return_value=fetch_result),
    ):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert

        result = _customer_pg_insert("TestCo", "Jane", "1234", "Addr")
    assert result == fetch_result
    # xcagi_mod_id must appear in the bind dict passed to execute
    call_args = conn.execute.call_args_list[1]
    bind = call_args[0][1]
    assert "xmid" in bind


# ---------------------------------------------------------------------------
# 5. _customer_pg_insert – lines 247-251
#    Branch: "is_active" in pu_cols, type contains "bool" → bind True
# ---------------------------------------------------------------------------


def test_customer_pg_insert_is_active_bool_type():
    """Line 247-251: is_active column with boolean type gets True."""
    new_id = 55
    conn = MagicMock()
    no_dup = MagicMock()
    no_dup.first.return_value = None
    ins_res = MagicMock()
    ins_res.scalar_one.return_value = new_id
    conn.execute.side_effect = [no_dup, ins_res]
    eng = MagicMock()
    eng.connect.return_value = _ctx_conn(conn)

    insp = MagicMock()
    bool_type = MagicMock()
    bool_type.__str__ = lambda s: "BOOLEAN"
    insp.get_columns.return_value = [
        {"name": "unit_name"},
        {"name": "id"},
        {"name": "is_active", "type": bool_type},
    ]

    with (
        patch(f"{MODULE}._customer_pg_engine_insp", return_value=(eng, insp)),
        patch(f"{MODULE}.scoped_mod_id", return_value=None),
        patch(f"{MODULE}.append_mod_scope_where"),
        patch(f"{MODULE}._pg_purchase_unit_active_sql", return_value="is_active = true"),
        patch(f"{MODULE}._sql_select_from_where", return_value="SELECT …"),
        patch(f"{MODULE}._sql_insert_returning", return_value="INSERT …"),
        patch(f"{MODULE}.utc_now_naive", return_value=MagicMock()),
        patch(f"{MODULE}._customer_pg_fetch_by_id", return_value={"id": new_id}),
    ):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert

        result = _customer_pg_insert("BoolCo", "cp", "ph", "addr")

    bind = conn.execute.call_args_list[1][0][1]
    assert bind["ia"] is True


# ---------------------------------------------------------------------------
# 6. _customer_pg_insert – lines 251-254
#    Branch: "is_active" in pu_cols, type does NOT contain "bool" → bind 1
# ---------------------------------------------------------------------------


def test_customer_pg_insert_is_active_non_bool_type():
    """Line 251-254: is_active column with INTEGER type gets 1."""
    new_id = 56
    conn = MagicMock()
    no_dup = MagicMock()
    no_dup.first.return_value = None
    ins_res = MagicMock()
    ins_res.scalar_one.return_value = new_id
    conn.execute.side_effect = [no_dup, ins_res]
    eng = MagicMock()
    eng.connect.return_value = _ctx_conn(conn)

    insp = MagicMock()
    int_type = MagicMock()
    int_type.__str__ = lambda s: "INTEGER"
    insp.get_columns.return_value = [
        {"name": "unit_name"},
        {"name": "id"},
        {"name": "is_active", "type": int_type},
    ]

    with (
        patch(f"{MODULE}._customer_pg_engine_insp", return_value=(eng, insp)),
        patch(f"{MODULE}.scoped_mod_id", return_value=None),
        patch(f"{MODULE}.append_mod_scope_where"),
        patch(f"{MODULE}._pg_purchase_unit_active_sql", return_value="is_active = 1"),
        patch(f"{MODULE}._sql_select_from_where", return_value="SELECT …"),
        patch(f"{MODULE}._sql_insert_returning", return_value="INSERT …"),
        patch(f"{MODULE}.utc_now_naive", return_value=MagicMock()),
        patch(f"{MODULE}._customer_pg_fetch_by_id", return_value={"id": new_id}),
    ):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert

        _customer_pg_insert("IntCo", "cp", "ph", "addr")

    bind = conn.execute.call_args_list[1][0][1]
    assert bind["ia"] == 1


# ---------------------------------------------------------------------------
# 7. _customer_pg_insert – lines 254-257
#    Branch: "created_at" in pu_cols → bind["ca"] set to now
# ---------------------------------------------------------------------------


def test_customer_pg_insert_created_at_appended():
    """Line 254-257: created_at column causes ca to be included in bind."""
    import datetime

    now_val = datetime.datetime(2024, 1, 1, 0, 0, 0)
    new_id = 57
    conn = MagicMock()
    no_dup = MagicMock()
    no_dup.first.return_value = None
    ins_res = MagicMock()
    ins_res.scalar_one.return_value = new_id
    conn.execute.side_effect = [no_dup, ins_res]
    eng = MagicMock()
    eng.connect.return_value = _ctx_conn(conn)

    insp = MagicMock()
    insp.get_columns.return_value = [
        {"name": "unit_name"},
        {"name": "id"},
        {"name": "created_at"},
    ]

    with (
        patch(f"{MODULE}._customer_pg_engine_insp", return_value=(eng, insp)),
        patch(f"{MODULE}.scoped_mod_id", return_value=None),
        patch(f"{MODULE}.append_mod_scope_where"),
        patch(f"{MODULE}._pg_purchase_unit_active_sql", return_value="is_active = true"),
        patch(f"{MODULE}._sql_select_from_where", return_value="SELECT …"),
        patch(f"{MODULE}.utc_now_naive", return_value=now_val),
        patch(f"{MODULE}._customer_pg_fetch_by_id", return_value={"id": new_id}),
    ):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert

        _customer_pg_insert("DateCo", "cp", "ph", "addr")

    bind = conn.execute.call_args_list[1][0][1]
    assert bind["ca"] == now_val


# ---------------------------------------------------------------------------
# 8. _customer_pg_update – lines 289-290
#    Branch: prev is None → raise 404
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9. _customer_pg_update – lines 303-304
#    Branch: clash exists → raise 400
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 10. _customer_pg_update – lines 314-315 (updated_at branch)
#     Branch: "updated_at" in pu_cols → UPDATE includes updated_at
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. _customer_pg_update – lines 314-325 (no updated_at)
#     Branch: "updated_at" NOT in pu_cols → UPDATE without :ua
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 12. _customer_pg_update – lines 333-334
#     Branch: old_name != new name → _products_unit_replace_pg called
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 13. _customer_pg_update – lines 333-335
#     Branch: old_name == new name → _products_unit_replace_pg NOT called
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 14. _customer_pg_delete_anywhere – line 381-382
#     Branch: "purchase_units" NOT in table names → skip first block
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 15. _customer_pg_delete_anywhere – lines 393-394
#     Branch: r (purchase_units row) exists → resolved_name set from it
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 16. _customer_pg_delete_anywhere – lines 393-396
#     Branch: r is None in purchase_units query → try customers table
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 17. _customer_pg_delete_anywhere – line 420 (n_prod==n_pu==n_cu==0)
#     Branch: nothing deleted → raise 404
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 18. products_pg_update_row – lines 456-460
#     Branch: "specification" NOT in col_names → no spec in sets
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 19. products_pg_update_row – lines 490-493
#     Branch: is_active is not None → added to sets
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 20. products_pg_update_row – lines 495-496
#     Branch: sets is empty → raise 400 (edge case: only is_active col, parse returns None)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 21. products_pg_insert_row – lines 528-529
#     Branch: model_number is empty → _norm_model called
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 22. products_pg_insert_row – lines 556-558
#     Branch: "xcagi_mod_id" in col_names AND mid is set → appended to icols
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 23. products_pg_insert_row – lines 558-559
#     Branch: icols is empty → raise 500
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 24. products_pg_batch_delete_rows – lines 561-562
#     Branch: pid is None → skipped.append(str(raw))
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 25. _customer_pg_delete_anywhere – lines 402-409
#     Branch: resolved_name still None → _customer_find_by_id consulted
# ---------------------------------------------------------------------------
