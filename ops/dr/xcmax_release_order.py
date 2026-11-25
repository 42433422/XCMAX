#!/usr/bin/env python3
"""Select DR release components without allowing automatic rollback."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENTS = ("modstore", "fhd")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_timestamp(path: Path) -> int:
    value = read_text(path)
    return int(value) if value.isdigit() else 0


def current_timestamp(incoming: Path, state: Path, component: str) -> int:
    timestamp = read_timestamp(state / f"release_applied_{component}_created_at")
    if timestamp:
        return timestamp

    current_sha = read_text(state / f"release_applied_{component}_sha")
    if not SHA_RE.fullmatch(current_sha):
        return 0
    return read_timestamp(incoming / current_sha / f"{component}.CREATED_AT")


def should_apply(incoming: Path, state: Path, candidate: Path, component: str) -> bool:
    sha = candidate.name
    if not SHA_RE.fullmatch(sha):
        return False
    if not (candidate / f"{component}.MANIFEST.txt").is_file():
        return False
    if read_text(state / f"release_applied_{component}_sha") == sha:
        return False
    candidate_timestamp = read_timestamp(candidate / f"{component}.CREATED_AT")
    return candidate_timestamp > 0 and candidate_timestamp > current_timestamp(
        incoming, state, component
    )


def select_release(incoming: Path, state: Path) -> Path | None:
    candidates: list[tuple[int, str, Path]] = []
    if not incoming.is_dir():
        return None

    for candidate in incoming.iterdir():
        if not candidate.is_dir() or not SHA_RE.fullmatch(candidate.name):
            continue
        component_timestamps = [
            read_timestamp(candidate / f"{component}.CREATED_AT")
            for component in COMPONENTS
            if should_apply(incoming, state, candidate, component)
        ]
        if component_timestamps:
            candidates.append((max(component_timestamps), candidate.name, candidate))
    if not candidates:
        return None
    return max(candidates)[2]


def release_identity(path: Path, sha: str, component: str) -> dict[str, str]:
    """Use the existing immutable release manifest, never HTTP status alone."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("release manifest is not a regular file")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid release manifest")
    version = manifest.get("product_version" if component == "modstore" else "version")
    digest = manifest.get("artifact_sha256" if component == "modstore" else "sha256")
    identity = {
        "git_sha": sha,
        "product_version": version,
        "artifact_sha256": digest,
        "release_id": manifest.get("release_id"),
    }
    if (
        not SHA_RE.fullmatch(sha)
        or manifest.get("git_sha") != sha
        or not isinstance(version, str)
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", version)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or identity["release_id"] != f"xcagi-{version}-{sha}"
    ):
        raise ValueError("release identity is missing or mismatched")
    return identity


def verify_health(path: Path, sha: str, component: str, observed: object) -> None:
    expected = release_identity(path, sha, component)
    if not isinstance(observed, dict):
        raise ValueError("invalid health response")
    if component == "modstore":
        if observed.get("ok") is not True:
            raise ValueError("MODstore health is not ready")
        actual = observed
        # The existing public MODstore contract carries the product version in
        # release_id; it deliberately has no separate product_version field.
        expected.pop("product_version")
    else:
        if observed.get("status") != "healthy" or observed.get("degradedReasons"):
            raise ValueError("FHD health is not ready")
        actual = observed.get("build")
        if not isinstance(actual, dict):
            raise ValueError("FHD build identity is missing")
        for field in ("git_sha", "release_id"):
            if observed.get(field) != expected[field]:
                raise ValueError("FHD public identity mismatch")
    if any(actual.get(field) != value for field, value in expected.items()):
        raise ValueError("runtime identity mismatch")


def verify_input(candidate: Path, sha: str, component: str) -> str:
    manifest_name = (
        "modstore-release.json" if component == "modstore" else "fhd-manifest.json"
    )
    identity = release_identity(candidate / manifest_name, sha, component)
    artifact = "modstore-source.tar.gz"
    expected = {manifest_name, artifact, "modstore-static.tar.gz"}
    if component == "fhd":
        manifest = json.loads((candidate / manifest_name).read_text(encoding="utf-8"))
        artifact = manifest.get("artifact")
        if (
            not isinstance(artifact, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", artifact)
            or manifest.get("deploy_mode", "tarball") != "tarball"
        ):
            raise ValueError("DR requires the original FHD tarball")
        expected = {manifest_name, artifact}
    entries = {}
    for line in (
        (candidate / f"{component}.MANIFEST.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        match = re.fullmatch(
            r"([0-9a-f]{64}) [ *](?:\./)?([A-Za-z0-9][A-Za-z0-9._-]*)", line
        )
        if not match or match[2] in entries or match[2] not in expected:
            raise ValueError("invalid or duplicate archive manifest entry")
        entries[match[2]] = match[1]
    if entries.keys() != expected:
        raise ValueError("release archive manifest is incomplete")
    for name, digest in entries.items():
        source = candidate / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("release archive is not a regular file")
        with source.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ValueError("release archive digest mismatch")
    if component == "fhd" and entries[artifact] != identity["artifact_sha256"]:
        raise ValueError("FHD artifact differs from original manifest")
    if component == "modstore":
        with gzip.open(candidate / artifact, "rb") as handle:
            if (
                hashlib.file_digest(handle, "sha256").hexdigest()
                != identity["artifact_sha256"]
            ):
                raise ValueError("MODstore artifact differs from original manifest")
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incoming", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("select")

    should_parser = subparsers.add_parser("should-apply")
    should_parser.add_argument("--candidate", type=Path, required=True)
    should_parser.add_argument("--component", choices=COMPONENTS, required=True)

    timestamp_parser = subparsers.add_parser("created-at")
    timestamp_parser.add_argument("--candidate", type=Path, required=True)
    timestamp_parser.add_argument("--component", choices=COMPONENTS, required=True)
    for name in ("verify-health", "verify-input", "verify-identity"):
        check = subparsers.add_parser(name)
        check.add_argument("--candidate", type=Path, required=True)
        check.add_argument("--component", choices=COMPONENTS, required=True)
        check.add_argument("--sha", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command in ("verify-health", "verify-input", "verify-identity"):
        try:
            if args.command == "verify-input":
                print(verify_input(args.candidate, args.sha, args.component))
            elif args.command == "verify-identity":
                release_identity(args.candidate, args.sha, args.component)
            else:
                verify_health(
                    args.candidate, args.sha, args.component, json.load(sys.stdin)
                )
        except (OSError, ValueError, TypeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    if args.command == "select":
        selected = select_release(args.incoming, args.state)
        if selected is not None:
            print(selected)
        return 0
    if args.command == "should-apply":
        return (
            0
            if should_apply(args.incoming, args.state, args.candidate, args.component)
            else 3
        )

    timestamp = read_timestamp(args.candidate / f"{args.component}.CREATED_AT")
    if timestamp <= 0:
        return 4
    print(timestamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
