# -*- coding: utf-8 -*-
"""employee_pack 安装后热加载路由与 registry。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import app.infrastructure.mods.mod_manager  # force real module load before stub injection
import app.infrastructure.mods.employee_registry  # force real module load before stub injection
import app.mod_sdk.employee_runtime  # force real module load before stub injection


def _minimal_pack(parent: Path, pack_id: str) -> Path:
    pack_dir = parent / "_employees" / pack_id
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "name": "Test Employee",
                "artifact": "employee_pack",
                "scope": "global",
                "backend": {"entry": "blueprints"},
            }
        ),
        encoding="utf-8",
    )
    backend = pack_dir / "backend"
    backend.mkdir()
    (backend / "blueprints.py").write_text(
        """def register_fastapi_routes(app, pack_id):
    @app.get(f"/api/test-employee/{pack_id}/ping")
    def _ping():
        return {"ok": True, "pack_id": pack_id}
""",
        encoding="utf-8",
    )
    return pack_dir


@pytest.fixture()
def employee_mods_root(tmp_path, monkeypatch):
    mods_root = tmp_path / "mods"
    mods_root.mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(mods_root))
    from app.infrastructure.mods import employee_registry as er
    from app.infrastructure.mods import mod_manager as mm

    er._registry.clear()
    mm._mod_manager = None
    mm._employee_pack_routes_registered.clear()
    return mods_root


def test_refresh_after_install_registers_routes(employee_mods_root, monkeypatch):
    pack_id = "csv-full-read-employee"
    _minimal_pack(employee_mods_root, pack_id)

    app = MagicMock()
    monkeypatch.setattr("app.fastapi_app.get_fastapi_app", lambda: app)

    from app.infrastructure.mods import mod_manager as mm

    mm._employee_pack_routes_registered.clear()

    from app.mod_sdk.employee_runtime import refresh_employee_pack_runtime

    refresh_employee_pack_runtime(pack_id)
    assert pack_id in mm._employee_pack_routes_registered


def test_register_employee_pack_routes_skips_duplicate(employee_mods_root, monkeypatch):
    pack_id = "csv-full-read-employee"
    _minimal_pack(employee_mods_root, pack_id)
    app = MagicMock()
    monkeypatch.setattr("app.fastapi_app.get_fastapi_app", lambda: app)

    from app.infrastructure.mods import mod_manager as mm
    from app.infrastructure.mods.mod_manager import get_mod_manager, register_employee_pack_routes

    mm._employee_pack_routes_registered.clear()
    assert register_employee_pack_routes(app, get_mod_manager(), pack_id) is True
    assert register_employee_pack_routes(app, get_mod_manager(), pack_id) is True
    assert app.mock_calls  # route registrar invoked at least once
