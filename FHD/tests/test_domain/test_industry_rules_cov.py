"""Branch-coverage supplement for app/domain/services/industry_rules.py.

The existing test_industry_rules.py covers the happy paths via real manifest data.
This file focuses on every *missed* branch: edge inputs, error paths, fallbacks,
and registry extension points — exercised with inline schemas so no FS/DB is needed.

Every test asserts a *concrete* observable: the exact returned value, the exact
error-message string, or the exact mutated record — never merely "is not None".
The validators' contract is "return None when valid, return the Chinese error
string when invalid", so the strong form is to pin the error string with ``==``
and to confirm the valid branch produces *no* error rather than just a truthy one.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from app.domain.services.industry_rules import (
    DERIVATION_REGISTRY,
    VALIDATOR_REGISTRY,
    FieldError,
    _is_empty,
    _op_add,
    _op_mul,
    _op_sub,
    _parse_date,
    _to_number,
    _validate_not_expired,
    _validate_one_of,
    _validate_range,
    _validate_regex,
    compute_subsystem_derived,
    register_derivation,
    register_validator,
    validate_subsystem_record,
)

# ---------------------------------------------------------------------------
# _is_empty — the empty/non-empty boundary is what gates every validator
# ---------------------------------------------------------------------------


class TestIsEmpty:
    def test_none_is_empty(self):
        assert _is_empty(None) is True

    def test_empty_string_is_empty(self):
        assert _is_empty("") is True

    def test_whitespace_string_is_empty(self):
        # whitespace-only collapses to empty after .strip()
        assert _is_empty("   ") is True
        assert _is_empty("\t\n ") is True

    def test_zero_is_not_empty(self):
        # numeric 0 is a real value, must NOT be treated as empty
        assert _is_empty(0) is False
        assert _is_empty(0.0) is False

    def test_nonempty_string_is_not_empty(self):
        assert _is_empty("hello") is False
        # leading/trailing space around real content is non-empty
        assert _is_empty("  x  ") is False

    def test_false_is_not_empty(self):
        # bool False is a value, not emptiness
        assert _is_empty(False) is False

    def test_empty_collections_are_not_empty_only_str_and_none_count(self):
        # _is_empty only special-cases None and blank str; [] / {} are "values"
        assert _is_empty([]) is False
        assert _is_empty({}) is False


# ---------------------------------------------------------------------------
# _to_number
# ---------------------------------------------------------------------------


class TestToNumber:
    def test_none_returns_zero(self):
        assert _to_number(None) == 0.0

    def test_empty_string_returns_zero(self):
        assert _to_number("") == 0.0
        assert _to_number("   ") == 0.0

    def test_valid_int(self):
        assert _to_number(42) == 42.0
        assert isinstance(_to_number(42), float)

    def test_valid_float_string(self):
        assert _to_number("3.14") == 3.14

    def test_negative_and_scientific_notation(self):
        assert _to_number("-7") == -7.0
        assert _to_number("1e3") == 1000.0

    def test_bool_true_is_one(self):
        # bool is an int subclass; float(True) == 1.0 — pins the real behavior
        assert _to_number(True) == 1.0

    def test_invalid_string_returns_zero(self):
        # unparseable text → ValueError branch → 0.0
        assert _to_number("abc") == 0.0

    def test_type_error_returns_zero(self):
        # A dict/list can't be converted — triggers the TypeError branch → 0.0
        assert _to_number({}) == 0.0
        assert _to_number([1, 2]) == 0.0


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None
        assert _parse_date("   ") is None

    def test_iso_date_string(self):
        assert _parse_date("2024-06-15") == date(2024, 6, 15)

    def test_iso_datetime_string_truncates_to_date(self):
        # text[:10] of "2024-06-15T10:30:00" is "2024-06-15" → first branch succeeds
        assert _parse_date("2024-06-15T10:30:00") == date(2024, 6, 15)

    def test_iso_datetime_with_space_separator(self):
        # "2025-12-31 23:59" → first 10 chars are a valid ISO date
        assert _parse_date("2025-12-31 23:59:00") == date(2025, 12, 31)

    def test_completely_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_date_object_passthrough(self):
        # date.fromisoformat(str(date_obj)[:10]) round-trips the same date
        assert _parse_date(date(2025, 1, 1)) == date(2025, 1, 1)

    def test_invalid_month_returns_none(self):
        # "2024-13-01" — month 13 invalid; both fromisoformat paths raise → None
        assert _parse_date("2024-13-01") is None

    def test_short_garbage_then_datetime_path_also_fails(self):
        # "abcd-ef-gh" first-branch raises; datetime.fromisoformat also raises → None
        assert _parse_date("abcd-ef-gh") is None


# ---------------------------------------------------------------------------
# _validate_one_of — returns None when OK, exact Chinese message when violated
# ---------------------------------------------------------------------------


class TestValidateOneOf:
    def test_empty_value_skips(self):
        # Empty value → None (required handles emptiness, not oneOf)
        assert _validate_one_of(None, ["A", "B"]) is None
        assert _validate_one_of("", ["A", "B"]) is None
        assert _validate_one_of("   ", ["A", "B"]) is None

    def test_non_list_params_impose_no_constraint(self):
        # Non-list params → allowed == [] → "not allowed" guard returns None,
        # i.e. ANY value passes (even one that would otherwise be rejected).
        assert _validate_one_of("anything", None) is None
        assert _validate_one_of("anything", "single_string") is None
        assert _validate_one_of("anything", []) is None

    def test_value_in_allowed_passes(self):
        assert _validate_one_of("A", ["A", "B"]) is None

    def test_value_not_in_allowed_returns_exact_message(self):
        # Message is deterministic: "必须是 <、-joined> 之一"
        assert _validate_one_of("C", ["A", "B"]) == "必须是 A、B 之一"

    def test_numeric_params_are_stringified_before_comparison(self):
        # params ints are coerced to str; "1" matches str(1)
        assert _validate_one_of("1", [1, 2]) is None
        # "3" not among {"1","2"} → exact message lists the stringified options
        assert _validate_one_of("3", [1, 2]) == "必须是 1、2 之一"

    def test_value_compared_as_string_not_by_type(self):
        # numeric value 1 stringifies to "1" and matches str(1) in params
        assert _validate_one_of(1, [1, 2]) is None


# ---------------------------------------------------------------------------
# _validate_range
# ---------------------------------------------------------------------------


class TestValidateRange:
    def test_empty_value_skips(self):
        assert _validate_range(None, {"min": 0, "max": 10}) is None
        assert _validate_range("", {"min": 0, "max": 10}) is None

    def test_non_dict_params_impose_no_constraint(self):
        # Non-dict params → p == {} → no min/max → always passes
        assert _validate_range(5, None) is None
        assert _validate_range(5, [1, 2]) is None
        assert _validate_range(-9999, "bogus") is None

    def test_below_min_returns_exact_message(self):
        assert _validate_range(3, {"min": 5}) == "不能小于 5"

    def test_above_max_returns_exact_message(self):
        assert _validate_range(15, {"max": 10}) == "不能大于 10"

    def test_within_range_passes(self):
        assert _validate_range(7, {"min": 5, "max": 10}) is None

    def test_only_max_constraint(self):
        # min absent → only the upper bound is enforced
        assert _validate_range(5, {"max": 10}) is None
        assert _validate_range(11, {"max": 10}) == "不能大于 10"

    def test_only_min_constraint(self):
        # max absent → only the lower bound is enforced
        assert _validate_range(10, {"min": 5}) is None
        assert _validate_range(4, {"min": 5}) == "不能小于 5"

    def test_boundaries_are_inclusive(self):
        # exactly-at-min and exactly-at-max both pass (uses < / > not <= / >=)
        assert _validate_range(5, {"min": 5, "max": 10}) is None
        assert _validate_range(10, {"min": 5, "max": 10}) is None

    def test_string_value_is_coerced_to_number(self):
        # "3" → 3.0 < 5 → rejected with the min message
        assert _validate_range("3", {"min": 5}) == "不能小于 5"
        assert _validate_range("7", {"min": 5, "max": 10}) is None


# ---------------------------------------------------------------------------
# _validate_regex
# ---------------------------------------------------------------------------


class TestValidateRegex:
    def test_empty_value_skips(self):
        assert _validate_regex(None, r"\d+") is None
        assert _validate_regex("", r"\d+") is None

    def test_string_params_match_and_mismatch(self):
        # params given as a bare pattern string
        assert _validate_regex("123", r"^\d+$") is None
        assert _validate_regex("abc", r"^\d+$") == "格式不正确"

    def test_dict_params_match_and_mismatch(self):
        # params given as {"pattern": ...}
        assert _validate_regex("123", {"pattern": r"^\d+$"}) is None
        assert _validate_regex("abc", {"pattern": r"^\d+$"}) == "格式不正确"

    def test_none_params_impose_no_constraint(self):
        # params None → pattern == "" → no constraint → any value passes
        assert _validate_regex("anything", None) is None

    def test_dict_without_pattern_key_imposes_no_constraint(self):
        assert _validate_regex("anything", {}) is None

    def test_empty_pattern_string_imposes_no_constraint(self):
        assert _validate_regex("test", "") is None

    def test_invalid_regex_is_swallowed_and_treated_as_pass(self):
        # "[invalid" is an unterminated character class → re.error → returns None
        # (a malformed schema pattern must not crash validation)
        assert _validate_regex("test", "[invalid") is None

    def test_search_not_fullmatch_semantics(self):
        # re.search → substring match is enough; "x9y" contains a digit
        assert _validate_regex("x9y", r"\d") is None
        assert _validate_regex("xyz", r"\d") == "格式不正确"


# ---------------------------------------------------------------------------
# _validate_not_expired
# ---------------------------------------------------------------------------


class TestValidateNotExpired:
    def test_empty_value_skips(self):
        assert _validate_not_expired(None, None) is None
        assert _validate_not_expired("", None) is None

    def test_unparseable_date_skips(self):
        # parse failure → None date → no expiry check possible → passes
        assert _validate_not_expired("not-a-date", None) is None

    def test_past_date_returns_exact_expiry_message(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        assert _validate_not_expired(past, None) == "已过保质期（到期日早于今天）"

    def test_distant_past_date_is_expired(self):
        assert _validate_not_expired("2000-01-01", None) == "已过保质期（到期日早于今天）"

    def test_future_date_passes(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        assert _validate_not_expired(future, None) is None

    def test_today_passes_boundary_is_not_expired(self):
        # uses strict `<`: today is NOT earlier than today → not expired
        assert _validate_not_expired(date.today().isoformat(), None) is None


# ---------------------------------------------------------------------------
# Operator functions — pin exact arithmetic, including identity elements
# ---------------------------------------------------------------------------


class TestOperators:
    def test_op_mul_empty_is_multiplicative_identity(self):
        assert _op_mul([]) == 1.0

    def test_op_mul_single(self):
        assert _op_mul([5.0]) == 5.0

    def test_op_mul_multiple(self):
        assert _op_mul([2.0, 3.0, 4.0]) == 24.0

    def test_op_mul_with_zero_collapses(self):
        assert _op_mul([2.0, 0.0, 9.0]) == 0.0

    def test_op_add_empty_is_additive_identity(self):
        assert _op_add([]) == 0.0

    def test_op_add_multiple(self):
        assert _op_add([1.0, 2.0, 3.0]) == 6.0

    def test_op_add_with_negatives(self):
        assert _op_add([10.0, -3.0, -2.0]) == 5.0

    def test_op_sub_empty_args_short_circuits_to_zero(self):
        # Distinct from add/mul: sub returns 0.0 (not an identity element) on []
        assert _op_sub([]) == 0.0

    def test_op_sub_single_returns_that_value(self):
        assert _op_sub([10.0]) == 10.0

    def test_op_sub_is_left_fold(self):
        # 10 - 3 - 2 == 5 (left-to-right), NOT 10 - (3 - 2) == 9
        assert _op_sub([10.0, 3.0, 2.0]) == 5.0

    def test_op_sub_can_go_negative(self):
        assert _op_sub([1.0, 5.0]) == -4.0


# ---------------------------------------------------------------------------
# register_validator / register_derivation — extension points
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_validator_adds_to_registry(self):
        def fn(v, p):
            return None

        register_validator("test_cov_v", fn)
        assert VALIDATOR_REGISTRY["test_cov_v"] is fn

    def test_register_validator_stringifies_type_name_key(self):
        # the key is coerced via str(); a non-str name still indexes by its str form
        def fn(v, p):
            return None

        register_validator(12345, fn)
        assert VALIDATOR_REGISTRY["12345"] is fn

    def test_register_derivation_adds_to_registry(self):
        def fn(args):
            return sum(args) * 2

        register_derivation("test_cov_d", fn)
        assert DERIVATION_REGISTRY["test_cov_d"] is fn

    def test_registered_validator_is_invoked_through_public_api(self):
        register_validator("must_be_positive", lambda v, p: None if float(v) > 0 else "必须为正数")
        schema = {
            "fields": [{"key": "x", "label": "X值", "validators": [{"type": "must_be_positive"}]}]
        }
        # valid branch: no errors at all
        assert validate_subsystem_record("k", {"x": 5}, schema=schema) == []
        # invalid branch: exactly one error, label-prefixed message
        errs = validate_subsystem_record("k", {"x": -1}, schema=schema)
        assert len(errs) == 1
        assert errs[0].field == "x"
        assert errs[0].label == "X值"
        assert errs[0].message == "X值必须为正数"

    def test_registered_derivation_is_invoked_through_public_api(self):
        register_derivation("double_sum", lambda args: sum(args) * 2)
        schema = {"rules": {"result": {"op": "double_sum", "args": ["a", "b"]}}}
        out = compute_subsystem_derived("k", {"a": 3, "b": 7}, schema=schema)
        # (3 + 7) * 2 == 20
        assert out["result"] == 20.0

    def test_re_registering_overwrites_previous_handler(self):
        register_derivation("cov_overwrite", lambda args: 1.0)
        register_derivation("cov_overwrite", lambda args: 99.0)
        schema = {"rules": {"r": {"op": "cov_overwrite", "args": []}}}
        out = compute_subsystem_derived("k", {}, schema=schema)
        assert out["r"] == 99.0


# ---------------------------------------------------------------------------
# _resolve_schema (tested indirectly via validate / compute)
# ---------------------------------------------------------------------------


class TestResolveSchema:
    def test_explicit_dict_schema_used_verbatim(self):
        # An explicit dict short-circuits the lazy profile lookup entirely.
        schema = {"fields": [{"key": "x", "label": "X", "required": True}]}
        errs = validate_subsystem_record("any", {}, schema=schema)
        assert [e.field for e in errs] == ["x"]

    def test_none_schema_pulls_from_current_subsystem_profile(self):
        # _resolve_schema imports get_current_subsystem_schema lazily inside the
        # function, so we patch it on the SOURCE module, not industry_rules.
        mock_schema = {"fields": [{"key": "x", "label": "X字段", "required": True}]}
        with patch(
            "app.domain.value_objects_industry.get_current_subsystem_schema",
            return_value=mock_schema,
        ) as mocked:
            errs = validate_subsystem_record("products", {})
            mocked.assert_called_once_with("products")
            assert len(errs) == 1
            assert errs[0].field == "x"
            assert errs[0].message == "X字段不能为空"

    def test_lazy_import_failure_is_recoverable_and_yields_empty_schema(self):
        # ImportError is in RECOVERABLE_ERRORS → schema falls back to {} →
        # no fields → no validation errors (validation must not crash).
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "app.domain.value_objects_industry":
                raise ImportError("module not found")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            assert validate_subsystem_record("products", {"name": "test"}) == []

    def test_non_dict_profile_result_falls_back_to_empty_schema(self):
        # If the profile returns None (non-dict), _resolve_schema uses {} →
        # required field "x" never appears → zero errors.
        with patch(
            "app.domain.value_objects_industry.get_current_subsystem_schema",
            return_value=None,
        ):
            assert validate_subsystem_record("products", {}) == []

    def test_none_schema_path_also_used_by_compute(self):
        # compute_subsystem_derived shares _resolve_schema; a profile-supplied rule
        # is applied when no explicit schema is passed.
        mock_schema = {"rules": {"total": {"op": "add", "args": ["a", "b"]}}}
        with patch(
            "app.domain.value_objects_industry.get_current_subsystem_schema",
            return_value=mock_schema,
        ):
            out = compute_subsystem_derived("orders", {"a": 4, "b": 6})
            assert out["total"] == 10.0


# ---------------------------------------------------------------------------
# validate_subsystem_record — edge branches
# ---------------------------------------------------------------------------


class TestValidateSubsystemRecord:
    def test_empty_schema_returns_no_errors(self):
        assert validate_subsystem_record("k", {}, schema={}) == []

    def test_fields_none_returns_no_errors(self):
        assert validate_subsystem_record("k", {}, schema={"fields": None}) == []

    def test_non_dict_field_entries_are_skipped(self):
        # str / int / None field entries are ignored without raising
        schema = {"fields": ["not_a_dict", 42, None]}
        assert validate_subsystem_record("k", {}, schema=schema) == []

    def test_field_without_key_is_skipped(self):
        schema = {"fields": [{"label": "无键字段", "required": True}]}
        # no key → field skipped → no error despite required+missing value
        assert validate_subsystem_record("k", {}, schema=schema) == []

    def test_field_key_blank_string_is_skipped(self):
        schema = {"fields": [{"key": "   ", "label": "空键", "required": True}]}
        assert validate_subsystem_record("k", {}, schema=schema) == []

    def test_label_falls_back_to_key_when_label_missing(self):
        schema = {"fields": [{"key": "myfield", "required": True}]}
        errs = validate_subsystem_record("k", {}, schema=schema)
        assert len(errs) == 1
        assert errs[0].label == "myfield"
        # message uses the key as label: "<key>不能为空"
        assert errs[0].message == "myfield不能为空"

    def test_required_empty_short_circuits_before_validators(self):
        # required+empty emits exactly the required error and does NOT also run
        # the oneOf validator (continue skips it) — so only ONE error.
        schema = {
            "fields": [
                {
                    "key": "name",
                    "label": "名称",
                    "required": True,
                    "validators": [{"type": "oneOf", "params": ["A"]}],
                }
            ]
        }
        errs = validate_subsystem_record("k", {}, schema=schema)
        assert len(errs) == 1
        assert errs[0].message == "名称不能为空"

    def test_required_with_present_value_runs_validators(self):
        # value present (not empty) → required passes → validators DO run →
        # "B" not in allowed → exact oneOf message, label-prefixed.
        schema = {
            "fields": [
                {
                    "key": "name",
                    "label": "名称",
                    "required": True,
                    "validators": [{"type": "oneOf", "params": ["A"]}],
                }
            ]
        }
        errs = validate_subsystem_record("k", {"name": "B"}, schema=schema)
        assert len(errs) == 1
        assert errs[0].message == "名称必须是 A 之一"

    def test_unknown_validator_type_is_skipped(self):
        schema = {
            "fields": [{"key": "x", "label": "X", "validators": [{"type": "nonexistent_type"}]}]
        }
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_non_dict_validator_entries_are_skipped(self):
        schema = {"fields": [{"key": "x", "label": "X", "validators": ["bad", 42]}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_validator_raising_recoverable_error_is_swallowed(self):
        # A validator that raises ValueError (a RECOVERABLE_ERROR) must not
        # propagate; the field is treated as valid (no error appended).
        def bad_validator(value, params):
            raise ValueError("simulated transient error")

        register_validator("cov_bad_v", bad_validator)
        schema = {"fields": [{"key": "x", "label": "X", "validators": [{"type": "cov_bad_v"}]}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_validators_none_skips_validators(self):
        schema = {"fields": [{"key": "x", "label": "X", "validators": None}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_record_none_treated_as_empty_dict(self):
        # record=None → all keys missing → required field flagged
        schema = {"fields": [{"key": "x", "label": "X字段", "required": True}]}
        errs = validate_subsystem_record("k", None, schema=schema)
        assert len(errs) == 1
        assert errs[0].field == "x"
        assert errs[0].message == "X字段不能为空"

    def test_multiple_required_fields_yield_one_error_each_in_order(self):
        schema = {
            "fields": [
                {"key": "a", "label": "甲", "required": True},
                {"key": "b", "label": "乙", "required": True},
            ]
        }
        errs = validate_subsystem_record("k", {}, schema=schema)
        assert [e.field for e in errs] == ["a", "b"]
        assert [e.message for e in errs] == ["甲不能为空", "乙不能为空"]

    def test_validator_without_type_key_is_skipped(self):
        # validator dict missing "type" → vtype == "" → handler None → skipped
        schema = {"fields": [{"key": "x", "label": "X", "validators": [{"params": ["A"]}]}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_two_validators_on_one_field_both_run(self):
        # range then regex: value "150" fails the max bound (→ message) but is a
        # valid digit string, so only the range validator should emit.
        schema = {
            "fields": [
                {
                    "key": "x",
                    "label": "数量",
                    "validators": [
                        {"type": "range", "params": {"max": 100}},
                        {"type": "regex", "params": r"^\d+$"},
                    ],
                }
            ]
        }
        errs = validate_subsystem_record("k", {"x": "150"}, schema=schema)
        assert len(errs) == 1
        assert errs[0].message == "数量不能大于 100"


# ---------------------------------------------------------------------------
# compute_subsystem_derived — edge branches
# ---------------------------------------------------------------------------


class TestComputeSubsystemDerived:
    def test_empty_schema_returns_copy_equal_to_record(self):
        rec = {"a": 1}
        out = compute_subsystem_derived("k", rec, schema={})
        assert out == {"a": 1}
        # returns a *copy*, not the same object (defensive against mutation)
        assert out is not rec

    def test_non_dict_rules_returns_record_unchanged(self):
        rec = {"a": 1}
        assert compute_subsystem_derived("k", rec, schema={"rules": "nope"}) == {"a": 1}
        assert compute_subsystem_derived("k", rec, schema={"rules": ["x"]}) == {"a": 1}

    def test_non_dict_rule_spec_is_skipped(self):
        schema = {"rules": {"result": "not_a_dict"}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert out == {"a": 5}
        assert "result" not in out

    def test_unknown_op_is_skipped(self):
        schema = {"rules": {"result": {"op": "nonexistent_op", "args": ["a"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert "result" not in out

    def test_missing_op_key_is_skipped(self):
        schema = {"rules": {"result": {"args": ["a"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert "result" not in out

    def test_non_list_args_is_skipped(self):
        schema = {"rules": {"result": {"op": "mul", "args": "not_a_list"}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert "result" not in out

    def test_missing_arg_key_contributes_zero(self):
        # "missing_key" absent from record → _to_number(None) → 0.0 → add → 5.0
        schema = {"rules": {"result": {"op": "add", "args": ["a", "missing_key"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert out["result"] == 5.0

    def test_missing_arg_in_mul_collapses_to_zero(self):
        # multiplying by a missing (→0) arg yields 0.0, distinguishing add vs mul
        schema = {"rules": {"result": {"op": "mul", "args": ["a", "missing"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert out["result"] == 0.0

    def test_op_raising_recoverable_error_leaves_target_unset(self):
        def bad_op(args):
            raise RuntimeError("transient failure")

        register_derivation("cov_bad_op", bad_op)
        schema = {"rules": {"result": {"op": "cov_bad_op", "args": ["a"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert "result" not in out
        # the original input is preserved untouched
        assert out["a"] == 5

    def test_record_none_treated_as_empty_dict(self):
        schema = {"rules": {"result": {"op": "add", "args": ["a"]}}}
        out = compute_subsystem_derived("k", None, schema=schema)
        # a missing → 0.0
        assert out == {"result": 0.0}

    def test_target_name_is_stringified(self):
        # rule target key 7 (int) is written back as the str "7"
        schema = {"rules": {7: {"op": "add", "args": ["a"]}}}
        out = compute_subsystem_derived("k", {"a": 3}, schema=schema)
        assert out["7"] == 3.0

    def test_chained_rules_see_earlier_outputs(self):
        # second rule reads qty_kg produced by the first (out updated in place)
        schema = {
            "rules": {
                "qty_kg": {"op": "mul", "args": ["qty_tins", "tin_spec"]},
                "amount": {"op": "mul", "args": ["qty_kg", "unit_price"]},
            }
        }
        out = compute_subsystem_derived(
            "k", {"qty_tins": 2, "tin_spec": 10, "unit_price": 5}, schema=schema
        )
        assert out["qty_kg"] == 20.0
        assert out["amount"] == 100.0

    def test_input_record_is_not_mutated(self):
        rec = {"a": 2, "b": 3}
        schema = {"rules": {"sum": {"op": "add", "args": ["a", "b"]}}}
        out = compute_subsystem_derived("k", rec, schema=schema)
        assert out["sum"] == 5.0
        assert "sum" not in rec  # original untouched


# ---------------------------------------------------------------------------
# FieldError
# ---------------------------------------------------------------------------


class TestFieldError:
    def test_to_dict_serializes_all_three_fields(self):
        e = FieldError("myfield", "我的字段", "必须不为空")
        assert e.to_dict() == {
            "field": "myfield",
            "label": "我的字段",
            "message": "必须不为空",
        }

    def test_dataclass_attributes_and_equality(self):
        e = FieldError(field="f", label="L", message="M")
        assert (e.field, e.label, e.message) == ("f", "L", "M")
        # dataclass __eq__ compares by value
        assert e == FieldError("f", "L", "M")
        assert e != FieldError("f", "L", "different")


# ---------------------------------------------------------------------------
# Integration: validate + compute together
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_valid_record_passes_then_derives_total(self):
        schema = {
            "fields": [
                {"key": "name", "label": "产品名", "required": True},
                {
                    "key": "unit",
                    "label": "单位",
                    "validators": [{"type": "oneOf", "params": ["kg", "L"]}],
                },
            ],
            "rules": {"total": {"op": "mul", "args": ["qty", "price"]}},
        }
        assert validate_subsystem_record("k", {"name": "Paint", "unit": "kg"}, schema=schema) == []
        out = compute_subsystem_derived("k", {"qty": 3, "price": 50}, schema=schema)
        assert out["total"] == 150.0

    def test_invalid_unit_is_rejected_with_exact_message(self):
        schema = {
            "fields": [
                {"key": "name", "label": "产品名", "required": True},
                {
                    "key": "unit",
                    "label": "单位",
                    "validators": [{"type": "oneOf", "params": ["kg", "L"]}],
                },
            ]
        }
        errs = validate_subsystem_record("k", {"name": "Paint", "unit": "箱"}, schema=schema)
        assert len(errs) == 1
        assert errs[0].field == "unit"
        assert errs[0].message == "单位必须是 kg、L 之一"

    def test_sub_operator_via_schema(self):
        schema = {"rules": {"diff": {"op": "sub", "args": ["big", "small"]}}}
        out = compute_subsystem_derived("k", {"big": 100, "small": 35}, schema=schema)
        assert out["diff"] == 65.0

    def test_add_operator_via_schema(self):
        schema = {"rules": {"total": {"op": "add", "args": ["a", "b", "c"]}}}
        out = compute_subsystem_derived("k", {"a": 10, "b": 20, "c": 30}, schema=schema)
        assert out["total"] == 60.0
