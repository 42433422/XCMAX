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


def verified_sources(root: Path, data: dict) -> dict[str, Path]:
    sources = {}
    for name, entry in entries(data).items():
        source = inside(root, entry["source"])
        if source not in sources:
            if not source.is_file():
                raise ValueError(f"missing original evidence: {entry['source']} (alias {name})")
            sources[source] = (source.stat().st_size, digest(source))
        if sources[source] != (entry["size"], entry["sha256"]):
            raise ValueError(f"original evidence checksum mismatch: {entry['source']}")
    return {name: inside(root, entry["source"]) for name, entry in data["assets"].items()}


def materialize(root: Path = ROOT, destination: Path | None = None) -> int:
    data = load(root)
    sources = verified_sources(root, data)  # Verify all inputs before creating output.
    publications = data["assets"]
    if destination is not None:
        publications = {**publications, **data["retained_sources"]}
        sources.update({name: inside(root, entry["source"]) for name, entry in data["retained_sources"].items()})
    output = destination or inside(root, PUBLIC)
    if output.is_symlink():
        raise ValueError("evidence output must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        copy_verified(source, inside(output, name), publications[name])
    # Reviewed records keep their original paths and checksums. Reconstruct that
    # layout for historical scripts without changing or re-certifying the records.
    if destination is None:
        materialize_sources(root, data)
    return len(sources) + (len(data.get("source_aliases", {})) if destination is None else 0)


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
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage", "-z"])
    blobs: dict[str, list[str]] = {}
    for row in tracked.split(b"\0"):
        if not row:
            continue
        meta, raw = row.split(b"\t", 1)
        path = raw.decode()
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
