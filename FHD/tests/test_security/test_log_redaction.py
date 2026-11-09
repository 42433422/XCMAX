"""Log redaction for support bundle export."""

from __future__ import annotations

from app.security.log_redaction import redact_log_text


def test_redact_bearer_and_phone():
    raw = "Authorization: Bearer secret-token-abc phone 13800138000"
    out = redact_log_text(raw)
    assert "secret-token" not in out
    assert "13800138000" not in out
    assert "<redacted>" in out or "<redacted-phone>" in out


def test_redact_private_key_variants_and_adjacent_text():
    for label in (
        "PRIVATE KEY",
        "RSA PRIVATE KEY",
        "EC PRIVATE KEY",
        "OPENSSH PRIVATE KEY",
        "ENCRYPTED PRIVATE KEY",
    ):
        block = f"-----BEGIN {label}-----\nfixture\n-----END {label}-----"
        assert redact_log_text(f"before {block} after") == "before <redacted-private-key> after"
        assert (
            redact_log_text(block + " gap " + block)
            == "<redacted-private-key> gap <redacted-private-key>"
        )


def test_redact_empty_and_unterminated_private_keys():
    assert redact_log_text("") == ""
    assert redact_log_text("ordinary message") == "ordinary message"
    assert (
        redact_log_text("-----BEGIN PRIVATE KEY----------END PRIVATE KEY-----")
        == "<redacted-private-key>"
    )
    assert (
        redact_log_text("prefix -----BEGIN PRIVATE KEY-----fixture")
        == "prefix <redacted-private-key>"
    )


def test_repeated_unterminated_private_keys_finish_without_backtracking():
    import subprocess
    import sys
    from pathlib import Path

    # A subprocess bounds regression failure time: the old regex takes quadratic time.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.security.log_redaction import redact_log_text; "
            "assert redact_log_text('-----BEGIN PRIVATE KEY-----' * 100000) == '<redacted-private-key>'",
        ],
        cwd=Path(__file__).resolve().parents[2],
        timeout=5,
        check=True,
        capture_output=True,
    )
