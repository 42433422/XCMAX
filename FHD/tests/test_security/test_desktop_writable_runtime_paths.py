"""桌面打包版的运行数据必须远离已签名/只读的应用资源目录。"""

from __future__ import annotations

import pytest

from app.security import lan_config, lan_settings_store
from XCAGI import run_fastapi


def test_runtime_port_file_uses_desktop_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)

    assert run_fastapi._runtime_port_file() == tmp_path / ".runtime" / "api.port"

    run_fastapi._persist_runtime_port(17500)
    assert (tmp_path / ".runtime" / "api.port").read_text(encoding="utf-8") == "17500"


def test_lan_license_db_uses_desktop_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.delenv("LAN_LICENSE_DB_PATH", raising=False)
    lan_config.reset_lan_config_cache()

    try:
        cfg = lan_config.get_lan_config()
        assert cfg.license_db_path == tmp_path / "data" / "lan_license.db"
        assert cfg.license_db_path.parent.is_dir()
    finally:
        lan_config.reset_lan_config_cache()


def test_lan_settings_use_desktop_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.delenv("LAN_SETTINGS_FILE", raising=False)

    assert lan_settings_store._settings_path() == tmp_path / "data" / "lan_settings.json"


@pytest.mark.parametrize("custom_directory", [False, True])
def test_memory_json_and_lock_stay_outside_packaged_resources(
    monkeypatch, tmp_path, custom_directory
):
    from app.desktop_runtime.desktop_runtime_paths import configure_desktop_environment
    from app.services import user_memory_service as memory

    for name in ("XCAGI_USER_MEMORY_DIR", "XCAGI_USER_MEMORY_JSON_PATH"):
        monkeypatch.delenv(name, raising=False)
    packaged = tmp_path / "signed-app" / "user_memory"
    monkeypatch.setattr(memory, "MEMORY_DIR", str(packaged))
    monkeypatch.setattr(memory, "JSON_MEMORY_PATH", str(packaged / "memory_store.json"))
    monkeypatch.setattr(memory.UserMemoryStore, "_instance", None)
    profile = tmp_path / "profile"
    expected = tmp_path / "custom-memory" if custom_directory else profile / "user_memory"
    if custom_directory:
        monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(expected))
    configure_desktop_environment(profile)
    store = memory.UserMemoryStore()
    store.save_memory("desktop-test", store.get_memory("desktop-test"))
    assert (expected / "memory_store.json").is_file()
    assert (expected / "memory_store.json.lock").is_file()
    assert not packaged.exists()
