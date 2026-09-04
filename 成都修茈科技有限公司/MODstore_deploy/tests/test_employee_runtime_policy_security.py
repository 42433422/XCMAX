from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from modstore_server.employee_runtime_policy import (
    load_policy,
    policy_for_employee,
    policy_path,
    record_employee_degradation,
    save_policy,
)


def test_runtime_policy_is_encrypted_and_owner_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))

    result = record_employee_degradation(
        employee_id="private-employee",
        fail_count=3,
        lookback_hours=24,
        reason="private customer task failed",
    )

    stored = policy_path().read_text(encoding="utf-8")
    envelope = json.loads(stored)
    assert result["ok"] is True
    assert envelope["schema"] == "xcagi.employee_runtime_policy.encrypted/v1"
    assert "private-employee" not in stored
    assert "private customer task" not in stored
    assert policy_path().stat().st_mode & 0o777 == 0o600
    assert policy_for_employee("private-employee")["reason"] == "private customer task failed"


def test_runtime_policy_save_fails_closed_without_master_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("MODSTORE_LLM_MASTER_KEY", raising=False)

    with pytest.raises(RuntimeError, match="MODSTORE_LLM_MASTER_KEY not configured"):
        save_policy({"employees": {"private-employee": {"reason": "private"}}})

    assert not policy_path().exists()


def test_runtime_policy_rejects_legacy_cleartext(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    policy_path().parent.mkdir(parents=True, exist_ok=True)
    policy_path().write_text(
        json.dumps({"employees": {"private-employee": {"reason": "private"}}}),
        encoding="utf-8",
    )

    assert load_policy() == {"employees": {}, "schema_version": 1}
