"""Verify host identity against the signed standard OTA feed and main history.

Uses the same release origin and Ed25519 root as the desktop updater. Neither
client-supplied URLs nor client assertions of branch membership are accepted.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from modstore_server.release_convergence import _fetch_json, _fetch_text

UPDATE_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAO6AeYJ05qwfSgpGR7+FZiL6cY0uGtSJVRqIiws3P6N8=\n"
    "-----END PUBLIC KEY-----\n"
)
_PREFIX = "signature: ed25519:"
_FEEDS = (
    "https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml",
    "https://xiu-ci.com/releases/stable/enterprise/latest.yml",
)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _archive_path(host_sha: str) -> Path:
    from modstore_server.mod_scaffold_runner import modstore_library_path

    return (
        Path(modstore_library_path()).resolve().parent
        / "verified-host-releases"
        / (host_sha + ".yml")
    )


def _remember_feed(host_sha: str, text: str) -> None:
    path = _archive_path(host_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _signed_release(text: str, host_sha: str, source_url: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    signatures = [line[len(_PREFIX) :] for line in lines if line.startswith(_PREFIX)]
    if len(signatures) != 1:
        return None
    signed = "\n".join(line for line in lines if not line.startswith(_PREFIX)).rstrip()
    key = serialization.load_pem_public_key(UPDATE_PUBLIC_KEY.encode())
    if not isinstance(key, Ed25519PublicKey):
        return None
    key.verify(base64.b64decode(signatures[0], validate=True), signed.encode("utf-8"))
    data = yaml.safe_load(signed)
    if not isinstance(data, dict) or data.get("buildSha") != host_sha:
        return None
    version = str(data.get("productVersion") or data.get("version") or "")
    release_id = str(data.get("releaseId") or "")
    files = data.get("files")
    if not version or not release_id or not isinstance(files, list) or not files:
        return None
    artifacts = []
    for item in files:
        if not isinstance(item, dict):
            return None
        digest = str(item.get("sha512") or "")
        if len(base64.b64decode(digest, validate=True)) != 64:
            return None
        if not str(item.get("url") or "") or int(item.get("size") or 0) <= 0:
            return None
        artifacts.append({"file": item["url"], "sha512": digest, "size": int(item["size"])})
    return {
        "git_sha": host_sha,
        "source_ref": "main",
        "version": version,
        "release_id": release_id,
        "artifacts": artifacts,
        "signed_metadata_sha256": hashlib.sha256(signed.encode()).hexdigest(),
        "source_url": source_url,
        "signature_algorithm": "Ed25519",
    }


def resolve_host_release(host_sha: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9a-f]{40}", host_sha):
        return None
    cached = _CACHE.get(host_sha)
    if cached and time.monotonic() - cached[0] < 300:
        return dict(cached[1])
    sources: list[tuple[str, str | None]] = [(url, None) for url in _FEEDS]
    try:
        archived = _archive_path(host_sha).read_text(encoding="utf-8")
        sources.insert(0, (_FEEDS[0], archived))
    except OSError:
        pass
    for url, archived_text in sources:
        try:
            text = archived_text if archived_text is not None else _fetch_text(url)
            release = _signed_release(text, host_sha, url)
            if release is None:
                continue
            comparison = _fetch_json(
                f"https://api.github.com/repos/42433422/XCMAX/compare/main...{host_sha}"
            )
            if comparison.get("status") not in {"behind", "identical"}:
                continue
            if (comparison.get("merge_base_commit") or {}).get("sha") != host_sha:
                continue
            release["main_comparison_url"] = comparison.get("html_url", "")
            if archived_text is None:
                try:
                    _remember_feed(host_sha, text)
                except OSError:
                    pass
            _CACHE[host_sha] = (time.monotonic(), release)
            return dict(release)
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            TypeError,
            InvalidSignature,
            yaml.YAMLError,
        ):
            continue
    return None
