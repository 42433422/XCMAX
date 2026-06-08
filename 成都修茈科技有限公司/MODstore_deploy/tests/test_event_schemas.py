"""Ensure JSON Schema files stay aligned with eventing/contracts.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modstore_server.eventing.contracts import EVENT_CONTRACTS

_DOCS_EVENTS = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "events"


def _schema_path(event_name: str) -> Path:
    return _DOCS_EVENTS / f"{event_name}.schema.json"


@pytest.mark.parametrize("name", sorted(EVENT_CONTRACTS.keys()))
def test_schema_required_matches_contract(name: str) -> None:
    contract = EVENT_CONTRACTS[name]
    path = _schema_path(name)
    assert path.is_file(), f"missing schema file for {name}: {path}"
    schema = json.loads(path.read_text(encoding="utf-8"))
    required = schema.get("required") or []
    assert isinstance(required, list)
    assert set(required) == set(contract.required_payload), (
        f"{name}: schema required {set(required)} != "
        f"contract required_payload {set(contract.required_payload)}"
    )


@pytest.mark.parametrize("name", sorted(EVENT_CONTRACTS.keys()))
def test_minimal_payload_validates_against_schema(name: str) -> None:
    contract = EVENT_CONTRACTS[name]
    path = _schema_path(name)
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = {k: _dummy_value(k) for k in contract.required_payload}
    Draft202012Validator(schema).validate(payload)


def _dummy_value(key: str) -> object:
    if key in ("user_id", "author_id", "workflow_id", "execution_id", "refund_id", "tokens"):
        return 1
    if key in ("total_amount", "amount", "cost", "duration_ms"):
        return 0.0
    if key == "order_kind":
        return "test"
    return f"dummy-{key}"
