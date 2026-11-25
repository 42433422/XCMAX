#!/usr/bin/env python3
"""Prepare and verify the offline semantic memory model in a release resource tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

MODEL = "BAAI/bge-small-zh-v1.5"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "resources" / "models" / "fastembed"
MANIFEST = "xcmax-model.json"


def artifact_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or path.name == MANIFEST or ".locks" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError("release model files must be regular files")
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def probe(root: Path) -> int:
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL, cache_dir=str(root), local_files_only=True)
    vectors = list(model.embed(["企业记忆离线验收"]))
    if len(vectors) != 1 or not len(vectors[0]):
        raise ValueError("offline memory embedding unavailable")
    return len(vectors[0])


def verify(root: Path) -> dict:
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if data.get("model") != MODEL or data.get("sha256") != artifact_digest(root):
        raise ValueError("memory model artifact hash mismatch")
    if data.get("dimensions") != probe(root):
        raise ValueError("memory model dimension mismatch")
    return data


def provision(root: Path) -> dict:
    from fastembed import TextEmbedding

    if (root / MANIFEST).is_file():
        try:
            return verify(root)
        except (OSError, ValueError, RuntimeError):
            pass
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="memory-model-", dir=root.parent) as temp:
        work = Path(temp)
        downloaded = work / "download"
        model = TextEmbedding(model_name=MODEL, cache_dir=str(downloaded))
        list(model.embed(["企业记忆构建预热"]))
        staged = work / "staged"
        # Hugging Face cache may contain snapshot links. Copy their bytes rather
        # than shipping symlinks that the immutable release verifier rejects.
        shutil.copytree(
            downloaded, staged, symlinks=False, ignore=shutil.ignore_patterns(".locks", ".no_exist")
        )
        dimensions = probe(staged)
        manifest = {"model": MODEL, "dimensions": dimensions, "sha256": artifact_digest(staged)}
        (staged / MANIFEST).write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        verify(staged)
        previous = work / "previous"
        if root.exists():
            os.replace(root, previous)
        try:
            os.replace(staged, root)
        except OSError:
            if previous.exists():
                os.replace(previous, root)
            raise
    return verify(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    operation = verify if args.verify_only else provision
    print(json.dumps(operation(args.output.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
