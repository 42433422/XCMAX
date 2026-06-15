"""COVERAGE_RAMP Phase 4 round 31: mod_manager load_mod branches, wechat delete,
normal_chat label print failure."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.infrastructure.mods.mod_manager as mm
from app.infrastructure.mods.mod_manager import ModManager, _default_mods_root


def _make_mod(root: Path, mod_id: str, extra: dict | None = None) -> Path:
    mod_dir = root / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    data = {"id": mod_id, "name": mod_id.title(), "version": "1.0.0"}
    if extra:
        data.update(extra)
    (mod_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return mod_dir


@pytest.fixture
def isolated_mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DISABLE_MODS", raising=False)
    monkeypatch.setattr(mm, "_repo_layout_mods_candidates", lambda: [])
    manager = ModManager(mods_root=str(tmp_path))
    return manager, tmp_path


# ---------------------------------------------------------------------------
# mod_manager
# ---------------------------------------------------------------------------


def test_default_mods_root_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
    assert _default_mods_root() == str(tmp_path.resolve())


def test_load_mod_missing_directory(isolated_mods) -> None:
    manager, _root = isolated_mods
    with patch.object(mm, "get_mod_registry", return_value=MagicMock(get_mod_metadata=MagicMock(return_value=None))):
        assert manager.load_mod("ghost-mod") is False


def test_load_mod_sku_policy_blocked(isolated_mods) -> None:
    manager, root = isolated_mods
    _make_mod(root, "blocked")
    with (
        patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("SKU policy"),
        ),
        patch.object(mm, "get_mod_registry", return_value=MagicMock(get_mod_metadata=MagicMock(return_value=None))),
    ):
        assert manager.load_mod("blocked") is False
    assert manager.get_recent_load_failures()[0]["stage"] == "sku_policy"


def test_load_mod_already_in_registry_syncs_loaded_list(isolated_mods) -> None:
    manager, _root = isolated_mods
    fake_meta = MagicMock()
    fake_reg = MagicMock()
    fake_reg.get_mod_metadata.return_value = fake_meta
    manager._loaded_mods = []
    with patch.object(mm, "get_mod_registry", return_value=fake_reg):
        assert manager.load_mod("alpha") is True
        assert "alpha" in manager._loaded_mods


def test_load_mod_bundle_metadata_only(isolated_mods) -> None:
    manager, root = isolated_mods
    from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE

    _make_mod(root, "bundle-mod", extra={"artifact": ARTIFACT_BUNDLE})
    fake_reg = MagicMock()
    fake_reg.get_mod_metadata.return_value = None
    fake_reg.register_mod.return_value = True
    with patch.object(mm, "get_mod_registry", return_value=fake_reg):
        assert manager.load_mod("bundle-mod") is True
    fake_reg.register_mod.assert_called_once()


# ---------------------------------------------------------------------------
# wechat — delete contact
# ---------------------------------------------------------------------------


def test_wechat_contact_delete_api() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_svc = MagicMock()
    mock_svc.delete_contact.return_value = {"success": True}
    with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
        out = wechat_routes.wechat_contact_delete_api(7)
    assert out.status_code == 200


# ---------------------------------------------------------------------------
# normal_chat — label print service failure
# ---------------------------------------------------------------------------


@patch("app.application.print_app_service.get_print_application_service")
def test_build_label_print_response_print_failed(mock_get: MagicMock) -> None:
    from app.application.normal_chat_dispatch import (
        build_label_print_response_dict,
        route_normal_mode_message,
    )

    mock_get.return_value.print_single_label.return_value = {
        "success": False,
        "message": "printer offline",
    }
    rr = route_normal_mode_message("贴标 ABCDEF 2张")
    body = build_label_print_response_dict(rr)
    assert body is not None
    assert "失败" in body["response"] or "printer" in body["response"]


# ---------------------------------------------------------------------------
# session_account_meta — enrich admin short-circuit
# ---------------------------------------------------------------------------


@patch("app.application.session_account_meta.load_session_account_meta")
def test_enrich_session_meta_admin_skips_tenant(mock_load: MagicMock) -> None:
    from app.application.session_account_meta import enrich_session_meta_with_tenant

    mock_load.return_value = {"account_kind": "admin", "market_is_admin": True}
    meta = enrich_session_meta_with_tenant("sid", SimpleNamespace(id=1))
    assert meta.get("account_kind") == "admin"
    assert "tenant_id" not in meta or meta.get("tenant_id") is None
