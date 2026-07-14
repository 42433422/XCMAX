"""桌面打包版的运行数据必须远离已签名/只读的应用资源目录。"""

from __future__ import annotations

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
