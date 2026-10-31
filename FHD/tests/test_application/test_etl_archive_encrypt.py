"""Business-archive Fernet landing: path root, encrypt roundtrip, request_key idempotency."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.etl import archive_store
from app.application.etl.archive_store import (
    _ENVELOPE_MAGIC,
    _KEY_FILE_NAME,
    create_original,
    default_archive_root,
    read_original,
)
from app.db.db_base import Base
from app.db.models.etl_archive import EtlArchiveQuota
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
        db.add(EtlArchiveQuota(tenant_id=1, limit_bytes=10_000_000, reserved_bytes=0))
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
    assert "etl" not in root.parts or root.parts[-1] == "business-archive"
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
        path.write_bytes(body)
        assert not path.read_bytes().startswith(_ENVELOPE_MAGIC)
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body
        assert path.read_bytes().startswith(_ENVELOPE_MAGIC)
        assert read_original(db, owner=7, version_id=version.id, root=archive_root) == body


def test_get_business_archive_dir_uses_desktop_state(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(tmp_path / "AppDataXCAGI"))
    root = Path(path_utils.get_business_archive_dir())
    assert root == tmp_path / "AppDataXCAGI" / "business-archive"
    assert root.is_dir()
