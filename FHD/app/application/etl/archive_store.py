"""Explicit, quota-reserved storage for new archive originals.

Caller must authenticate the actor and establish tenant scope. Incomplete writes
remain pending for operator reconciliation; they are never silently retried.
"""

import hashlib
import os
from pathlib import Path

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.application.etl.archive_policy import ArchivePolicy, ArchivePolicyError
from app.application.etl.service_support import MAX_FILE_BYTES, clean_filename, new_id
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveQuota, EtlArchiveVersion
from app.infrastructure.tenant_scope import tenant_id_for_write


def create_original(db: Session, *, owner: int, name: str, body: bytes, root: Path,
                    request_key: str) -> EtlArchiveVersion:
    tenant = tenant_id_for_write()
    if not request_key or len(request_key) > 80:
        raise ArchivePolicyError("缺少有效的归档请求标识")
    if not body or len(body) > MAX_FILE_BYTES:
        raise ArchivePolicyError("文件为空或超过单文件大小限制")
    digest = hashlib.sha256(body).hexdigest()
    existing = db.query(EtlArchiveAsset).filter_by(tenant_id=tenant, owner_user_id=owner,
                                                   request_key=request_key).first()
    if existing:
        version = db.query(EtlArchiveVersion).filter_by(asset_id=existing.id, tenant_id=tenant,
                                                        owner_user_id=owner, version=1).one()
        if version.sha256 != digest or existing.name != clean_filename(name):
            raise ArchivePolicyError("归档请求标识已用于不同文件")
        if version.status != "ready":
            raise ArchivePolicyError("归档结果待核对，不能重复提交")
        read_original(db, owner=owner, version_id=version.id, root=root)
        return version
    quota = db.get(EtlArchiveQuota, tenant)
    if quota is None:
        raise ArchivePolicyError("归档配额尚未配置")
    policy = ArchivePolicy(None, quota.limit_bytes, "manual")
    if len(body) > policy.quota_bytes:
        raise ArchivePolicyError("归档配额不足")
    reserved = db.execute(update(EtlArchiveQuota).where(
        EtlArchiveQuota.tenant_id == tenant,
        EtlArchiveQuota.reserved_bytes + len(body) <= EtlArchiveQuota.limit_bytes,
    ).values(reserved_bytes=EtlArchiveQuota.reserved_bytes + len(body)))
    if reserved.rowcount != 1:
        db.rollback()
        raise ArchivePolicyError("归档配额不足")
    asset_id, version_id = new_id(), new_id()
    root = root.resolve()
    directory = root / str(tenant) / str(owner)
    if directory.resolve() != directory:
        db.rollback()
        raise ArchivePolicyError("归档路径无效")
    path = directory / version_id
    db.add(EtlArchiveAsset(id=asset_id, tenant_id=tenant, owner_user_id=owner,
                           name=clean_filename(name), retention_mode="manual", request_key=request_key))
    version = EtlArchiveVersion(id=version_id, asset_id=asset_id, tenant_id=tenant,
        owner_user_id=owner, version=1, size_bytes=len(body), sha256=digest,
        storage_path=str(path), status="pending", request_key=request_key)
    db.add(version)
    db.commit()
    _write_pending(db, version, body, directory, path)
    return version


def _write_pending(db: Session, version: EtlArchiveVersion, body: bytes, directory: Path, path: Path) -> None:
    # A crash or a failed write leaves an explicit pending record and reservation.
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("xb") as handle:
        path.chmod(0o600)
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    version.status = "ready"
    db.commit()


