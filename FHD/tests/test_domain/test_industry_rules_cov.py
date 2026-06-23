"""Branch-coverage supplement for app/domain/services/industry_rules.py.

The existing test_industry_rules.py covers the happy paths via real manifest data.
This file focuses on every *missed* branch: edge inputs, error paths, fallbacks,
and registry extension points — exercised with inline schemas so no FS/DB is needed.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

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
# _is_empty
# ---------------------------------------------------------------------------


class TestIsEmpty:
    def test_none_is_empty(self):
        assert _is_empty(None) is True

    def test_empty_string_is_empty(self):
        assert _is_empty("") is True

    def test_whitespace_string_is_empty(self):
        assert _is_empty("   ") is True

    def test_zero_is_not_empty(self):
        assert _is_empty(0) is False

    def test_nonempty_string_is_not_empty(self):
        assert _is_empty("hello") is False

    def test_false_is_not_empty(self):
        assert _is_empty(False) is False


# ---------------------------------------------------------------------------
# _to_number
# ---------------------------------------------------------------------------


class TestToNumber:
    def test_none_returns_zero(self):
        assert _to_number(None) == 0.0

    def test_empty_string_returns_zero(self):
        assert _to_number("") == 0.0

    def test_valid_int(self):
        assert _to_number(42) == 42.0

    def test_valid_float_string(self):
        assert _to_number("3.14") == 3.14

    def test_invalid_string_returns_zero(self):
        assert _to_number("abc") == 0.0

    def test_type_error_returns_zero(self):
        # A dict can't be converted — triggers TypeError branch
        assert _to_number({}) == 0.0


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_iso_date_string(self):
        assert _parse_date("2024-06-15") == date(2024, 6, 15)

    def test_iso_datetime_string(self):
        # First branch fails (only 10 chars of "2024-06-15T10:30:00" is still a valid date)
        assert _parse_date("2024-06-15T10:30:00") == date(2024, 6, 15)

    def test_completely_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_date_object_passthrough(self):
        # date.fromisoformat(str(date_obj)[:10]) should work
        result = _parse_date(date(2025, 1, 1))
        assert result == date(2025, 1, 1)

    def test_invalid_isoformat_falls_through_to_datetime_path(self):
        # "2024-13-01" is an invalid month → first branch raises, second also raises
        assert _parse_date("2024-13-01") is None


# ---------------------------------------------------------------------------
# _validate_one_of
# ---------------------------------------------------------------------------


class TestValidateOneOf:
    def test_empty_value_skips(self):
        # Empty value → None (let required handle it)
        assert _validate_one_of(None, ["A", "B"]) is None

    def test_empty_string_skips(self):
        assert _validate_one_of("", ["A", "B"]) is None

    def test_params_not_list_means_no_allowed(self):
        # Non-list params → allowed becomes [] → no constraint → None
        assert _validate_one_of("X", None) is None
        assert _validate_one_of("X", "single_string") is None

    def test_empty_list_params(self):
        assert _validate_one_of("X", []) is None

    def test_value_in_allowed(self):
        assert _validate_one_of("A", ["A", "B"]) is None

    def test_value_not_in_allowed(self):
        msg = _validate_one_of("C", ["A", "B"])
        assert msg is not None
        assert "之一" in msg
        assert "A" in msg and "B" in msg

    def test_numeric_params_coerced_to_str(self):
        # params are ints, value is str representation
        assert _validate_one_of("1", [1, 2]) is None
        assert _validate_one_of("3", [1, 2]) is not None


# ---------------------------------------------------------------------------
# _validate_range
# ---------------------------------------------------------------------------


class TestValidateRange:
    def test_empty_value_skips(self):
        assert _validate_range(None, {"min": 0, "max": 10}) is None

    def test_params_not_dict(self):
        # Non-dict params → p={} → no min/max → always ok
        assert _validate_range(5, None) is None
        assert _validate_range(5, [1, 2]) is None

    def test_below_min(self):
        msg = _validate_range(3, {"min": 5})
        assert msg is not None
        assert "5" in msg

    def test_above_max(self):
        msg = _validate_range(15, {"max": 10})
        assert msg is not None
        assert "10" in msg

    def test_within_range(self):
        assert _validate_range(7, {"min": 5, "max": 10}) is None

    def test_no_min_key(self):
        # Only max
        assert _validate_range(5, {"max": 10}) is None

    def test_no_max_key(self):
        # Only min
        assert _validate_range(10, {"min": 5}) is None

    def test_exactly_at_min(self):
        assert _validate_range(5, {"min": 5}) is None

    def test_exactly_at_max(self):
        assert _validate_range(10, {"max": 10}) is None


# ---------------------------------------------------------------------------
# _validate_regex
# ---------------------------------------------------------------------------


class TestValidateRegex:
    def test_empty_value_skips(self):
        assert _validate_regex(None, r"\d+") is None

    def test_params_str_pattern_matches(self):
        assert _validate_regex("123", r"^\d+$") is None

    def test_params_str_pattern_no_match(self):
        msg = _validate_regex("abc", r"^\d+$")
        assert msg == "格式不正确"

    def test_params_dict_with_pattern(self):
        assert _validate_regex("123", {"pattern": r"^\d+$"}) is None
        assert _validate_regex("abc", {"pattern": r"^\d+$"}) is not None

    def test_params_none_skips(self):
        # params is None → pattern becomes "" → no constraint
        assert _validate_regex("anything", None) is None

    def test_params_dict_no_pattern_key(self):
        assert _validate_regex("anything", {}) is None

    def test_invalid_regex_returns_none(self):
        # Bad regex pattern → re.error caught → returns None
        assert _validate_regex("test", "[invalid") is None

    def test_empty_pattern_string_skips(self):
        assert _validate_regex("test", "") is None


# ---------------------------------------------------------------------------
# _validate_not_expired
# ---------------------------------------------------------------------------


class TestValidateNotExpired:
    def test_empty_value_skips(self):
        assert _validate_not_expired(None, None) is None
        assert _validate_not_expired("", None) is None

    def test_unparseable_date_skips(self):
        assert _validate_not_expired("not-a-date", None) is None

    def test_past_date_is_expired(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        msg = _validate_not_expired(past, None)
        assert msg is not None
        assert "保质期" in msg

    def test_future_date_is_ok(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        assert _validate_not_expired(future, None) is None

    def test_today_is_ok(self):
        # today is NOT earlier than today
        assert _validate_not_expired(date.today().isoformat(), None) is None


# ---------------------------------------------------------------------------
# Operator functions
# ---------------------------------------------------------------------------


class TestOperators:
    def test_op_mul_empty(self):
        assert _op_mul([]) == 1.0  # identity for multiplication

    def test_op_mul_single(self):
        assert _op_mul([5.0]) == 5.0

    def test_op_mul_multiple(self):
        assert _op_mul([2.0, 3.0, 4.0]) == 24.0

    def test_op_add_empty(self):
        assert _op_add([]) == 0.0

    def test_op_add_multiple(self):
        assert _op_add([1.0, 2.0, 3.0]) == 6.0

    def test_op_sub_empty_args(self):
        # Empty list → early return 0.0
        assert _op_sub([]) == 0.0

    def test_op_sub_single(self):
        assert _op_sub([10.0]) == 10.0

    def test_op_sub_multiple(self):
        assert _op_sub([10.0, 3.0, 2.0]) == 5.0


# ---------------------------------------------------------------------------
# register_validator / register_derivation
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_validator_adds_to_registry(self):
        fn = lambda v, p: None
        register_validator("test_cov_v", fn)
        assert VALIDATOR_REGISTRY["test_cov_v"] is fn

    def test_register_derivation_adds_to_registry(self):
        fn = lambda args: sum(args) * 2
        register_derivation("test_cov_d", fn)
        assert DERIVATION_REGISTRY["test_cov_d"] is fn

    def test_registered_validator_used_in_validate(self):
        register_validator("must_be_positive", lambda v, p: None if float(v) > 0 else "必须为正数")
        schema = {
            "fields": [{"key": "x", "label": "X值", "validators": [{"type": "must_be_positive"}]}]
        }
        assert validate_subsystem_record("k", {"x": 5}, schema=schema) == []
        errs = validate_subsystem_record("k", {"x": -1}, schema=schema)
        assert errs and "正数" in errs[0].message

    def test_registered_derivation_used_in_compute(self):
        register_derivation("double_sum", lambda args: sum(args) * 2)
        schema = {"rules": {"result": {"op": "double_sum", "args": ["a", "b"]}}}
        out = compute_subsystem_derived("k", {"a": 3, "b": 7}, schema=schema)
        assert out["result"] == 20.0


# ---------------------------------------------------------------------------
# _resolve_schema (tested indirectly via validate / compute)
# ---------------------------------------------------------------------------


class TestResolveSchema:
    def test_dict_schema_returned_directly(self):
        schema = {"fields": []}
        errs = validate_subsystem_record("any", {}, schema=schema)
        assert errs == []

    def test_none_schema_calls_get_current_subsystem_schema(self):
        # _resolve_schema imports get_current_subsystem_schema lazily inside the function,
        # so we must patch the source module, not the industry_rules module namespace.
        mock_schema = {"fields": [{"key": "x", "label": "X", "required": True}]}
        with patch(
            "app.domain.value_objects_industry.get_current_subsystem_schema",
            return_value=mock_schema,
        ):
            errs = validate_subsystem_record("products", {})
            assert any(e.field == "x" for e in errs)

    def test_none_schema_import_raises_recoverable_returns_empty(self):
        # When the lazy import itself raises ImportError (a RECOVERABLE_ERROR), schema → {}
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "app.domain.value_objects_industry":
                raise ImportError("module not found")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            errs = validate_subsystem_record("products", {"name": "test"})
            assert errs == []

    def test_none_schema_returns_non_dict_falls_back_to_empty(self):
        # If get_current_subsystem_schema returns non-dict (e.g. None), use {}
        with patch(
            "app.domain.value_objects_industry.get_current_subsystem_schema",
            return_value=None,
        ):
            errs = validate_subsystem_record("products", {})
            assert errs == []


# ---------------------------------------------------------------------------
# validate_subsystem_record — edge branches
# ---------------------------------------------------------------------------


class TestValidateSubsystemRecord:
    def test_empty_schema_returns_no_errors(self):
        assert validate_subsystem_record("k", {}, schema={}) == []

    def test_fields_is_none_returns_no_errors(self):
        assert validate_subsystem_record("k", {}, schema={"fields": None}) == []

    def test_non_dict_field_is_skipped(self):
        schema = {"fields": ["not_a_dict", 42, None]}
        assert validate_subsystem_record("k", {}, schema=schema) == []

    def test_field_with_no_key_is_skipped(self):
        schema = {"fields": [{"label": "无键字段"}]}
        assert validate_subsystem_record("k", {}, schema=schema) == []

    def test_field_key_empty_string_is_skipped(self):
        schema = {"fields": [{"key": "   ", "label": "空键"}]}
        assert validate_subsystem_record("k", {}, schema=schema) == []

    def test_label_falls_back_to_key_when_missing(self):
        schema = {"fields": [{"key": "myfield", "required": True}]}
        errs = validate_subsystem_record("k", {}, schema=schema)
        assert errs and errs[0].label == "myfield"

    def test_required_and_empty_value_adds_error_and_skips_validators(self):
        # Even if there are validators, required+empty should stop at the required error
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
        assert "不能为空" in errs[0].message

    def test_unknown_validator_type_is_skipped(self):
        schema = {
            "fields": [{"key": "x", "label": "X", "validators": [{"type": "nonexistent_type"}]}]
        }
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_non_dict_validator_entry_is_skipped(self):
        schema = {"fields": [{"key": "x", "label": "X", "validators": ["bad_entry", 42]}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_validator_raises_recoverable_error_treated_as_no_error(self):
        # Register a validator that raises a ValueError (in RECOVERABLE_ERRORS)
        def bad_validator(value, params):
            raise ValueError("simulated transient error")

        register_validator("cov_bad_v", bad_validator)
        schema = {"fields": [{"key": "x", "label": "X", "validators": [{"type": "cov_bad_v"}]}]}
        # Should NOT raise — the error is swallowed
        errs = validate_subsystem_record("k", {"x": "val"}, schema=schema)
        assert errs == []

    def test_validators_list_is_none_skips_validators(self):
        schema = {"fields": [{"key": "x", "label": "X", "validators": None}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []

    def test_record_none_treated_as_empty_dict(self):
        schema = {"fields": [{"key": "x", "label": "X", "required": True}]}
        errs = validate_subsystem_record("k", None, schema=schema)
        assert errs and errs[0].field == "x"

    def test_multiple_fields_multiple_errors(self):
        schema = {
            "fields": [
                {"key": "a", "label": "A", "required": True},
                {"key": "b", "label": "B", "required": True},
            ]
        }
        errs = validate_subsystem_record("k", {}, schema=schema)
        assert len(errs) == 2

    def test_validator_type_key_missing_or_empty(self):
        # validator dict has no "type" key → vtype="" → handler=None → skip
        schema = {"fields": [{"key": "x", "label": "X", "validators": [{"params": ["A"]}]}]}
        assert validate_subsystem_record("k", {"x": "val"}, schema=schema) == []


# ---------------------------------------------------------------------------
# compute_subsystem_derived — edge branches
# ---------------------------------------------------------------------------


class TestComputeSubsystemDerived:
    def test_empty_schema_returns_record_unchanged(self):
        rec = {"a": 1}
        out = compute_subsystem_derived("k", rec, schema={})
        assert out == rec

    def test_rules_not_dict_returns_record_unchanged(self):
        rec = {"a": 1}
        out = compute_subsystem_derived("k", rec, schema={"rules": "not_a_dict"})
        assert out == rec
        out2 = compute_subsystem_derived("k", rec, schema={"rules": ["list"]})
        assert out2 == rec

    def test_non_dict_rule_spec_is_skipped(self):
        schema = {"rules": {"result": "not_a_dict"}}
        rec = {"a": 5}
        out = compute_subsystem_derived("k", rec, schema=schema)
        assert "result" not in out

    def test_unknown_op_is_skipped(self):
        schema = {"rules": {"result": {"op": "nonexistent_op", "args": ["a"]}}}
        rec = {"a": 5}
        out = compute_subsystem_derived("k", rec, schema=schema)
        assert "result" not in out

    def test_empty_op_string_is_skipped(self):
        schema = {"rules": {"result": {"args": ["a"]}}}  # no "op" key
        rec = {"a": 5}
        out = compute_subsystem_derived("k", rec, schema=schema)
        assert "result" not in out

    def test_args_not_list_is_skipped(self):
        schema = {"rules": {"result": {"op": "mul", "args": "not_a_list"}}}
        rec = {"a": 5}
        out = compute_subsystem_derived("k", rec, schema=schema)
        assert "result" not in out

    def test_args_missing_key_treated_as_zero(self):
        # arg "missing_key" not in record → _to_number(None) → 0.0
        schema = {"rules": {"result": {"op": "add", "args": ["a", "missing_key"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        assert out["result"] == 5.0

    def test_fn_raises_recoverable_error_skips_target(self):
        def bad_op(args):
            raise RuntimeError("transient failure")

        register_derivation("cov_bad_op", bad_op)
        schema = {"rules": {"result": {"op": "cov_bad_op", "args": ["a"]}}}
        out = compute_subsystem_derived("k", {"a": 5}, schema=schema)
        # result not written because the fn raised
        assert "result" not in out

    def test_record_none_treated_as_empty_dict(self):
        schema = {"rules": {"result": {"op": "add", "args": ["a"]}}}
        out = compute_subsystem_derived("k", None, schema=schema)
        assert out["result"] == 0.0

    def test_multiple_rules_computed_sequentially(self):
        # Second rule depends on result of first (output dict is updated in-place)
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


# ---------------------------------------------------------------------------
# FieldError
# ---------------------------------------------------------------------------


class TestFieldError:
    def test_to_dict(self):
        e = FieldError("myfield", "我的字段", "必须不为空")
        assert e.to_dict() == {"field": "myfield", "label": "我的字段", "message": "必须不为空"}

    def test_dataclass_attributes(self):
        e = FieldError(field="f", label="L", message="M")
        assert e.field == "f"
        assert e.label == "L"
        assert e.message == "M"


# ---------------------------------------------------------------------------
# Integration: validate + compute together
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_validate_then_compute_full_pipeline(self):
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
        errs = validate_subsystem_record("k", {"name": "Paint", "unit": "kg"}, schema=schema)
        assert errs == []
        out = compute_subsystem_derived("k", {"qty": 3, "price": 50}, schema=schema)
        assert out["total"] == 150.0

    def test_sub_operator_via_schema(self):
        schema = {"rules": {"diff": {"op": "sub", "args": ["big", "small"]}}}
        out = compute_subsystem_derived("k", {"big": 100, "small": 35}, schema=schema)
        assert out["diff"] == 65.0

    def test_add_operator_via_schema(self):
        schema = {"rules": {"total": {"op": "add", "args": ["a", "b", "c"]}}}
        out = compute_subsystem_derived("k", {"a": 10, "b": 20, "c": 30}, schema=schema)
        assert out["total"] == 60.0
