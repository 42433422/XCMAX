"""The neutral source API uses the shared archive, quota and recovery protocol."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.etl import archive_store, service_history, service_uploads
from app.application.etl.archive_policy import ArchivePolicyError
from app.application.etl.errors import EtlError
from app.application.etl.service import EtlService
from app.application.etl.service_support import MAX_FILE_BYTES
from app.db.db_base import Base
from app.db.models import Product, PurchaseUnit
from app.db.models.etl import EtlRun, EtlUpload
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveQuota, EtlArchiveVersion
from app.infrastructure.tenant_scope import TenantScopeError, tenant_scope

RAW = "部门,姓名,未知符号\n甲,同名员工,√ 2\n".encode()


@pytest.mark.parametrize("source_first", [True, False])
def test_source_and_legacy_service_imports_work_in_a_fresh_process(source_first):
    imports = [
        "from app.application.elt.sources import SourceAssetServiceMixin",
        "from app.application.etl import EtlService, get_etl_service",
    ]
    if not source_first:
        imports.reverse()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join([*imports, "assert isinstance(get_etl_service(), EtlService)"]),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sources.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for tenant in (1, 2):
            db.add(
                EtlArchiveQuota(tenant_id=tenant, limit_bytes=MAX_FILE_BYTES * 2, reserved_bytes=0)
            )
        db.commit()
    for module in (service_uploads, service_history):
        monkeypatch.setattr(module, "get_app_data_dir", lambda: str(tmp_path))
    from app.application.etl import archive_store
    from app.utils.path_io import path_utils

    archive_root = tmp_path / "business-archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(tmp_path))
    monkeypatch.setattr(path_utils, "get_business_archive_dir", lambda **_: str(archive_root))
    monkeypatch.setattr(archive_store, "get_business_archive_dir", lambda **_: str(archive_root))
    monkeypatch.setattr(archive_store, "default_archive_root", lambda: archive_root)
    yield SimpleNamespace(engine=engine, factory=factory, root=archive_root, service=EtlService())
    engine.dispose()


def publish(store, *, source=None, key=None, expected=1, owner=7, body=RAW, stream=None):
    with store.factory() as db:
        method = store.service.append_source_revision if source else store.service.create_source
        arguments = {"asset_id": source["id"], "expected_version": expected} if source else {}
        return method(
            db,
            owner_user_id=owner,
            file_name="资料.csv",
            content_type="text/csv",
            stream=stream if stream is not None else BytesIO(body),
            request_key=key or uuid4().hex,
            **arguments,
        )


def content(store, db, source):
    return store.service.get_source_content(
        db, asset_id=source["id"], revision_id=source["revision"]["id"], owner_user_id=7
    )[0]


def test_neutral_archive_lifecycle_survives_restart_without_importing_business_data(store):
    source = publish(store)
    second = publish(store, source=source)
    assert second["id"] == source["id"] and second["current_version"] == 2
    assert source["revision"]["sha256"] == second["revision"]["sha256"]
    assert source["revision"]["id"] != second["revision"]["id"]
    store.engine.dispose()
    with store.factory() as db:
        restarted = EtlService()
        assert restarted.get_source(db, asset_id=source["id"], owner_user_id=7) == second
        versions = restarted.list_source_revisions(db, asset_id=source["id"], owner_user_id=7)
        assert [item["version"] for item in versions] == [1, 2]
        assert all(
            item["status"] == "ready" and item["file_name"] == "资料.csv" for item in versions
        )
        assert db.get(EtlArchiveAsset, source["id"]).retention_mode == "manual"
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == len(RAW) * 2
        assert all(
            db.query(model).count() == 0 for model in (EtlUpload, EtlRun, PurchaseUnit, Product)
        )


def test_request_identity_is_idempotent_but_identical_content_is_not_an_asset_identity(store):
    source = publish(store, key="create")
    assert publish(store, key="create") == source
    other = publish(store, key="another")
    assert other["id"] != source["id"]
    second = publish(store, source=source, key="append")
    assert publish(store, source=source, key="append", expected=1)["revision"] == second["revision"]
    for arguments in ({"key": "create"}, {"source": source, "key": "append"}):
        with pytest.raises(EtlError) as error:
            publish(store, body=b"different", **arguments)
        assert error.value.code == "ETL_SOURCE_ARCHIVE_CONFLICT"
    with store.factory() as db:
        assert db.query(EtlArchiveAsset).count() == 2 and db.query(EtlArchiveVersion).count() == 3
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == len(RAW) * 3


@pytest.mark.parametrize("tenant,owner", [(1, 8), (2, 7)])
@pytest.mark.parametrize("operation", ["get", "list", "revision", "content", "append"])
def test_source_operations_never_cross_tenant_or_owner(store, tenant, owner, operation):
    source = publish(store)
    with tenant_scope(tenant), store.factory() as db, pytest.raises(EtlError) as error:
        arguments = {"asset_id": source["id"], "owner_user_id": owner}
        if operation in {"revision", "content"}:
            arguments["revision_id"] = source["revision"]["id"]
        if operation == "append":
            publish(store, source=source, owner=owner)
        else:
            method = {
                "get": "get_source",
                "list": "list_source_revisions",
                "revision": "get_source_revision",
                "content": "get_source_content",
            }[operation]
            getattr(store.service, method)(db, **arguments)
    assert error.value.status_code == 404


def test_revision_cannot_be_read_through_a_different_asset(store):
    first, second = publish(store), publish(store)
    with store.factory() as db, pytest.raises(EtlError) as error:
        store.service.get_source_revision(
            db, asset_id=first["id"], revision_id=second["revision"]["id"], owner_user_id=7
        )
    assert error.value.status_code == 404


@pytest.mark.parametrize("tenant,limit", [(3, None), (1, 1)])
def test_archive_admission_requires_configured_available_quota(store, tenant, limit):
    with tenant_scope(tenant), store.factory() as db:
        if limit is not None:
            db.get(EtlArchiveQuota, tenant).limit_bytes = limit
            db.commit()
        with pytest.raises(EtlError) as error:
            publish(store)
        assert error.value.code == "ETL_SOURCE_ARCHIVE_CONFLICT"
        assert db.query(EtlArchiveAsset).count() == 0
        assert db.query(EtlArchiveVersion).count() == 0
        if limit is not None:
            assert db.get(EtlArchiveQuota, tenant).reserved_bytes == 0
    assert not list(store.root.rglob("*"))


def test_legacy_upload_ttl_cleanup_never_deletes_shared_archive_originals(store):
    source = publish(store)
    with store.factory() as db:
        legacy = store.service.save_upload(
            db,
            owner_user_id=7,
            file_name="temporary.csv",
            content_type="text/csv",
            stream=BytesIO(RAW),
        )
        upload = db.get(EtlUpload, legacy["upload_id"])
        expires = upload.expires_at.replace(tzinfo=UTC)
        assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
        upload.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
        assert store.service.cleanup_retention(db, owner_user_id=7)["removed_upload_files"] == 1
        with content(store, db, source) as snapshot:
            assert snapshot.read() == RAW
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == len(RAW)


def test_concurrent_expected_version_allows_only_one_new_archive_version(store):
    source, barrier = publish(store), Barrier(2)

    def synchronize(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE etl_archive_assets SET"):
            barrier.wait(timeout=10)

    def append(body):
        with tenant_scope(1):
            try:
                return publish(store, source=source, body=body)
            except EtlError as error:
                return error

    event.listen(store.engine, "before_cursor_execute", synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(append, [b"first", b"second"]))
    finally:
        event.remove(store.engine, "before_cursor_execute", synchronize)
    successes = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, EtlError)]
    assert len(successes) == len(failures) == 1
    assert failures[0].code == "ETL_SOURCE_VERSION_CONFLICT"
    with store.factory() as db:
        assert db.query(EtlArchiveVersion).count() == 2
        assert (
            db.get(EtlArchiveQuota, 1).reserved_bytes
            == len(RAW) + successes[0]["revision"]["size_bytes"]
        )


@pytest.mark.parametrize("change", ["in_place", "replace"])
def test_download_snapshot_is_stable_after_original_changes(store, change):
    source = publish(store)
    with store.factory() as db, content(store, db, source) as snapshot:
        original = Path(db.get(EtlArchiveVersion, source["revision"]["id"]).storage_path)
        if change == "in_place":
            original.write_bytes(b"changed")
        else:
            replacement = original.with_suffix(".replacement")
            replacement.write_bytes(b"changed")
            replacement.replace(original)
        assert snapshot.read() == RAW


@pytest.mark.parametrize("damage", ["hash", "missing", "symlink", "withdrawn"])
def test_archive_integrity_and_withdrawal_are_enforced_by_source_download(store, damage):
    source = publish(store)
    with store.factory() as db:
        original = Path(db.get(EtlArchiveVersion, source["revision"]["id"]).storage_path)
        if damage == "hash":
            original.write_bytes(b"x" * len(RAW))
        elif damage == "withdrawn":
            db.get(EtlArchiveAsset, source["id"]).state = "trashed"
            db.commit()
        else:
            original.unlink()
            if damage == "symlink":
                outside = store.root.parent / "unrelated"
                outside.write_bytes(RAW)
                original.symlink_to(outside)
        with pytest.raises(EtlError) as error:
            content(store, db, source)
        assert error.value.status_code == (404 if damage == "withdrawn" else 409)


@pytest.mark.parametrize("append", [False, True])
def test_failed_publication_keeps_recoverable_pending_archive_and_reserved_quota(
    store, monkeypatch, append
):
    source = publish(store) if append else None

    def fail_write(*_args, **_kwargs):
        raise OSError("unacknowledged archive write")

    with monkeypatch.context() as patch:
        patch.setattr(archive_store, "_write_pending", fail_write)
        with pytest.raises(OSError):
            publish(store, source=source, key="pending")
    with store.factory() as db:
        version = db.query(EtlArchiveVersion).filter_by(request_key="pending").one()
        pending = store.service.get_source(db, asset_id=version.asset_id, owner_user_id=7)
        assert pending["revision"]["status"] == "pending"
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == len(RAW) * (2 if append else 1)
        with pytest.raises(EtlError):
            content(store, db, pending)
        with pytest.raises(ArchivePolicyError):
            archive_store.recover_complete_pending(
                db, owner=7, version_id=version.id, root=store.root
            )
        original = Path(version.storage_path)
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(RAW)
        archive_store.recover_complete_pending(db, owner=7, version_id=version.id, root=store.root)
        assert publish(store, source=source, key="pending")["revision"]["id"] == version.id


def test_sources_read_the_same_asset_created_by_the_existing_archive_entrypoint(store):
    with store.factory() as db:
        version = archive_store.create_original(
            db, owner=7, name="existing.csv", body=RAW, root=store.root, request_key="existing"
        )
        source = store.service.get_source(db, asset_id=version.asset_id, owner_user_id=7)
        assert source["revision"]["id"] == version.id
        assert db.query(EtlArchiveAsset).count() == db.query(EtlArchiveVersion).count() == 1
        with content(store, db, source) as snapshot:
            assert snapshot.read() == RAW


def test_missing_tenant_cannot_create_an_archive_source(store):
    with tenant_scope(None), pytest.raises(TenantScopeError):
        publish(store)


@pytest.mark.parametrize("body", [b"12345678", b"123456789"])
def test_short_reads_are_complete_and_oversize_admission_does_not_reserve_quota(
    store, monkeypatch, body
):
    from app.application.elt import sources

    class ShortRead(BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 3))

    monkeypatch.setattr(sources, "MAX_FILE_BYTES", 8)
    with store.factory() as db:
        if len(body) == 8:
            source = publish(store, stream=ShortRead(body))
            with content(store, db, source) as snapshot:
                assert snapshot.read() == body
            assert db.get(EtlArchiveQuota, 1).reserved_bytes == 8
        else:
            with pytest.raises(EtlError) as error:
                publish(store, stream=ShortRead(body))
            assert error.value.code == "ETL_FILE_TOO_LARGE" and error.value.status_code == 413
            assert db.get(EtlArchiveQuota, 1).reserved_bytes == 0
            assert db.query(EtlArchiveAsset).count() == db.query(EtlArchiveVersion).count() == 0
