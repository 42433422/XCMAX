from __future__ import annotations

from scripts.ensure_llm_master_key import KEY_NAME, ensure_key


def test_ensure_key_fills_empty_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(f"FOO=bar\n{KEY_NAME}=\n", encoding="utf-8")

    changed = ensure_key(env_path)
    text = env_path.read_text(encoding="utf-8")

    assert changed is True
    assert f"{KEY_NAME}=" in text
    value = next(
        line.split("=", 1)[1] for line in text.splitlines() if line.startswith(f"{KEY_NAME}=")
    )
    assert len(value) == 44


def test_ensure_key_preserves_existing_value(tmp_path):
    env_path = tmp_path / ".env"
    existing = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    env_path.write_text(f"{KEY_NAME}={existing}\n", encoding="utf-8")

    changed = ensure_key(env_path)

    assert changed is False
    assert env_path.read_text(encoding="utf-8") == f"{KEY_NAME}={existing}\n"


def test_ensure_key_rejects_invalid_existing_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(f"{KEY_NAME}=not-a-fernet-key\n", encoding="utf-8")

    try:
        ensure_key(env_path)
    except ValueError as exc:
        assert "不是有效 Fernet 密钥" in str(exc)
    else:
        raise AssertionError("invalid existing keys should not be overwritten")
