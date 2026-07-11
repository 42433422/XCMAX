from __future__ import annotations

import os


def test_local_runtime_secret_reads_private_snapshot(tmp_path, monkeypatch):
    from app.security.local_runtime_secret import local_runtime_secret

    snapshot = tmp_path / "runtime.env"
    snapshot.write_text(
        "XCAGI_MARKET_INTERNAL_API_KEY='shared-key'\nOTHER_SECRET='ignored'\n",
        encoding="utf-8",
    )
    snapshot.chmod(0o600)
    monkeypatch.setenv("MODSTORE_DAILY_ENV_SNAPSHOT", str(snapshot))
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    assert local_runtime_secret("XCAGI_MARKET_INTERNAL_API_KEY") == "shared-key"
    assert local_runtime_secret("OTHER_SECRET") == ""


def test_local_runtime_secret_rejects_world_readable_snapshot(tmp_path, monkeypatch):
    from app.security.local_runtime_secret import local_runtime_secret

    snapshot = tmp_path / "runtime.env"
    snapshot.write_text("XCAGI_MARKET_INTERNAL_API_KEY='leaked'\n", encoding="utf-8")
    snapshot.chmod(0o644)
    monkeypatch.setenv("MODSTORE_DAILY_ENV_SNAPSHOT", str(snapshot))
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    assert local_runtime_secret("XCAGI_MARKET_INTERNAL_API_KEY") == ""


def test_environment_takes_precedence_over_snapshot(tmp_path, monkeypatch):
    from app.security.local_runtime_secret import local_runtime_secret

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "from-env")
    monkeypatch.setenv("MODSTORE_DAILY_ENV_SNAPSHOT", str(tmp_path / "missing"))
    assert local_runtime_secret("XCAGI_MARKET_INTERNAL_API_KEY") == "from-env"
