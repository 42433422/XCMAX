"""员工包运行时加载顺序。"""

from __future__ import annotations

from pathlib import Path


def test_load_employee_pack_prefers_catalog_row_over_duty_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    from modstore_server import models
    from modstore_server.catalog_store import append_package
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    from modstore_server.employee_runtime import load_employee_pack
    from modstore_server.models import CatalogItem

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    manifest = {
        "id": "duty-pack",
        "name": "新版编制员工",
        "version": "2.0.0",
        "artifact": "employee_pack",
        "scope": "global",
        "employee": {"id": "duty-pack", "label": "新版编制员工", "capabilities": []},
        "employee_config_v2": {
            "actions": {"handlers": ["agent"]},
        },
    }
    archive = build_employee_pack_zip("duty-pack", manifest)
    tmp_archive = Path(tmp_path / "duty-pack.xcemp")
    tmp_archive.write_bytes(archive)
    saved = append_package(
        {
            "id": "duty-pack",
            "name": "新版编制员工",
            "version": "2.0.0",
            "artifact": "employee_pack",
        },
        tmp_archive,
    )

    monkeypatch.setattr(
        "modstore_server.employee_runtime.is_planned_duty_employee_pack",
        lambda pkg_id, artifact: pkg_id == "duty-pack" and artifact == "employee_pack",
    )
    monkeypatch.setattr(
        "modstore_server.employee_runtime.get_duty_employee_record",
        lambda _pkg_id: {
            "id": "duty-pack",
            "name": "旧版编制员工",
            "version": "1.0.0",
            "stored_filename": "duty-pack-1.0.0.xcemp",
        },
    )

    session_factory = models.get_session_factory()
    with session_factory() as db:
        db.add(
            CatalogItem(
                pkg_id="duty-pack",
                version="2.0.0",
                name="新版编制员工",
                artifact="employee_pack",
                stored_filename=str(saved["stored_filename"]),
            )
        )
        db.commit()

        pack = load_employee_pack(db, "duty-pack")

    actions = pack["manifest"]["employee_config_v2"]["actions"]
    assert pack["version"] == "2.0.0"
    assert pack["stored_filename"] == saved["stored_filename"]
    assert actions["handlers"] == ["agent"]