def append_original_version(db: Session, *, owner: int, asset_id: str, body: bytes,
                            root: Path, request_key: str) -> EtlArchiveVersion:
    """Create a new version only under an explicitly selected active asset."""
    tenant = tenant_id_for_write()
    if not request_key or len(request_key) > 80 or not body or len(body) > MAX_FILE_BYTES:
        raise ArchivePolicyError('请求标识或文件无效')
    digest = hashlib.sha256(body).hexdigest()
    existing = db.query(EtlArchiveVersion).filter_by(tenant_id=tenant, owner_user_id=owner,
                                                     request_key=request_key).first()
    if existing:
        if existing.asset_id != asset_id or existing.sha256 != digest:
            raise ArchivePolicyError('归档请求标识已用于不同文件')
        if existing.status != 'ready':
            raise ArchivePolicyError('归档结果待核对，不能重复提交')
        read_original(db, owner=owner, version_id=existing.id, root=root)
        return existing
    locked = db.execute(update(EtlArchiveAsset).where(
        EtlArchiveAsset.id == asset_id, EtlArchiveAsset.tenant_id == tenant,
        EtlArchiveAsset.owner_user_id == owner, EtlArchiveAsset.state == 'active',
    ).values(state=EtlArchiveAsset.state))
    if locked.rowcount != 1:
        db.rollback()
        raise ArchivePolicyError('归档不存在或已撤回')
    reserved = db.execute(update(EtlArchiveQuota).where(
        EtlArchiveQuota.tenant_id == tenant,
        EtlArchiveQuota.reserved_bytes + len(body) <= EtlArchiveQuota.limit_bytes,
    ).values(reserved_bytes=EtlArchiveQuota.reserved_bytes + len(body)))
    if reserved.rowcount != 1:
        db.rollback()
        raise ArchivePolicyError('归档配额不足或尚未配置')
    root = root.resolve()
    directory = root / str(tenant) / str(owner)
    if directory.resolve() != directory:
        db.rollback()
        raise ArchivePolicyError('归档路径无效')
    version_id = new_id()
    version_number = (db.query(func.max(EtlArchiveVersion.version)).filter_by(
        tenant_id=tenant, owner_user_id=owner, asset_id=asset_id).scalar() or 0) + 1
    path = directory / version_id
    version = EtlArchiveVersion(id=version_id, asset_id=asset_id, tenant_id=tenant,
        owner_user_id=owner, version=version_number, size_bytes=len(body), sha256=digest,
        storage_path=str(path), status='pending', request_key=request_key)
    db.add(version)
    db.commit()
    _write_pending(db, version, body, directory, path)
    return version


def read_original(db: Session, *, owner: int, version_id: str, root: Path) -> bytes:
    tenant = tenant_id_for_write()
    version = db.query(EtlArchiveVersion).filter_by(
        id=version_id, tenant_id=tenant, owner_user_id=owner, status="ready").first()
    if version is None:
        raise ArchivePolicyError("归档版本不存在或尚不可用")
    asset = db.query(EtlArchiveAsset).filter_by(id=version.asset_id, tenant_id=tenant,
                                               owner_user_id=owner, state='active').first()
    if asset is None:
        raise ArchivePolicyError("归档原件已撤回或不可用")
    return _read_verified(version, tenant=tenant, owner=owner, root=root)


def _read_verified(version: EtlArchiveVersion, *, tenant: int, owner: int, root: Path) -> bytes:
    root = root.resolve()
    directory = root / str(tenant) / str(owner)
    if directory.resolve() != directory:
        raise ArchivePolicyError("归档路径无效")
    raw = Path(version.storage_path)
    path = raw.resolve()
    if raw.is_symlink() or path.parent != directory or not path.is_file():
        raise ArchivePolicyError("归档原件不可用")
    if path.stat().st_size != version.size_bytes or version.size_bytes > MAX_FILE_BYTES:
        raise ArchivePolicyError("归档原件大小已改变")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != version.sha256:
        raise ArchivePolicyError("归档原件校验失败")
    return body


def recover_complete_pending(db: Session, *, owner: int, version_id: str, root: Path) -> None:
    """Accept an intact pending write only after verifying its full stored bytes."""
    tenant = tenant_id_for_write()
    version = db.query(EtlArchiveVersion).filter_by(id=version_id, tenant_id=tenant,
                                                     owner_user_id=owner, status='pending').first()
    if version is None:
        raise ArchivePolicyError('没有可核对的待处理归档')
    asset = db.query(EtlArchiveAsset).filter_by(id=version.asset_id, tenant_id=tenant,
                                               owner_user_id=owner, state='active').first()
    if asset is None:
        raise ArchivePolicyError('归档原件已撤回或不可用')
    _read_verified(version, tenant=tenant, owner=owner, root=root)
    changed = db.execute(update(EtlArchiveVersion).where(
        EtlArchiveVersion.id == version_id, EtlArchiveVersion.tenant_id == tenant,
        EtlArchiveVersion.owner_user_id == owner, EtlArchiveVersion.status == 'pending',
    ).values(status='ready'))
    if changed.rowcount != 1:
        db.rollback()
        raise ArchivePolicyError('归档状态已改变，请刷新')
    db.commit()
