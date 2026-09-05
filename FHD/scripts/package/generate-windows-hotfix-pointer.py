#!/usr/bin/env python3
"""Generate non-publishable metadata for an unsigned Windows test artifact."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--release-metadata-source", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_release(metadata_path: Path, version: str) -> dict:
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        payload.get("version_lock") != version
        or payload.get("download_version") != version
    ):
        raise ValueError(
            "release metadata version does not match requested hotfix version"
        )
    history = payload.get("release_history")
    if not isinstance(history, list) or not history:
        raise ValueError("release metadata must contain release_history")
    release = history[0]
    if not isinstance(release, dict) or release.get("version") != version:
        raise ValueError(
            "release_history[0].version does not match requested hotfix version"
        )
    for key in ("date", "title", "channel"):
        if not isinstance(release.get(key), str) or not release[key].strip():
            raise ValueError(f"release_history[0].{key} must be a non-empty string")
    notes = release.get("notes")
    if (
        not isinstance(notes, list)
        or not notes
        or not all(isinstance(note, str) and note.strip() for note in notes)
    ):
        raise ValueError("release_history[0].notes must contain non-empty strings")
    return release


def main() -> int:
    args = parse_args()
    version = args.version.strip().lstrip("vV")
    git_sha = args.git_sha.strip().lower()
    artifact = Path(args.artifact)
    metadata_path = Path(args.release_metadata_source)
    output = Path(args.output)

    if not VERSION_RE.fullmatch(version):
        print(f"[error] invalid four-part version: {version}", file=sys.stderr)
        return 1
    if not SHA_RE.fullmatch(git_sha):
        print(
            "[error] git SHA must contain 40 or 64 hexadecimal characters",
            file=sys.stderr,
        )
        return 1
    if not artifact.is_file():
        print(
            f"[error] Windows interim installer not found: {artifact}", file=sys.stderr
        )
        return 1

    try:
        release = load_release(metadata_path, version)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    filename = artifact.name
    expected_filename = f"XCAGI-Enterprise-Setup-{version}-x64-macalign.exe"
    if filename != expected_filename:
        print(
            f"[error] interim installer filename mismatch: {filename} != {expected_filename}",
            file=sys.stderr,
        )
        return 1
    if not args.artifact_url.endswith("/" + filename):
        print(
            "[error] artifact URL filename does not match the installer",
            file=sys.stderr,
        )
        return 1

    payload = {
        "schema": "xcagi.windows_interim_release/v1",
        "version": version,
        "channel": "enterprise-quarantine",
        "git_sha": git_sha,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "download_allowed": False,
        "signature_status": "unsigned",
        "warning": (
            "此 Windows 产物未完成 Authenticode 代码签名，仅可用于受控测试设备；"
            "禁止公开下载或写入任何更新通道。"
        ),
        "artifact": {
            "filename": filename,
            "url": args.artifact_url,
            "size": artifact.stat().st_size,
            "sha256": sha256(artifact),
            "arch": "x64",
            "platform": "windows",
        },
        "release": release,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[ok] wrote {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
