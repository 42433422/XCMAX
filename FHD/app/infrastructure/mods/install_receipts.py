"""Signed package identity and restart-aware Mod installation state.

Receipts live outside Mod directories. A package cannot declare itself verified;
the retained archive must pass the host's trusted-key verification on every read.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from threading import RLock
from typing import Any

from app.infrastructure.mods.state_lock import state_lock

PROCESS_ID = uuid.uuid4().hex
_LOCK = RLock()
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _root(mods_root: str | None) -> Path:
    if mods_root is None:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mods_root = get_mod_manager().mods_root
    return Path(mods_root).resolve()


def _state_dir(root: Path, mod_id: str) -> Path:
    if not _ID.fullmatch(mod_id) or mod_id in {".", ".."}:
        raise ValueError("Invalid Mod package identity")
    path = root / ".install-receipts" / mod_id
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Invalid Mod receipt directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _write(path: Path, row: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(row, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return row if isinstance(row, dict) else None


def _signed_files(package: Path) -> tuple[dict[str, Any], dict[str, str]] | None:
    from app.infrastructure.mods.package_signing import verify_signed_package_bytes

    with zipfile.ZipFile(package) as archive:
        if "META-INF/signature.json" not in archive.namelist():
            return None
    verified = verify_signed_package_bytes(package.read_bytes())
    return verified["manifest"], verified["files_sha256"]


def _files_match(directory: Path, files: dict[str, str]) -> bool:
    if directory.is_symlink() or not directory.is_dir():
        return False
    for relative, checksum in files.items():
        path = directory / relative
        if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            return False
    for path in directory.rglob("*"):
        if path.is_symlink():
            return False
        if path.is_file() and "__pycache__" not in path.relative_to(directory).parts:
            relative = path.relative_to(directory).as_posix()
            if relative not in files and relative != "META-INF/signature.json":
                return False
    return True


def install_extracted(
    *,
    mods_root: str,
    extracted_root: str,
    manifest: dict[str, Any],
    package_path: str,
    verify_signature: bool,
    was_loaded: bool,
    owner_scope: str = "",
) -> bool:
    """Atomically install, retaining previous code and staging active updates.

    Return True if a new process is required. The active code directory is never
    replaced beneath a running backend (including its templates and lazy imports).
    """
    root = _root(mods_root)
    mid = str(manifest.get("id") or "")
    state = _state_dir(root, mid)
    with _LOCK, state_lock(state):
        target = root / mid
        if target.is_symlink():
            raise ValueError("Mod destination must not be a symlink")
        package = Path(package_path)
        signed = _signed_files(package) if verify_signature else None
        if signed and signed[0] != manifest:
            raise ValueError("Signed manifest does not match installed manifest")
        if signed and not _files_match(Path(extracted_root), signed[1]):
            raise ValueError("Extracted files differ from the signed package")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        current = _read(state / "receipt.json")
        if current and current.get("owner_scope") != owner_scope:
            raise ValueError("Mod installation belongs to another owner")
        if (
            manifest.get("scope") == "account" or manifest.get("entitlement_mod_id")
        ) and not owner_scope:
            raise ValueError("Account Mod installation requires an owner")
        identical = bool(current and current.get("package_sha256") == digest)
        if (
            identical
            and current
            and Path(current["installed_root"]).is_dir()
            and (not signed or _files_match(Path(current["installed_root"]), signed[1]))
        ):
            return bool(current.get("requires_restart"))
        if (
            not identical
            and current
            and current.get("package_version") == str(manifest.get("version") or "")
        ):
            raise ValueError("Mod version already exists with different package bytes")
        destination = state / ("pending-" + digest) if was_loaded else target
        with tempfile.TemporaryDirectory(prefix=".mod-install-", dir=root) as staging:
            staged = Path(staging) / mid
            shutil.copytree(extracted_root, staged)
            backup = state / ("previous-" + uuid.uuid4().hex)
            if destination.exists():
                os.replace(destination, backup)
            try:
                os.replace(staged, destination)
            except OSError:
                if backup.exists():
                    os.replace(backup, destination)
                raise
        archive = state / (digest + ".zip")
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            fd, temporary = tempfile.mkstemp(prefix=".archive-", dir=state)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(package.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, archive)
            finally:
                Path(temporary).unlink(missing_ok=True)
        row = {
            "mod_id": mid,
            "package_version": str(manifest.get("version") or ""),
            "package_sha256": digest,
            "signature_verified": signed is not None,
            "installed_root": str(destination),
            "owner_scope": owner_scope,
            "requires_restart": was_loaded,
            "install_process_id": PROCESS_ID,
            "runtime_process_id": "",
            "runtime_status": "restart_required" if was_loaded else "installed",
        }
        _write(state / "receipt.json", row)
        return was_loaded


def activate_pending_install(mod_id: str, *, mods_root: str) -> bool:
    """Apply a staged package only in a different process, before loading it."""
    root = _root(mods_root)
    state = _state_dir(root, mod_id)
    with _LOCK, state_lock(state):
        row = _read(state / "receipt.json")
        if not row or not row.get("requires_restart"):
            return True
        if row.get("install_process_id") == PROCESS_ID:
            return False
        pending = state / ("pending-" + str(row.get("package_sha256") or ""))
        if str(pending) != row.get("installed_root") or not pending.is_dir():
            raise ValueError("Pending Mod package is unavailable")
        if (
            row.get("signature_verified")
            and read_verified_install(mod_id, mods_root=mods_root) is None
        ):
            raise ValueError("Pending Mod signature or content changed")
        target = root / mod_id
        backup = state / ("previous-" + uuid.uuid4().hex)
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(pending, target)
        except OSError:
            if backup.exists():
                os.replace(backup, target)
            raise
        row.update(installed_root=str(target), requires_restart=False, runtime_status="installed")
        _write(state / "receipt.json", row)
        return True


def read_verified_install(mod_id: str, *, mods_root: str | None = None) -> dict[str, Any] | None:
    from app.infrastructure.mods.package import ModSignatureError

    root = _root(mods_root)
    state = _state_dir(root, mod_id)
    row = _read(state / "receipt.json")
    if not row or not row.get("signature_verified"):
        return None
    digest = str(row.get("package_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    package = state / (digest + ".zip")
    try:
        if hashlib.sha256(package.read_bytes()).hexdigest() != digest:
            return None
        signed = _signed_files(package)
        if signed is None:
            return None
        manifest, files = signed
        if manifest.get("id") != mod_id or str(manifest.get("version") or "") != row.get(
            "package_version"
        ):
            return None
        expected_root = (
            state / ("pending-" + digest) if row.get("requires_restart") else root / mod_id
        )
        if str(expected_root) != row.get("installed_root") or expected_root.is_symlink():
            return None
        if not _files_match(expected_root, files):
            return None
    except (OSError, ValueError, zipfile.BadZipFile, ModSignatureError):
        return None
    result = dict(row, file_sha256=files)
    if result.get("runtime_process_id") != PROCESS_ID and not result.get("requires_restart"):
        result["runtime_status"] = "installed"
    return result


def mark_runtime_loaded(mod_id: str, *, mods_root: str, api_registered: bool = False) -> None:
    state = _state_dir(_root(mods_root), mod_id)
    with _LOCK, state_lock(state):
        row = read_verified_install(mod_id, mods_root=mods_root)
        if not row or row.get("requires_restart"):
            return
        row.pop("file_sha256", None)
        row.update(
            runtime_process_id=PROCESS_ID,
            runtime_status="running" if api_registered else "backend_loaded",
        )
        _write(_state_dir(_root(mods_root), mod_id) / "receipt.json", row)
