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
MODEL_REPO = "Qdrant/bge-small-zh-v1.5"
MODEL_REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
# MIT model; verified against this immutable upstream revision before native parsing.
# https://huggingface.co/Qdrant/bge-small-zh-v1.5/tree/46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59
MODEL_HASHES = {
    "model_optimized.onnx": "1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38",
    "config.json": "9088751d39abbf86ec3d19ffca92ad62ad19075f7e59712e6c71217fa125d1d3",
    "ort_config.json": "97e78d1d21c2eb719e865b018f17915df6a12ed987446eb7f3f3a783a5afb1e1",
    "special_tokens_map.json": "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
    "tokenizer.json": "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26",
    "tokenizer_config.json": "e6f3b96db926a37d4039995fbf5ad17de158dfb8f6343d607e4dbaad18d75f5a",
    "vocab.txt": "45bbac6b341c319adc98a532532882e91a9cefc0329aa57bac9ae761c27b291c",
}
MANIFEST = "xcmax-model.json"


def pinned_model_dir(root: Path) -> Path:
    return root / ("models--" + MODEL_REPO.replace("/", "--")) / "snapshots" / MODEL_REVISION


def verify_model_files(snapshot: Path) -> None:
    for name, expected in MODEL_HASHES.items():
        path = snapshot / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"pinned model file missing or not regular: {name}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"pinned model file hash mismatch: {name}")


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
    snapshot = pinned_model_dir(root)
    verify_model_files(snapshot)
    if (snapshot.parent.parent / "refs/main").read_text() != MODEL_REVISION:
        raise ValueError("memory model cache revision mismatch")
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL, cache_dir=str(root), local_files_only=True)
    vectors = list(model.embed(["企业记忆离线验收"]))
    if len(vectors) != 1 or not len(vectors[0]):
        raise ValueError("offline memory embedding unavailable")
    return len(vectors[0])


def verify(root: Path) -> dict:
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if (
        data.get("model") != MODEL
        or data.get("revision") != MODEL_REVISION
        or data.get("sha256") != artifact_digest(root)
    ):
        raise ValueError("memory model artifact hash mismatch")
    if data.get("dimensions") != probe(root):
        raise ValueError("memory model dimension mismatch")
    return data


def provision(root: Path) -> dict:
    from huggingface_hub import snapshot_download

    if (root / MANIFEST).is_file():
        try:
            return verify(root)
        except (OSError, ValueError, RuntimeError):
            pass
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="memory-model-", dir=root.parent) as temp:
        work = Path(temp)
        downloaded = Path(
            snapshot_download(
                repo_id=MODEL_REPO,
                revision=MODEL_REVISION,
                cache_dir=work / "download",
                allow_patterns=list(MODEL_HASHES),
            )
        )
        staged = work / "staged"
        snapshot = pinned_model_dir(staged)
        snapshot.mkdir(parents=True)
        for name in MODEL_HASHES:
            shutil.copyfile(downloaded / name, snapshot / name)
        verify_model_files(snapshot)
        refs = snapshot.parent.parent / "refs"
        refs.mkdir()
        (refs / "main").write_text(MODEL_REVISION)
        dimensions = probe(staged)
        manifest = {
            "model": MODEL,
            "revision": MODEL_REVISION,
            "dimensions": dimensions,
            "sha256": artifact_digest(staged),
        }
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    output = args.output
    if output is None:
        script = Path(__file__).resolve()
        if script.parent.name != "dev" or script.parent.parent.name != "scripts":
            parser.error("--output is required when the provisioner is copied outside scripts/dev")
        output = script.parent.parent.parent / "resources" / "models" / "fastembed"
    operation = verify if args.verify_only else provision
    print(json.dumps(operation(output.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
