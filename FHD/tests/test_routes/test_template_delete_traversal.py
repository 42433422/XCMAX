"""Synthetic filesystem deletion contracts: tenant ownership, references and paths."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, current_thread

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore
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
                "original_file_path TEXT, is_active INTEGER, updated_at TEXT, "
                "template_key TEXT, template_name TEXT, template_type TEXT, "
                "analyzed_data TEXT, editable_config TEXT, business_rules TEXT)"
            )
        )
    monkeypatch.setattr(compat, "get_app_data_dir", lambda: str(runtime), raising=False)
    monkeypatch.setattr(
        "app.infrastructure.templates.template_store_impl.get_app_data_dir", lambda: str(runtime)
    )
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


def _assert_hidden(base, path):
    store = FileSystemTemplateStore(str(base))
    found = store._discover_excel_templates() + store._discover_word_templates()
    assert str(path) not in {item["path"] for item in found}
    assert store.resolve_template_file(f"fs:{path.name}") is None


@pytest.mark.parametrize("folder", ["", "templates", "resources/templates"])
@pytest.mark.parametrize("collision", [False, True])
def test_builtin_is_never_deleted(files, folder, collision):
    base, runtime, engine = files
    builtin = _file(base / folder / "sample.xlsx")
    private = _file(runtime / "tenants/11/templates/sample.xlsx") if collision else None
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO templates (tenant_id, original_file_path, is_active) "
                "VALUES (11, :path, 0)"
            ),
            {"path": str(builtin)},
        )
    _delete(base)
    assert builtin.read_bytes() == b"synthetic template"
    assert private is None or private.exists()
    store = FileSystemTemplateStore(str(base))
    assert str(builtin) in {item["path"] for item in store._discover_excel_templates()}
    assert store.resolve_template_file("fs:sample.xlsx") == str(builtin)


@pytest.mark.parametrize("folder", ["templates", "document_templates"])
def test_unique_tenant_file_hidden_without_touching_same_name_in_other_tenant(files, folder):
    base, runtime, _engine = files
    own = _file(runtime / "tenants/11" / folder / "sample.xlsx")
    other = _file(runtime / "tenants/22" / folder / "sample.xlsx")
    data = _delete(base, expected=200)
    assert data["deleted"]["id"] == "fs:sample.xlsx"
    assert data["deleted"]["soft_deleted"] is True
    assert own.read_bytes() == b"synthetic template"
    _assert_hidden(base, own)
    repeated = _delete(base, expected=200)
    assert repeated["deleted"]["db_id"] == data["deleted"]["db_id"]
    with tenant_scope(22):
        store = FileSystemTemplateStore(str(base))
        assert str(other) in {item["path"] for item in store._discover_excel_templates()}
        assert store.resolve_template_file("fs:sample.xlsx") == str(other)
    assert other.read_bytes() == b"synthetic template"


@pytest.mark.parametrize("name,status", [(" sample.xlsx", 200), ("sample.xlsx ", 400)])
def test_filename_whitespace_never_aliases_another_file(files, name, status):
    base, runtime, _engine = files
    normal = _file(runtime / "tenants/11/templates/sample.xlsx")
    requested = _file(normal.parent / name)
    data = _delete(base, f"fs:{name}", expected=status)
    assert normal.read_bytes() == b"synthetic template"
    assert requested.read_bytes() == b"synthetic template"
    assert FileSystemTemplateStore(str(base)).resolve_template_file("fs:sample.xlsx") == str(normal)
    if status == 200:
        assert data["deleted"]["id"] == f"fs:{name}"
        _assert_hidden(base, requested)


def test_runtime_root_symlink_does_not_resurrect_removed_alias(files, monkeypatch):
    base, runtime, _engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    alias = runtime.with_name("runtime-alias")
    alias.symlink_to(runtime, target_is_directory=True)
    monkeypatch.setattr(compat, "get_app_data_dir", lambda: str(alias))
    monkeypatch.setattr(
        "app.infrastructure.templates.template_store_impl.get_app_data_dir", lambda: str(alias)
    )
    _delete(base, expected=200)
    assert target.read_bytes() == b"synthetic template"
    _assert_hidden(base, target)


def test_same_name_in_both_tenant_directories_is_ambiguous(files):
    base, runtime, _engine = files
    targets = [
        _file(runtime / "tenants/11" / folder / "sample.xlsx")
        for folder in ("templates", "document_templates")
    ]
    _delete(base, expected=409)
    assert all(path.exists() for path in targets)


def test_removed_copy_does_not_block_removing_later_visible_same_name(files):
    base, runtime, _engine = files
    old = _file(runtime / "tenants/11/templates/sample.xlsx")
    first = _delete(base, expected=200)
    new = _file(runtime / "tenants/11/document_templates/sample.xlsx")
    assert FileSystemTemplateStore(str(base)).resolve_template_file("fs:sample.xlsx") == str(new)
    second = _delete(base, expected=200)
    assert first["deleted"]["db_id"] != second["deleted"]["db_id"]
    assert second["deleted"]["path"] == str(new)
    _assert_hidden(base, old)
    repeated = _delete(base, expected=200)
    assert repeated["deleted"]["already_removed"] is True
    assert old.read_bytes() == new.read_bytes() == b"synthetic template"


def test_inactive_database_path_using_runtime_alias_stays_hidden(files, monkeypatch):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    alias = runtime.with_name("runtime-alias")
    alias.symlink_to(runtime, target_is_directory=True)
    monkeypatch.setattr(
        "app.infrastructure.templates.template_store_impl.get_app_data_dir", lambda: str(alias)
    )
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO templates (tenant_id, original_file_path, is_active) VALUES (11, :path, 0)"
            ),
            {"path": str(alias / target.relative_to(runtime))},
        )
    _assert_hidden(base, target)
    assert target.read_bytes() == b"synthetic template"


@pytest.mark.parametrize("tenant,active", [(11, 1), (11, 0), (22, 1), (22, 0)])
def test_referenced_file_retained_including_inactive_or_other_tenant_record(files, tenant, active):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO templates (id, tenant_id, original_file_path, is_active) "
                "VALUES (1, :tenant, :path, :active)"
            ),
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
    builtin = _file(base / "resources/templates/builtin.xlsx")
    with engine.begin() as db:
        db.execute(text("DROP TABLE templates"))
    _delete(base, expected=503)
    assert target.read_bytes() == b"synthetic template"
    _assert_hidden(base, target)
    store = FileSystemTemplateStore(str(base))
    assert str(builtin) in {item["path"] for item in store._discover_excel_templates()}
    assert store.resolve_template_file("fs:builtin.xlsx") == str(builtin)
    assert builtin.read_bytes() == b"synthetic template"


def test_commit_failure_rolls_back_visibility_and_retry_succeeds(files, monkeypatch):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")

    def denied(_session):
        raise RuntimeError("synthetic commit refusal")

    with monkeypatch.context() as failing:
        failing.setattr("sqlalchemy.orm.Session.commit", denied)
        _delete(base, expected=503)
    assert target.read_bytes() == b"synthetic template"
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 0
    store = FileSystemTemplateStore(str(base))
    assert str(target) in {item["path"] for item in store._discover_excel_templates()}
    assert store.resolve_template_file("fs:sample.xlsx") == str(target)
    _delete(base, expected=200)
    _assert_hidden(base, target)


def test_retained_asset_can_be_recovered_by_reactivating_persisted_marker(files):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    data = _delete(base, expected=200)
    marker_id = data["deleted"]["db_id"]
    _assert_hidden(base, target)
    with engine.begin() as db:
        db.execute(
            text("UPDATE templates SET is_active = 1 WHERE id = :id AND tenant_id = 11"),
            {"id": marker_id},
        )
    store = FileSystemTemplateStore(str(base))
    assert str(target) in {item["path"] for item in store._discover_excel_templates()}
    assert store.resolve_template_file("fs:sample.xlsx") == str(target)
    assert store.resolve_template_file(f"db:{marker_id}") == str(target)
    assert any(item["id"] == f"db:{marker_id}" for item in store.list_templates())
    assert target.read_bytes() == b"synthetic template"


def _thread_delete(base):
    with tenant_scope(11):
        return _delete(base, expected=200)


def _is_insert(statement):
    return " ".join(statement.upper().split()).startswith("INSERT INTO TEMPLATES")


def test_new_reference_between_lookup_and_marker_keeps_backing_file(files):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    inserting, reference_saved = Event(), Event()

    def pause_marker(_conn, _cursor, statement, _params, _context, _many):
        if current_thread().name.startswith("template-delete") and _is_insert(statement):
            inserting.set()
            assert reference_saved.wait(5), "reference writer did not finish"

    event.listen(engine, "before_cursor_execute", pause_marker)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="template-delete") as workers:
            deletion = workers.submit(_thread_delete, base)
            try:
                assert inserting.wait(5), "delete did not reach marker insertion"
                with engine.begin() as db:
                    reference = db.execute(
                        text(
                            "INSERT INTO templates (tenant_id, original_file_path, is_active, "
                            "template_key, template_name) VALUES (11, :path, 1, 'new_ref', 'Reference')"
                        ),
                        {"path": str(target)},
                    ).lastrowid
            finally:
                reference_saved.set()
            deletion.result(timeout=10)
    finally:
        event.remove(engine, "before_cursor_execute", pause_marker)
    assert target.read_bytes() == b"synthetic template"
    _assert_hidden(base, target)
    store = FileSystemTemplateStore(str(base))
    assert any(item["db_id"] == reference for item in store._db_templates())
    assert store.resolve_template_file(f"db:{reference}") == str(target)


def test_concurrent_duplicate_deletes_keep_bytes_and_hide_alias(files):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    both_ready = Barrier(2, timeout=5)

    def pause_marker(_conn, _cursor, statement, _params, _context, _many):
        if current_thread().name.startswith("template-delete") and _is_insert(statement):
            both_ready.wait()

    event.listen(engine, "before_cursor_execute", pause_marker)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="template-delete") as workers:
            deletions = [workers.submit(_thread_delete, base) for _ in range(2)]
            results = [deletion.result(timeout=10) for deletion in deletions]
    finally:
        event.remove(engine, "before_cursor_execute", pause_marker)
    assert all(result["deleted"]["soft_deleted"] for result in results)
    assert target.read_bytes() == b"synthetic template"
    _assert_hidden(base, target)
    with engine.connect() as db:
        rows = db.execute(text("SELECT tenant_id, is_active FROM templates")).all()
    assert rows and all(row.tenant_id == 11 and row.is_active == 0 for row in rows)


@pytest.mark.parametrize("phase", ["lookup", "insert"])
def test_parent_path_swap_before_marker_never_mutates_either_file(files, phase):
    base, runtime, engine = files
    target = _file(runtime / "tenants/11/templates/sample.xlsx")
    outside = _file(runtime / "outside/sample.xlsx")
    moved = target.parent.with_name("original-templates")
    swapped = False

    def swap_parent(_conn, _cursor, statement, _params, _context, _many):
        nonlocal swapped
        trigger = (
            _is_insert(statement)
            if phase == "insert"
            else " ".join(statement.upper().split()).startswith("SELECT ID, TENANT_ID")
        )
        if trigger and not swapped:
            target.parent.rename(moved)
            target.parent.symlink_to(outside.parent, target_is_directory=True)
            swapped = True

    event.listen(engine, "before_cursor_execute", swap_parent)
    try:
        deleted = _delete(base, expected=200)
    finally:
        event.remove(engine, "before_cursor_execute", swap_parent)
    assert swapped
    assert (moved / target.name).read_bytes() == b"synthetic template"
    assert outside.read_bytes() == b"synthetic template"
    with engine.connect() as db:
        row = db.execute(
            text("SELECT tenant_id, original_file_path, is_active FROM templates")
        ).one()
    assert (row.tenant_id, row.original_file_path, row.is_active) == (11, str(target), 0)
    target.parent.unlink()
    moved.rename(target.parent)
    assert _delete(base, expected=200)["deleted"]["db_id"] == deleted["deleted"]["db_id"]


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
