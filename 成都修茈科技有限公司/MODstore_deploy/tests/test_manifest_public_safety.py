from __future__ import annotations

import json

import pytest

from modman.manifest_util import (
    get_public_workflow_rows,
    public_workflow_rows_field,
    read_manifest,
    save_manifest_validated,
    set_public_workflow_rows,
    write_manifest,
)


def _manifest() -> dict:
    return {
        "id": "public-mod",
        "name": "公开模块",
        "version": "1.0.0",
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {"routes": "frontend/routes.js"},
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("config", "api_key"), "private-value"),
        (("connector", "client-secret"), "private-value"),
        (("metadata", "note"), "Bearer abcdefghijklmnopqrstuvwxyz"),
        (
            ("metadata", "note"),
            "-----BEGIN " + "PRIVATE KEY-----\nprivate-value\n-----END " + "PRIVATE KEY-----",
        ),
    ],
)
def test_public_manifest_rejects_credentials(tmp_path, path, value) -> None:
    manifest = _manifest()
    container = manifest
    for key in path[:-1]:
        container = container.setdefault(key, {})
    container[path[-1]] = value
    mod_dir = tmp_path / manifest["id"]
    mod_dir.mkdir()

    with pytest.raises(ValueError, match="公共元数据"):
        write_manifest(mod_dir, manifest)

    assert not (mod_dir / "manifest.json").exists()


def test_public_manifest_round_trips_display_metadata_without_credentials(
    tmp_path,
) -> None:
    manifest = _manifest()
    manifest["workflow_employees"] = [
        {
            "id": "invoice_helper",
            "label": "发票助手",
            "panel_title": "发票处理",
            "panel_summary": "仅保存可公开展示的职责说明。",
        }
    ]
    mod_dir = tmp_path / manifest["id"]
    mod_dir.mkdir()

    warnings = save_manifest_validated(mod_dir, manifest)
    saved, error = read_manifest(mod_dir)

    assert error is None
    assert warnings == []
    assert saved == manifest
    assert json.loads((mod_dir / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_public_workflow_field_helper_preserves_legacy_schema() -> None:
    manifest = _manifest()
    rows = [{"id": "invoice_helper", "label": "发票助手"}]

    set_public_workflow_rows(manifest, rows)

    assert public_workflow_rows_field() == "workflow_employees"
    assert get_public_workflow_rows(manifest) == rows


def test_public_workflow_rows_still_reject_nested_credentials(tmp_path) -> None:
    manifest = _manifest()
    set_public_workflow_rows(
        manifest,
        [{"id": "invoice_helper", "label": "发票助手", "api_key": "not-public"}],
    )
    mod_dir = tmp_path / manifest["id"]
    mod_dir.mkdir()

    with pytest.raises(ValueError, match="公共元数据"):
        write_manifest(mod_dir, manifest)
