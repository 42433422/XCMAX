"""Reproducible release signatures and trusted archive verification."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.infrastructure.mods.package import ModPackage, ModSignatureError
from app.infrastructure.mods.package_hashing import build_signed_message, compute_members_hash


def sign_members(
    members: list[tuple[str, bytes]], manifest: dict[str, Any], private_key: Path
) -> bytes:
    """Sign exact archive members; no timestamp, host path or random ZIP metadata."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ModSignatureError("MOD release signing requires an Ed25519 private key")
    content_hash = compute_members_hash(members)
    mid, version = str(manifest["id"]), str(manifest["version"])
    signature = {
        "version": "1.0",
        "algorithm": "sha256",
        "key_algorithm": "Ed25519",
        "content_hash": content_hash,
        "signed_fields": ["manifest_id", "version", "content_hash"],
        "manifest_id": mid,
        "manifest_version": version,
        "signature": base64.b64encode(
            key.sign(build_signed_message(mid, version, content_hash))
        ).decode("ascii"),
    }
    return json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def verify_signed_package_bytes(raw: bytes) -> dict[str, Any]:
    """Require the host's actual trust roots and attest the unique archive identity."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name
            for name in names
        ):
            raise ModSignatureError("Ambiguous or unsafe signed package members")
        if "META-INF/signature.json" not in names:
            raise ModSignatureError("Release package is missing its signature")
        if ModPackage._verify_package_signature("", archive) is not True:
            raise ModSignatureError("Release package did not pass trusted Ed25519 verification")
        manifests = [
            name
            for name in names
            if name == "manifest.json"
            or (
                name.count("/") == 1
                and name.endswith("/manifest.json")
                and not name.startswith("META-INF/")
            )
        ]
        if len(manifests) != 1:
            raise ModSignatureError("Release package must have one manifest")
        manifest = json.loads(archive.read(manifests[0]))
        signature = json.loads(archive.read("META-INF/signature.json"))
        if (
            not isinstance(manifest, dict)
            or not manifest.get("id")
            or not manifest.get("version")
            or signature.get("manifest_id") != manifest["id"]
            or signature.get("manifest_version") != manifest["version"]
        ):
            raise ModSignatureError("Signature identity differs from the packaged manifest")
        prefix = manifests[0].removesuffix("manifest.json")
        return {
            "manifest": manifest,
            "package_sha256": hashlib.sha256(raw).hexdigest(),
            "content_hash": signature["content_hash"],
            "files_sha256": {
                name[len(prefix) :]: hashlib.sha256(archive.read(name)).hexdigest()
                for name in names
                if name.startswith(prefix)
                and not name.endswith("/")
                and not name.startswith("META-INF/")
            },
        }
