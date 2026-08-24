from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from app.services.document_templates.storage import (
    get_document_template_upload_dir,
    migrate_legacy_template_uploads,
)


def test_upload_dir_uses_runtime_data_root(monkeypatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "Application Support" / "XCAGI"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(runtime_root))

    upload_dir = get_document_template_upload_dir()

    assert upload_dir == (runtime_root / "uploads" / "templates").resolve()
    assert upload_dir.is_dir()
    assert "app/services/uploads/templates" not in upload_dir.as_posix()


def test_migration_copies_and_updates_database_only_after_verification(tmp_path: Path) -> None:
    legacy_dir = (
        tmp_path
        / "XCAGI.app"
        / "Contents"
        / "Resources"
        / "backend"
        / "_internal"
        / "app"
        / "services"
        / "uploads"
        / "templates"
    )
    legacy_dir.mkdir(parents=True)
    source = legacy_dir / "abc123.xlsx"
    source.write_bytes(b"real-template-content")
    destination = tmp_path / "user-data" / "uploads" / "templates"

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE templates ("
                "id INTEGER PRIMARY KEY, original_file_path TEXT, updated_at TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO templates (id, original_file_path) VALUES (1, :path)"
            ),
            {"path": str(source)},
        )
        report = migrate_legacy_template_uploads(db=db, destination_dir=destination)
        stored_path = db.execute(
            text("SELECT original_file_path FROM templates WHERE id = 1")
        ).scalar_one()

    target = destination / source.name
    assert report["failed"] == []
    assert report["missing"] == []
    assert report["migrated"][0]["id"] == 1
    assert stored_path == str(target.resolve())
    assert target.read_bytes() == source.read_bytes()
    assert source.is_file(), "legacy source stays available for upgrade recovery"


def test_migration_reports_missing_legacy_file_without_rewriting_path(tmp_path: Path) -> None:
    missing = (
        tmp_path
        / "XCAGI.app"
        / "Contents"
        / "Resources"
        / "backend"
        / "_internal"
        / "app"
        / "services"
        / "uploads"
        / "templates"
        / "missing.xlsx"
    )
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE templates ("
                "id INTEGER PRIMARY KEY, original_file_path TEXT, updated_at TIMESTAMP)"
            )
        )
        db.execute(
            text("INSERT INTO templates (id, original_file_path) VALUES (2, :path)"),
            {"path": str(missing)},
        )
        report = migrate_legacy_template_uploads(
            db=db, destination_dir=tmp_path / "destination"
        )
        stored_path = db.execute(
            text("SELECT original_file_path FROM templates WHERE id = 2")
        ).scalar_one()

    assert report["migrated"] == []
    assert report["missing"] == [{"id": 2, "source": str(missing)}]
    assert stored_path == str(missing)
