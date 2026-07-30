"""Regression coverage for desktop-only writable roots outside app resources."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from app import traditional_mode_fs as traditional
from app.services import wechat_contact_cache_import as wechat_cache


def test_wechat_sync_writes_raw_and_decrypted_databases_to_user_data(tmp_path, monkeypatch) -> None:
    tool_dir = tmp_path / "bundled-wechat-decrypt"
    tool_dir.mkdir()
    (tool_dir / "config.py").write_text("# bundled tool", encoding="utf-8")
    source_dir = tmp_path / "source" / "message"
    source_dir.mkdir(parents=True)
    (source_dir / "message_0.db").write_bytes(b"encrypted database")
    keys_file = tool_dir / "all_keys.json"
    keys_file.write_text(json.dumps({"keys": []}), encoding="utf-8")
    runtime = tmp_path / "userData"

    config_module = ModuleType("config")
    config_module.load_config = lambda: {
        "db_dir": str(source_dir.parent),
        "keys_file": str(keys_file),
        # Must be ignored as a writable cache target because it is bundled.
        "decrypted_dir": str(tool_dir / "decrypted"),
    }
    key_utils_module = ModuleType("key_utils")
    key_utils_module.strip_key_metadata = lambda value: value
    key_utils_module.get_key_info = lambda _keys, rel: {
        "enc_key": "00" * 32
    } if rel == "message/message_0.db" else None
    decrypt_module = ModuleType("decrypt_db")

    def _decrypt(raw_path: str, decrypted_path: str, _key: bytes) -> bool:
        Path(decrypted_path).write_bytes(Path(raw_path).read_bytes())
        return True

    decrypt_module.decrypt_database = _decrypt
    monkeypatch.setattr(wechat_cache, "get_desktop_state_dir", lambda: str(runtime))
    monkeypatch.setattr(wechat_cache, "_resolve_wechat_decrypt_dir", lambda: str(tool_dir))

    with patch.dict(
        sys.modules,
        {
            "config": config_module,
            "key_utils": key_utils_module,
            "decrypt_db": decrypt_module,
        },
    ):
        result = wechat_cache.ensure_decrypted_wechat_dbs()

    cache_root = runtime / "integrations" / "wechat" / "decrypt"
    assert result["success"] is True
    assert (cache_root / "raw_db" / "message" / "message_0.db").is_file()
    assert (cache_root / "decrypted" / "message" / "message_0.db").is_file()
    assert not (tool_dir / "raw_db").exists()
    assert not (tool_dir / "decrypted").exists()


def test_wechat_contact_refresh_prefers_user_data_decrypted_cache(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    contact_db = runtime / "integrations" / "wechat" / "decrypt" / "decrypted" / "contact" / "contact.db"
    contact_db.parent.mkdir(parents=True)
    with sqlite3.connect(contact_db) as conn:
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, "
            "is_in_chat_room TEXT, delete_flag INTEGER)"
        )
        conn.execute("INSERT INTO contact VALUES ('wxid_cache', '缓存联系人', '', '0', 0)")

    db = MagicMock()
    db.query.return_value.all.return_value = []
    db.bind = MagicMock()
    db.bind.dialect.name = "sqlite"
    monkeypatch.setattr(wechat_cache, "get_desktop_state_dir", lambda: str(runtime))
    monkeypatch.setattr(wechat_cache, "ensure_decrypted_wechat_dbs", lambda: {"success": True})
    monkeypatch.setattr(wechat_cache, "_resolve_wechat_decrypt_dir", lambda: str(tmp_path / "tool"))

    with patch.object(wechat_cache, "get_db") as get_db:
        get_db.return_value.__enter__ = MagicMock(return_value=db)
        get_db.return_value.__exit__ = MagicMock(return_value=False)
        payload, status = wechat_cache.refresh_wechat_contacts_from_decrypt()

    assert status == 200
    assert payload["imported"] == 1


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("XCAGI_DATA_DIR", "relative-user-data"),
        ("XCAGI_DESKTOP_DATA_DIR", "relative-user-data"),
        # The path helper does not strip environment values either. Treat a
        # whitespace-padded absolute-looking value as unsafe before it can
        # become a relative cwd write.
        ("XCAGI_DATA_DIR", " /safe-looking-but-relative"),
        ("XCAGI_DESKTOP_DATA_DIR", " /safe-looking-but-relative"),
    ],
)
def test_wechat_runtime_cache_rejects_relative_user_data_before_mkdir(
    monkeypatch, env_name: str, value: str
) -> None:
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.setenv(env_name, value)
    monkeypatch.setattr(
        wechat_cache,
        "get_desktop_state_dir",
        lambda: (_ for _ in ()).throw(AssertionError("must not mkdir a relative data root")),
    )

    with pytest.raises(OSError, match="must be absolute"):
        wechat_cache._wechat_runtime_cache_root()


def test_traditional_workspace_defaults_to_desktop_user_data(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    monkeypatch.delenv("TRADITIONAL_MODE_ROOT", raising=False)
    monkeypatch.setattr(traditional, "get_desktop_state_dir", lambda: str(runtime))

    root = traditional._resolve_root_dir()

    assert root == str(runtime / "traditional_workspace")
    assert Path(root).is_dir()


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("XCAGI_DATA_DIR", "relative-user-data"),
        ("XCAGI_DESKTOP_DATA_DIR", "relative-user-data"),
        ("XCAGI_DATA_DIR", " /safe-looking-but-relative"),
        ("XCAGI_DESKTOP_DATA_DIR", " /safe-looking-but-relative"),
    ],
)
def test_traditional_workspace_rejects_relative_user_data_before_mkdir(
    monkeypatch, env_name: str, value: str
) -> None:
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.setenv(env_name, value)
    monkeypatch.setattr(
        traditional,
        "get_desktop_state_dir",
        lambda: (_ for _ in ()).throw(AssertionError("must not mkdir a relative data root")),
    )

    with pytest.raises(OSError, match="must be absolute"):
        traditional._default_root_dir()


def test_traditional_workspace_rejects_app_bundle_override(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    bundle = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(traditional, "get_desktop_state_dir", lambda: str(runtime))
    monkeypatch.setattr(traditional.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("TRADITIONAL_MODE_ROOT", str(bundle / "mutable"))

    root = traditional._resolve_root_dir()

    assert root == str(runtime / "traditional_workspace")
    assert not (bundle / "mutable").exists()


def test_traditional_workspace_rejects_electron_resource_override(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    bundled_backend = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend"
    bundled_backend.mkdir(parents=True)
    monkeypatch.setattr(traditional, "get_desktop_state_dir", lambda: str(runtime))
    monkeypatch.setattr(traditional, "get_base_dir", lambda: str(bundled_backend))
    monkeypatch.delenv("TRADITIONAL_MODE_ROOT", raising=False)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("TRADITIONAL_MODE_ROOT", str(bundled_backend / "mutable"))

    root = traditional._resolve_root_dir()

    assert root == str(runtime / "traditional_workspace")
    assert not (bundled_backend / "mutable").exists()


def test_traditional_workspace_honors_explicit_external_override(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    override = tmp_path / "approved-external-workspace"
    monkeypatch.setattr(traditional, "get_desktop_state_dir", lambda: str(runtime))
    monkeypatch.setenv("TRADITIONAL_MODE_ROOT", str(override))

    root = traditional._resolve_root_dir()

    assert root == str(override.resolve())
    assert Path(root).is_dir()
