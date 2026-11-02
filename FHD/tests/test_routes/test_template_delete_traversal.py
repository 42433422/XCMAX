"""Synthetic filesystem deletion contracts: tenant ownership, references and paths."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.infrastructure.tenant_scope import tenant_scope
from app.legacy.routes import document_templates_compat as compat


@pytest.fixture
def files(tmp_path, monkeypatch):
    base, runtime = tmp_path / "install", tmp_path / "runtime"
    base.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'templates.db'}")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE templates (id INTEGER PRIMARY KEY, tenant_id INTEGER, "
                "original_file_path TEXT, is_active INTEGER, updated_at TEXT)"
            )
        )
    monkeypatch.setattr(compat, "get_app_data_dir", lambda: str(runtime), raising=False)
    monkeypatch.setattr("app.db.session.get_db", sessionmaker(bind=engine))
    monkeypatch.setattr("app.db.init_db.init_template_tables", lambda: None)
    monkeypatch.setattr(
        "app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column", lambda: None
    )
    try:
        with tenant_scope(11):
            yield base, runtime, engine
    finally:
        engine.dispose()


def _file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic template")
    return path


def _delete(base, template_id="fs:sample.xlsx", expected=403):
    data, code = compat.run_archive_template_delete({"id": template_id}, base_dir=str(base))
    assert code == expected, data
    assert data["success"] is (expected == 200)
    return data


@pytest.mark.parametrize("folder", ["", "templates", "resources/templates"])
@pytest.mark.parametrize("collision", [False, True])
def test_builtin_is_never_deleted(files, folder, collision):
    base, runtime, _engine = files
    builtin = _file(base / folder / "sample.xlsx")
    private = _file(runtime / "tenants/11/templates/sample.xlsx") if collision else None
    _delete(base)
    assert builtin.read_bytes() == b"synthetic template"
    assert private is None or private.exists()


@pytest.mark.parametrize("folder", ["templates", "document_templates"])
def test_unique_tenant_file_deleted_without_touching_same_name_in_other_tenant(files, folder):
    base, runtime, _engine = files
    own = _file(runtime / "tenants/11" / folder / "sample.xlsx")
    other = _file(runtime / "tenants/22" / folder / "sample.xlsx")
    data = _delete(base, expected=200)
    assert data["deleted"]["id"] == "fs:sample.xlsx"
    assert not own.exists() and other.exists()
    _delete(base, expected=404)
    assert other.read_bytes() == b"synthetic template"


@pytest.mark.parametrize("name,status", [(" sample.xlsx", 200), ("sample.xlsx ", 400)])
def test_filename_whitespace_never_aliases_another_file(files, name, status):
    base, runtime, _engine = files
    normal = _file(runtime / "tenants/11/templates/sample.xlsx")
    requested = _file(normal.parent / name)
    data = _delete(base, f"fs:{name}", expected=status)
    assert normal.read_bytes() == b"synthetic template"
    assert requested.exists() is (status != 200)
    if status == 200:
        assert data["deleted"]["id"] == f"fs:{name}"


def test_same_name_in_both_tenant_directories_is_ambiguous(files):
    base, runtime, _engine = files
    targets = [
        _file(runtime / "tenants/11" / folder / "sample.xlsx")
        for folder in ("templates", "document_templates")
    ]
    _delete(base, expected=409)
    assert all(path.exists() for path in targets)


@pytest.mark.parametrize("tenant,active", [(11, 1), (11, 0), (22, 1), (22, 0)])
def test_referenced_file_retained_including_inactive_or_other_tenant_record(files, tenant, active):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    with engine.begin() as db:
        db.execute(
            text("INSERT INTO templates VALUES (1, :tenant, :path, :active, NULL)"),
            {"tenant": tenant, "path": str(target), "active": active},
        )
    _delete(base, expected=409)
    assert target.read_bytes() == b"synthetic template"


def test_missing_tenant_cannot_delete(files):
    base, runtime, _engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    with tenant_scope(None):
        _delete(base)
    assert target.exists()


def test_unknown_id_does_not_resolve_another_tenants_file(files):
    base, runtime, _engine = files
    other = _file(runtime / "tenants/22/templates/sample.xlsx")
    _delete(base, expected=404)
    assert other.exists()


def test_reference_query_failure_retains_file(files):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    with engine.begin() as db:
        db.execute(text("DROP TABLE templates"))
    _delete(base, expected=503)
    assert target.read_bytes() == b"synthetic template"


def test_filesystem_failure_never_reports_success(files, monkeypatch):
    base, runtime, _engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")

    def denied(_path):
        raise PermissionError("synthetic refusal")

    monkeypatch.setattr(compat.os, "remove", denied)
    _delete(base, expected=503)
    assert target.read_bytes() == b"synthetic template"


@pytest.mark.parametrize(
    "name",
    [
        "/sample.xlsx",
        "../sample.xlsx",
        "a/sample.xlsx",
        r"a\sample.xlsx",
        "..",
        "",
        "C:sample.xlsx",
        "sample\0.xlsx",
        "sample.txt",
    ],
)
def test_path_traversal_is_rejected_without_changes(files, name):
    base, runtime, _engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    _delete(base, f"fs:{name}", expected=400)
    assert target.read_bytes() == b"synthetic template"


@pytest.mark.parametrize("kind", ["file", "parent"])
def test_symlink_file_or_parent_is_rejected(files, kind):
    base, runtime, _engine = files
    outside = _file(runtime / "outside/sample.xlsx")
    folder = runtime / "tenants/11/templates"
    folder.parent.mkdir(parents=True)
    try:
        if kind == "parent":
            folder.symlink_to(outside.parent, target_is_directory=True)
        else:
            folder.mkdir()
            (folder / outside.name).symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    _delete(base)
    assert (folder / outside.name).is_file()
    assert outside.read_bytes() == b"synthetic template"
