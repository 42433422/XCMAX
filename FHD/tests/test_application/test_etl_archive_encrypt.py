"""Business-archive Fernet landing: path root, encrypt roundtrip, request_key idempotency."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.elt import archive_store
from app.application.elt.archive_policy import ArchivePolicyError
from app.application.elt.archive_store import (
    _ENVELOPE_MAGIC,
    _KEY_FILE_NAME,
    create_original,
    default_archive_root,
    read_original,
)
from app.db.db_base import Base
from app.db.models.elt_archive import EltArchiveQuota
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.path_io import path_utils


@pytest.fixture
def archive_db(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    state = tmp_path / "XCAGI"
    state.mkdir()
    archive_root = state / "business-archive"
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(state))
    monkeypatch.setattr(path_utils, "get_business_archive_dir", lambda **_: str(archive_root))
    monkeypatch.setattr(archive_store, "get_business_archive_dir", lambda **_: str(archive_root))

    engine = create_engine(
        f"sqlite:///{tmp_path / 'archive.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with tenant_scope(1), factory() as db:
        db.add(EltArchiveQuota(tenant_id=1, limit_bytes=10_000_000, reserved_bytes=0))
        db.commit()
    yield factory, archive_root
    engine.dispose()


def test_default_archive_root_under_desktop_state_business_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(tmp_path / "state"))
    monkeypatch.setattr(
        path_utils,
        "get_business_archive_dir",
        lambda **_: str(tmp_path / "state" / "business-archive"),
    )
    monkeypatch.setattr(
        archive_store,
        "get_business_archive_dir",
        lambda **_: str(tmp_path / "state" / "business-archive"),
    )
    root = default_archive_root()
    assert root.name == "business-archive"
    assert root.parent == (tmp_path / "state").resolve() or root.parent.name == "state"
    assert "elt" not in root.parts or root.parts[-1] == "business-archive"
    assert root.as_posix().endswith("business-archive")


def test_encrypt_roundtrip_and_key_file(archive_db):
    factory, archive_root = archive_db
    body = b"name,qty\nwidget,3\n"
    request_key = uuid4().hex
    with tenant_scope(1), factory() as db:
        version = create_original(
            db,
            owner=7,
            name="sheet.csv",
            body=body,
            root=archive_root,
            request_key=request_key,
        )
        assert version.sha256 == hashlib.sha256(body).hexdigest()
        assert version.size_bytes == len(body)
        disk = Path(version.storage_path).read_bytes()
        assert disk.startswith(_ENVELOPE_MAGIC)
        assert body not in disk
        assert (archive_root / _KEY_FILE_NAME).is_file()
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body


def test_request_key_idempotent_reuses_encrypted_original(archive_db):
    factory, archive_root = archive_db
    body = b"a,b\n1,2\n"
    key = "same-request-key-001"
    with tenant_scope(1), factory() as db:
        first = create_original(
            db, owner=7, name="a.csv", body=body, root=archive_root, request_key=key
        )
        second = create_original(
            db, owner=7, name="a.csv", body=body, root=archive_root, request_key=key
        )
        assert first.id == second.id
        assert read_original(db, owner=7, version_id=first.id, root=archive_root) == body


def test_legacy_plaintext_migrates_on_read(archive_db):
    factory, archive_root = archive_db
    body = b"legacy-plain\n"
    key = uuid4().hex
    with tenant_scope(1), factory() as db:
        version = create_original(
            db, owner=7, name="legacy.csv", body=body, root=archive_root, request_key=key
        )
        path = Path(version.storage_path)
        # Simulate pre-encrypt disk layout.
        path.chmod(0o600)
        path.write_bytes(body)
        assert not path.read_bytes().startswith(_ENVELOPE_MAGIC)
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body
        assert path.read_bytes().startswith(_ENVELOPE_MAGIC)
        assert path.stat().st_mode & 0o222 == 0
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body


def test_get_business_archive_dir_uses_desktop_state(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(tmp_path / "AppDataXCAGI"))
    root = Path(path_utils.get_business_archive_dir())
    assert root == tmp_path / "AppDataXCAGI" / "business-archive"
    assert root.is_dir()


def test_maximum_plaintext_remains_readable_after_encryption_and_recovery(archive_db, monkeypatch):
    factory, archive_root = archive_db
    monkeypatch.setattr(archive_store, "MAX_FILE_BYTES", 16_384)
    body = b"x" * archive_store.MAX_FILE_BYTES
    with tenant_scope(1), factory() as db:
        version = create_original(
            db, owner=7, name="large.csv", body=body, root=archive_root, request_key="large"
        )
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body
        assert (
            create_original(
                db, owner=7, name="large.csv", body=body, root=archive_root, request_key="large"
            ).id
            == version.id
        )
        version.status = "pending"
        db.commit()
        archive_store.recover_complete_pending(
            db, owner=7, version_id=version.id, root=archive_root
        )
        assert version.status == "ready"
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body
        with pytest.raises(ArchivePolicyError, match="大小限制"):
            create_original(
                db,
                owner=7,
                name="oversize.csv",
                body=body + b"x",
                root=archive_root,
                request_key="oversize",
            )


def test_concurrent_first_archive_encryptions_keep_one_durable_key(archive_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, Lock

    _factory, archive_root = archive_db
    barrier, generated_twice, guard = Barrier(2), Event(), Lock()
    original_generate = archive_store.secrets.token_urlsafe
    calls = []

    def stalled_generate(size):
        result = original_generate(size)
        with guard:
            calls.append(result)
            if len(calls) == 2:
                generated_twice.set()
        # Expose a competing first writer; a correctly serialized caller waits
        # outside key creation and reads the first complete key afterwards.
        generated_twice.wait(timeout=0.5)
        return result

    monkeypatch.setattr(archive_store.secrets, "token_urlsafe", stalled_generate)

    def encrypt(body):
        barrier.wait(timeout=5)
        return archive_store._encrypt_body(body, archive_root=archive_root)

    bodies = [b"first customer original", b"second customer original"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        payloads = list(pool.map(encrypt, bodies))
    cipher = archive_store._archive_cipher(archive_root)
    assert [cipher.decrypt(payload[len(_ENVELOPE_MAGIC) :]) for payload in payloads] == bodies
    assert len(calls) == 1


def test_existing_empty_archive_key_is_not_replaced(archive_db):
    factory, archive_root = archive_db
    archive_root.mkdir(parents=True)
    key_path = archive_root / _KEY_FILE_NAME
    key_path.write_text("", encoding="utf-8")
    with tenant_scope(1), factory() as db:
        with pytest.raises(ArchivePolicyError, match="密钥"):
            create_original(
                db,
                owner=7,
                name="original.csv",
                body=b"original",
                root=archive_root,
                request_key="empty-key",
            )
    assert key_path.read_bytes() == b""


def _archive_encrypt_process(root, body, start, results):
    start.wait(timeout=15)
    results.put((body, archive_store._encrypt_body(body, archive_root=Path(root))))


def test_separate_processes_share_the_durable_archive_key(archive_db):
    import multiprocessing
    import os

    _factory, root = archive_db
    context = multiprocessing.get_context("spawn")
    start, results = context.Barrier(3), context.Queue()
    processes = [
        context.Process(target=_archive_encrypt_process, args=(str(root), body, start, results))
        for body in (b"process-one-original", b"process-two-original")
    ]
    try:
        for process in processes:
            process.start()
        start.wait(timeout=15)
        payloads = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        cipher = archive_store._archive_cipher(root)
        assert all(
            cipher.decrypt(payload[len(_ENVELOPE_MAGIC) :]) == body for body, payload in payloads
        )
        if os.name == "posix":
            assert (root / _KEY_FILE_NAME).stat().st_mode & 0o077 == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
