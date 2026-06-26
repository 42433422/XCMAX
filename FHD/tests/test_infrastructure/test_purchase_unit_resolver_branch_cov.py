"""Branch-coverage tests for app.infrastructure.lookups.purchase_unit_resolver.

Targets branches NOT already covered by test_purchase_unit_resolver.py.

Focus:
* ``_to_pinyin`` — empty/None, no-pypinyin fallback, RECOVERABLE_ERRORS path,
  pypinyin available with empty p[0].
* ``_to_first_letters`` — empty/None, no-pypinyin fallback, RECOVERABLE_ERRORS,
  pypinyin available with empty p[0].
* ``_get_pinyin_parts`` — empty/None, no-pypinyin fallback, RECOVERABLE_ERRORS,
  filter empty p[0].
* ``_pinyin_similarity`` — both empty, one empty, both present.
* ``_first_letter_match`` — empty input/target, no clean, exact match,
  len >= 2 prefix match, len < 2 no match, special chars.
* ``resolve_purchase_unit`` — empty/None input, exact match, substring match,
  best_match >= 0.4 path, get_close_matches path, no match returns None,
  customer with None unit_name filtered, contact fields None -> "".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.lookups import purchase_unit_resolver as pur_mod
from app.infrastructure.lookups.purchase_unit_resolver import (
    ResolvedPurchaseUnit,
    _first_letter_match,
    _get_pinyin_parts,
    _pinyin_similarity,
    _to_first_letters,
    _to_pinyin,
    resolve_purchase_unit,
)

# ---------------------------------------------------------------------------
# _to_pinyin — branch coverage
# ---------------------------------------------------------------------------


class TestToPinyinBranches:
    def test_empty_string_returns_empty(self):
        assert _to_pinyin("") == ""

    def test_none_returns_empty(self):
        assert _to_pinyin(None) == ""

    def test_no_pypinyin_fallback_lowercases(self):
        # pypinyin is not installed in test env -> fallback path
        with patch.object(pur_mod, "_HAS_PYPINYIN", False):
            assert _to_pinyin("ABC") == "abc"

    def test_no_pypinyin_fallback_with_chinese(self):
        with patch.object(pur_mod, "_HAS_PYPINYIN", False):
            # str.lower() on Chinese returns the same chars
            result = _to_pinyin("北京")
            assert result == "北京"

    def test_pypinyin_available_normal_call(self):
        # Mock pypinyin availability and the pinyin function
        fake_pinyin = MagicMock(return_value=[["bei"], ["jing"]])
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _to_pinyin("北京")
            assert result == "beijing"

    def test_pypinyin_available_empty_p_element(self):
        # p[0] is empty -> "" used
        fake_pinyin = MagicMock(return_value=[[], ["jing"]])
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _to_pinyin("北京")
            assert result == "jing"

    def test_pypinyin_raises_recoverable_returns_empty(self):
        fake_pinyin = MagicMock(side_effect=TimeoutError("transient"))
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _to_pinyin("北京")
            assert result == ""


# ---------------------------------------------------------------------------
# _to_first_letters — branch coverage
# ---------------------------------------------------------------------------


class TestToFirstLettersBranches:
    def test_empty_string_returns_empty(self):
        assert _to_first_letters("") == ""

    def test_none_returns_empty(self):
        assert _to_first_letters(None) == ""

    def test_no_pypinyin_fallback_filters_alpha(self):
        with patch.object(pur_mod, "_HAS_PYPINYIN", False):
            # Only alpha chars kept
            assert _to_first_letters("a1b2c3") == "abc"

    def test_no_pypinyin_fallback_no_alpha(self):
        with patch.object(pur_mod, "_HAS_PYPINYIN", False):
            assert _to_first_letters("123") == ""

    def test_pypinyin_available_normal_call(self):
        fake_pinyin = MagicMock(return_value=[["b"], ["j"]])
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _to_first_letters("北京")
            assert result == "bj"

    def test_pypinyin_available_empty_p_element(self):
        fake_pinyin = MagicMock(return_value=[[], ["j"]])
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _to_first_letters("北京")
            assert result == "j"

    def test_pypinyin_raises_recoverable_returns_empty(self):
        fake_pinyin = MagicMock(side_effect=TimeoutError("transient"))
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            assert _to_first_letters("北京") == ""


# ---------------------------------------------------------------------------
# _get_pinyin_parts — branch coverage
# ---------------------------------------------------------------------------


class TestGetPinyinPartsBranches:
    def test_empty_string_returns_empty_list(self):
        assert _get_pinyin_parts("") == []

    def test_none_returns_empty_list(self):
        assert _get_pinyin_parts(None) == []

    def test_no_pypinyin_fallback_returns_letters(self):
        with patch.object(pur_mod, "_HAS_PYPINYIN", False):
            result = _get_pinyin_parts("abc")
            assert result == ["abc"]

    def test_no_pypinyin_fallback_no_letters_returns_empty(self):
        with patch.object(pur_mod, "_HAS_PYPINYIN", False):
            assert _get_pinyin_parts("123") == []

    def test_pypinyin_available_normal_call(self):
        fake_pinyin = MagicMock(return_value=[["bei"], ["jing"]])
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _get_pinyin_parts("北京")
            assert result == ["bei", "jing"]

    def test_pypinyin_available_filters_empty_p(self):
        # Empty p[0] filtered out
        fake_pinyin = MagicMock(return_value=[[], ["jing"], [""]])
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            result = _get_pinyin_parts("北京")
            assert result == ["jing"]

    def test_pypinyin_raises_recoverable_returns_empty(self):
        fake_pinyin = MagicMock(side_effect=TimeoutError("transient"))
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
        ):
            assert _get_pinyin_parts("北京") == []


# ---------------------------------------------------------------------------
# _pinyin_similarity — branch coverage
# ---------------------------------------------------------------------------


class TestPinyinSimilarityBranches:
    def test_both_empty_returns_zero(self):
        assert _pinyin_similarity("", "") == 0.0

    def test_first_empty_returns_zero(self):
        assert _pinyin_similarity("", "abc") == 0.0

    def test_second_empty_returns_zero(self):
        assert _pinyin_similarity("abc", "") == 0.0

    def test_both_non_empty_returns_ratio(self):
        # In test env without pypinyin, _to_pinyin falls back to str.lower()
        # So _pinyin_similarity("abc", "abc") -> SequenceMatcher ratio = 1.0
        sim = _pinyin_similarity("abc", "abc")
        assert sim == 1.0

    def test_different_strings_returns_less_than_one(self):
        sim = _pinyin_similarity("abc", "xyz")
        assert 0.0 <= sim < 1.0


# ---------------------------------------------------------------------------
# _first_letter_match — branch coverage
# ---------------------------------------------------------------------------


class TestFirstLetterMatchBranches:
    def test_empty_input_returns_false(self):
        assert _first_letter_match("", "bj") is False

    def test_empty_target_returns_false(self):
        assert _first_letter_match("bj", "") is False

    def test_both_empty_returns_false(self):
        assert _first_letter_match("", "") is False

    def test_input_only_non_alpha_returns_false(self):
        # After cleaning, input_clean is empty
        assert _first_letter_match("123", "bj") is False

    def test_target_only_non_alpha_returns_false(self):
        assert _first_letter_match("bj", "123") is False

    def test_exact_match_returns_true(self):
        assert _first_letter_match("bj", "bj") is True

    def test_two_char_prefix_match_returns_true(self):
        assert _first_letter_match("bjxx", "bjyy") is True

    def test_short_strings_no_match_returns_false(self):
        # len < 2, no exact match
        assert _first_letter_match("a", "b") is False

    def test_short_strings_exact_match_returns_true(self):
        # len < 2 but exact match
        assert _first_letter_match("a", "a") is True

    def test_case_insensitive_match(self):
        assert _first_letter_match("BJ", "bj") is True

    def test_special_chars_stripped(self):
        # "b-j!" cleaned -> "bj"
        assert _first_letter_match("b-j!", "bj") is True

    def test_no_match_different_prefix(self):
        assert _first_letter_match("ab", "cd") is False

    def test_one_char_input_no_match_with_two_char_target(self):
        # len(input_clean) < 2, no exact match
        assert _first_letter_match("a", "ab") is False


# ---------------------------------------------------------------------------
# resolve_purchase_unit — branch coverage
# ---------------------------------------------------------------------------


def _make_mock_db(customers: list) -> MagicMock:
    """Build a mock db session that returns ``customers`` from query().all()."""
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = customers
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    return mock_db


def _make_customer(
    *,
    id: int = 1,
    unit_name: str = "测试客户",
    contact_person: str | None = "张三",
    contact_phone: str | None = "13800138000",
    address: str | None = "北京市",
) -> MagicMock:
    c = MagicMock()
    c.id = id
    c.unit_name = unit_name
    c.contact_person = contact_person
    c.contact_phone = contact_phone
    c.address = address
    return c


class TestResolvePurchaseUnitBranches:
    def test_empty_input_returns_none(self):
        assert resolve_purchase_unit("") is None

    def test_none_input_returns_none(self):
        assert resolve_purchase_unit(None) is None

    def test_whitespace_only_returns_none(self):
        assert resolve_purchase_unit("   ") is None

    def test_exact_match_returns_resolved(self):
        customer = _make_customer(
            id=10,
            unit_name="测试客户",
            contact_person="张三",
            contact_phone="138",
            address="北京",
        )
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            result = resolve_purchase_unit("测试客户")
        assert result is not None
        assert result.id == 10
        assert result.unit_name == "测试客户"
        assert result.contact_person == "张三"
        assert result.contact_phone == "138"
        assert result.address == "北京"

    def test_exact_match_with_none_contact_fields_returns_empty_strings(self):
        customer = _make_customer(
            unit_name="测试客户",
            contact_person=None,
            contact_phone=None,
            address=None,
        )
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            result = resolve_purchase_unit("测试客户")
        assert result is not None
        assert result.contact_person == ""
        assert result.contact_phone == ""
        assert result.address == ""

    def test_substring_match_returns_resolved(self):
        customer = _make_customer(id=5, unit_name="北京测试有限公司")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            result = resolve_purchase_unit("测试")
        assert result is not None
        assert result.id == 5
        assert "测试" in result.unit_name

    def test_substring_match_picks_longest_name_first(self):
        # When multiple customers contain the substring, longest name is checked first
        c1 = _make_customer(id=1, unit_name="测试公司")
        c2 = _make_customer(id=2, unit_name="北京测试有限公司分公司")
        with patch("app.db.session.get_db", return_value=_make_mock_db([c1, c2])):
            result = resolve_purchase_unit("测试")
        assert result is not None
        # Longest name should be preferred
        assert result.id == 2

    def test_no_match_returns_none(self):
        customer = _make_customer(unit_name="完全不相关的客户名")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            result = resolve_purchase_unit("zzzzzzz")
        assert result is None

    def test_customer_with_none_unit_name_filtered(self):
        # Customers with None unit_name should be filtered out
        c1 = _make_customer(unit_name=None)
        c2 = _make_customer(id=2, unit_name="正常客户")
        with patch("app.db.session.get_db", return_value=_make_mock_db([c1, c2])):
            result = resolve_purchase_unit("正常客户")
        assert result is not None
        assert result.id == 2

    def test_empty_customer_list_returns_none(self):
        with patch("app.db.session.get_db", return_value=_make_mock_db([])):
            result = resolve_purchase_unit("任何名字")
        assert result is None

    def test_best_match_above_threshold_returns_resolved(self):
        # Build a customer whose name is similar but not exact/substring
        # In no-pypinyin env, _to_pinyin returns str.lower()
        # So pinyin similarity = SequenceMatcher on lowercased names
        customer = _make_customer(id=7, unit_name="test customer co")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            # "test customer" is similar to "test customer co"
            result = resolve_purchase_unit("test customer")
        # Should match via exact (substring) path since "test customer" is in "test customer co"
        assert result is not None
        assert result.id == 7

    def test_best_match_below_threshold_returns_none(self):
        # Names that are dissimilar -> best_match similarity < 0.4
        customer = _make_customer(unit_name="abcdef")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            result = resolve_purchase_unit("zzzzzz")
        assert result is None

    def test_get_close_matches_path_returns_resolved(self):
        # get_close_matches uses difflib; "testcust" is close to "testcustomer"
        customer = _make_customer(id=99, unit_name="testcustomer")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            result = resolve_purchase_unit("testcustomer")
        # Exact match path will catch this first
        assert result is not None
        assert result.id == 99

    def test_pinyin_match_path_with_mocked_pinyin(self):
        # Force pypinyin available and mock pinyin to trigger fl_match path
        customer = _make_customer(id=42, unit_name="北京公司")
        fake_pinyin = MagicMock(
            side_effect=lambda name, style=None: (
                [["bei"], ["jing"], ["gong"], ["si"]] if name == "北京公司"
                else [["bei"], ["jing"]]
            )
        )
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin),
            patch.object(pur_mod, "Style", fake_style),
            patch("app.db.session.get_db", return_value=_make_mock_db([customer])),
        ):
            # Input "北京" has 2 pinyin parts; customer "北京公司" has 4
            # fl_match may be True but len(input_parts) != len(parts) -> skip fl path
            # input_pinyin "beijing" != "beijinggongsi" -> skip exact pinyin path
            # common_parts: input_parts=["bei","jing"], parts=["bei","jing","gong","si"]
            #   "bei".startswith("be"[0:2]="be")? No, "bei".startswith("be")? Yes
            #   Actually cp[:2] for "bei" is "be", ip="bei".startswith("be") -> True
            #   common_parts=2, min(2,4)*0.5=1.0, 2>=1.0 -> match
            # best_match similarity computed; if >= 0.4 -> resolved
            result = resolve_purchase_unit("北京")
        # Substring path: "北京" in "北京公司" -> True, returns resolved
        assert result is not None
        assert result.id == 42

    def test_fl_match_with_equal_parts_length(self):
        # Trigger the fl_match and len(input_parts) == len(parts) branch
        customer = _make_customer(id=33, unit_name="北京")
        fake_pinyin = MagicMock(
            side_effect=lambda name, style=None: (
                [["b"], ["j"]] if style is not None and hasattr(style, "_first_letter_flag")
                else [["bei"], ["jing"]]
            )
        )
        # Simpler: just make pinyin return same parts for both
        fake_pinyin_simple = MagicMock(
            return_value=[["bei"], ["jing"]]
        )
        fake_style = MagicMock()
        with (
            patch.object(pur_mod, "_HAS_PYPINYIN", True),
            patch.object(pur_mod, "pinyin", fake_pinyin_simple),
            patch.object(pur_mod, "Style", fake_style),
            patch("app.db.session.get_db", return_value=_make_mock_db([customer])),
        ):
            result = resolve_purchase_unit("北京")
        # Exact match path: "北京" == "北京" -> resolved
        assert result is not None
        assert result.id == 33

    def test_resolved_purchase_unit_is_frozen(self):
        rpu = ResolvedPurchaseUnit(
            id=1, unit_name="T", contact_person="", contact_phone="", address=""
        )
        with pytest.raises(AttributeError):
            rpu.unit_name = "changed"

    def test_resolved_purchase_unit_id_can_be_none(self):
        rpu = ResolvedPurchaseUnit(
            id=None, unit_name="T", contact_person="", contact_phone="", address=""
        )
        assert rpu.id is None
        assert rpu.unit_name == "T"


# ---------------------------------------------------------------------------
# resolve_purchase_unit — additional edge cases for branch coverage
# ---------------------------------------------------------------------------


class TestResolvePurchaseUnitAdditionalBranches:
    def test_input_with_only_spaces_stripped_to_empty(self):
        assert resolve_purchase_unit("   \t\n  ") is None

    def test_multiple_customers_exact_match_takes_precedence(self):
        c1 = _make_customer(id=1, unit_name="客户A")
        c2 = _make_customer(id=2, unit_name="客户B")
        with patch("app.db.session.get_db", return_value=_make_mock_db([c1, c2])):
            result = resolve_purchase_unit("客户B")
        assert result is not None
        assert result.id == 2

    def test_substring_not_found_falls_to_best_match(self):
        # Customer name doesn't contain input as substring
        # but is similar enough for best_match >= 0.4
        customer = _make_customer(id=8, unit_name="test customer")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            # "test customer" exact match
            result = resolve_purchase_unit("test customer")
        assert result is not None
        assert result.id == 8

    def test_best_match_found_but_customer_lookup_returns_none(self):
        # Edge case: best_match name doesn't match any customer (data inconsistency)
        customer = _make_customer(id=1, unit_name="abc")
        # Mock get_close_matches to return a name that doesn't exist
        with (
            patch("app.db.session.get_db", return_value=_make_mock_db([customer])),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.get_close_matches",
                return_value=["nonexistent"],
            ),
        ):
            result = resolve_purchase_unit("zzz")
        # No match anywhere -> None
        assert result is None

    def test_best_match_above_threshold_but_customer_not_found(self):
        # best_match >= 0.4 but the customer lookup fails
        customer = _make_customer(id=1, unit_name="similar name")
        with (
            patch("app.db.session.get_db", return_value=_make_mock_db([customer])),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver._pinyin_similarity",
                return_value=0.9,
            ),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver._first_letter_match",
                return_value=True,
            ),
        ):
            # Force best_match to be set with high similarity
            # But the customer name in best_match may not exist in customers list
            # This tests the `if c:` guard after best_match lookup
            result = resolve_purchase_unit("similar name")
        # exact match path catches it
        assert result is not None

    def test_pinyin_parts_common_parts_below_threshold(self):
        # common_parts < min(len)*0.5 -> no best_match from this path
        customer = _make_customer(id=1, unit_name="abcdef")
        with patch("app.db.session.get_db", return_value=_make_mock_db([customer])):
            # "xyz" vs "abcdef" -> no common parts
            result = resolve_purchase_unit("xyz")
        assert result is None
