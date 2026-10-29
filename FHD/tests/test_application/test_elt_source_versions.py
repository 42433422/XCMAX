"""Durable, neutral source versions on real SQLite and isolated file storage."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.application.etl import service_history, service_uploads
from app.application.etl.errors import EtlError
from app.application.etl.service import EtlService
from app.db.db_base import Base
from app.db.models import Product, PurchaseUnit
from app.db.models.etl import EltSourceAsset, EltSourceRevision, EtlRun, EtlUpload
from app.infrastructure.tenant_scope import TenantScopeError, tenant_scope

ORIGINAL = "部门,姓名,未知符号\n甲,同名员工,√ 2\n".encode()
CORRECTION = "部门,姓名,未知符号\n乙,同名员工,?\n".encode()


@pytest.fixture
def source_store(tmp_path, monkeypatch):
    database = tmp_path / "source-versions.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(service_uploads, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(service_history, "get_app_data_dir", lambda: str(tmp_path))
    store = SimpleNamespace(
        engine=engine,
        database=database,
        factory=sessionmaker(bind=engine),
        root=tmp_path,
        service=EtlService(),
    )
    try:
        yield store
    finally:
        engine.dispose()


def create_source(store, *, owner=7, content=ORIGINAL):
    with store.factory() as db:
        return store.service.create_source(
            db,
            owner_user_id=owner,
            file_name="未分类资料.csv",
            content_type="text/csv",
            stream=BytesIO(content),
        )


def append_source(store, source, *, expected=1, owner=7, content=CORRECTION):
    with store.factory() as db:
        return store.service.append_source_revision(
            db,
            asset_id=source["id"],
            expected_version=expected,
            owner_user_id=owner,
            file_name="补充资料.csv",
            content_type="text/csv",
            stream=BytesIO(content),
        )


def stored_files(store):
    return {path: path.read_bytes() for path in (store.root / "etl").rglob("*") if path.is_file()}


def counts(store):
    with store.factory() as db:
        return tuple(
            db.query(model).count() for model in (EltSourceAsset, EltSourceRevision, EtlUpload)
        )


def test_neutral_source_is_committed_and_can_be_read_after_restart(source_store):
    store = source_store
    with tenant_scope(1):
        source = create_source(store)
        assert source["name"] == "未分类资料.csv"
        assert source["current_version"] == 1
        revision = source["revision"]
        assert revision["asset_id"] == source["id"] and revision["version"] == 1
        assert revision["file_name"] == "未分类资料.csv"
        assert revision["suffix"] == ".csv"
        assert revision["size_bytes"] == len(ORIGINAL)
        assert revision["sha256"] == hashlib.sha256(ORIGINAL).hexdigest()
        assert revision["created_at"]
        with store.factory() as db:
            upload = db.get(EtlUpload, revision["upload_id"])
            assert upload.expires_at is None
            original_path = Path(upload.storage_path)
            assert original_path.read_bytes() == ORIGINAL
            assert db.query(EtlRun).count() == 0
            assert db.query(PurchaseUnit).count() == 0
            assert db.query(Product).count() == 0

    store.engine.dispose()
    restarted_engine = create_engine(f"sqlite:///{store.database}")
    try:
        with tenant_scope(1), sessionmaker(bind=restarted_engine)() as db:
            restarted = EtlService()
            assert restarted.get_source(db, asset_id=source["id"], owner_user_id=7) == source
            restored = restarted.get_source_revision(
                db, asset_id=source["id"], revision_id=revision["id"], owner_user_id=7
            )
            assert restored == revision
            assert original_path.read_bytes() == ORIGINAL
    finally:
        restarted_engine.dispose()


def test_append_keeps_original_and_identical_bytes_have_distinct_revision_identity(source_store):
    store = source_store
    with tenant_scope(1):
        source = create_source(store)
        second = append_source(store, source, content=ORIGINAL)
        assert second["id"] == source["id"]
        assert second["current_version"] == 2
        assert second["revision"]["version"] == 2
        assert second["revision"]["sha256"] == source["revision"]["sha256"]
        assert second["revision"]["id"] != source["revision"]["id"]
        assert second["revision"]["upload_id"] != source["revision"]["upload_id"]
        with store.factory() as db:
            revisions = store.service.list_source_revisions(
                db, asset_id=source["id"], owner_user_id=7
            )
            assert {item["version"] for item in revisions} == {1, 2}
            restored = store.service.get_source_revision(
                db, asset_id=source["id"], revision_id=source["revision"]["id"], owner_user_id=7
            )
            assert restored == source["revision"]
            uploads = db.query(EtlUpload).all()
            assert len(uploads) == 2 and all(item.expires_at is None for item in uploads)
            assert len({item.storage_path for item in uploads}) == 2
            assert all(Path(item.storage_path).read_bytes() == ORIGINAL for item in uploads)


def test_identical_uploads_are_separate_assets_in_each_owner_scope(source_store):
    store = source_store
    with tenant_scope(1):
        first = create_source(store)
        same_owner = create_source(store)
        other_owner = create_source(store, owner=8)
    with tenant_scope(2):
        other_tenant = create_source(store)
    sources = (first, same_owner, other_owner, other_tenant)
    assert len({item["id"] for item in sources}) == 4
    assert len({item["revision"]["upload_id"] for item in sources}) == 4
    assert {item["revision"]["sha256"] for item in sources} == {
        hashlib.sha256(ORIGINAL).hexdigest()
    }
    assert len(stored_files(store)) == 4


@pytest.mark.parametrize("tenant,owner", [(1, 8), (2, 7), (2, 8)])
@pytest.mark.parametrize("operation", ["get", "list", "revision", "content", "append"])
def test_source_access_checks_both_tenant_and_owner(source_store, tenant, owner, operation):
    store = source_store
    with tenant_scope(1):
        source = create_source(store)
    before = stored_files(store)
    with tenant_scope(tenant), store.factory() as db, pytest.raises(EtlError) as error:
        if operation == "get":
            store.service.get_source(db, asset_id=source["id"], owner_user_id=owner)
        elif operation == "list":
            store.service.list_source_revisions(db, asset_id=source["id"], owner_user_id=owner)
        elif operation == "revision":
            store.service.get_source_revision(
                db, asset_id=source["id"], revision_id=source["revision"]["id"], owner_user_id=owner
            )
        elif operation == "content":
            store.service.get_source_content(
                db, asset_id=source["id"], revision_id=source["revision"]["id"], owner_user_id=owner
            )
        else:
            store.service.append_source_revision(
                db,
                asset_id=source["id"],
                expected_version=1,
                owner_user_id=owner,
                file_name="无权追加.csv",
                content_type="text/csv",
                stream=BytesIO(CORRECTION),
            )
    assert error.value.status_code == 404
    assert stored_files(store) == before


def test_revision_lookup_cannot_mix_two_assets_owned_by_the_same_user(source_store):
    store = source_store
    with tenant_scope(1), store.factory() as db:
        first = create_source(store)
        second = create_source(store)
        with pytest.raises(EtlError) as error:
            store.service.get_source_revision(
                db, asset_id=first["id"], revision_id=second["revision"]["id"], owner_user_id=7
            )
        assert error.value.status_code == 404


def test_legacy_retention_removes_only_temporary_uploads(source_store):
    store = source_store
    with tenant_scope(1):
        source = create_source(store)
        with store.factory() as db:
            legacy = store.service.save_upload(
                db,
                owner_user_id=7,
                file_name="临时导入.csv",
                content_type="text/csv",
                stream=BytesIO(ORIGINAL),
            )
            upload = db.get(EtlUpload, legacy["upload_id"])
            expires = upload.expires_at.replace(tzinfo=UTC)
            assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
            temporary_path = Path(upload.storage_path)
            upload.expires_at = datetime.now(UTC) - timedelta(days=1)
            durable = db.get(EtlUpload, source["revision"]["upload_id"])
            durable.created_at = datetime.now(UTC) - timedelta(days=100)
            durable_path = Path(durable.storage_path)
            db.commit()
            result = store.service.cleanup_retention(db, owner_user_id=7)
            assert result["removed_upload_files"] == 1
            assert not temporary_path.exists()
            assert durable_path.read_bytes() == ORIGINAL
            assert store.service.get_source(db, asset_id=source["id"], owner_user_id=7) == source


def test_stale_expected_version_has_no_database_or_file_effect(source_store):
    store = source_store
    with tenant_scope(1):
        source = create_source(store)
        current = append_source(store, source)
        before_files, before_counts = stored_files(store), counts(store)
        with pytest.raises(EtlError) as error:
            append_source(store, source, expected=1, content=b"stale\nvalue\n")
        assert error.value.code == "ETL_SOURCE_VERSION_CONFLICT"
        assert error.value.status_code == 409
        assert stored_files(store) == before_files and counts(store) == before_counts
        with store.factory() as db:
            assert store.service.get_source(db, asset_id=source["id"], owner_user_id=7) == current


def test_concurrent_append_claims_one_version_without_leaking_the_losing_upload(source_store):
    store = source_store
    with tenant_scope(1):
        source = create_source(store)
    ready = Barrier(2)

    def synchronize_claim(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE elt_source_assets SET"):
            ready.wait(timeout=10)

    def append(content):
        with tenant_scope(1):
            try:
                return append_source(store, source, content=content)
            except EtlError as exc:
                return exc

    event.listen(store.engine, "before_cursor_execute", synchronize_claim)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(append, content) for content in (CORRECTION, b"key\nother\n")
            ]
            results = [future.result(timeout=15) for future in futures]
    finally:
        event.remove(store.engine, "before_cursor_execute", synchronize_claim)
    successes = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, EtlError)]
    assert len(successes) == len(failures) == 1
    assert failures[0].code == "ETL_SOURCE_VERSION_CONFLICT"
    assert failures[0].status_code == 409
    with tenant_scope(1), store.factory() as db:
        assert store.service.get_source(db, asset_id=source["id"], owner_user_id=7) == successes[0]
        revisions = store.service.list_source_revisions(db, asset_id=source["id"], owner_user_id=7)
        assert [item["version"] for item in revisions] == [1, 2]
        assert counts(store) == (1, 2, 2)
    assert len(stored_files(store)) == 2
    assert ORIGINAL in stored_files(store).values()


@pytest.mark.parametrize("change_after_read", [None, "in_place", "replace"])
def test_source_content_returns_a_verified_stable_snapshot(source_store, change_after_read):
    store = source_store
    with tenant_scope(1), store.factory() as db:
        source = create_source(store)
        content, name = store.service.get_source_content(
            db, asset_id=source["id"], revision_id=source["revision"]["id"], owner_user_id=7
        )
        assert name == "未分类资料.csv"
        with content:
            original = Path(db.get(EtlUpload, source["revision"]["upload_id"]).storage_path)
            if change_after_read == "in_place":
                original.write_bytes(CORRECTION)
            elif change_after_read == "replace":
                replacement = original.with_suffix(".replacement")
                replacement.write_bytes(CORRECTION)
                replacement.replace(original)
            assert content.read() == ORIGINAL


@pytest.mark.parametrize(
    "damage,code,status",
    [
        ("same_size", "ETL_SOURCE_CONTENT_CHANGED", 409),
        ("different_size", "ETL_SOURCE_CONTENT_CHANGED", 409),
        ("missing", "ETL_UPLOAD_MISSING", 410),
        ("escaped_path", "ETL_SOURCE_STORAGE_INVALID", 409),
        ("file_symlink", "ETL_SOURCE_STORAGE_INVALID", 409),
        ("parent_symlink", "ETL_SOURCE_STORAGE_INVALID", 409),
    ],
)
def test_source_content_rejects_missing_changed_or_redirected_originals(
    source_store, damage, code, status
):
    store = source_store
    with tenant_scope(1), store.factory() as db:
        source = create_source(store)
        upload = db.get(EtlUpload, source["revision"]["upload_id"])
        original = Path(upload.storage_path)
        if damage == "same_size":
            original.write_bytes(b"x" * len(ORIGINAL))
        elif damage == "different_size":
            original.write_bytes(ORIGINAL + b"extra")
        elif damage == "missing":
            original.unlink()
        elif damage in {"escaped_path", "file_symlink"}:
            outside = store.root / "unrelated.csv"
            outside.write_bytes(ORIGINAL)
            if damage == "escaped_path":
                upload.storage_path = str(outside)
                db.commit()
            else:
                original.unlink()
                original.symlink_to(outside)
        else:
            moved = store.root / "moved-owner"
            original.parent.rename(moved)
            original.parent.symlink_to(moved, target_is_directory=True)
        with pytest.raises(EtlError) as error:
            store.service.get_source_content(
                db, asset_id=source["id"], revision_id=source["revision"]["id"], owner_user_id=7
            )
        assert error.value.code == code and error.value.status_code == status


@pytest.mark.parametrize("operation", ["create", "append"])
@pytest.mark.parametrize(
    "failure_phase", ["upload", "insert", "commit", "lookup_sql", "lookup_runtime"]
)
def test_database_failure_rolls_back_rows_and_removes_only_new_file(
    source_store, monkeypatch, operation, failure_phase
):
    store = source_store
    with tenant_scope(1):
        source = create_source(store) if operation == "append" else None
        before_files, before_counts = stored_files(store), counts(store)
        error_type = IntegrityError
        if not failure_phase.startswith("lookup"):
            with store.engine.begin() as connection:
                if failure_phase == "commit":
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                    connection.exec_driver_sql(
                        "CREATE TABLE deferred_parent (id INTEGER PRIMARY KEY)"
                    )
                    connection.exec_driver_sql(
                        "CREATE TABLE deferred_child (parent_id INTEGER REFERENCES deferred_parent(id) "
                        "DEFERRABLE INITIALLY DEFERRED)"
                    )
                    trigger_body = "INSERT INTO deferred_child VALUES (999)"
                else:
                    trigger_body = "SELECT RAISE(ABORT, 'injected source revision constraint')"
                target = "etl_uploads" if failure_phase == "upload" else "elt_source_revisions"
                connection.execute(
                    text(
                        f"CREATE TRIGGER reject_source_revision BEFORE INSERT ON {target} "
                        f"BEGIN {trigger_body}; END"
                    )
                )
        else:
            error_type = OperationalError if failure_phase == "lookup_sql" else RuntimeError

        def reject_lookup(*_args):
            if failure_phase == "lookup_sql":
                raise OperationalError("SELECT upload", {}, RuntimeError("lookup unavailable"))
            raise RuntimeError("lookup unavailable")

        with monkeypatch.context() as patch, store.factory() as db:
            if failure_phase.startswith("lookup"):
                patch.setattr(store.service, "_source_upload", reject_lookup)
            method = store.service.append_source_revision if source else store.service.create_source
            arguments = {"asset_id": source["id"], "expected_version": 1} if source else {}
            with pytest.raises(error_type):
                method(
                    db,
                    owner_user_id=7,
                    file_name="失败来源.csv",
                    content_type="text/csv",
                    stream=BytesIO(CORRECTION),
                    **arguments,
                )
            assert db.is_active
            assert db.query(EltSourceRevision).count() == before_counts[1]
        assert stored_files(store) == before_files
        assert counts(store) == before_counts
        if source:
            with store.factory() as db:
                assert (
                    store.service.get_source(db, asset_id=source["id"], owner_user_id=7) == source
                )


def test_missing_tenant_cannot_create_a_source(source_store):
    store = source_store
    with tenant_scope(None), pytest.raises(TenantScopeError):
        create_source(store)
    assert counts(store) == (0, 0, 0)
    assert not stored_files(store)


@pytest.mark.parametrize("operation", ["create", "append"])
@pytest.mark.parametrize("failure", ["stream", "unsupported", "empty"])
def test_rejected_upload_rolls_back_publication_and_preserves_previous_version(
    source_store, operation, failure
):
    store = source_store

    class FailingStream(BytesIO):
        def read(self, _size=-1):
            if self.tell():
                raise OSError("stream interrupted after partial write")
            return super().read(4)

    with tenant_scope(1), store.factory() as db:
        source = create_source(store) if operation == "append" else None
        before_files, before_counts = stored_files(store), counts(store)
        stream = (
            FailingStream(ORIGINAL)
            if failure == "stream"
            else BytesIO(b"" if failure == "empty" else ORIGINAL)
        )
        method = store.service.append_source_revision if source else store.service.create_source
        arguments = {"asset_id": source["id"], "expected_version": 1} if source else {}
        with pytest.raises(OSError if failure == "stream" else EtlError):
            method(
                db,
                owner_user_id=7,
                file_name="invalid.exe" if failure == "unsupported" else "input.csv",
                content_type="text/csv",
                stream=stream,
                **arguments,
            )
        assert db.is_active
        assert stored_files(store) == before_files and counts(store) == before_counts
        if source:
            assert store.service.get_source(db, asset_id=source["id"], owner_user_id=7) == source


@pytest.mark.parametrize("operation", ["create", "append"])
def test_lost_commit_response_preserves_the_committed_revision_and_original(
    source_store, operation
):
    store = source_store

    class LostCommitResponse(Session):
        def commit(self):
            super().commit()
            raise OperationalError("COMMIT", {}, RuntimeError("commit response lost"))

    with tenant_scope(1):
        source = create_source(store) if operation == "append" else None
        store.factory = sessionmaker(bind=store.engine, class_=LostCommitResponse)
        with pytest.raises(OperationalError, match="commit response lost"):
            append_source(store, source) if source else create_source(store)
        store.factory = sessionmaker(bind=store.engine)
        with store.factory() as db:
            asset = db.query(EltSourceAsset).one()
            current = store.service.get_source(db, asset_id=asset.id, owner_user_id=7)
            assert current["current_version"] == (2 if source else 1)
            content, _name = store.service.get_source_content(
                db,
                asset_id=asset.id,
                revision_id=current["revision"]["id"],
                owner_user_id=7,
            )
            with content:
                assert content.read() == (CORRECTION if source else ORIGINAL)
            assert len(stored_files(store)) == current["current_version"]
