#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""Stamp and verify the immutable FHD admin-console release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

IDENTITY_NAME = ".release-identity.json"
SCHEMA = "xcmax.admin-console.release.v1"


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.git_sha = ""
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and values.get("name") == "xcmax-release-git-sha":
            self.git_sha = str(values.get("content") or "").strip()
        candidate = values.get("src") if tag == "script" else values.get("href")
        if candidate and candidate.startswith("/admin/"):
            self.assets.append(candidate)


def _parse_index(text: str) -> _IndexParser:
    parser = _IndexParser()
    parser.feed(text)
    return parser


def tree_sha256(root: Path) -> str:
    """Hash relative names and bytes, excluding the self-referential identity file."""
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and path.name != IDENTITY_NAME
    )
    if not files:
        raise ValueError("admin console contains no files")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        size = path.stat().st_size
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _validate_identity(
    payload: Any,
    expected_git_sha: str,
    expected_sha256: str,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("admin identity is not an object")
    schema = str(payload.get("schema") or "")
    git_sha = str(payload.get("git_sha") or "")
    sha256 = str(payload.get("sha256") or "")
    if schema != SCHEMA:
        raise ValueError(f"admin identity schema mismatch: {schema or '<missing>'}")
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise ValueError("admin identity git_sha is not a full lowercase commit SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("admin identity sha256 is invalid")
    if expected_git_sha and git_sha != expected_git_sha:
        raise ValueError(f"admin git SHA mismatch expected={expected_git_sha} actual={git_sha}")
    if expected_sha256 and sha256 != expected_sha256:
        raise ValueError(f"admin asset SHA256 mismatch expected={expected_sha256} actual={sha256}")
    return {"git_sha": git_sha, "sha256": sha256}


def verify_root(
    root: Path,
    expected_git_sha: str = "",
    expected_sha256: str = "",
) -> dict[str, str]:
    index = root / "index.html"
    identity_path = root / IDENTITY_NAME
    if not index.is_file() or not identity_path.is_file():
        raise ValueError("admin release is missing index.html or identity")
    parsed = _parse_index(index.read_text(encoding="utf-8"))
    identity = _validate_identity(
        json.loads(identity_path.read_text(encoding="utf-8")),
        expected_git_sha,
        expected_sha256,
    )
    if parsed.git_sha != identity["git_sha"]:
        raise ValueError("admin index Git SHA does not match release identity")
    if not any(asset.endswith(".js") for asset in parsed.assets):
        raise ValueError("admin index references no JavaScript bundle")
    for asset in parsed.assets:
        relative = asset.removeprefix("/admin/")
        if not (root / relative).is_file():
            raise ValueError(f"admin index references a missing asset: {asset}")
    actual = tree_sha256(root)
    if actual != identity["sha256"]:
        raise ValueError(f"admin asset tree mismatch expected={identity['sha256']} actual={actual}")
    return identity


def stamp_root(root: Path, git_sha: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise ValueError("stamp requires a full lowercase Git commit SHA")
    index = root / "index.html"
    if not index.is_file():
        raise ValueError("admin release is missing index.html")
    parsed = _parse_index(index.read_text(encoding="utf-8"))
    if parsed.git_sha != git_sha:
        raise ValueError(
            "built admin index Git SHA mismatch "
            f"expected={git_sha} actual={parsed.git_sha or '<missing>'}"
        )
    sha256 = tree_sha256(root)
    payload = {"git_sha": git_sha, "schema": SCHEMA, "sha256": sha256}
    temporary = root / f"{IDENTITY_NAME}.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(root / IDENTITY_NAME)
    return verify_root(root, git_sha, sha256)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "xcmax-release-verifier/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise ValueError(f"HTTP {response.status} for {url}")
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError(f"admin release URL is unavailable: {url}: {exc}") from exc


def verify_url(
    base_url: str,
    expected_git_sha: str,
    expected_sha256: str,
) -> dict[str, str]:
    base = base_url.rstrip("/") + "/"
    parsed = _parse_index(_fetch(base).decode("utf-8"))
    identity = _validate_identity(
        json.loads(_fetch(urllib.parse.urljoin(base, IDENTITY_NAME)).decode("utf-8")),
        expected_git_sha,
        expected_sha256,
    )
    if parsed.git_sha != identity["git_sha"]:
        raise ValueError("served admin index Git SHA does not match identity")
    if not any(asset.endswith(".js") for asset in parsed.assets):
        raise ValueError("served admin index references no JavaScript bundle")
    for asset in parsed.assets:
        _fetch(urllib.parse.urljoin(base, asset.removeprefix("/admin/")))
    return identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--stamp-git-sha", default="")
    parser.add_argument("--expected-git-sha", default="")
    parser.add_argument("--expected-sha256", default="")
    args = parser.parse_args()
    try:
        if args.stamp_git_sha:
            if args.root is None:
                raise ValueError("--stamp-git-sha requires --root")
            result = stamp_root(args.root, args.stamp_git_sha)
        elif args.root is not None:
            result = verify_root(
                args.root,
                args.expected_git_sha,
                args.expected_sha256,
            )
        elif args.base_url:
            if not args.expected_git_sha or not args.expected_sha256:
                raise ValueError("URL verification requires expected Git and asset SHA")
            result = verify_url(
                args.base_url,
                args.expected_git_sha,
                args.expected_sha256,
            )
        else:
            raise ValueError("provide --root or --base-url")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"[admin-release] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
