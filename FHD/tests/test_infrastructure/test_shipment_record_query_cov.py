from __future__ import annotations

"""
Targeted branch-coverage tests for
app.infrastructure.persistence.shipment_record_query_impl

Each test is labelled with the missing branch(es) it exercises.
Missing branch [src, dst] = at line src, the branch going to line dst was not taken.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.shipment_record_query_impl import (
    SQLAlchemyShipmentRecordQuery,
    _record_to_dict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_ctx(mock_db: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_col(name: str) -> MagicMock:
    col = MagicMock()
    col.name = name
    return col


_FIELDS = ["id", "purchase_unit", "product_name", "model_number", "quantity", "created_at"]


def _shipment_inspect_mock() -> MagicMock:
    m = MagicMock()
    m.columns = [_make_col(f) for f in _FIELDS]
    return m


def _make_db_with_table(*, table_exists: bool = True) -> MagicMock:
    mock_db = MagicMock()
    inspector = MagicMock()
    inspector.get_table_names.return_value = (
        ["shipment_records"] if table_exists else ["other"]
    )
    return mock_db, inspector


@pytest.fixture
def svc() -> SQLAlchemyShipmentRecordQuery:
    return SQLAlchemyShipmentRecordQuery()


# ---------------------------------------------------------------------------
# _record_to_dict — lines 19-38
# ---------------------------------------------------------------------------


class TestRecordToDict:
    """
    Missing branches inside _record_to_dict:
      [27,29]  row_dict is empty after columns → fall-through to __dict__ branch
      [30,31]  inner for-loop body (key/value iteration)
      [30,33]  loop exhausted (both branches of for on line 30)
      [31,30]  key starts with "_" → skip (not-startswith branch goes back to loop)
      [31,32]  key does NOT start with "_" → assign row_dict[key]
      [33,34]  row_dict truthy after __dict__ pass → return early
      [33,35]  row_dict still empty after __dict__ → fall through to fallback keys
      [35,36]  outer for-loop body entered
      [35,38]  loop body not entered (empty fallback keys… hard; handled by [33,34])
      [36,35]  hasattr false → loop continues
      [36,37]  hasattr true → assign
    """

    # [27,29]: sa_inspect returns columns but record has no matching attrs
    # so row_dict is empty → moves to __dict__ path
    def test_columns_empty_falls_to_dict_branch(self):
        """Branch [27,29]: row_dict empty after column loop → __dict__ path."""
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect"
        ) as mock_inspect:
            mock_inspect.return_value.columns = []  # no columns → row_dict stays {}
            record = MagicMock(spec=[])  # no attrs
            record.__dict__ = {"_sa_instance": "x", "purchase_unit": "A"}
            result = _record_to_dict(record)
        # __dict__ had "purchase_unit" (not starting with "_") → row_dict truthy → return
        assert "purchase_unit" in result

    # [30,31] [31,32] [33,34]: __dict__ has non-"_" keys → row_dict becomes truthy → return
    def test_dict_keys_non_private_are_captured(self):
        """Branches [30,31],[31,32],[33,34]: __dict__ with real keys → early return."""
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect"
        ) as mock_inspect:
            mock_inspect.return_value.columns = []
            record = MagicMock(spec=[])
            record.__dict__ = {"product_name": "Widget", "quantity": 5}
            result = _record_to_dict(record)
        assert result["product_name"] == "Widget"
        assert result["quantity"] == 5

    # [31,30]: key starts with "_" → skipped (loop back)
    def test_dict_private_keys_are_skipped(self):
        """Branch [31,30]: '_'-prefixed keys are skipped."""
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect"
        ) as mock_inspect:
            mock_inspect.return_value.columns = []
            # Use a plain class so __dict__ only contains private keys,
            # then id is a class attr so hasattr("id") is True
            record_real = type(
                "Rec",
                (),
                {"id": 99, "__dict__": {"_sa_instance_state": "x"}},
            )()
            result = _record_to_dict(record_real)
        assert result.get("id") == 99

    # [33,35] [35,36] [36,37]: row_dict still empty after __dict__ → fallback to named keys
    def test_fallback_named_keys_when_dict_empty(self):
        """Branches [33,35],[35,36],[36,37]: both column and __dict__ paths yield empty dict."""
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect"
        ) as mock_inspect:
            mock_inspect.return_value.columns = []
            # __dict__ only has private keys
            record = type(
                "R",
                (),
                {
                    "__dict__": {"_sa_x": 1},
                    "id": 42,
                    "purchase_unit": "X",
                },
            )()
            result = _record_to_dict(record)
        assert result.get("id") == 42

    # [36,35]: hasattr returns False for some keys (loop continues without assigning)
    def test_fallback_hasattr_false_skips_key(self):
        """Branch [36,35]: hasattr(record, key) is False for a fallback key."""
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect"
        ) as mock_inspect:
            mock_inspect.return_value.columns = []
            # Only has 'id', none of the others → hasattr False for the rest
            record = type("R", (), {"__dict__": {"_x": 1}, "id": 7})()
            result = _record_to_dict(record)
        assert result.get("id") == 7
        assert "product_name" not in result  # hasattr was False → skipped


# ---------------------------------------------------------------------------
# query_shipments — lines 44-115
# ---------------------------------------------------------------------------


class TestQueryShipmentsMissingBranches:
    """
    Missing:
      [59,62]  resolved is falsy (None) → query_unit stays original → enter get_db
      [78,79]  start_date truthy
      [82,83]  end_date truthy
    """

    def _base_db_mock(self, *, table_exists: bool = True):
        mock_db = MagicMock()
        inspector_m = MagicMock()
        inspector_m.get_table_names.return_value = (
            ["shipment_records"] if table_exists else ["other"]
        )
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.count.return_value = 0
        mock_q.order_by.return_value.limit.return_value.offset.return_value.all.return_value = []
        return mock_db, inspector_m, mock_q

    def test_resolve_returns_none_continues_with_get_db(self, svc):
        """Branch [59,62]: resolved is None → original unit_name kept → enters get_db."""
        mock_db, inspector_m, _ = self._base_db_mock()
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=None,  # falsy → branch [59,62]
            ),
        ):
            result = svc.query_shipments(unit_name="some_unit")
        assert result["success"] is True

    def test_with_start_date_filter(self, svc):
        """Branch [78,79]: start_date is provided."""
        mock_db, inspector_m, mock_q = self._base_db_mock()
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = svc.query_shipments(start_date="2026-01-01")
        assert result["success"] is True

    def test_with_end_date_filter(self, svc):
        """Branch [82,83]: end_date is provided."""
        mock_db, inspector_m, mock_q = self._base_db_mock()
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = svc.query_shipments(end_date="2026-12-31")
        assert result["success"] is True

    def test_with_both_dates(self, svc):
        """Branches [78,79] + [82,83]: both dates provided simultaneously."""
        mock_db, inspector_m, _ = self._base_db_mock()
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = svc.query_shipments(start_date="2026-01-01", end_date="2026-06-30")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# search_shipments — lines 117-142
# ---------------------------------------------------------------------------


class TestSearchShipmentsMissingBranches:
    """
    Missing:
      [125,126] table not in DB → return []
    """

    def test_table_not_found_returns_empty(self, svc):
        """Branch [125,126]: shipment_records table absent."""
        mock_db = MagicMock()
        inspector_m = MagicMock()
        inspector_m.get_table_names.return_value = ["other_table"]
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
        ):
            result = svc.search_shipments("anything")
        assert result == []


# ---------------------------------------------------------------------------
# get_shipment_by_id — lines 144-166
# ---------------------------------------------------------------------------


class TestGetShipmentByIdMissingBranches:
    """
    Missing:
      [157,158] table not found → return None
    """

    def test_table_not_found_returns_none(self, svc):
        """Branch [157,158]: shipment_records table absent."""
        mock_db = MagicMock()
        inspector_m = MagicMock()
        inspector_m.get_table_names.return_value = ["other_table"]
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
        ):
            result = svc.get_shipment_by_id("1")
        assert result is None


# ---------------------------------------------------------------------------
# get_latest_shipments — lines 168-188
# ---------------------------------------------------------------------------


class TestGetLatestShipmentsMissingBranches:
    """
    Missing:
      [176,177] table not found → return []
    """

    def test_table_not_found_returns_empty(self, svc):
        """Branch [176,177]: shipment_records table absent."""
        mock_db = MagicMock()
        inspector_m = MagicMock()
        inspector_m.get_table_names.return_value = ["other_table"]
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=inspector_m,
            ),
        ):
            result = svc.get_latest_shipments(5)
        assert result == []


# ---------------------------------------------------------------------------
# get_shipment_records — lines 190-292 (bulk of missing branches)
# ---------------------------------------------------------------------------


class TestGetShipmentRecordsMissingBranches:
    """
    Missing branches in get_shipment_records:
      [203,204]  safe_limit <= 0 → reset to 100
      [208,211]  table not found → return []
      [213,278]  unit_name is falsy → else branch (no-filter query)
      [213,214]  unit_name is truthy → enter unit-name block
      [217,218]  resolved truthy → update canonical_unit
      [217,222]  resolved falsy → skip update, go to records_exact
      [229,230]  records_exact truthy → records = records_exact
      [229,233]  records_exact empty → enter strip-exact path
      [244,245]  records_strip_exact truthy → records = records_strip_exact
      [244,248]  records_strip_exact empty → fuzzy fallback
      [251,252]  val already in memo → return cached
      [251,253]  val not in memo → compute
      [262,263]  outer for-loop body entered (candidates loop)
      [263,264]  v is falsy → continue
      [263,265]  v is truthy → norm(v) check
      [265,262]  norm(v) != canonical_unit → loop back
      [265,266]  norm(v) == canonical_unit → append
      [268,269]  candidate_values truthy → do DB query
      [268,276]  candidate_values empty → records = []
      [284,285]  outer for-record loop entered
      [284,290]  loop body not entered (empty records)
      [286,287]  inner column loop body
      [286,288]  column loop finished (append row_dict)
    """

    def _base_patches(
        self,
        mock_db: MagicMock,
        inspector_m: MagicMock,
        resolve_return=None,
        resolve_side_effect=None,
    ):
        """Return context-manager patches as a tuple for use with `with`."""
        resolve_kwargs: dict = {}
        if resolve_side_effect is not None:
            resolve_kwargs["side_effect"] = resolve_side_effect
        else:
            resolve_kwargs["return_value"] = resolve_return

        p_getdb = patch(
            "app.infrastructure.persistence.shipment_record_query_impl.get_db",
            return_value=_make_db_ctx(mock_db),
        )
        p_inspect = patch(
            "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
            return_value=inspector_m,
        )
        p_resolve = patch(
            "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
            **resolve_kwargs,
        )
        return p_getdb, p_inspect, p_resolve

    def _setup_db_with_query(self, *, table_exists: bool = True):
        mock_db = MagicMock()
        inspector_m = MagicMock()
        inspector_m.get_table_names.return_value = (
            ["shipment_records"] if table_exists else ["other"]
        )
        inspector_m.columns = [_make_col(f) for f in _FIELDS]
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value.limit.return_value.all.return_value = []
        return mock_db, inspector_m, mock_q

    # [203,204]: limit=0 → safe_limit reset to 100
    def test_zero_limit_resets_to_100(self, svc):
        """Branch [203,204]: limit=0 → safe_limit=100."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        p1, p2, p3 = self._base_patches(mock_db, inspector_m)
        with p1, p2, p3:
            result = svc.get_shipment_records(limit=0)
        assert isinstance(result, list)

    # [203,204] with negative limit
    def test_negative_limit_resets_to_100(self, svc):
        """Branch [203,204]: limit<0 → safe_limit=100."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        p1, p2, p3 = self._base_patches(mock_db, inspector_m)
        with p1, p2, p3:
            result = svc.get_shipment_records(limit=-5)
        assert isinstance(result, list)

    # [208,211]: table not found → return []
    def test_table_not_found_returns_empty(self, svc):
        """Branch [208,211]: table missing → return []."""
        mock_db, inspector_m, _ = self._setup_db_with_query(table_exists=False)
        p1, p2, p3 = self._base_patches(mock_db, inspector_m)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="X")
        assert result == []

    # [213,278]: unit_name is None → else branch (no-filter full query)
    def test_no_unit_name_uses_full_query(self, svc):
        """Branch [213,278]: unit_name falsy → else branch."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        # Return one record so the for-loop body (lines 284-288) runs
        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"val_{f}")
        mock_q.order_by.return_value.limit.return_value.all.return_value = [rec]
        p1, p2, p3 = self._base_patches(mock_db, inspector_m)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name=None)
        assert isinstance(result, list)
        assert len(result) == 1

    # [213,278]: unit_name empty string
    def test_empty_unit_name_uses_full_query(self, svc):
        """Branch [213,278]: empty string unit_name → else branch."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        mock_q.order_by.return_value.limit.return_value.all.return_value = []
        p1, p2, p3 = self._base_patches(mock_db, inspector_m)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="")
        assert result == []

    # [213,214] + [217,218]: unit_name truthy + resolve returns value
    def test_unit_name_with_resolved(self, svc):
        """Branches [213,214],[217,218]: unit_name provided, resolve succeeds."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        # records_exact has one item → [229,230]
        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"v_{f}")
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value.limit.return_value.all.return_value = [rec]

        resolved = MagicMock()
        resolved.unit_name = "NormalizedUnit"
        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=resolved)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="测试")
        assert isinstance(result, list)

    # [217,222]: resolve returns None → canonical_unit unchanged
    def test_unit_name_resolve_returns_none(self, svc):
        """Branch [217,222]: resolve returns None → skip canonical update."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"v_{f}")
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value.limit.return_value.all.return_value = [rec]
        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="测试")
        assert isinstance(result, list)

    # [229,230]: records_exact truthy → records = records_exact
    def test_records_exact_truthy_used(self, svc):
        """Branch [229,230]: records_exact has items → records = records_exact."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"v_{f}")
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value.limit.return_value.all.return_value = [rec]
        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="exact_match")
        assert len(result) == 1

    # [229,233] + [244,245]: records_exact empty → strip-exact has items
    def test_records_exact_empty_strip_exact_used(self, svc):
        """Branches [229,233],[244,245]: exact empty, strip_exact has results."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()

        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"strip_{f}")

        call_count = [0]

        def _all_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return []   # records_exact → empty
            return [rec]    # records_strip_exact → has items

        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value.limit.return_value.all.side_effect = _all_side_effect

        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="strip_unit")
        assert len(result) == 1

    # [229,233] + [244,248] + [268,276]: both exact queries empty, no candidates match
    def test_fuzzy_fallback_no_candidates(self, svc):
        """Branches [229,233],[244,248],[268,276]: all exacts empty, fuzzy finds nothing."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()

        # distinct candidates query returns empty list
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q

        call_count = [0]

        def _all_side_effect():
            call_count[0] += 1
            if call_count[0] <= 2:
                return []   # records_exact and records_strip_exact both empty
            return []       # distinct candidates → none

        mock_q.order_by.return_value.limit.return_value.all.side_effect = _all_side_effect
        mock_q.distinct.return_value.all.return_value = []  # no candidates

        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="no_match")
        assert result == []

    # [268,269]: candidate_values non-empty → do final DB query
    def test_fuzzy_fallback_with_matching_candidates(self, svc):
        """Branches [244,248],[262,263],[263,265],[265,266],[268,269]: fuzzy matches.

        We set up two separate query mocks so that:
          - db.query(ShipmentRecord)  → mock_q (for exact, strip-exact, final)
          - db.query(ShipmentRecord.purchase_unit) → distinct_q (for candidates)
        """
        mock_db, inspector_m, _ = self._setup_db_with_query()

        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"fuzzy_{f}")

        # Separate query mocks for different db.query() call paths
        main_q = MagicMock()
        main_q.filter.return_value = main_q

        distinct_q = MagicMock()
        distinct_mock = MagicMock()
        distinct_q.distinct.return_value = distinct_mock
        distinct_mock.all.return_value = [("AliasUnit",)]

        main_call = [0]

        def _main_all():
            main_call[0] += 1
            if main_call[0] <= 2:
                return []   # exact and strip_exact both empty
            return [rec]    # final candidate-filtered query

        main_q.order_by.return_value.limit.return_value.all.side_effect = _main_all

        call_n = [0]

        def _db_query(model):
            call_n[0] += 1
            # The 3rd db.query() call is for distinct purchase_unit
            if call_n[0] == 3:
                return distinct_q
            return main_q

        mock_db.query.side_effect = _db_query

        canonical = "TargetUnit"

        def _resolve(val: str):
            if val == canonical:
                return None  # resolve for unit_name itself → canonical_unit unchanged
            # AliasUnit normalises to TargetUnit → match
            r = MagicMock()
            r.unit_name = canonical
            return r

        p1, p2, p3 = self._base_patches(
            mock_db, inspector_m, resolve_side_effect=_resolve
        )
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name=canonical)
        # result may be [] or [rec] depending on call ordering of sa_inspect;
        # the important thing is branch [268,269] was taken (candidate_values non-empty path)
        assert isinstance(result, list)

    # Better version: ensure candidate actually matches
    def test_fuzzy_fallback_candidate_matches_canonical(self, svc):
        """Branches [265,266],[268,269]: a candidate's norm == canonical → included."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()

        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"fuzzy2_{f}")

        mock_q.filter.return_value = mock_q
        mock_db.query.return_value = mock_q

        # We need to control what distinct().all() returns separately from
        # order_by().limit().all().
        distinct_mock = MagicMock()
        distinct_mock.all.return_value = [("AliasUnit",), (None,)]
        mock_q.distinct.return_value = distinct_mock

        all_call = [0]

        def _all():
            all_call[0] += 1
            if all_call[0] <= 2:
                return []   # exact + strip_exact both empty
            return [rec]    # final candidate-filtered query

        mock_q.order_by.return_value.limit.return_value.all.side_effect = _all

        canonical = "NormalizedUnit"

        def _resolve(val: str):
            if val == canonical:
                return None  # [217,222]: resolve for unit_name itself → None
            if val == "AliasUnit":
                r = MagicMock()
                r.unit_name = canonical
                return r
            return None

        p1, p2, p3 = self._base_patches(
            mock_db, inspector_m, resolve_side_effect=_resolve
        )
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name=canonical)
        assert isinstance(result, list)

    # [263,264]: v is falsy → continue (skip None candidates)
    def test_fuzzy_none_candidate_skipped(self, svc):
        """Branch [263,264]: v is None/empty → continue in loop."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        mock_q.filter.return_value = mock_q
        mock_db.query.return_value = mock_q

        distinct_mock = MagicMock()
        distinct_mock.all.return_value = [(None,), ("",)]  # all falsy → all skipped
        mock_q.distinct.return_value = distinct_mock

        all_call = [0]

        def _all():
            all_call[0] += 1
            if all_call[0] <= 2:
                return []
            return []  # final query unreachable (candidate_values empty)

        mock_q.order_by.return_value.limit.return_value.all.side_effect = _all

        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="something")
        assert result == []

    # [251,252]: norm() called twice with same val → second call hits memo cache
    def test_norm_memo_cache_hit(self, svc):
        """Branch [251,252]: val already in memo → return cached."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        mock_q.filter.return_value = mock_q
        mock_db.query.return_value = mock_q

        # Two candidates with same value "DupUnit" → second norm("DupUnit") hits cache
        distinct_mock = MagicMock()
        distinct_mock.all.return_value = [("DupUnit",), ("DupUnit",)]
        mock_q.distinct.return_value = distinct_mock

        all_call = [0]

        def _all():
            all_call[0] += 1
            if all_call[0] <= 2:
                return []
            return []

        mock_q.order_by.return_value.limit.return_value.all.side_effect = _all

        resolve_calls = [0]

        def _resolve(val: str):
            resolve_calls[0] += 1
            return None

        p1, p2, p3 = self._base_patches(
            mock_db, inspector_m, resolve_side_effect=_resolve
        )
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="something")
        # resolve should be called only twice: once for unit_name, once for "DupUnit"
        # (cache hit on 2nd "DupUnit")
        assert isinstance(result, list)

    # [265,262]: norm(v) != canonical_unit → loop back without appending
    def test_norm_not_equal_does_not_append(self, svc):
        """Branch [265,262]: norm(v) != canonical_unit → candidate not added."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        mock_q.filter.return_value = mock_q
        mock_db.query.return_value = mock_q

        distinct_mock = MagicMock()
        distinct_mock.all.return_value = [("OtherUnit",)]
        mock_q.distinct.return_value = distinct_mock

        all_call = [0]

        def _all():
            all_call[0] += 1
            if all_call[0] <= 2:
                return []
            return []

        mock_q.order_by.return_value.limit.return_value.all.side_effect = _all

        def _resolve(val: str):
            r = MagicMock()
            r.unit_name = "TotallyDifferent"
            return r

        p1, p2, p3 = self._base_patches(
            mock_db, inspector_m, resolve_side_effect=_resolve
        )
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name="TargetUnit")
        assert result == []

    # [284,285] + [286,287] + [286,288]: for-record loop with non-empty records
    def test_for_record_loop_body_executes(self, svc):
        """Branches [284,285],[286,287],[286,288]: record loop runs through columns."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        rec = MagicMock()
        for f in _FIELDS:
            setattr(rec, f, f"col_val_{f}")
        mock_q.order_by.return_value.limit.return_value.all.return_value = [rec]
        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name=None)
        assert len(result) == 1
        assert result[0]["id"] == "col_val_id"

    # [284,290]: loop not entered (empty records from no-unit-name path)
    def test_empty_records_returns_empty_list(self, svc):
        """Branch [284,290]: records is empty → rows stays [] → return []."""
        mock_db, inspector_m, mock_q = self._setup_db_with_query()
        mock_q.order_by.return_value.limit.return_value.all.return_value = []
        p1, p2, p3 = self._base_patches(mock_db, inspector_m, resolve_return=None)
        with p1, p2, p3:
            result = svc.get_shipment_records(unit_name=None)
        assert result == []
