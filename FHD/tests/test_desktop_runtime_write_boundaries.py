"""Regression tests: packaged desktop state never writes below _MEIPASS."""

from __future__ import annotations

import sys
from pathlib import Path

from app.fastapi_routes import service_bridge, state, upload
from app.infrastructure.templates import template_store_impl
from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore


def test_service_bridge_identity_defaults_to_user_data(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    monkeypatch.setattr(service_bridge, "_INSTANCE_ID_FILE", None)
    monkeypatch.setattr(service_bridge, "get_app_data_dir", lambda: str(runtime))

    value = service_bridge._get_or_create_instance_id()
    target = runtime / "config" / "service_bridge" / ".service_bridge_instance_id"

    assert value.startswith("xcagi-host-")
    assert target.read_text(encoding="utf-8") == value


def test_temp_upload_default_path_is_under_user_data(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    monkeypatch.setattr(upload, "UPLOAD_FOLDER", None)
    monkeypatch.setattr(upload, "get_app_data_dir", lambda: str(runtime))

    upload._ensure_upload_folder()

    assert upload._upload_folder() == str(runtime / "uploads" / "temp")
    assert (runtime / "uploads" / "temp").is_dir()


def test_client_state_defaults_to_user_data(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    monkeypatch.setattr(state, "STATE_FILE", None)
    monkeypatch.setattr(state, "get_app_data_dir", lambda: str(runtime))

    state.write_client_mods_off_state(True)

    target = runtime / "config" / "client_mods_state.json"
    assert target.is_file()
    assert state.read_client_mods_off_state() is True


def test_template_store_redirects_packaged_writes_to_user_data(tmp_path, monkeypatch) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "source.xlsx").write_bytes(b"PK source")
    runtime = tmp_path / "userData"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(template_store_impl, "get_app_data_dir", lambda: str(runtime))

    store = FileSystemTemplateStore(str(bundle))
    result = store.save_template_file("source.xlsx", "saved.xlsx", overwrite=True)

    assert result["success"] is True
    assert (runtime / "templates" / "saved.xlsx").read_bytes() == b"PK source"
    assert not (bundle / "saved.xlsx").exists()


def test_default_template_store_factories_use_user_data(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "userData"
    monkeypatch.setattr("app.utils.path_utils.get_app_data_dir", lambda: str(runtime))

    from app.application import shipment_template_resolve
    from app.di.registry import ServiceContainer

    registry_store = ServiceContainer().template_application_service._template_service
    assert registry_store._base_dir == str(runtime)

    class _EmptyTemplateService:
        _template_service = None

    monkeypatch.setattr("app.bootstrap.get_template_app_service", lambda: _EmptyTemplateService())
    fallback_store = shipment_template_resolve._get_template_store()
    assert fallback_store._base_dir == str(runtime)
