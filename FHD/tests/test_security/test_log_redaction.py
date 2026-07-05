"""Log redaction for support bundle export."""

from __future__ import annotations

from app.security.log_redaction import redact_log_text


def test_redact_bearer_and_phone():
    raw = "Authorization: Bearer secret-token-abc phone 13800138000"
    out = redact_log_text(raw)
    assert "secret-token" not in out
    assert "13800138000" not in out
    assert "<redacted>" in out or "<redacted-phone>" in out
