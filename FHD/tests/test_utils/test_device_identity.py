from __future__ import annotations

import app.utils.device_identity as device_identity


def _reset_cache() -> None:
    device_identity._cached = None


def test_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DEVICE_ID", "fixed-device")
    _reset_cache()

    assert device_identity.get_stable_device_id() == "fixed-device"


def test_device_id_persists_across_cache_reset(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_DEVICE_ID", raising=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    _reset_cache()

    first = device_identity.get_stable_device_id()
    assert first
    assert (tmp_path / "device_id").read_text(encoding="utf-8").strip() == first

    _reset_cache()
    assert device_identity.get_stable_device_id() == first


def test_device_id_never_empty_when_unwritable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_DEVICE_ID", raising=False)
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setattr(device_identity, "get_app_data_dir", lambda: str(not_a_dir))
    _reset_cache()

    assert device_identity.get_stable_device_id()
