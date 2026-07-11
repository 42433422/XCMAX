"""Dedicated registry for management-side duty employees.

Public/store employee packs live in ``catalog_data/packages.json``.
Duty employees are internal management staff and must not be treated as store
items, even when their runtime package files still live under catalog_data/files.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from modstore_server.duty_roster import (
    employee_partition_meta,
    is_planned_duty_employee_pack,
)


class DutyAssetSeedError(RuntimeError):
    """The immutable duty-employee release seed failed validation."""


_DUTY_ASSET_ROOT = Path(__file__).resolve().parent / "duty_assets"
_MARKET_FILES_ROOT = Path(__file__).resolve().parent / "market_files"
_SEED_LOCK = threading.Lock()
_SAFE_ARCHIVE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}\.(?:xcemp|xcmod|zip)$")
_SAFE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
_MAX_ZIP_MEMBERS = 2000
_MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_archive_name(value: Any) -> str:
    name = str(value or "").strip()
    if not _SAFE_ARCHIVE_NAME.fullmatch(name) or Path(name).name != name:
        raise DutyAssetSeedError(f"unsafe duty archive filename: {name!r}")
    return name


def _validate_archive(record: Dict[str, Any], path: Path) -> None:
    package_id = str(record.get("id") or "").strip()
    filename = _validate_archive_name(record.get("stored_filename"))
    if path.is_symlink() or not path.is_file():
        raise DutyAssetSeedError(f"duty archive is missing or not a regular file: {filename}")
    expected_size = int(record.get("file_size") or 0)
    if expected_size <= 0 or expected_size > _MAX_ARCHIVE_BYTES:
        raise DutyAssetSeedError(f"invalid duty archive size metadata: {filename}")
    if path.stat().st_size != expected_size:
        raise DutyAssetSeedError(f"duty archive size mismatch: {filename}")
    expected_sha256 = str(record.get("sha256") or "").strip().lower()
    if not _SAFE_SHA256.fullmatch(expected_sha256):
        raise DutyAssetSeedError(f"invalid duty archive sha256 metadata: {filename}")
    actual_sha256 = _sha256_file(path)
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise DutyAssetSeedError(f"duty archive sha256 mismatch: {filename}")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_ZIP_MEMBERS:
                raise DutyAssetSeedError(f"invalid duty archive member count: {filename}")
            total_size = 0
            names: set[str] = set()
            for info in infos:
                normalized = str(info.filename or "").replace("\\", "/")
                member = PurePosixPath(normalized)
                if member.is_absolute() or ".." in member.parts:
                    raise DutyAssetSeedError(
                        f"unsafe duty archive member path: {filename}:{normalized}"
                    )
                total_size += max(0, int(info.file_size or 0))
                if total_size > _MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise DutyAssetSeedError(
                        f"duty archive uncompressed size exceeds limit: {filename}"
                    )
                names.add(normalized)
            manifest_name = f"{package_id}/manifest.json"
            if manifest_name not in names:
                raise DutyAssetSeedError(
                    f"duty archive manifest is missing: {filename}:{manifest_name}"
                )
            manifest_info = archive.getinfo(manifest_name)
            if manifest_info.file_size > 1024 * 1024:
                raise DutyAssetSeedError(f"duty archive manifest is too large: {filename}")
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
    except DutyAssetSeedError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise DutyAssetSeedError(f"invalid duty archive: {filename}") from exc
    if not isinstance(manifest, dict) or str(manifest.get("id") or "").strip() != package_id:
        raise DutyAssetSeedError(f"duty archive manifest id mismatch: {filename}")
    expected_version = str(record.get("version") or "").strip()
    if expected_version and str(manifest.get("version") or "").strip() != expected_version:
        raise DutyAssetSeedError(f"duty archive manifest version mismatch: {filename}")


def _seed_source_path(filename: str) -> Path:
    bundled = _DUTY_ASSET_ROOT / "files" / filename
    market = _MARKET_FILES_ROOT / filename
    if bundled.is_file() and not bundled.is_symlink():
        return bundled
    if market.is_file() and not market.is_symlink():
        return market
    raise DutyAssetSeedError(f"duty seed archive is missing: {filename}")


def _load_validated_seed() -> tuple[Dict[str, Any], list[tuple[Dict[str, Any], Path]]]:
    seed_path = _DUTY_ASSET_ROOT / "registry.json"
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DutyAssetSeedError("duty asset seed registry is missing or invalid") from exc
    if not isinstance(seed, dict) or seed.get("immutable") is not True:
        raise DutyAssetSeedError("duty asset seed registry is not immutable")
    packages = seed.get("packages")
    if not isinstance(packages, list) or not packages:
        raise DutyAssetSeedError("duty asset seed registry has no packages")
    declared_count = int(seed.get("package_count") or 0)
    if declared_count != len(packages):
        raise DutyAssetSeedError("duty asset seed package count mismatch")

    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    validated: list[tuple[Dict[str, Any], Path]] = []
    for raw in packages:
        if not isinstance(raw, dict):
            raise DutyAssetSeedError("duty asset seed contains a non-object package")
        record = dict(raw)
        package_id = str(record.get("id") or "").strip()
        if not is_planned_duty_employee_pack(package_id, str(record.get("artifact") or "")):
            raise DutyAssetSeedError(f"duty asset seed contains an unplanned package: {package_id}")
        filename = _validate_archive_name(record.get("stored_filename"))
        if package_id in seen_ids or filename in seen_files:
            raise DutyAssetSeedError(f"duplicate duty asset seed record: {package_id}")
        seen_ids.add(package_id)
        seen_files.add(filename)
        source = _seed_source_path(filename)
        _validate_archive(record, source)
        validated.append((record, source))
    return seed, validated


@contextmanager
def _catalog_seed_process_lock(catalog_dir: Path):
    lock_path = catalog_dir / ".duty-assets-seed.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows falls back to the thread lock
            fcntl = None  # type: ignore[assignment]
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if "fcntl" in locals() and fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _seed_duty_assets_if_missing(registry_path: Path) -> None:
    if registry_path.is_file():
        return
    catalog_dir = registry_path.parent
    catalog_dir.mkdir(parents=True, exist_ok=True)
    with _SEED_LOCK, _catalog_seed_process_lock(catalog_dir):
        if registry_path.is_file():
            return
        seed, entries = _load_validated_seed()
        files_root = catalog_dir / "files"
        files_root.mkdir(parents=True, exist_ok=True)

        # Existing state always wins. Validate it, but never replace it.
        missing: list[tuple[Dict[str, Any], Path, Path]] = []
        for record, source in entries:
            target = files_root / str(record["stored_filename"])
            if target.exists() or target.is_symlink():
                _validate_archive(record, target)
            else:
                missing.append((record, source, target))

        with tempfile.TemporaryDirectory(prefix=".duty-seed-", dir=catalog_dir) as raw_stage:
            stage = Path(raw_stage)
            staged: list[tuple[Dict[str, Any], Path, Path]] = []
            for record, source, target in missing:
                staged_path = stage / target.name
                with source.open("rb") as source_handle:
                    _write_bytes_exclusive(staged_path, source_handle.read())
                _validate_archive(record, staged_path)
                staged.append((record, staged_path, target))

            # An external writer may not honor our lock. Recheck before making
            # any seed file visible and leave its state untouched if it won.
            if registry_path.exists() or registry_path.is_symlink():
                return
            for record, staged_path, target in staged:
                try:
                    os.link(staged_path, target)
                except FileExistsError:
                    _validate_archive(record, target)

            registry_payload = (
                json.dumps(seed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            staged_registry = stage / "registry.json"
            _write_bytes_exclusive(staged_registry, registry_payload)
            try:
                os.link(staged_registry, registry_path)
            except FileExistsError:
                # Never overwrite a catalog registry created by another actor.
                pass


def duty_registry_path() -> Path:
    from modstore_server.catalog_store import packages_path

    return packages_path().with_name("duty_employee_registry.json")


def load_duty_registry() -> Dict[str, Any]:
    path = duty_registry_path()
    if not path.is_file():
        _seed_duty_assets_if_missing(path)
    if not path.is_file():
        return {"schema": 1, "packages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": 1, "packages": []}
    if not isinstance(data, dict):
        return {"schema": 1, "packages": []}
    packages = data.get("packages")
    if not isinstance(packages, list):
        data["packages"] = []
    return data


def save_duty_registry(data: Dict[str, Any]) -> None:
    path = duty_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data or {})
    payload.setdefault("schema", 1)
    payload.setdefault("packages", [])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record_pkg_id(record: Dict[str, Any]) -> str:
    return str(record.get("id") or record.get("pkg_id") or "").strip()


def duty_employee_records() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw in load_duty_registry().get("packages") or []:
        if not isinstance(raw, dict):
            continue
        pid = _record_pkg_id(raw)
        if not is_planned_duty_employee_pack(pid, str(raw.get("artifact") or "employee_pack")):
            continue
        rec = dict(raw)
        rec.update(employee_partition_meta(pid, "employee_pack"))
        rec["is_public"] = False
        rec["market_visible"] = False
        out[pid] = rec
    return out


def get_duty_employee_record(pack_id: str) -> Optional[Dict[str, Any]]:
    return duty_employee_records().get(str(pack_id or "").strip())


def list_duty_employee_records() -> List[Dict[str, Any]]:
    return [duty_employee_records()[k] for k in sorted(duty_employee_records())]
