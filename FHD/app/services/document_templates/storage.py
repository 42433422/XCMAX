"""Durable storage and one-time migration for uploaded document templates.

Uploaded business templates are runtime data.  They must never be written next
to the packaged Python modules because doing so mutates the signed desktop app
bundle and makes an application replacement lose the user's source files.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.utils.path_io.path_utils import get_upload_dir

logger = logging.getLogger(__name__)

_LEGACY_PATH_SUFFIX = ("app", "services", "uploads", "templates")


def get_document_template_upload_dir() -> Path:
    """Return the writable, durable template upload directory."""

    target = Path(get_upload_dir()).expanduser().resolve() / "templates"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _is_legacy_packaged_template_path(path: Path) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    suffix = tuple(part.lower() for part in _LEGACY_PATH_SUFFIX)
    return len(parts) > len(suffix) and parts[-(len(suffix) + 1) : -1] == suffix


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination_dir: Path) -> Path:
    source_hash = _sha256(source)
    target = destination_dir / source.name
    if target.exists():
        if target.is_file() and _sha256(target) == source_hash:
            return target
        target = destination_dir / f"{source.stem}-{source_hash[:12]}{source.suffix}"
        if target.exists() and target.is_file() and _sha256(target) == source_hash:
            return target

    temporary = destination_dir / f".{target.name}.migrating-{uuid.uuid4().hex}"
    try:
        shutil.copy2(source, temporary)
        if _sha256(temporary) != source_hash:
            raise OSError(f"template migration checksum mismatch: {source}")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning("清理模板迁移临时文件失败: %s", temporary)
    return target


def migrate_legacy_template_uploads(
    *, db: Any | None = None, destination_dir: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    """Move DB-referenced legacy app-bundle templates into durable storage.

    Files are copied and checksum-verified before the corresponding database
    path is updated.  The legacy source is intentionally retained so an
    interrupted application upgrade remains recoverable.
    """

    destination = (
        Path(destination_dir).expanduser().resolve()
        if destination_dir is not None
        else get_document_template_upload_dir()
    )
    destination.mkdir(parents=True, exist_ok=True)

    owns_session = db is None
    session_context = None
    if owns_session:
        from app.db.session import get_db

        session_context = get_db()
        db = session_context.__enter__()

    migrated: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    try:
        rows = db.execute(
            text(
                "SELECT id, original_file_path FROM templates "
                "WHERE original_file_path IS NOT NULL AND original_file_path != ''"
            )
        ).fetchall()
        for row in rows:
            template_id = int(row[0])
            raw_path = str(row[1] or "").strip()
            source = Path(raw_path).expanduser()
            if not _is_legacy_packaged_template_path(source):
                continue
            if not source.is_file():
                missing.append({"id": template_id, "source": raw_path})
                continue
            try:
                target = _copy_verified(source.resolve(), destination)
                db.execute(
                    text(
                        "UPDATE templates SET original_file_path = :path, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                    ),
                    {"path": str(target), "id": template_id},
                )
                migrated.append(
                    {"id": template_id, "source": raw_path, "target": str(target)}
                )
            except OSError as exc:
                failed.append({"id": template_id, "source": raw_path, "error": str(exc)})
                logger.exception("迁移模板源文件失败: id=%s path=%s", template_id, raw_path)
        if owns_session:
            session_context.__exit__(None, None, None)
            session_context = None
    except Exception as exc:
        if owns_session and session_context is not None:
            session_context.__exit__(type(exc), exc, exc.__traceback__)
            session_context = None
        raise
    finally:
        if owns_session and session_context is not None:
            session_context.__exit__(None, None, None)

    if migrated:
        logger.info("已迁移 %s 个模板源文件到用户数据目录", len(migrated))
    if missing or failed:
        logger.warning(
            "模板源文件迁移未完全完成: missing=%s failed=%s", len(missing), len(failed)
        )
    return {
        "migrated": migrated,
        "missing": missing,
        "failed": failed,
        "destination": str(destination),
    }
