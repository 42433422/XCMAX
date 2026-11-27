"""Explicit JSON Schema empty values preserve required-field presence checks."""

import pytest

from app.application.agent_orchestrator.tool_spec import validate_schema_object


def _schema(prop):
    return {
        "type": "object",
        "required": ["value"],
        "properties": {"value": prop},
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    "prop,value",
    [
        ({"type": ["string", "null"]}, None),
        ({"type": "null"}, None),
        ({"type": "string", "minLength": 0}, ""),
        ({"type": "string", "minLength": 0}, " \t "),
        ({"type": ["string", "null"], "minLength": 0}, ""),
        ({"type": "number"}, 0),
        ({"type": "boolean"}, False),
    ],
)
def test_declared_empty_values_are_present_but_missing_keys_still_fail(prop, value):
    assert validate_schema_object(_schema(prop), {"value": value})[0] is True
    assert validate_schema_object(_schema(prop), {})[0] is False


@pytest.mark.parametrize("value", [None, "", " \t "])
def test_legacy_required_scalar_does_not_implicitly_allow_empty_values(value):
    assert validate_schema_object(_schema({"type": "string"}), {"value": value})[0] is False


@pytest.mark.parametrize(
    "prop,payload",
    [
        ({"type": ["string", "null"]}, {"value": 7}),
        ({"type": ["string", "null"], "minLength": 0}, {"value": []}),
        ({"type": "string", "minLength": 0}, {"value": 7}),
        ({"type": "string", "minLength": False}, {"value": ""}),
        ({"type": "number"}, {"value": False}),
        ({"type": ["string", "null"]}, {"value": None, "extra": "forbidden"}),
        ({"type": "string", "minLength": 0}, {"value": "", "extra": "forbidden"}),
    ],
)
def test_explicit_empty_contract_keeps_type_and_additional_field_rejections(prop, payload):
    assert validate_schema_object(_schema(prop), payload)[0] is False
