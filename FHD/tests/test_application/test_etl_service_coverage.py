"""Focused branch coverage for ETL service mixins / transforms / knowledge payload.

Targets CI branch ratchet (≥80.5%) via high-ROI modules from latest backend-test.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application.etl.compatibility_presets import validate_compatibility_preset
from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.service_draft import DraftServiceMixin
from app.application.etl.service_support import (
    apply_validation_rules,
    clean_batch_id,
    clean_filename,
    clean_relative_path,
    dump_json,
    has_blocking_issues,
    load_json,
    mapping_key,
    safe_error,
    sanitize_webhook_headers,
)
from app.application.etl.service_targets import TargetConfigServiceMixin
from app.application.etl.targets.base import TargetAdapter, TargetField
from app.application.etl.transforms import (
    apply_mapping,
    apply_transform,
    neutralize_spreadsheet_formula,
)
from app.fastapi_routes.knowledge_v1_payload import (
    _ensure_bounded_metadata,
    _public_dataset_payload,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _StubAdapter(TargetAdapter):
    type = "customers"
    label = "客户"
    actions = ("new", "update", "skip")
    fields = (
        TargetField(key="name", label="名称", updatable=True),
        TargetField(key="phone", label="电话", updatable=False),
        TargetField(key="score", label="评分", updatable=True),
    )
    default_match_keys = ("name",)
    allow_dynamic_fields = False


class _DynamicAdapter(TargetAdapter):
    type = "export_csv"
    label = "导出"
    actions = ("new", "skip")
    fields = ()
    default_match_keys = ()
    allow_dynamic_fields = True


class _DraftHarness(DraftServiceMixin):
    def __init__(self) -> None:
        self._adviser = MagicMock()
        self._adviser.suggest.return_value = {"degraded": False}

    def get_run(self, db, *, run_id, owner_user_id):  # noqa: ANN001
        return {"id": run_id, "owner_user_id": owner_user_id}


class _TargetHarness(TargetConfigServiceMixin):
    pass


def _run(**kwargs):
    base = {
        "id": "run-1",
        "owner_user_id": 7,
        "status": "preview_ready",
        "target_type": "customers",
        "draft_json": "{}",
        "summary_json": "{}",
        "upload_id": "up-1",
        "total_rows": 1,
        "new_rows": 0,
        "update_rows": 0,
        "skip_rows": 0,
        "error_rows": 0,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# transforms.py
# ---------------------------------------------------------------------------


def test_neutralize_and_decimal_date_cast_branches():
    assert neutralize_spreadsheet_formula(12) == 12
    assert neutralize_spreadsheet_formula("safe") == "safe"
    for prefix in ("=", "+", "-", "@"):
        assert neutralize_spreadsheet_formula(f"{prefix}CMD").startswith("'")

    assert apply_transform(None, {"op": "number"}, {}) == ""
    assert apply_transform("", {"op": "number"}, {}) == ""
    assert apply_transform(Decimal("1.5"), {"op": "number"}, {}) == "1.5"
    assert apply_transform("(1,200.50)", {"op": "number"}, {}) == "-1200.50"
    assert apply_transform("（￥99元）", {"op": "number"}, {}) == "-99"
    assert apply_transform("¥1，234", {"op": "number"}, {}) == "1234"
    with pytest.raises(EtlError) as exc:
        apply_transform("not-a-number", {"op": "number"}, {})
    assert exc.value.code == "ETL_TRANSFORM_NUMBER_INVALID"

    assert apply_transform(None, {"op": "date"}, {}) == ""
    assert apply_transform("", {"op": "date"}, {}) == ""
    assert apply_transform(datetime(2026, 7, 31, 12, 0, 0), {"op": "date"}, {}) == "2026-07-31"
    assert apply_transform(date(2026, 1, 2), {"op": "date"}, {}) == "2026-01-02"
    assert apply_transform("20260731", {"op": "date"}, {}) == "2026-07-31"
    assert (
        apply_transform("31/07/2026", {"op": "date", "formats": ["%d/%m/%Y"]}, {}) == "2026-07-31"
    )
    assert apply_transform("2026-07-31T10:00:00", {"op": "date"}, {}) == "2026-07-31"
    with pytest.raises(EtlError) as date_exc:
        apply_transform("nope", {"op": "date"}, {})
    assert date_exc.value.code == "ETL_TRANSFORM_DATE_INVALID"

    assert apply_transform(None, {"op": "cast", "type": "string"}, {}) == ""
    assert apply_transform(9, {"op": "cast", "type": "string"}, {}) == "9"
    assert apply_transform(None, {"op": "cast", "type": "number"}, {}) == ""
    assert apply_transform("", {"op": "cast", "type": "decimal"}, {}) == ""
    assert apply_transform("3.5", {"op": "cast", "type": "float"}, {}) == 3.5
    assert apply_transform("3.5", {"op": "cast", "type": "number"}, {}) == "3.5"
    assert apply_transform(None, {"op": "cast", "type": "int"}, {}) == ""
    assert apply_transform("8", {"op": "cast", "type": "integer"}, {}) == 8
    assert apply_transform(True, {"op": "cast", "type": "bool"}, {}) is True
    for truthy in ("1", "true", "YES", "y", "是", "有"):
        assert apply_transform(truthy, {"op": "cast", "type": "boolean"}, {}) is True
    for falsy in ("0", "false", "no", "n", "否", "无", ""):
        assert apply_transform(falsy, {"op": "cast", "type": "boolean"}, {}) is False
    with pytest.raises(EtlError) as bool_exc:
        apply_transform("maybe", {"op": "cast", "type": "boolean"}, {})
    assert bool_exc.value.code == "ETL_TRANSFORM_BOOLEAN_INVALID"
    assert apply_transform("2026.07.31", {"op": "cast", "type": "date"}, {}) == "2026-07-31"
    with pytest.raises(EtlError) as cast_exc:
        apply_transform("x", {"op": "cast", "type": "blob"}, {})
    assert cast_exc.value.code == "ETL_TRANSFORM_CAST_UNSUPPORTED"


def test_formula_map_split_concat_and_mapping_branches():
    row = {"a": "10", "b": "2", "c": "", "name": "甲"}
    assert (
        apply_transform(
            None,
            {"op": "formula", "operator": "add", "operands": [{"field": "a"}, {"literal": "5"}]},
            row,
        )
        == "15"
    )
    assert (
        apply_transform(
            None,
            {"op": "formula", "operator": "sub", "operands": [{"field": "a"}, {"field": "b"}]},
            row,
        )
        == "8"
    )
    assert (
        apply_transform(
            None,
            {"op": "formula", "operator": "mul", "operands": [{"field": "a"}, {"field": "b"}]},
            row,
        )
        == "20"
    )
    assert (
        apply_transform(
            None,
            {"op": "formula", "operator": "div", "operands": [{"field": "a"}, {"field": "b"}]},
            row,
        )
        == "5"
    )
    with pytest.raises(EtlError) as zero_exc:
        apply_transform(
            None,
            {"op": "formula", "operator": "div", "operands": [{"field": "a"}, {"literal": "0"}]},
            row,
        )
    assert zero_exc.value.code == "ETL_FORMULA_DIVISION_BY_ZERO"
    assert (
        apply_transform(
            None,
            {
                "op": "formula",
                "operator": "coalesce",
                "operands": [{"field": "c"}, {"literal": "fallback"}],
            },
            row,
        )
        == "fallback"
    )
    with pytest.raises(EtlError) as op_exc:
        apply_transform(None, {"op": "formula", "operator": "pow", "operands": [1, 2]}, row)
    assert op_exc.value.code == "ETL_FORMULA_OPERATOR_FORBIDDEN"
    with pytest.raises(EtlError) as empty_exc:
        apply_transform(None, {"op": "formula", "operator": "add", "operands": []}, row)
    assert empty_exc.value.code == "ETL_FORMULA_OPERANDS_REQUIRED"
    with pytest.raises(EtlError) as operand_exc:
        apply_transform(
            None,
            {"op": "formula", "operator": "add", "operands": [{"field": "a", "literal": 1}]},
            row,
        )
    assert operand_exc.value.code == "ETL_FORMULA_OPERAND_INVALID"

    assert apply_transform("  hi\t", {"op": "trim"}, {}) == "hi"
    assert apply_transform(9, {"op": "trim"}, {}) == 9
    assert apply_transform("", {"op": "default", "value": "x"}, {}) == "x"
    assert apply_transform("keep", {"op": "default", "value": "x"}, {}) == "keep"
    assert apply_transform("A", {"op": "map", "values": {"A": "甲"}, "fallback": "?"}, {}) == "甲"
    assert apply_transform("Z", {"op": "lookup", "values": {"A": "甲"}, "fallback": "?"}, {}) == "?"
    assert apply_transform(None, {"op": "map", "values": {}}, {}) is None
    assert apply_transform("Z", {"op": "map", "values": {}}, {}) == "Z"
    with pytest.raises(EtlError) as map_exc:
        apply_transform("A", {"op": "map"}, {})
    assert map_exc.value.code == "ETL_TRANSFORM_MAP_INVALID"
    assert apply_transform("a,b,c", {"op": "split", "delimiter": ",", "index": 1}, {}) == "b"
    assert apply_transform("a|b", {"op": "split", "delimiter": "|", "index": 9}, {}) == ""
    assert (
        apply_transform(None, {"op": "concat", "fields": ["name", "a"], "separator": "-"}, row)
        == "甲-10"
    )
    with pytest.raises(EtlError) as concat_exc:
        apply_transform(None, {"op": "concat", "fields": "name"}, row)
    assert concat_exc.value.code == "ETL_TRANSFORM_CONCAT_INVALID"
    with pytest.raises(EtlError) as forbidden:
        apply_transform("x", {"op": "eval"}, {})
    assert forbidden.value.code == "ETL_TRANSFORM_FORBIDDEN"

    mapped = apply_mapping(
        {"客户": " 甲 ", "标签": "vip,gold"},
        [
            {"source": "客户", "target": "", "transforms": []},
            {
                "source": "客户",
                "target": "name",
                "transforms": [{"op": "trim"}, {"op": "cast", "type": "string"}],
            },
            {
                "source": "标签",
                "target": "tier",
                "transforms": [{"op": "split", "delimiter": ",", "index": 0}],
            },
        ],
    )
    assert mapped == {"name": "甲", "tier": "vip"}
    with pytest.raises(EtlError) as transforms_exc:
        apply_mapping({"a": 1}, [{"source": "a", "target": "x", "transforms": "bad"}])
    assert transforms_exc.value.code == "ETL_TRANSFORMS_INVALID"
    with pytest.raises(EtlError) as rule_exc:
        apply_mapping({"a": 1}, [{"source": "a", "target": "x", "transforms": ["trim"]}])
    assert rule_exc.value.code == "ETL_TRANSFORM_INVALID"


# ---------------------------------------------------------------------------
# service_support.py
# ---------------------------------------------------------------------------


def test_service_support_helpers_and_validation_branches():
    assert load_json(None, {"d": 1}) == {"d": 1}
    assert load_json("{bad", [1]) == [1]
    assert load_json('{"ok": true}', {}) == {"ok": True}
    dumped = dump_json({"z": 1, "a": date(2026, 1, 1)})
    assert '"a"' in dumped and '"z"' in dumped

    assert clean_filename("dir/../evil\x00.xlsx") == "evil.xlsx"
    assert clean_filename("") == "upload"
    assert clean_relative_path(r"..\a\..\b\c.xlsx", "fallback.csv") == "a/b/c.xlsx"
    assert clean_relative_path(None, "x.csv") == "x.csv"
    assert clean_relative_path("\x00", "y.csv") == "y.csv"
    assert clean_batch_id(None) is None
    assert clean_batch_id("  ") is None
    assert clean_batch_id("550e8400-e29b-41d4-a716-446655440000") == (
        "550e8400-e29b-41d4-a716-446655440000"
    )
    with pytest.raises(EtlError) as batch_exc:
        clean_batch_id("not-uuid")
    assert batch_exc.value.code == "ETL_BATCH_ID_INVALID"
    assert mapping_key("Foo-Bar_1") == "foobar1"

    code, message = safe_error(EtlError("ETL_X", "msg"))
    assert code == "ETL_X" and message == "msg"
    code2, message2 = safe_error(RuntimeError("boom"))
    assert code2 == "ETL_INTERNAL_ERROR"

    with pytest.raises(EtlError) as hdr_count:
        sanitize_webhook_headers({f"h{i}": "v" for i in range(41)})
    assert hdr_count.value.code == "ETL_WEBHOOK_HEADERS_INVALID"
    with pytest.raises(EtlError):
        sanitize_webhook_headers({"": "v"})
    with pytest.raises(EtlError):
        sanitize_webhook_headers({"x" * 129: "v"})
    with pytest.raises(EtlError):
        sanitize_webhook_headers({"ok": "v" * 2049})
    with pytest.raises(EtlError):
        sanitize_webhook_headers({"bad\nname": "v"})
    with pytest.raises(EtlError):
        sanitize_webhook_headers({"name": "bad\rvalue"})
    with pytest.raises(EtlError) as secret_hdr:
        sanitize_webhook_headers({"X-Api-Key": "secret"})
    assert secret_hdr.value.code == "ETL_WEBHOOK_SECRET_HEADER_FORBIDDEN"
    assert sanitize_webhook_headers({"X-Trace": "abc"}) == {"X-Trace": "abc"}

    data = {"name": "甲", "score": "5", "note": "ab"}
    issues = apply_validation_rules(
        data,
        [
            {"field": "name", "op": "required"},
            {"field": "missing", "op": "required", "message": "缺字段"},
            {"field": "name", "op": "enum", "value": ["乙"]},
            {"field": "name", "op": "enum", "value": "not-list"},
            {"field": "score", "op": "min", "value": 10},
            {"field": "score", "op": "max", "value": 1},
            {"field": "score", "op": "min", "value": "bad"},
            {"field": "note", "op": "min_length", "value": 5},
            {"field": "note", "op": "max_length", "value": 1},
            {"field": "note", "op": "min_length", "value": "xx"},
            {"field": "score", "op": "max", "value": 100},
            {"field": "unknown", "op": "noop"},
        ],
    )
    codes = [item["code"] for item in issues]
    assert codes.count("ETL_VALIDATION_RULE_FAILED") >= 7
    assert has_blocking_issues([{"severity": "warning"}, {"severity": "error"}]) is True
    assert has_blocking_issues([{"severity": "warning"}, "bad"]) is False
    assert has_blocking_issues([]) is False


# ---------------------------------------------------------------------------
# knowledge_v1_payload.py + compatibility_presets.py
# ---------------------------------------------------------------------------


def test_knowledge_payload_bounds_and_public_strip():
    _ensure_bounded_metadata({"ok": 1, "nested": [{"a": 1}]})
    with pytest.raises(ValueError, match="nesting"):
        deep = current = {}
        for _ in range(10):
            current["k"] = {}
            current = current["k"]
        _ensure_bounded_metadata(deep)
    with pytest.raises(ValueError, match="too many fields"):
        _ensure_bounded_metadata({f"k{i}": i for i in range(201)})
    with pytest.raises(ValueError, match="key is too long"):
        _ensure_bounded_metadata({"x" * 201: 1})
    with pytest.raises(ValueError, match="list is too long"):
        _ensure_bounded_metadata({"items": list(range(1001))})

    class _Bad:
        def __str__(self) -> str:
            raise ValueError("cannot stringify")

    with pytest.raises(ValueError, match="JSON serializable"):
        _ensure_bounded_metadata({"bad": _Bad()})
    with pytest.raises(ValueError, match="cannot exceed"):
        _ensure_bounded_metadata({"blob": "x" * 200}, max_bytes=16)

    public = _public_dataset_payload(
        {
            "name": "ds",
            "_private": 1,
            "storage_path": "/tmp/x",
            "file_path": "/tmp/y",
            "vector_index_path": "/tmp/z",
            "kids": [{"_hidden": True, "ok": 1}, "plain"],
        }
    )
    assert public == {"name": "ds", "kids": [{"ok": 1}, "plain"]}
    assert _public_dataset_payload("scalar") == "scalar"


def test_compatibility_preset_validation_branches(monkeypatch):
    with pytest.raises(EtlError) as target_exc:
        validate_compatibility_preset("p", target_type="webhook", upload_suffix=".xlsx")
    assert target_exc.value.code == "ETL_COMPATIBILITY_PRESET_TARGET_MISMATCH"
    with pytest.raises(EtlError) as file_exc:
        validate_compatibility_preset("p", target_type="customers", upload_suffix=".csv")
    assert file_exc.value.code == "ETL_COMPATIBILITY_PRESET_FILE_UNSUPPORTED"

    monkeypatch.setattr(
        "app.application.shipment_etl_profile.list_profiles",
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
    )
    with pytest.raises(EtlError) as unavailable:
        validate_compatibility_preset("p", target_type="products", upload_suffix=".xlsm")
    assert unavailable.value.code == "ETL_COMPATIBILITY_PRESET_UNAVAILABLE"
    assert unavailable.value.status_code == 503

    monkeypatch.setattr(
        "app.application.shipment_etl_profile.list_profiles",
        lambda: [{"id": "preset-a"}, "bad", {"id": ""}],
    )
    with pytest.raises(EtlError) as missing:
        validate_compatibility_preset(
            "missing", target_type="shipment_records", upload_suffix=".xlsx"
        )
    assert missing.value.code == "ETL_COMPATIBILITY_PRESET_NOT_FOUND"
    validate_compatibility_preset(
        "preset-a", target_type="customer_products", upload_suffix=".xlsx"
    )


# ---------------------------------------------------------------------------
# service_draft.py — validate / update / overrides
# ---------------------------------------------------------------------------


def test_validate_draft_error_matrix():
    svc = _DraftHarness()
    adapter = _StubAdapter()

    with pytest.raises(EtlError) as e1:
        svc._validate_draft({"field_mappings": {}}, adapter)
    assert e1.value.code == "ETL_MAPPINGS_INVALID"
    with pytest.raises(EtlError) as e2:
        svc._validate_draft({"field_mappings": [{}] * 501}, adapter)
    assert e2.value.code == "ETL_MAPPINGS_INVALID"
    with pytest.raises(EtlError) as e3:
        svc._validate_draft({"field_mappings": [{"target": "unknown"}]}, adapter)
    assert e3.value.code == "ETL_MAPPING_TARGET_INVALID"
    with pytest.raises(EtlError) as e4:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}, {"target": "name", "source": "x"}]},
            adapter,
        )
    assert e4.value.code == "ETL_MAPPING_TARGET_DUPLICATE"
    with pytest.raises(EtlError) as e5:
        svc._validate_draft(
            {"field_mappings": [{"target": "name", "transforms": "nope"}]},
            adapter,
        )
    assert e5.value.code == "ETL_TRANSFORMS_INVALID"
    with pytest.raises(EtlError) as e6:
        svc._validate_draft(
            {"field_mappings": [{"target": "name", "transforms": [{"op": "trim"}] * 21}]},
            adapter,
        )
    assert e6.value.code == "ETL_TRANSFORMS_INVALID"
    with pytest.raises(EtlError) as e7:
        svc._validate_draft(
            {"field_mappings": [{"target": "name", "transforms": ["trim"]}]},
            adapter,
        )
    assert e7.value.code == "ETL_TRANSFORM_INVALID"
    with pytest.raises(EtlError) as e8:
        svc._validate_draft(
            {"field_mappings": [{"target": "name", "transforms": [{"op": "eval"}]}]},
            adapter,
        )
    assert e8.value.code == "ETL_TRANSFORM_FORBIDDEN"
    with pytest.raises(EtlError) as e9:
        svc._validate_draft(
            {
                "field_mappings": [{"target": "name"}],
                "allowed_update_fields": ["phone"],
            },
            adapter,
        )
    assert e9.value.code == "ETL_UPDATE_FIELDS_FORBIDDEN"
    with pytest.raises(EtlError) as e10:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "match_keys": ["phone"]},
            adapter,
        )
    assert e10.value.code == "ETL_MATCH_KEYS_UNSUPPORTED"
    with pytest.raises(EtlError) as e11:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "action_rules": ["bad"]},
            adapter,
        )
    assert e11.value.code == "ETL_ACTION_RULES_INVALID"
    with pytest.raises(EtlError) as e12:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "ocr_confirmed": "yes"},
            adapter,
        )
    assert e12.value.code == "ETL_CONFIRMATION_VALUE_INVALID"
    with pytest.raises(EtlError) as e13:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "document_confirmed": 1},
            adapter,
        )
    assert e13.value.code == "ETL_CONFIRMATION_VALUE_INVALID"
    with pytest.raises(EtlError) as e14:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "validation_rules": {"bad": True}},
            adapter,
        )
    assert e14.value.code == "ETL_VALIDATION_RULES_INVALID"
    with pytest.raises(EtlError) as e15:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "validation_rules": [{}] * 101},
            adapter,
        )
    assert e15.value.code == "ETL_VALIDATION_RULES_INVALID"
    with pytest.raises(EtlError) as e16:
        svc._validate_draft(
            {"field_mappings": [{"target": "name"}], "validation_rules": ["bad"]},
            adapter,
        )
    assert e16.value.code == "ETL_VALIDATION_RULE_INVALID"
    with pytest.raises(EtlError) as e17:
        svc._validate_draft(
            {
                "field_mappings": [{"target": "name"}],
                "validation_rules": [{"field": "name", "op": "regex"}],
            },
            adapter,
        )
    assert e17.value.code == "ETL_VALIDATION_RULE_INVALID"
    with pytest.raises(EtlError) as e18:
        svc._validate_draft(
            {
                "field_mappings": [{"target": "name"}],
                "validation_rules": [{"field": "name", "op": "enum", "value": "x"}],
            },
            adapter,
        )
    assert e18.value.code == "ETL_VALIDATION_RULE_INVALID"
    with pytest.raises(EtlError) as e19:
        svc._validate_draft(
            {
                "field_mappings": [{"target": "name"}],
                "validation_rules": [{"field": "name", "op": "enum", "value": list(range(1001))}],
            },
            adapter,
        )
    assert e19.value.code == "ETL_VALIDATION_RULE_INVALID"

    # happy path + dynamic fields
    svc._validate_draft(
        {
            "field_mappings": [
                {"target": "name", "transforms": [{"op": "trim"}]},
                {"target": "score", "transforms": []},
            ],
            "allowed_update_fields": ["name", "score"],
            "match_keys": ["name"],
            "action_rules": {},
            "ocr_confirmed": True,
            "document_confirmed": False,
            "validation_rules": [
                {"field": "name", "op": "required"},
                {"field": "name", "op": "enum", "value": ["甲", "乙"]},
            ],
        },
        adapter,
    )
    dyn = _DynamicAdapter()
    svc._validate_draft(
        {"field_mappings": [{"target": "custom_col", "transforms": []}]},
        dyn,
    )
    with pytest.raises(EtlError) as long_target:
        svc._validate_draft(
            {"field_mappings": [{"target": "t" * 161}]},
            dyn,
        )
    assert long_target.value.code == "ETL_MAPPING_TARGET_INVALID"


def test_update_draft_and_row_override_branches(monkeypatch):
    svc = _DraftHarness()
    db = MagicMock()

    locked = _run(status="executing")
    monkeypatch.setattr(svc, "_owned_run", lambda *_a, **_k: locked, raising=False)
    with pytest.raises(EtlConflict) as conflict:
        svc.update_draft(
            db, run_id="run-1", owner_user_id=7, patch={"row_overrides": {"1": "skip"}}
        )
    assert conflict.value.code == "ETL_RUN_NOT_EDITABLE"

    editable = _run(status="failed", draft_json='{"field_mappings":[]}')
    monkeypatch.setattr(svc, "_owned_run", lambda *_a, **_k: editable, raising=False)
    applied: list[dict] = []

    def _apply(_db, run_id, owner, overrides):
        applied.append(overrides)

    monkeypatch.setattr(svc, "_apply_row_overrides", _apply, raising=False)
    monkeypatch.setattr(svc, "_record_correction_metrics", MagicMock(), raising=False)
    out = svc.update_draft(
        db, run_id="run-1", owner_user_id=7, patch={"row_overrides": {"9": "skip"}}
    )
    assert out["id"] == "run-1"
    assert applied == [{"9": "skip"}]

    # no draft keys and empty/non-dict overrides → plain get_run
    applied.clear()
    bare = svc.update_draft(db, run_id="run-1", owner_user_id=7, patch={"noop": True})
    assert bare["id"] == "run-1"
    assert applied == []
    svc.update_draft(db, run_id="run-1", owner_user_id=7, patch={"row_overrides": "bad"})
    assert applied == []

    # mapping change path submits revalidation
    submitted = MagicMock()
    monkeypatch.setattr(svc, "_validate_draft", MagicMock(), raising=False)
    monkeypatch.setattr(svc, "_submit_revalidation", submitted, raising=False)
    monkeypatch.setattr(
        "app.application.etl.service_draft.get_adapter",
        lambda _t: _StubAdapter(),
    )
    monkeypatch.setattr(
        "app.application.etl.service_draft.tenant_id_for_write",
        lambda: 42,
    )
    monkeypatch.setattr(
        "app.application.etl.service_draft.dump_json",
        lambda value: json.dumps(value),
    )
    result = svc.update_draft(
        db,
        run_id="run-1",
        owner_user_id=7,
        patch={
            "field_mappings": [{"target": "name"}],
            "row_overrides": {"1": "new"},
            "ocr_confirmed": True,
        },
    )
    assert result["id"] == "run-1"
    assert editable.status == "previewing"
    submitted.assert_called_once()
    assert submitted.call_args.args[0] == "run-1"

    # metrics swallow errors
    with patch(
        "app.utils.metrics.etl_manual_corrections_total",
        side_effect=RuntimeError("metrics down"),
    ):
        DraftServiceMixin._record_correction_metrics(mapping_changed=True, overrides={"1": "skip"})

    counter = MagicMock()
    with patch("app.utils.metrics.etl_manual_corrections_total", counter):
        DraftServiceMixin._record_correction_metrics(
            mapping_changed=True, overrides={"1": "skip", "2": "new"}
        )
    assert counter.labels.call_count == 2

    # override matrix (call unbound mixin method; update_draft patched the instance)
    run = _run(draft_json='{"allowed_update_fields":[]}')
    monkeypatch.setattr(svc, "_owned_run", lambda *_a, **_k: run, raising=False)
    monkeypatch.setattr(
        "app.application.etl.service_draft.get_adapter",
        lambda _t: _StubAdapter(),
    )
    apply_overrides = DraftServiceMixin._apply_row_overrides
    with pytest.raises(EtlError) as bad_action:
        apply_overrides(svc, db, "run-1", 7, {"1": "delete"})
    assert bad_action.value.code == "ETL_ROW_ACTION_INVALID"

    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.first.return_value = None
    q.count.return_value = 0
    with pytest.raises(EtlNotFound):
        apply_overrides(svc, db, "run-1", 7, {"1": "skip"})

    row = SimpleNamespace(
        id=1,
        execution_status="success",
        validation_json="[]",
        match_ref="",
        suggested_action="new",
        final_action="new",
        action_overridden=False,
    )
    q.first.return_value = row
    with pytest.raises(EtlConflict) as executed:
        apply_overrides(svc, db, "run-1", 7, {"1": "skip"})
    assert executed.value.code == "ETL_ROW_ALREADY_EXECUTED"

    row.execution_status = "pending"
    row.validation_json = '[{"severity":"error"}]'
    with pytest.raises(EtlConflict) as invalid_row:
        apply_overrides(svc, db, "run-1", 7, {"1": "skip"})
    assert invalid_row.value.code == "ETL_INVALID_ROW_CANNOT_OVERRIDE"

    row.validation_json = "[]"
    row.match_ref = ""
    with pytest.raises(EtlConflict) as need_match:
        apply_overrides(svc, db, "run-1", 7, {"1": "update"})
    assert need_match.value.code == "ETL_ROW_UPDATE_REQUIRES_MATCH"

    row.match_ref = "ref-1"
    with pytest.raises(EtlConflict) as need_fields:
        apply_overrides(svc, db, "run-1", 7, {"1": "update"})
    assert need_fields.value.code == "ETL_ROW_UPDATE_FIELDS_REQUIRED"

    run.draft_json = '{"allowed_update_fields":["name"]}'
    row.suggested_action = "skip"
    with pytest.raises(EtlConflict) as force_new:
        apply_overrides(svc, db, "run-1", 7, {"1": "new"})
    assert force_new.value.code == "ETL_DUPLICATE_CANNOT_FORCE_NEW"

    row.suggested_action = "new"
    row.match_ref = ""
    apply_overrides(svc, db, "run-1", 7, {"1": "skip"})
    assert row.final_action == "skip"
    assert row.action_overridden is True
    db.commit.assert_called()

    svc._set_run_counts(run, {"new": 2, "update": 1, "skip": 3, "error": 4})
    assert run.new_rows == 2
    assert run.error_rows == 4
    assert '"counts"' in run.summary_json


def test_revalidate_existing_rows_page_and_issue_branches(monkeypatch):
    from app.application.etl.targets.base import PreviewDecision

    svc = _DraftHarness()
    db = MagicMock()
    run = _run(
        draft_json=json.dumps(
            {
                "field_mappings": [
                    {
                        "source": "name",
                        "target": "name",
                        "transforms": [{"op": "trim"}],
                    },
                    {
                        "source": "bad",
                        "target": "score",
                        "transforms": [{"op": "number"}],
                    },
                ],
                "allowed_update_fields": ["name"],
                "validation_rules": [{"field": "name", "op": "required"}],
                "ocr_confirmed": False,
            }
        ),
        total_rows=3,
        summary_json="{}",
    )
    upload = SimpleNamespace(id="up-1")
    monkeypatch.setattr(svc, "_owned_run", lambda *_a, **_k: run, raising=False)
    monkeypatch.setattr(svc, "_owned_upload_record", lambda *_a, **_k: upload, raising=False)
    monkeypatch.setattr(svc, "_row_context", lambda *_a, **_k: {}, raising=False)

    adapter = MagicMock()
    adapter.preview.side_effect = [
        PreviewDecision(action="new", reason="create", after={"name": "甲"}),
        PreviewDecision(
            action="update",
            match_ref="r1",
            before={"name": "旧"},
            after={"name": "乙"},
            issues=[{"code": "WARN", "severity": "warning", "field": "name", "message": "w"}],
        ),
    ]
    monkeypatch.setattr("app.application.etl.service_draft.get_adapter", lambda _t: adapter)
    svc._adviser.suggest.side_effect = [
        {"degraded": False, "action": "new"},
        {"degraded": True, "action": "update"},
    ]

    success_row = SimpleNamespace(
        id=1,
        execution_status="success",
        final_action="skip",
        source_row=1,
        source_json="{}",
        provenance_json="{}",
        normalized_json="{}",
        validation_json="[]",
        suggested_action="skip",
        action_overridden=False,
        match_ref=None,
        before_json="{}",
        after_json="{}",
        llm_suggestion_json="{}",
    )
    mapping_error_row = SimpleNamespace(
        id=2,
        execution_status="pending",
        final_action="new",
        source_row=2,
        source_json=json.dumps({"name": "甲", "bad": "not-num"}),
        provenance_json=json.dumps({"ocr": True}),
        normalized_json="{}",
        validation_json="[]",
        suggested_action="new",
        action_overridden=True,
        match_ref=None,
        before_json="{}",
        after_json="{}",
        llm_suggestion_json="{}",
    )
    ok_row = SimpleNamespace(
        id=3,
        execution_status="pending",
        final_action="new",
        source_row=3,
        source_json=json.dumps({"name": "乙", "bad": "1"}),
        provenance_json="{}",
        normalized_json="{}",
        validation_json="[]",
        suggested_action="new",
        action_overridden=False,
        match_ref=None,
        before_json="{}",
        after_json="{}",
        llm_suggestion_json="{}",
    )

    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.side_effect = [[success_row, mapping_error_row, ok_row], []]

    DraftServiceMixin._revalidate_existing_rows(svc, db, "run-1", 7)

    assert success_row.final_action == "skip"
    assert mapping_error_row.final_action == "error"
    assert "ETL_OCR_CONFIRMATION_REQUIRED" in mapping_error_row.validation_json
    assert ok_row.final_action == "update"
    assert run.status == "preview_ready"
    assert run.progress == 100
    assert '"llm_degraded": true' in run.summary_json.replace(" ", "") or (
        json.loads(run.summary_json).get("llm_degraded") is True
    )
    db.commit.assert_called()


def test_submit_revalidation_dedupes_and_failure_persist(monkeypatch):
    from app.application.etl import service_support as support

    svc = _DraftHarness()
    support.SUBMITTED.clear()
    monkeypatch.setattr(
        svc, "_revalidate_existing_rows", MagicMock(side_effect=RuntimeError("x")), raising=False
    )
    monkeypatch.setattr(svc, "_apply_row_overrides", MagicMock(), raising=False)
    failed_run = _run(status="previewing")
    monkeypatch.setattr(svc, "_owned_run", lambda *_a, **_k: failed_run, raising=False)

    class _ImmediateExecutor:
        def submit(self, fn):  # noqa: ANN001
            fn()
            return SimpleNamespace(result=lambda: None)

    class _Scope:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.application.etl.service_draft.EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(
        "app.application.etl.service_draft.tenant_scope", lambda *_a, **_k: _Scope()
    )
    db = MagicMock()
    monkeypatch.setattr("app.application.etl.service_draft.new_session", lambda: db)

    svc._submit_revalidation("run-dup", 1, 7, {"1": "skip"})
    assert failed_run.status == "failed"
    assert failed_run.error_code == "ETL_INTERNAL_ERROR"
    assert "run-dup" not in support.SUBMITTED

    # second call while already submitted is a no-op
    support.SUBMITTED.add("run-dup")
    svc._submit_revalidation("run-dup", 1, 7, None)
    support.SUBMITTED.discard("run-dup")

    # success path applies overrides; nested persist failure is swallowed
    monkeypatch.setattr(svc, "_revalidate_existing_rows", MagicMock(), raising=False)
    apply_mock = MagicMock()
    monkeypatch.setattr(svc, "_apply_row_overrides", apply_mock, raising=False)
    svc._submit_revalidation("run-ok", 1, 7, {"2": "skip"})
    apply_mock.assert_called_once()
    assert "run-ok" not in support.SUBMITTED

    monkeypatch.setattr(
        svc,
        "_revalidate_existing_rows",
        MagicMock(side_effect=RuntimeError("again")),
        raising=False,
    )
    monkeypatch.setattr(
        svc, "_owned_run", MagicMock(side_effect=RuntimeError("persist failed")), raising=False
    )
    svc._submit_revalidation("run-persist-fail", 1, 7, None)
    assert "run-persist-fail" not in support.SUBMITTED


# ---------------------------------------------------------------------------
# service_targets.py
# ---------------------------------------------------------------------------


def test_target_config_mixin_crud_and_download_branches(tmp_path, monkeypatch):
    svc = _TargetHarness()
    db = MagicMock()

    monkeypatch.setattr(
        "app.application.etl.service_targets.tenant_id_for_write",
        lambda: 9,
    )
    monkeypatch.setattr(
        "app.application.etl.service_targets.store_webhook_secret",
        lambda owner, secret: f"etl:{owner}:ref",
    )
    deleted: list[str] = []
    monkeypatch.setattr(
        "app.application.etl.service_targets.delete_webhook_secret",
        lambda ref: deleted.append(ref) if ref else None,
    )

    with pytest.raises(EtlError) as invalid:
        svc.create_target_config(
            db,
            owner_user_id=3,
            name="",
            endpoint_url="",
            headers={"X-Trace": "1"},
            secret="sekrit",
        )
    assert invalid.value.code == "ETL_TARGET_CONFIG_INVALID"
    assert deleted == ["etl:3:ref"]

    deleted.clear()
    created_cfg = {}

    def _add(config):
        created_cfg.update(
            {
                "id": config.id,
                "name": config.name,
                "endpoint_url": config.endpoint_url,
                "headers_json": config.headers_json,
                "secret_ref": config.secret_ref,
                "target_type": config.target_type,
                "is_active": True,
            }
        )

    db.add.side_effect = _add
    out = svc.create_target_config(
        db,
        owner_user_id=3,
        name=" hook ",
        endpoint_url=" https://example.com/h ",
        headers={"X-Trace": "1"},
        secret="sekrit",
    )
    assert out["name"] == "hook"
    assert out["has_secret"] is True
    db.flush.assert_called()

    cfg = SimpleNamespace(
        id="cfg-1",
        name="old",
        target_type="webhook",
        endpoint_url="https://old",
        headers_json='{"X-Trace":"1"}',
        secret_ref="etl:3:old",
        is_active=True,
        owner_user_id=3,
    )
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = [cfg]
    q.first.return_value = cfg
    listed = svc.list_target_configs(db, owner_user_id=3)
    assert listed[0]["id"] == "cfg-1"

    deleted.clear()
    with pytest.raises(EtlError) as upd_invalid:
        svc.update_target_config(
            db,
            config_id="cfg-1",
            owner_user_id=3,
            name="",
            endpoint_url="",
            headers={},
            secret="new-secret",
        )
    assert upd_invalid.value.code == "ETL_TARGET_CONFIG_INVALID"
    assert "etl:3:ref" in deleted

    deleted.clear()
    cfg.name = "old"
    cfg.endpoint_url = "https://old"
    cfg.secret_ref = "etl:3:old"
    updated = svc.update_target_config(
        db,
        config_id="cfg-1",
        owner_user_id=3,
        name="新钩子",
        endpoint_url="https://example.com/new",
        headers={"X-Trace": "2"},
        secret="rotated",
    )
    assert updated["name"] == "新钩子"
    assert "etl:3:old" in deleted

    # update without rotating secret
    deleted.clear()
    cfg.secret_ref = "etl:3:keep"
    svc.update_target_config(
        db,
        config_id="cfg-1",
        owner_user_id=3,
        name="keep",
        endpoint_url="https://example.com/keep",
        headers={},
        secret=None,
    )
    assert deleted == []

    svc.delete_target_config(db, config_id="cfg-1", owner_user_id=3)
    assert cfg.is_active is False

    q.first.return_value = None
    with pytest.raises(EtlNotFound):
        svc._owned_target_config(db, "missing", 3)

    adapter = MagicMock()
    adapter.execute_batch.return_value = {"receipt": {"ok": True}}
    monkeypatch.setattr("app.application.etl.service_targets.get_adapter", lambda _t: adapter)
    q.first.return_value = cfg
    cfg.secret_ref = "etl:3:keep"
    tested = svc.target_config_for_test(db, config_id="cfg-1", owner_user_id=3)
    assert tested["success"] is True
    assert tested["receipt"]["ok"] is True

    # download_path branches
    monkeypatch.setattr(
        "app.application.etl.service_targets.get_app_data_dir",
        lambda: str(tmp_path),
    )
    export_root = tmp_path / "etl" / "exports"
    export_root.mkdir(parents=True)
    good = export_root / "file.csv"
    good.write_text("a\n", encoding="utf-8")

    run = SimpleNamespace(
        id="run-x",
        owner_user_id=3,
        target_type="customers",
        status="completed",
        receipt_json='{"file_name":"file.csv"}',
    )
    monkeypatch.setattr(svc, "_owned_run", lambda *_a, **_k: run, raising=False)
    with pytest.raises(EtlNotFound):
        svc.download_path(db, run_id="run-x", owner_user_id=3)

    run.target_type = "export_csv"
    run.status = "failed"
    with pytest.raises(EtlNotFound):
        svc.download_path(db, run_id="run-x", owner_user_id=3)

    run.status = "completed"
    run.receipt_json = '{"file_name":"../escape.csv"}'
    with pytest.raises(EtlNotFound):
        svc.download_path(db, run_id="run-x", owner_user_id=3)

    run.receipt_json = '{"file_name":"missing.csv"}'
    with pytest.raises(EtlNotFound):
        svc.download_path(db, run_id="run-x", owner_user_id=3)

    run.receipt_json = '{"file_name":"file.csv"}'
    assert svc.download_path(db, run_id="run-x", owner_user_id=3) == good.resolve()

    # export_error_rows
    err_row = SimpleNamespace(
        source_sheet="S1",
        source_row=2,
        source_json='{"a":1}',
        validation_json='[{"code":"x"}]',
    )
    q.all.return_value = [err_row]
    path = svc.export_error_rows(db, run_id="run-x", owner_user_id=3)
    assert path.exists()
    text = path.read_text(encoding="utf-8-sig")
    assert "source_sheet" in text and "S1" in text

    q.first.return_value = None
    with pytest.raises(EtlNotFound):
        TargetConfigServiceMixin._owned_run(svc, db, "missing", 3)
