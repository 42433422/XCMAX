#!/usr/bin/env python3
"""Synchronise bundled Mods against the exact previously deployed archive.

The old archive is accepted as an ownership baseline only when its digest,
build identity and deployed identity stamps agree. Only Mods present in the
incoming release are touched; local Mods, receipts and excluded user state are
kept outside that destructive surface.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

RECEIPTS = ".install-receipts"
PROTECTED = {RECEIPTS, "_employees", ".fhd-release-managed.json"}
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "frontend",
    "desktop",
    "mobile-flutter-poc",
    "tests",
    "data",
    "uploads",
    "dist",
    ".coverage",
    ".pytest_cache",
    ".ruff_cache",
    ".secrets",
    RECEIPTS,
}
PRESERVED_EXCLUDED_DIRS = EXCLUDED_DIRS - {
    "__pycache__",
    ".coverage",
    ".pytest_cache",
    ".ruff_cache",
}


class GuardError(RuntimeError):
    pass


@contextlib.contextmanager
def mod_locks(target: Path, mod_ids: set[str]):
    """Use the same per-Mod nonblocking flock as install_receipts.state_lock."""
    handles = []
    try:
        if not mod_ids:
            yield
            return
        receipt_root = target / RECEIPTS
        if receipt_root.is_symlink():
            raise GuardError("Mod receipt root is a symlink")
        receipt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for mod_id in sorted(mod_ids):
            if not ID_RE.fullmatch(mod_id) or mod_id in PROTECTED:
                raise GuardError("invalid Mod id while acquiring update locks")
            state = receipt_root / mod_id
            if state.is_symlink():
                raise GuardError(f"Mod receipt state is a symlink: {mod_id}")
            state.mkdir(mode=0o700, exist_ok=True)
            lock_path = state / ".state.lock"
            if lock_path.is_symlink():
                raise GuardError(f"Mod state lock is a symlink: {mod_id}")
            handle = lock_path.open("a+b")
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise GuardError(f"Mod install is active; retry deployment: {mod_id}") from exc
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def is_release_excluded(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        any(part in EXCLUDED_DIRS for part in parts)
        or any(part == ".env" or part.startswith(".env.") for part in parts)
        or any(part.endswith((".pyc", ".pyo")) for part in parts)
        or "._" in parts
        or relative
        in {
            "routing_policies/routing_decisions.jsonl",
            "routing_policies/.online_update_state.json",
        }
    )


def is_preserved_user_state(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        any(part in PRESERVED_EXCLUDED_DIRS for part in parts)
        or any(part == ".env" or part.startswith(".env.") for part in parts)
        or relative
        in {
            "routing_policies/routing_decisions.jsonl",
            "routing_policies/.online_update_state.json",
        }
    )


def release_view(root: Path) -> dict[str, tuple[str, int, str]]:
    if root.is_symlink() or not root.is_dir():
        raise GuardError(f"Mod directory is missing or unsafe: {root.name}")
    rows: dict[str, tuple[str, int, str]] = {}
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        if is_release_excluded(rel):
            continue
        if path.is_symlink():
            raise GuardError(f"symlink in release-managed files: {root.name}/{rel}")
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            rows[rel] = ("dir", mode, "")
        elif path.is_file():
            rows[rel] = ("file", mode, hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            raise GuardError(f"unsupported filesystem entry: {root.name}/{rel}")
    return rows


def release_hash(root: Path) -> str:
    h = hashlib.sha256()
    for rel, (kind, mode, content_hash) in sorted(release_view(root).items()):
        h.update(kind.encode() + b"\0" + rel.encode("utf-8") + b"\0")
        h.update(mode.to_bytes(4, "big"))
        h.update(content_hash.encode("ascii"))
    return h.hexdigest()


def source_mods(source: Path) -> dict[str, Path]:
    if source.is_symlink() or not source.is_dir():
        raise GuardError("release mods directory is missing or unsafe")
    result: dict[str, Path] = {}
    for child in source.iterdir():
        if child.name in PROTECTED or child.name in {"_employees", "README.md"}:
            continue
        if not ID_RE.fullmatch(child.name) or child.is_symlink() or not child.is_dir():
            raise GuardError(f"unsupported release Mod entry: {child.name}")
        for path in child.rglob("*"):
            rel = path.relative_to(child).as_posix()
            if is_preserved_user_state(rel):
                raise GuardError(
                    f"release contains a path reserved for host-local state: {child.name}/{rel}"
                )
        result[child.name] = child
        release_view(child)
    return result


def verify_previous_identity(archive: Path, deploy_root: Path) -> dict[str, object]:
    sha_path = deploy_root / ".deploy-sha256"
    git_path = deploy_root / ".deploy-git-sha"
    identity_path = deploy_root / ".build-identity.json"
    if (
        not archive.is_file()
        or not sha_path.is_file()
        or not git_path.is_file()
        or not identity_path.is_file()
    ):
        raise GuardError("previous release archive or identity stamps are missing")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    stamped_digest = sha_path.read_text(encoding="utf-8").strip()
    stamped_git = git_path.read_text(encoding="utf-8").strip()
    if not SHA_RE.fullmatch(stamped_digest) or digest != stamped_digest:
        raise GuardError("previous release archive SHA256 does not match .deploy-sha256")
    try:
        installed = json.loads(identity_path.read_text(encoding="utf-8"))
        with tarfile.open(archive, "r:gz") as tar:
            identity_members = [
                m for m in tar.getmembers() if m.name.removeprefix("./") == ".build-identity.json"
            ]
            if len(identity_members) != 1 or not identity_members[0].isfile():
                raise GuardError("previous archive has no unique build identity")
            stream = tar.extractfile(identity_members[0])
            archived = json.load(stream) if stream else None
    except (OSError, ValueError, tarfile.TarError) as exc:
        raise GuardError("previous release identity is unreadable") from exc
    if not isinstance(installed, dict) or archived != installed:
        raise GuardError("deployed build identity differs from previous archive")
    if archived.get("git_sha") != stamped_git:
        raise GuardError("previous archive Git SHA does not match .deploy-git-sha")
    return archived


def extract_previous_mods(archive: Path, target: Path) -> dict[str, Path]:
    target.mkdir(parents=True)
    found: dict[str, Path] = {}
    seen: set[str] = set()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                if not name.startswith("mods/"):
                    continue
                rel = PurePosixPath(name[5:])
                if rel.is_absolute() or any(part in {"..", ""} for part in rel.parts):
                    raise GuardError("previous archive has an unsafe Mod path")
                if not rel.parts:
                    continue
                mod_id = rel.parts[0]
                if mod_id in {RECEIPTS, "_employees", "README.md"}:
                    continue
                if not ID_RE.fullmatch(mod_id):
                    raise GuardError("previous archive contains an invalid Mod id")
                if len(rel.parts) == 1:
                    if not member.isdir():
                        raise GuardError(f"previous archive Mod root is not a directory: {mod_id}")
                    found[mod_id] = target / mod_id
                    found[mod_id].mkdir(parents=True, exist_ok=True)
                    continue
                relative = PurePosixPath(*rel.parts[1:]).as_posix()
                if is_release_excluded(relative):
                    continue
                if member.name in seen:
                    raise GuardError("previous archive has duplicate Mod paths")
                seen.add(member.name)
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise GuardError(f"previous archive has unsafe Mod member: {mod_id}")
                mod_root = target / mod_id
                found[mod_id] = mod_root
                dest = mod_root / relative
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                    os.chmod(dest, stat.S_IMODE(member.mode))
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    stream = tar.extractfile(member)
                    if stream is None:
                        raise GuardError("previous archive member cannot be read")
                    with dest.open("xb") as out:
                        shutil.copyfileobj(stream, out)
                    os.chmod(dest, stat.S_IMODE(member.mode))
    except (OSError, tarfile.TarError) as exc:
        raise GuardError("previous release Mods cannot be read safely") from exc
    return found


def receipt_has_install_state(target: Path, mod_id: str) -> bool:
    receipt_root = target / RECEIPTS
    state = receipt_root / mod_id
    if receipt_root.is_symlink() or state.is_symlink():
        return True
    if not receipt_root.exists():
        return False
    if not receipt_root.is_dir() or not state.exists():
        return not receipt_root.is_dir()
    if not state.is_dir():
        return True
    try:
        return any(entry.name != ".state.lock" for entry in state.iterdir())
    except OSError:
        return True


def copy_user_state(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise GuardError(f"user state is a symlink: {source}")
    if not source.exists():
        return
    if source.is_dir():
        if any(child.is_symlink() for child in source.rglob("*")):
            raise GuardError(f"symlink in preserved user state: {source}")
        if destination.exists() and not destination.is_dir():
            raise GuardError(f"release conflicts with preserved user directory: {destination}")
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False)
    elif source.is_file():
        if destination.exists() and destination.is_dir():
            raise GuardError(f"release conflicts with preserved user file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        raise GuardError(f"unsupported user-state entry: {source}")


def preserve_user_state(source_mod: Path, destination_mod: Path) -> None:
    copied: set[str] = set()
    for path in sorted(source_mod.rglob("*"), key=lambda p: p.relative_to(source_mod).as_posix()):
        rel = path.relative_to(source_mod).as_posix()
        if not is_preserved_user_state(rel):
            continue
        parts = PurePosixPath(rel).parts
        if any(
            part in PRESERVED_EXCLUDED_DIRS or part == ".env" or part.startswith(".env.")
            for part in parts
        ):
            # Copy each excluded root once; nested traversal is covered by it.
            first = next(
                i
                for i, part in enumerate(parts)
                if part in PRESERVED_EXCLUDED_DIRS or part == ".env" or part.startswith(".env.")
            )
            rel = PurePosixPath(*parts[: first + 1]).as_posix()
            path = source_mod / rel
        elif not rel.startswith("routing_policies/"):
            continue
        if rel in copied:
            continue
        copied.add(rel)
        copy_user_state(path, destination_mod / rel)


def load_state(path: Path) -> dict[str, dict[str, object]]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GuardError(f"update recovery state is corrupt: {path.name}") from exc
    if not isinstance(row, dict):
        raise GuardError(f"update recovery state is corrupt: {path.name}")
    for mod_id, item in row.items():
        if not isinstance(mod_id, str) or not ID_RE.fullmatch(mod_id) or not isinstance(item, dict):
            raise GuardError(f"update recovery state is corrupt: {path.name}")
        for key in ("new_hash", "prior_hash"):
            value = item.get(key)
            if value is not None and (not isinstance(value, str) or not SHA_RE.fullmatch(value)):
                raise GuardError(f"update recovery state is corrupt: {path.name}")
    return row


def _rollback_locked(state: Path, target: Path, allow_unapplied: bool = False) -> None:
    plan_path = state / "plan.json"
    plan = load_state(plan_path) if plan_path.exists() else {}
    prior_dir = state / "prior"
    for mod_id, entry in plan.items():
        dest = target / mod_id
        if receipt_has_install_state(target, mod_id):
            raise GuardError(f"rollback blocked by Mod receipt state: {mod_id}")
        if not dest.exists():
            continue
        current_hash = release_hash(dest)
        allowed = {entry.get("new_hash"), entry.get("prior_hash")} - {None}
        if current_hash not in allowed and not allow_unapplied:
            raise GuardError(f"rollback blocked by changed Mod files: {mod_id}")
    for mod_id, entry in plan.items():
        dest = target / mod_id
        prior_exists = bool(entry.get("prior_exists"))
        if prior_exists:
            backup = prior_dir / mod_id
            if not backup.is_dir():
                raise GuardError(f"rollback backup missing: {mod_id}")
            stage = target / f".fhd-rollback-{os.getpid()}-{mod_id}"
            if stage.exists():
                raise GuardError(f"rollback staging path exists: {stage.name}")
            shutil.copytree(backup, stage, symlinks=True)
            if dest.exists():
                preserve_user_state(dest, stage)
                shutil.rmtree(dest)
            os.replace(stage, dest)
        elif dest.exists():
            stage = target / f".fhd-rollback-{os.getpid()}-{mod_id}"
            stage.mkdir()
            preserve_user_state(dest, stage)
            shutil.rmtree(dest)
            if any(stage.iterdir()):
                os.replace(stage, dest)
            else:
                stage.rmdir()


def apply(
    source: Path, target: Path, state: Path, previous_archive: Path, deploy_root: Path
) -> None:
    if state.exists():
        raise GuardError("update recovery path already exists")
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or not target.is_dir():
        raise GuardError("deployment mods root is unsafe")
    bundled = source_mods(source)
    identity = verify_previous_identity(previous_archive, deploy_root)
    protected_ids = {mod_id for mod_id in bundled if receipt_has_install_state(target, mod_id)}
    eligible = set(bundled) - protected_ids
    with tempfile.TemporaryDirectory(prefix="fhd-previous-mods-") as extraction:
        archived = extract_previous_mods(previous_archive, Path(extraction) / "mods")
        with mod_locks(target, eligible):
            # Re-check receipt ownership under the same per-Mod locks used by installs.
            prior: dict[str, dict[str, object]] = {}
            for mod_id in sorted(eligible):
                dest = target / mod_id
                old = archived.get(mod_id)
                if receipt_has_install_state(target, mod_id):
                    protected_ids.add(mod_id)
                    continue
                if dest.is_symlink():
                    raise GuardError(f"existing Mod is a symlink: {mod_id}")
                if dest.exists():
                    if old is None or release_hash(dest) != release_hash(old):
                        raise GuardError(
                            f"existing Mod differs from verified deployed archive: {mod_id}"
                        )
                    prior_hash = release_hash(old)
                    prior_exists = True
                else:
                    prior_hash = None
                    prior_exists = False
                prior[mod_id] = {
                    "prior_exists": prior_exists,
                    "prior_hash": prior_hash,
                    "new_hash": release_hash(bundled[mod_id]),
                }
            state.mkdir(parents=True)
            prior_dir = state / "prior"
            prior_dir.mkdir()
            backup_complete = False
            try:
                for mod_id, entry in prior.items():
                    if entry["prior_exists"]:
                        shutil.copytree(target / mod_id, prior_dir / mod_id, symlinks=True)
                (state / "identity.json").write_text(
                    json.dumps(identity, sort_keys=True), encoding="utf-8"
                )
                (state / "plan.json").write_text(
                    json.dumps(prior, sort_keys=True), encoding="utf-8"
                )
                backup_complete = True
            finally:
                if not backup_complete:
                    shutil.rmtree(state, ignore_errors=True)
            stages: dict[str, Path] = {}
            mutated = False
            applied = False
            try:
                for mod_id, src in sorted(bundled.items()):
                    if mod_id not in prior:
                        continue
                    stage = target / f".fhd-stage-{os.getpid()}-{mod_id}"
                    if stage.exists():
                        raise GuardError(f"staging path already exists: {stage.name}")
                    stages[mod_id] = stage
                    shutil.copytree(src, stage, symlinks=False)
                    if (dest := target / mod_id).exists():
                        preserve_user_state(dest, stage)
                for mod_id, stage in stages.items():
                    dest = target / mod_id
                    if dest.exists():
                        mutated = True
                        shutil.rmtree(dest)
                    else:
                        mutated = True
                    os.replace(stage, dest)
                if protected_ids:
                    print(
                        "[mods-guard] skipped receipt-owned or unknown install state: "
                        + ",".join(sorted(protected_ids))
                    )
                print(
                    f"[mods-guard] updated {len(stages)} bundled Mod(s); preserved {len(protected_ids)} receipt-owned Mod(s)"
                )
                applied = True
            finally:
                if not applied:
                    for stage in stages.values():
                        if stage.exists():
                            shutil.rmtree(stage)
                    if mutated:
                        _rollback_locked(state, target, allow_unapplied=True)
                    else:
                        shutil.rmtree(state, ignore_errors=True)


def rollback(state: Path, target: Path) -> None:
    if not state.is_dir():
        return
    plan = load_state(state / "plan.json")
    with mod_locks(target, set(plan)):
        _rollback_locked(state, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    ap = sub.add_parser("apply")
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--target", type=Path, required=True)
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--previous-archive", type=Path, required=True)
    ap.add_argument("--deploy-root", type=Path, required=True)
    rb = sub.add_parser("rollback")
    rb.add_argument("--target", type=Path, required=True)
    rb.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "apply":
            apply(args.source, args.target, args.state, args.previous_archive, args.deploy_root)
        else:
            rollback(args.state, args.target)
    except (GuardError, OSError) as exc:
        print(f"[mods-guard] ERROR: {exc}", file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
