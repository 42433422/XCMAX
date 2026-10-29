from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.etl.archive_policy import ArchivePolicyError
from app.application.etl.archive_store import (
    create_original,
    read_original,
    recover_complete_pending,
)
from app.db.db_base import Base
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveQuota, EtlArchiveVersion
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[EtlArchiveQuota.__table__, EtlArchiveAsset.__table__,
                                             EtlArchiveVersion.__table__])
    with Session(engine, expire_on_commit=False) as db:
        with tenant_scope(1):
            db.add(EtlArchiveQuota(tenant_id=1, limit_bytes=10, reserved_bytes=0))
            db.commit()
        yield db, tmp_path
    engine.dispose()


def test_manual_archive_readback_quota_and_owner_isolation(store):
    db, root = store
    with tenant_scope(1):
        item = create_original(db, owner=3, name="报价.xlsx", body=b"original", root=root, request_key="one")
        assert item.status == "ready"
        assert db.get(EtlArchiveAsset, item.asset_id).retention_mode == "manual"
        assert read_original(db, owner=3, version_id=item.id, root=root) == b"original"
        assert create_original(db, owner=3, name="报价.xlsx", body=b"original", root=root, request_key="one").id == item.id
        with pytest.raises(ArchivePolicyError, match="不同文件"):
            create_original(db, owner=3, name="报价.xlsx", body=b"different", root=root, request_key="one")
        with pytest.raises(ArchivePolicyError, match="配额"):
            create_original(db, owner=3, name="x.xlsx", body=b"123", root=root, request_key="two")
        with pytest.raises(ArchivePolicyError, match="不存在"):
            read_original(db, owner=4, version_id=item.id, root=root)
        Path(item.storage_path).write_bytes(b"tampered")
        with pytest.raises(ArchivePolicyError, match="校验"):
            read_original(db, owner=3, version_id=item.id, root=root)
    with tenant_scope(2):
        with pytest.raises(ArchivePolicyError, match="不存在"):
            read_original(db, owner=3, version_id=item.id, root=root)


def test_missing_quota_never_creates_archive(store):
    db, root = store
    with tenant_scope(2), pytest.raises(ArchivePolicyError, match="尚未配置"):
        create_original(db, owner=3, name="x.xlsx", body=b"x", root=root, request_key="one")


def test_failed_write_stays_pending_and_reserved(store, monkeypatch):
    db, root = store
    def fail_open(*args, **kwargs):
        raise OSError("synthetic write failure")
    monkeypatch.setattr(Path, "open", fail_open)
    with tenant_scope(1):
        with pytest.raises(OSError, match="synthetic"):
            create_original(db, owner=3, name="x.xlsx", body=b"abcd", root=root, request_key="one")
        version = db.query(EtlArchiveVersion).one()
        assert version.status == "pending"
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == 4
        with pytest.raises(ArchivePolicyError, match="待核对"):
            create_original(db, owner=3, name="x.xlsx", body=b"abcd", root=root, request_key="one")
        with pytest.raises(ArchivePolicyError, match="尚不可用"):
            read_original(db, owner=3, version_id=version.id, root=root)
        with pytest.raises(ArchivePolicyError, match="不可用"):
            recover_complete_pending(db, owner=3, version_id=version.id, root=root)


def test_archive_rejects_symlinked_tenant_directory(store, tmp_path):
    db, root = store
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / '1').symlink_to(outside, target_is_directory=True)
    with tenant_scope(1):
        with pytest.raises(ArchivePolicyError, match='路径'):
            create_original(db, owner=3, name='x.xlsx', body=b'x', root=root, request_key='one')
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == 0
    assert not list(outside.iterdir())


def test_concurrent_admissions_cannot_exceed_quota(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine = create_engine(f"sqlite:///{tmp_path / 'quota.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine, tables=[EtlArchiveQuota.__table__, EtlArchiveAsset.__table__, EtlArchiveVersion.__table__])
    with Session(engine) as db, tenant_scope(1):
        db.add(EtlArchiveQuota(tenant_id=1, limit_bytes=7, reserved_bytes=0))
        db.commit()
    barrier = Barrier(2)
    def submit(key):
        with Session(engine) as db, tenant_scope(1):
            barrier.wait()
            try:
                create_original(db, owner=3, name='x.xlsx', body=b'abcd', root=tmp_path / 'objects', request_key=key)
                return 'ready'
            except ArchivePolicyError:
                return 'full'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, ['one', 'two'])) == ['full', 'ready']
    with Session(engine) as db, tenant_scope(1):
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == 4
    engine.dispose()
