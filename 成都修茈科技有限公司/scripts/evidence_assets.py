#!/usr/bin/env python3
"""Verify and rebuild public evidence aliases from checksum-pinned source files.

The originals stay in Git until an accessible, verified archive is available.
Generated aliases are ordinary files at deployment time, never Git symlinks.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from functools import lru_cache
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
SITE = "成都修茈科技有限公司"
PUBLIC = f"{SITE}/capabilities/assets/evidence"
MANIFEST = f"{SITE}/data/capabilities/evidence-materialization.json"
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov"}
SECTIONS = ("retained_sources", "source_aliases", "assets")



@lru_cache(maxsize=1)
def archive_manifest_index() -> dict[str, dict]:
    """Map repo-relative evidence paths to archive metadata.

    Supports both MANIFEST shapes used by hygiene trains:
    - dict path -> {sha256, size}
    - list of {path, sha256, bytes}
    See FHD/docs/evidence/ARCHIVE_POINTER.md.
    """
    roots: list[Path] = []
    env = os.environ.get("XCMAX_ARCHIVE_ROOT")
    if env:
        roots.append(Path(env))
    roots.append(Path.home() / "XCMAX-archives")
    # Committed manifests travel with the repo so CI can verify without blobs.
    index: dict[str, dict] = {}
    in_repo = []
    # ROOT may not be defined yet at function definition time; resolve relative to this file.
    repo_root = Path(__file__).resolve().parents[2]
    in_repo_dir = repo_root / "FHD" / "docs" / "evidence" / "archives"
    if in_repo_dir.is_dir():
        roots.append(in_repo_dir)
    for root in roots:
        if not root.is_dir():
            continue
        for man in sorted(root.glob("evidence-bulk-*/MANIFEST.json")):
            try:
                data = json.loads(man.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            batch = data.get("batch") or man.parent.name
            files = data.get("files") or []
            if isinstance(files, dict):
                iterable = [
                    (rel, meta.get("sha256"), meta.get("bytes", meta.get("size", 0)))
                    for rel, meta in files.items()
                    if isinstance(meta, dict)
                ]
            else:
                iterable = [
                    (
                        item.get("path"),
                        item.get("sha256"),
                        item.get("bytes", item.get("size", 0)),
                    )
                    for item in files
                    if isinstance(item, dict)
                ]
            for rel, sha, nbytes in iterable:
                rel_s = str(rel or "").replace("\\", "/")
                if not rel_s or not sha:
                    continue
                index[rel_s] = {
                    "sha256": sha,
                    "bytes": int(nbytes or 0),
                    "batch": batch,
                    "archive_path": str(man.parent / rel_s),
                }
    return index

def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or ".." in path.parts or str(path) != value:
        raise ValueError(f"unsafe evidence path: {value!r}")
    return value


def inside(root: Path, rel: str) -> Path:
    path = root / relative(rel)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f"evidence path escapes its root or is a symlink: {rel}")
    return path


def load(root: Path = ROOT) -> dict:
    path = root / MANIFEST
    if not path.exists():
        return {"schema": "xcmax.evidence-materialization/v1", "assets": {}, "retained_sources": {}}
    return _load(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _load(path: str, _mtime: int) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(data)
    return data


def validate(data: dict) -> None:
    if data.get("schema") != "xcmax.evidence-materialization/v1":
        raise ValueError("unsupported evidence manifest schema")
    retained = data["retained_sources"]
    aliases = data.get("source_aliases", {})
    for name, entry in entries(data).items():
        relative(name)
        if name in aliases:
            if not name.startswith("FHD/docs/evidence/") or Path(name).suffix.lower() not in MEDIA:
                raise ValueError(f"invalid source media alias: {name}")
        elif "/" in name:
            raise ValueError(f"invalid public evidence alias: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError(f"invalid evidence alias or checksum: {name}")
        source = relative(entry["source"])
        if not source.startswith("FHD/docs/evidence/") and source not in {
            f"{PUBLIC}/{n}" for n in retained
        }:
            raise ValueError(f"unregistered evidence source: {source}")
        if not isinstance(entry["size"], int) or entry["size"] < 0:
            raise ValueError(f"invalid evidence size: {name}")
        if name in retained and source != f"{PUBLIC}/{name}":
            raise ValueError(f"retained evidence must be its own source: {name}")
        if source in aliases:
            raise ValueError(f"evidence must reference a canonical file, not another alias: {source}")
    if set(retained) & set(data["assets"]):
        raise ValueError("an evidence original cannot also be a generated alias")


def entries(data: dict) -> dict[str, dict]:
    return {name: entry for section in SECTIONS for name, entry in data.get(section, {}).items()}


def resolve_source(root: Path, rel: str) -> Path:
    """Resolve old public references even in a clean checkout without build output."""
    prefix = PUBLIC + "/"
    data = load(root)
    entry = data["assets"].get(rel[len(prefix):]) if rel.startswith(prefix) else data.get("source_aliases", {}).get(rel)
    return inside(root, entry["source"] if entry else rel)


def readable_evidence_source(root: Path, entry: dict) -> Path | None:
    """Return a readable path for an evidence entry, or None when only the archive
    MANIFEST verifies the bytes (CI without archive blobs mounted).
    """
    rel = relative(entry["source"])
    source = inside(root, rel)
    if source.is_file():
        return source
    meta = archive_manifest_index().get(rel)
    if not meta or meta.get("sha256") != entry["sha256"]:
        raise ValueError(f"missing original evidence: {entry['source']}")
    if int(meta.get("bytes") or 0) != int(entry["size"]):
        raise ValueError(f"archived evidence size mismatch: {entry['source']}")
    archive_path = Path(meta["archive_path"])
    if archive_path.is_file():
        return archive_path
    return None



def _pinned_entry(root: Path, rel: str) -> dict | None:
    """Find a materialization entry for a repo-relative evidence path or public alias."""
    data = load(root)
    norm = rel.replace("\\", "/")
    prefix = PUBLIC + "/"
    if norm.startswith(prefix):
        entry = data.get("assets", {}).get(norm[len(prefix):])
        if entry:
            return entry
    entry = data.get("source_aliases", {}).get(norm)
    if entry:
        return entry
    for section in SECTIONS:
        for _name, ent in (data.get(section) or {}).items():
            src = str(ent.get("source") or "").replace("\\", "/")
            if src == norm:
                return ent
    return None


def evidence_file_state(root: Path, rel: str) -> dict:
    """Return availability for an evidence path without requiring archive blobs.

    ``exists`` is True when bytes are readable locally OR the committed archive
    MANIFEST (+ materialization pin when present) verifies the checksum. CI
    checkouts without mounted blobs must keep the same verified/pending status
    as a full archive mount.
    """
    empty = {"exists": False, "path": None, "sha256": None, "size": None}
    if not rel or "://" in rel.split(":", 1)[0]:
        return empty
    try:
        path = resolve_source(root, rel)
    except ValueError:
        return empty
    if path.is_file():
        return {
            "exists": True,
            "path": path,
            "sha256": digest(path),
            "size": path.stat().st_size,
        }
    try:
        norm = relative(rel.replace("\\", "/"))
    except ValueError:
        return empty
    entry = _pinned_entry(root, norm)
    archive_key = relative(entry["source"]) if entry else norm
    meta = archive_manifest_index().get(archive_key)
    if entry:
        if not meta or meta.get("sha256") != entry["sha256"]:
            return empty
        if int(meta.get("bytes") or 0) != int(entry["size"]):
            return empty
        archive_path = Path(meta["archive_path"])
        return {
            "exists": True,
            "path": archive_path if archive_path.is_file() else None,
            "sha256": entry["sha256"],
            "size": int(entry["size"]),
        }
    if meta and meta.get("sha256"):
        archive_path = Path(meta["archive_path"])
        return {
            "exists": True,
            "path": archive_path if archive_path.is_file() else None,
            "sha256": meta["sha256"],
            "size": int(meta.get("bytes") or 0),
        }
    return empty


def verified_sources(root: Path, data: dict) -> dict[str, Path]:
    sources = {}
    archived = 0
    archive_index = archive_manifest_index()
    for name, entry in entries(data).items():
        source = inside(root, entry["source"])
        rel = relative(entry["source"])
        if source not in sources:
            if source.is_file():
                sources[source] = (source.stat().st_size, digest(source))
            else:
                meta = archive_index.get(rel)
                if not meta or meta.get("sha256") != entry["sha256"]:
                    raise ValueError(
                        f"missing original evidence: {entry['source']} (alias {name})"
                    )
                if int(meta.get("bytes") or 0) != int(entry["size"]):
                    raise ValueError(
                        f"archived evidence size mismatch: {entry['source']}"
                    )
                # Treat as verified via external archive (not present in git tree).
                sources[source] = (int(entry["size"]), entry["sha256"])
                archived += 1
        if sources[source] != (entry["size"], entry["sha256"]):
            raise ValueError(f"original evidence checksum mismatch: {entry['source']}")
    if archived:
        print(f"[evidence-assets] INFO: {archived} originals verified via XCMAX-archives manifests")
    return {name: inside(root, entry["source"]) for name, entry in data["assets"].items()}


def materialize(root: Path = ROOT, destination: Path | None = None) -> int:
    data = load(root)
    verified_sources(root, data)  # Verify all inputs before creating output.
    publications = data["assets"]
    if destination is not None:
        publications = {**publications, **data["retained_sources"]}
    output = destination or inside(root, PUBLIC)
    if output.is_symlink():
        raise ValueError("evidence output must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    published = 0
    skipped = 0
    for name, entry in publications.items():
        source = readable_evidence_source(root, entry)
        if source is None:
            # Manifest-verified historical media: capability-center serves via COS;
            # CI without archive mounts skips local publication of those bytes.
            skipped += 1
            continue
        copy_verified(source, inside(output, name), entry)
        published += 1
    if skipped:
        print(
            f"[evidence-assets] INFO: skipped {skipped} archive-only assets "
            "(manifest-verified; blob not mounted)"
        )
    # Reviewed records keep their original paths and checksums. Reconstruct that
    # layout for historical scripts without changing or re-certifying the records.
    if destination is None:
        materialize_sources(root, data)
    return published + (len(data.get("source_aliases", {})) if destination is None else 0)


def materialize_sources(root: Path = ROOT, verified: dict | None = None) -> int:
    data = verified if verified is not None else load(root)
    if verified is None:
        verified_sources(root, data)
    for alias, entry in data.get("source_aliases", {}).items():
        copy_verified(inside(root, entry["source"]), inside(root, alias), entry, overwrite=False)
    return len(data.get("source_aliases", {}))


def copy_verified(source: Path, target: Path, entry: dict, overwrite: bool = True) -> None:
    if target.is_file() and target.stat().st_size == entry["size"] and digest(target) == entry["sha256"]:
        return
    if target.exists() and not overwrite:
        raise ValueError(f"refusing to overwrite different historical evidence alias: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".evidence-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream, source.open("rb") as original:
            shutil.copyfileobj(original, stream)
        if digest(Path(temporary)) != entry["sha256"]:
            raise ValueError(f"evidence changed during publication: {target.name}")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def record(root: Path, sources: dict[str, str], withdrawn: set[str] = frozenset()) -> None:
    """Extend the alias manifest when the existing capability builder adds evidence."""
    data = copy.deepcopy(load(root))
    for name, rel in sources.items():
        source = resolve_source(root, rel)
        canonical = source.relative_to(root).as_posix()
        if name in data["retained_sources"]:
            continue
        data["assets"][name] = {"source": canonical, "sha256": digest(source), "size": source.stat().st_size}
    for name in withdrawn:
        data["assets"].pop(name, None)
    validate(data)  # Reject unsafe sources before replacing the reviewed manifest.
    path = root / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {key: value for key, value in data.items() if key not in SECTIONS}
    text = json.dumps(header, ensure_ascii=False, indent=2)[:-2]
    for section in SECTIONS:
        rows = ",\n".join(f"    {json.dumps(name, ensure_ascii=False)}: "
                          f"{json.dumps(entry, ensure_ascii=False, separators=(',', ':'))}"
                          for name, entry in sorted(data.get(section, {}).items()))
        text += f',\n  "{section}": {{\n{rows}\n  }}'
    path.write_text(text + "\n}\n", encoding="utf-8")


def archive(root: Path, target: Path) -> None:
    """Create a local, content-addressed recovery archive; never remove originals."""
    data = load(root)
    verified_sources(root, data)
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as output, tarfile.open(fileobj=output, mode="w") as bundle:
        payload = json.dumps(data, ensure_ascii=False).encode()
        header = tarfile.TarInfo("manifest.json")
        header.size = len(payload)
        bundle.addfile(header, io.BytesIO(payload))
        seen = set()
        for entry in entries(data).values():
            checksum = entry["sha256"]
            if checksum in seen:
                continue
            seen.add(checksum)
            header = tarfile.TarInfo("objects/" + checksum)
            header.size = entry["size"]
            with inside(root, entry["source"]).open("rb") as stream:
                bundle.addfile(header, stream)


def restore(root: Path, source: Path) -> None:
    """Recover declared originals only; never extract arbitrary archive paths."""
    data = load(root)
    if not data["assets"]:
        raise ValueError("restore requires the reviewed manifest from the repository")
    with tarfile.open(source, "r:") as bundle, tempfile.TemporaryDirectory(prefix="evidence-restore-") as tmp:
        expected = {e["sha256"]: e for e in entries(data).values()}
        for checksum, entry in expected.items():
            member = bundle.getmember("objects/" + checksum)
            if not member.isfile() or member.size != entry["size"]:
                raise ValueError(f"invalid archived evidence object: {checksum}")
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError(f"missing archived evidence object: {checksum}")
            with stream, (Path(tmp) / checksum).open("wb") as output:
                shutil.copyfileobj(stream, output)
            if digest(Path(tmp) / checksum) != checksum:
                raise ValueError(f"archived evidence checksum mismatch: {checksum}")
        for entry in entries(data).values():
            target = inside(root, entry["source"])
            if target.exists() and digest(target) != entry["sha256"]:
                raise ValueError(f"refusing to overwrite different original: {entry['source']}")
        for entry in entries(data).values():
            target = inside(root, entry["source"])
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(tmp) / entry["sha256"], target)
    verified_sources(root, data)


def guard(root: Path, base: str | None = None) -> None:
    data = load(root)
    media_registry = root / "config/media-aliases.json"
    static_aliases = json.loads(media_registry.read_text()).get("aliases", {}) if media_registry.is_file() else {}
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage", "-z"])
    blobs: dict[str, list[str]] = {}
    for row in tracked.split(b"\0"):
        if not row:
            continue
        meta, raw = row.split(b"\t", 1)
        path = raw.decode()
        if path in static_aliases:
            raise ValueError(f"generated media alias is tracked; use its canonical source: {path}")
        if path in data.get("source_aliases", {}):
            raise ValueError(f"duplicate evidence alias is tracked; use its canonical file: {path}")
        if path.startswith(PUBLIC + "/") and path[len(PUBLIC) + 1:] not in data["retained_sources"]:
            raise ValueError(f"generated evidence is tracked; keep only its source and manifest: {path}")
        if Path(path).suffix.lower() in MEDIA:
            blobs.setdefault(meta.split()[1].decode(), []).append(path)
    if base:
        changed = set(subprocess.check_output([
            "git", "-C", str(root), "diff", "--name-only", "--diff-filter=ACMRT", "-z", base, "--"
        ]).decode().split("\0"))
        for paths in blobs.values():
            if len(paths) > 1 and changed.intersection(paths):
                raise ValueError(f"new duplicate media must reference its existing source: {paths}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "materialize", "materialize-sources", "archive", "restore", "guard"))
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--base")
    args = parser.parse_args()
    try:
        if not (args.repo_root / MANIFEST).is_file():
            raise ValueError("the reviewed evidence manifest is missing")
        if args.action == "check":
            verified_sources(args.repo_root, load(args.repo_root))
        elif args.action == "materialize":
            materialize(args.repo_root, args.destination)
        elif args.action == "materialize-sources":
            materialize_sources(args.repo_root)
        elif args.action == "guard":
            guard(args.repo_root, args.base)
        elif args.archive is None:
            parser.error("archive/restore requires --archive")
        elif args.action == "archive":
            archive(args.repo_root, args.archive)
        else:
            restore(args.repo_root, args.archive)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"[evidence-assets] FAIL: {exc}")
        return 1
    print(f"[evidence-assets] {args.action}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
