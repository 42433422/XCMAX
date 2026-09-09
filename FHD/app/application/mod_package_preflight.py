"""Read-only catalog package inspection; never install or initialize package code."""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from app.application.mod_store_catalog_app import catalog_download_to
from app.infrastructure.mods.manifest import _check_xcagi_version
from app.infrastructure.mods.package import ModPackageError, ModSignatureError
from app.infrastructure.mods.package_signing import verify_signed_package_bytes
from app.infrastructure.mods.version_constraints import version_satisfies


def dependency_report(manifest: dict[str, Any], versions: dict[str, str]) -> dict[str, Any]:
    raw = manifest.get("dependencies", {})
    if isinstance(raw, list) and all(isinstance(item, str) and item.strip() for item in raw):
        raw = dict.fromkeys(raw, "*")
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and key.strip() and isinstance(value, str)
        for key, value in raw.items()
    ):
        raise HTTPException(422, "包依赖声明格式无效")
    satisfied: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for dep_id, spec in raw.items():
        host = dep_id == "xcagi"
        current = "1.0.0.1" if host else versions.get(dep_id)
        matches = (
            _check_xcagi_version(spec)
            if host
            else (current is not None and version_satisfies(current, spec))
        )
        row = {
            "id": dep_id,
            "version_spec": spec,
            "installed_version": current,
            "type": "host" if host else "mod",
            "status": "satisfied"
            if matches
            else ("missing" if current is None else "incompatible"),
        }
        (satisfied if matches else missing).append(row)
    return {
        "mod_id": manifest["id"],
        "dependencies": list(raw),
        "satisfied": satisfied,
        "missing": missing,
        "can_install": not missing,
        "scope": "declared_dependencies_only",
    }


async def download_verified_catalog_package(
    package_file: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    # This is a catalog identity, never a local path, URL or arbitrary download path.
    match = re.fullmatch(
        r"([A-Za-z0-9][A-Za-z0-9_.-]{0,127}):([0-9]+(?:\.[0-9]+){0,7})", package_file
    )
    if not match or len(package_file) > 230:
        raise HTTPException(400, "需要明确的 package_file（包编号:数值版本）")
    mod_id, version = match.groups()
    from app.infrastructure.mods.mod_manager import get_mod_manager

    with tempfile.TemporaryDirectory(prefix="xcagi-mod-preflight-") as directory:
        package = Path(directory) / "package.zip"
        try:
            await asyncio.wait_for(
                catalog_download_to(
                    f"/packages/{quote(mod_id, safe='')}/{quote(version, safe='')}/download",
                    package,
                    max_bytes=64 * 1024 * 1024,
                ),
                timeout=30,
            )
        except TimeoutError as exc:
            raise HTTPException(504, "Mod 包预检下载超时") from exc
        valid, message, details = get_mod_manager().validate_mod_package(str(package))
        if not valid:
            raise HTTPException(422, f"包验证失败：{message}")
        # Require a trusted release even when developer unsigned-package switches are on.
        try:
            content = package.read_bytes()
            verified = verify_signed_package_bytes(content)
        except (ModPackageError, ModSignatureError, ValueError, KeyError) as exc:
            raise HTTPException(422, "包签名或清单验证失败") from exc
        manifest = verified["manifest"]
        if manifest.get("id") != mod_id or manifest.get("version") != version:
            raise HTTPException(422, "下载包身份与请求的编号或版本不一致")
        return content, verified, details


async def inspect_catalog_package(package_file: str, versions: dict[str, str]) -> dict[str, Any]:
    _, verified, details = await download_verified_catalog_package(package_file)
    dependencies = dependency_report(verified["manifest"], versions)
    return {
        **details,
        "package_sha256": verified["package_sha256"],
        "signature_verified": True,
        "dependency_check": dependencies,
        "installed": False,
    }
