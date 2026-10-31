"""Explicit, quota-reserved storage for new archive originals.

Caller must authenticate the actor and establish tenant scope. Incomplete writes
remain pending for operator reconciliation; they are never silently retried.

On-disk bodies are Fernet-encrypted under ``business-archive/`` (see
:func:`default_archive_root`). Metadata ``sha256`` / ``size_bytes`` always
describe the **plaintext** original. Idempotency remains ``request_key``.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import secrets
from pathlib import Path
from typing import cast

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.elt.archive_policy import ArchivePolicy, ArchivePolicyError
from app.application.elt.errors import EltConflict
from app.application.elt.service_support import MAX_FILE_BYTES, clean_filename, new_id
from app.db.models.elt_archive import EltArchiveAsset, EltArchiveQuota, EltArchiveVersion
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_io.path_utils import get_business_archive_dir

_KEY_FILE_NAME = ".archive.key"
_ENVELOPE_MAGIC = b"XCAGIARC1\0"
# Owner: unset quota uses 10 GiB default; admins may raise via archive-quota API (no extra hard ceiling on the default).
DEFAULT_ARCHIVE_QUOTA_BYTES = 10 * 1024 * 1024 * 1024


def default_archive_root() -> Path:
    """Stable user-data root for archived business originals."""
    return Path(get_business_archive_dir())


def _ensure_tenant_quota(db: Session, tenant: int) -> EltArchiveQuota:
    """Return the tenant quota row, inserting the 10 GiB default when unset."""
    quota = db.get(EltArchiveQuota, tenant)
    if quota is not None:
        return quota
    try:
        with db.begin_nested():
            db.add(
                EltArchiveQuota(
                    tenant_id=tenant,
                    limit_bytes=DEFAULT_ARCHIVE_QUOTA_BYTES,
                    reserved_bytes=0,
                )
            )
            db.flush()
    except IntegrityError:
        pass
    quota = db.get(EltArchiveQuota, tenant)
    if quota is None:
        raise ArchivePolicyError("归档配额不足")
    return quota


def create_original(
    db: Session, *, owner: int, name: str, body: bytes, root: Path, request_key: str
) -> EltArchiveVersion:
    tenant = tenant_id_for_write()
    if not request_key or len(request_key) > 80:
        raise ArchivePolicyError("缺少有效的归档请求标识")
    if not body or len(body) > MAX_FILE_BYTES:
        raise ArchivePolicyError("文件为空或超过单文件大小限制")
    digest = hashlib.sha256(body).hexdigest()
    existing = (
        db.query(EltArchiveAsset)
        .filter_by(tenant_id=tenant, owner_user_id=owner, request_key=request_key)
        .first()
    )
    if existing:
        version = (
            db.query(EltArchiveVersion)
            .filter_by(asset_id=existing.id, tenant_id=tenant, owner_user_id=owner, version=1)
            .one()
        )
        if version.sha256 != digest or existing.name != clean_filename(name):
            raise ArchivePolicyError("归档请求标识已用于不同文件")
        if version.status != "ready":
            raise ArchivePolicyError("归档结果待核对，不能重复提交")
        read_original(db, owner=owner, version_id=version.id, root=root)
        return version
    quota = _ensure_tenant_quota(db, tenant)
    policy = ArchivePolicy(None, quota.limit_bytes, "manual")
    if len(body) > policy.quota_bytes:
        raise ArchivePolicyError("归档配额不足")
    reserved = db.execute(
        update(EltArchiveQuota)
        .where(
            EltArchiveQuota.tenant_id == tenant,
            EltArchiveQuota.reserved_bytes + len(body) <= EltArchiveQuota.limit_bytes,
        )
        .values(reserved_bytes=EltArchiveQuota.reserved_bytes + len(body))
    )
    if cast(CursorResult, reserved).rowcount != 1:
        db.rollback()
        raise ArchivePolicyError("归档配额不足")
    asset_id, version_id = new_id(), new_id()
    root = root.resolve()
    directory = root / str(tenant) / str(owner)
    if directory.resolve() != directory:
        db.rollback()
        raise ArchivePolicyError("归档路径无效")
    path = directory / version_id
    db.add(
        EltArchiveAsset(
            id=asset_id,
            tenant_id=tenant,
            owner_user_id=owner,
            name=clean_filename(name),
            retention_mode="manual",
            request_key=request_key,
        )
    )
    version = EltArchiveVersion(
        id=version_id,
        asset_id=asset_id,
        tenant_id=tenant,
        owner_user_id=owner,
        version=1,
        size_bytes=len(body),
        sha256=digest,
        storage_path=str(path),
        status="pending",
        request_key=request_key,
    )
    db.add(version)
    db.commit()
    _write_pending(db, version, body, directory, path, root=root)
    return version


def _write_pending(
    db: Session,
    version: EltArchiveVersion,
    body: bytes,
    directory: Path,
    path: Path,
    *,
    root: Path | None = None,
) -> None:
    # A crash or a failed write leaves an explicit pending record and reservation.
    archive_root = root if root is not None else path.parent.parent.parent
    payload = _encrypt_body(body, archive_root=archive_root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("xb") as handle:
        path.chmod(0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    version.status = "ready"
    db.commit()


def append_original_version(
    db: Session,
    *,
    owner: int,
    asset_id: str,
    body: bytes,
    root: Path,
    request_key: str,
    expected_version: int | None = None,
) -> EltArchiveVersion:
    """Create a new version only under an explicitly selected active asset."""
    tenant = tenant_id_for_write()
    if not request_key or len(request_key) > 80 or not body or len(body) > MAX_FILE_BYTES:
        raise ArchivePolicyError("请求标识或文件无效")
    digest = hashlib.sha256(body).hexdigest()
    existing = (
        db.query(EltArchiveVersion)
        .filter_by(tenant_id=tenant, owner_user_id=owner, request_key=request_key)
        .first()
    )
    if existing:
        if existing.asset_id != asset_id or existing.sha256 != digest:
            raise ArchivePolicyError("归档请求标识已用于不同文件")
        if existing.status != "ready":
            raise ArchivePolicyError("归档结果待核对，不能重复提交")
        read_original(db, owner=owner, version_id=existing.id, root=root)
        return existing
    locked = db.execute(
        update(EltArchiveAsset)
        .where(
            EltArchiveAsset.id == asset_id,
            EltArchiveAsset.tenant_id == tenant,
            EltArchiveAsset.owner_user_id == owner,
            EltArchiveAsset.state == "active",
        )
        .values(state=EltArchiveAsset.state)
    )
    if cast(CursorResult, locked).rowcount != 1:
        db.rollback()
        raise ArchivePolicyError("归档不存在或已撤回")
    current_version = (
        db.query(func.max(EltArchiveVersion.version))
        .filter_by(tenant_id=tenant, owner_user_id=owner, asset_id=asset_id)
        .scalar()
        or 0
    )
    if expected_version is not None and current_version != expected_version:
        db.rollback()
        raise EltConflict("ELT_SOURCE_VERSION_CONFLICT", "来源已有新版本，请刷新后再追加")
    _ensure_tenant_quota(db, tenant)
    reserved = db.execute(
        update(EltArchiveQuota)
        .where(
            EltArchiveQuota.tenant_id == tenant,
            EltArchiveQuota.reserved_bytes + len(body) <= EltArchiveQuota.limit_bytes,
        )
        .values(reserved_bytes=EltArchiveQuota.reserved_bytes + len(body))
    )
    if cast(CursorResult, reserved).rowcount != 1:
        db.rollback()
        raise ArchivePolicyError("归档配额不足")
    root = root.resolve()
    directory = root / str(tenant) / str(owner)
    if directory.resolve() != directory:
        db.rollback()
        raise ArchivePolicyError("归档路径无效")
    version_id = new_id()
    path = directory / version_id
    version = EltArchiveVersion(
        id=version_id,
        asset_id=asset_id,
        tenant_id=tenant,
        owner_user_id=owner,
        version=current_version + 1,
        size_bytes=len(body),
        sha256=digest,
        storage_path=str(path),
        status="pending",
        request_key=request_key,
    )
    db.add(version)
    db.commit()
    _write_pending(db, version, body, directory, path, root=root)
    return version


def read_original(db: Session, *, owner: int, version_id: str, root: Path) -> bytes:
    tenant = tenant_id_for_write()
    version = (
        db.query(EltArchiveVersion)
        .filter_by(id=version_id, tenant_id=tenant, owner_user_id=owner, status="ready")
        .first()
    )
    if version is None:
        raise ArchivePolicyError("归档版本不存在或尚不可用")
    asset = (
        db.query(EltArchiveAsset)
        .filter_by(id=version.asset_id, tenant_id=tenant, owner_user_id=owner, state="active")
        .first()
    )
    if asset is None:
        raise ArchivePolicyError("归档原件已撤回或不可用")
    return _read_verified(version, tenant=tenant, owner=owner, root=root)


def _read_verified(version: EltArchiveVersion, *, tenant: int, owner: int, root: Path) -> bytes:
    root = root.resolve()
    directory = root / str(tenant) / str(owner)
    if directory.resolve() != directory:
        raise ArchivePolicyError("归档路径无效")
    raw = Path(version.storage_path)
    path = raw.resolve()
    if raw.is_symlink() or path.parent != directory or not path.is_file():
        raise ArchivePolicyError("归档原件不可用")
    disk = path.read_bytes()
    if len(disk) > MAX_FILE_BYTES + 4096:
        raise ArchivePolicyError("归档原件大小已改变")
    body = _decrypt_or_migrate(disk, path=path, archive_root=root, version=version)
    if len(body) != version.size_bytes or version.size_bytes > MAX_FILE_BYTES:
        raise ArchivePolicyError("归档原件大小已改变")
    if hashlib.sha256(body).hexdigest() != version.sha256:
        raise ArchivePolicyError("归档原件校验失败")
    return body


def recover_complete_pending(db: Session, *, owner: int, version_id: str, root: Path) -> None:
    """Accept an intact pending write only after verifying its full stored bytes."""
    tenant = tenant_id_for_write()
    version = (
        db.query(EltArchiveVersion)
        .filter_by(id=version_id, tenant_id=tenant, owner_user_id=owner, status="pending")
        .first()
    )
    if version is None:
        raise ArchivePolicyError("没有可核对的待处理归档")
    asset = (
        db.query(EltArchiveAsset)
        .filter_by(id=version.asset_id, tenant_id=tenant, owner_user_id=owner, state="active")
        .first()
    )
    if asset is None:
        raise ArchivePolicyError("归档原件已撤回或不可用")
    _read_verified(version, tenant=tenant, owner=owner, root=root)
    changed = db.execute(
        update(EltArchiveVersion)
        .where(
            EltArchiveVersion.id == version_id,
            EltArchiveVersion.tenant_id == tenant,
            EltArchiveVersion.owner_user_id == owner,
            EltArchiveVersion.status == "pending",
        )
        .values(status="ready")
    )
    if cast(CursorResult, changed).rowcount != 1:
        db.rollback()
        raise ArchivePolicyError("归档状态已改变，请刷新")
    db.commit()


def _archive_cipher(archive_root: Path) -> Fernet:
    """Install/user-data scoped Fernet key (never logged).

    Prefer ``SECRET_KEY`` / ``XCAGI_SECRET_KEY`` when set (server). Otherwise a
    random key file ``{archive_root}/.archive.key`` with mode 0600, matching the
    group-chat desktop key-file pattern.
    """
    secret = (
        os.environ.get("SECRET_KEY", "").strip() or os.environ.get("XCAGI_SECRET_KEY", "").strip()
    )
    if not secret:
        secret = _load_or_create_key_file(archive_root)
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _load_or_create_key_file(archive_root: Path) -> str:
    key_path = archive_root.expanduser().resolve() / _KEY_FILE_NAME
    try:
        if key_path.is_file():
            existing = key_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        generated = secrets.token_urlsafe(32)
        # Write then tighten perms (Windows may ignore chmod; still best-effort).
        key_path.write_text(generated + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(key_path, 0o600)
        return generated
    except OSError as exc:
        raise ArchivePolicyError("归档密钥不可用") from exc


def _encrypt_body(plaintext: bytes, *, archive_root: Path) -> bytes:
    token = _archive_cipher(archive_root).encrypt(plaintext)
    return _ENVELOPE_MAGIC + token


def _decrypt_or_migrate(
    disk: bytes, *, path: Path, archive_root: Path, version: EltArchiveVersion
) -> bytes:
    if disk.startswith(_ENVELOPE_MAGIC):
        token = disk[len(_ENVELOPE_MAGIC) :]
        try:
            return _archive_cipher(archive_root).decrypt(token)
        except InvalidToken as exc:
            raise ArchivePolicyError("归档原件解密失败") from exc
    # Legacy plaintext under old etl/archive (or pre-encrypt writes): verify then
    # transparently re-encrypt on read when the digest matches.
    if hashlib.sha256(disk).hexdigest() != version.sha256 or len(disk) != version.size_bytes:
        raise ArchivePolicyError("归档原件校验失败")
    try:
        payload = _encrypt_body(disk, archive_root=archive_root)
        tmp = path.with_suffix(path.suffix + ".migrating")
        with tmp.open("xb") as handle:
            tmp.chmod(0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError:
        # Migration is best-effort; plaintext still verifies and is returned.
        with contextlib.suppress(OSError):
            tmp = path.with_suffix(path.suffix + ".migrating")
            if tmp.exists():
                tmp.unlink()
    return disk
