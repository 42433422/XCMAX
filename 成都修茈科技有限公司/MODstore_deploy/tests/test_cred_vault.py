"""凭据统一托管第一版：审计记录、短期授权过期失效、日志/工单不含凭据值。"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time

import pytest

from modstore_server import cred_vault as cv


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CREDENTIAL_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.delenv("MODSTORE_CREDENTIAL_BACKENDS", raising=False)
    monkeypatch.delenv("MODSTORE_CREDENTIAL_FILE_DIR", raising=False)
    cv._REVOKED_TASKS.clear()
    yield
    cv._REVOKED_TASKS.clear()


def _audit_rows():
    path = cv.audit_log_path()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_get_credential_writes_audit_without_value(monkeypatch):
    value = "v-" + secrets.token_hex(16)
    monkeypatch.setenv("XCMAX_TEST_API_KEY", value)
    got = cv.get_credential("XCMAX_TEST_API_KEY", task_id="t-1", purpose="unit", actor="pytest")
    assert got == value
    raw = cv.audit_log_path().read_text(encoding="utf-8")
    assert value not in raw
    row = _audit_rows()[-1]
    assert row["event"] == "access" and row["outcome"] == "hit"
    assert row["credential"] == "XCMAX_TEST_API_KEY"
    assert row["task_id"] == "t-1" and row["purpose"] == "unit" and row["actor"] == "pytest"
    assert row["backend"] == "env" and row["ts"].endswith("Z")


def test_alias_and_miss_are_audited(monkeypatch):
    monkeypatch.delenv("XCMAX_PRIMARY_TOKEN", raising=False)
    monkeypatch.setenv("XCMAX_ALIAS_TOKEN", "a-" + secrets.token_hex(8))
    assert cv.get_credential(
        "XCMAX_PRIMARY_TOKEN", task_id="t", purpose="p", aliases=("XCMAX_ALIAS_TOKEN",)
    )
    assert _audit_rows()[-1]["resolved"] == "XCMAX_ALIAS_TOKEN"
    monkeypatch.delenv("XCMAX_ALIAS_TOKEN")
    assert cv.get_credential("XCMAX_PRIMARY_TOKEN", task_id="t", purpose="p") is None
    assert _audit_rows()[-1]["outcome"] == "miss"
    with pytest.raises(cv.CredentialError):
        cv.get_credential("XCMAX_PRIMARY_TOKEN", task_id="t", purpose="p", required=True)


def test_task_id_and_purpose_required():
    with pytest.raises(ValueError):
        cv.get_credential("XCMAX_X_TOKEN", task_id="", purpose="p")
    with pytest.raises(ValueError):
        cv.get_credential("XCMAX_X_TOKEN", task_id="t", purpose="")


def test_file_backend_requires_0600(tmp_path, monkeypatch):
    value = "f-" + secrets.token_hex(12)
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secret_file = secret_dir / "XCMAX_FILE_TOKEN"
    secret_file.write_text(value + "\n", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_CREDENTIAL_FILE_DIR", str(secret_dir))
    if os.name == "posix":
        secret_file.chmod(0o644)
        with pytest.raises(cv.CredentialError):
            cv.get_credential("XCMAX_FILE_TOKEN", task_id="t", purpose="p")
    secret_file.chmod(0o600)
    assert cv.get_credential("XCMAX_FILE_TOKEN", task_id="t", purpose="p") == value
    assert _audit_rows()[-1]["backend"] == "file"


def test_reserved_backend_fails_loudly(monkeypatch):
    monkeypatch.setenv("MODSTORE_CREDENTIAL_BACKENDS", "vault,env")
    with pytest.raises(cv.CredentialError, match="尚未实现"):
        cv.get_credential("XCMAX_ANY_TOKEN", task_id="t", purpose="p")


def test_grant_scope_expiry_and_revocation(monkeypatch):
    value = "g-" + secrets.token_hex(12)
    monkeypatch.setenv("OPENAI_API_KEY", value)
    grant = cv.issue_task_grant("task-9", ["OPENAI_API_KEY"], purpose="unit", ttl_seconds=120)
    assert cv.get_credential("OPENAI_API_KEY", task_id="task-9", purpose="p", grant=grant) == value
    with pytest.raises(cv.CredentialError, match="out_of_scope"):
        cv.get_credential("XCMAX_OTHER_TOKEN", task_id="task-9", purpose="p", grant=grant)
    assert grant.denial_reason("OPENAI_API_KEY", now=time.time() + 121) == "expired"
    assert cv.verify_grant_token(grant.token()).grant_id == grant.grant_id
    with pytest.raises(cv.CredentialError, match="expired"):
        cv.verify_grant_token(grant.token(), now=time.time() + 121)
    cv.revoke_task_grants("task-9", reason="task_finished")
    with pytest.raises(cv.CredentialError, match="revoked"):
        cv.get_credential("OPENAI_API_KEY", task_id="task-9", purpose="p", grant=grant)
    events = [row["event"] for row in _audit_rows()]
    assert "grant_issue" in events and "grant_revoke" in events
    assert value not in cv.audit_log_path().read_text(encoding="utf-8")


def test_tampered_grant_token_rejected():
    grant = cv.issue_task_grant("task-x", ["OPENAI_API_KEY"], purpose="unit")
    body, sig = grant.token().rsplit(".", 1)
    with pytest.raises(cv.CredentialError):
        cv.verify_grant_token(body + "." + ("0" * len(sig)))


def test_prompt_line_carries_no_secret(monkeypatch):
    value = "p-" + secrets.token_hex(12)
    monkeypatch.setenv("OPENAI_API_KEY", value)
    grant = cv.issue_task_grant("task-p", ["OPENAI_API_KEY"], purpose="unit")
    line = grant.prompt_line()
    assert line.startswith(cv.GRANT_PROMPT_KEY + "=")
    assert value not in line and grant.signature not in line
    assert json.loads(line.split("=", 1)[1])["scopes"] == ["OPENAI_API_KEY"]


def test_redact_known_env_and_shapes(monkeypatch):
    env_value = "e-" + secrets.token_hex(12)
    monkeypatch.setenv("XCMAX_SAMPLE_PASSWORD", env_value)
    text = f"login with {env_value} and Authorization: Bearer abc.def"
    out = cv.redact(text)
    assert env_value not in out and "abc.def" not in out
    assert cv.REDACTED in out


def test_log_records_are_redacted(monkeypatch, caplog):
    value = "l-" + secrets.token_hex(12)
    monkeypatch.setenv("XCMAX_LOG_TOKEN", value)
    original = logging.getLogRecordFactory()
    try:
        assert cv.install_log_redaction() is True
        assert cv.install_log_redaction() is False
        with caplog.at_level(logging.INFO):
            logging.getLogger("credential.test").info("dispatch using %s", value)
        assert value not in caplog.text
        assert cv.REDACTED in caplog.text
    finally:
        logging.setLogRecordFactory(original)


def test_ticket_digest_redact_text_hides_loaded_credentials(monkeypatch):
    from modstore_server.incident_team_handler_digest import redact_text

    value = "d-" + secrets.token_hex(12)
    monkeypatch.setenv("XCMAX_DIGEST_API_KEY", value)
    cv.get_credential("XCMAX_DIGEST_API_KEY", task_id="t", purpose="p")
    monkeypatch.delenv("XCMAX_DIGEST_API_KEY")
    assert value not in redact_text(f"executor failed with {value}")


def test_para_dispatch_attaches_grant_reference(monkeypatch):
    from modstore_server import para_delegate_handler_part04 as part04

    monkeypatch.setenv("MODSTORE_CREDENTIAL_GRANT_SCOPES", "OPENAI_API_KEY")
    prompt, grant = part04._attach_credential_grant("fix it", "para-task-1")
    assert grant is not None and grant.task_id == "para-task-1"
    assert prompt.startswith("fix it\n" + cv.GRANT_PROMPT_KEY + "=")
    monkeypatch.setenv("MODSTORE_CREDENTIAL_TASK_GRANTS", "0")
    assert part04._attach_credential_grant("fix it", "para-task-2") == ("fix it", None)
