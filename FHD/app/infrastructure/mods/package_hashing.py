"""Canonical hashing and signature-message helpers for MOD packages."""

from __future__ import annotations

import hashlib
import os


def require_signed_mods() -> bool:
    """Return whether signature verification is fail-closed for this runtime."""
    return os.environ.get("XCAGI_REQUIRE_SIGNED_MODS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def compute_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """Calculate a file digest without loading the whole file into memory."""
    hash_func = hashlib.new(algorithm)
    with open(file_path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(8192), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


SIGNATURE_EXCLUDE_PREFIXES: tuple[str, ...] = ("META-INF/", "META-INF" + os.sep)


def is_excluded_rel_path(rel_path: str, exclude_prefixes: tuple[str, ...]) -> bool:
    """Return whether a normalized relative path has an excluded prefix."""
    normalized = rel_path.replace(os.sep, "/")
    for prefix in exclude_prefixes:
        normalized_prefix = prefix.replace(os.sep, "/")
        if normalized == normalized_prefix.rstrip("/") or normalized.startswith(normalized_prefix):
            return True
    return False


def build_signed_message(manifest_id: str, version: str, content_hash: str) -> bytes:
    """Bind manifest identity and version to the signed content digest."""
    return f"{manifest_id}:{version}:{content_hash}".encode()


def compute_members_hash(
    members: list[tuple[str, bytes]],
    algorithm: str = "sha256",
    exclude_prefixes: tuple[str, ...] = SIGNATURE_EXCLUDE_PREFIXES,
) -> str:
    """Calculate the canonical digest for in-memory package members."""
    normalized_members: list[tuple[str, bytes]] = []
    for archive_name, content in members:
        relative_path = archive_name.replace(os.sep, "/")
        if is_excluded_rel_path(relative_path, exclude_prefixes):
            continue
        if relative_path.rsplit("/", 1)[-1].startswith("."):
            continue
        normalized_members.append((relative_path, content))

    hash_func = hashlib.new(algorithm)
    for relative_path, content in sorted(normalized_members, key=lambda item: item[0]):
        file_hash = hashlib.new(algorithm)
        file_hash.update(content)
        hash_func.update(f"{relative_path}:{file_hash.hexdigest()}".encode())
    return hash_func.hexdigest()


def compute_directory_hash(
    dir_path: str,
    algorithm: str = "sha256",
    exclude_prefixes: tuple[str, ...] = SIGNATURE_EXCLUDE_PREFIXES,
) -> str:
    """Calculate the canonical digest for files below a MOD directory."""
    hash_func = hashlib.new(algorithm)
    for root, _, files in os.walk(dir_path):
        for filename in sorted(files):
            if filename.startswith("."):
                continue
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, dir_path)
            if is_excluded_rel_path(relative_path, exclude_prefixes):
                continue
            file_hash = compute_file_hash(file_path, algorithm)
            hash_func.update(f"{relative_path}:{file_hash}".encode())
    return hash_func.hexdigest()
