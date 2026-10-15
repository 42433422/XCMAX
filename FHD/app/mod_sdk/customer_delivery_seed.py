"""Install private delivery data into the current authenticated owner's workspace."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request

from app.application.mod_store_catalog_app import catalog_download_to, catalog_get_json
from app.mod_sdk.attendance_roster import initialize_roster_once
from app.mod_sdk.customer_delivery import (
    delivery_for_account_custom_mod,
    delivery_for_runtime_mod,
    delivery_seed_package_for_mod,
)
from app.mod_sdk.customer_features import require_attendance_conversion
from app.mod_sdk.owner_workspace import (
    authenticated_owner,
    owner_context,
    owner_workspace,
)

_MOD_ID = "sunbird-attendance-custom"
_SEED_FILES = {
    "config/sunbird-roster.json": "seed-roster.json",
    "424/考勤-2026-3月份考勤统计表.xlsx": "attendance-template.xlsx",
}
_MAX_SEED_BYTES = 64 * 1024 * 1024


def _safe_member_relpath(name: str) -> Path | None:
    raw = str(name or "").replace("\\", "/")
    rel = PurePosixPath(raw)
    if not raw or raw.endswith("/"):
        return None
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in raw.split("/")):
        raise ValueError(f"交付包包含非法路径: {name}")
    return Path(*rel.parts)


def extract_customer_delivery_seed(zip_path: Path) -> dict[str, Any]:
    """Only fixed data files are accepted; legacy code/DB payloads are never activated."""
    workspace = owner_workspace(_MOD_ID)
    payloads: dict[str, bytes] = {}
    ignored: list[str] = []
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_member_relpath(info.filename)
            if relative is None:
                continue
            name = relative.as_posix()
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("交付包不可包含符号链接")
            total += info.file_size
            if total > _MAX_SEED_BYTES or info.file_size < 0:
                raise ValueError("交付种子数据超过 64 MB")
            if name in _SEED_FILES:
                if name in payloads:
                    raise ValueError("交付包包含重复数据文件")
                with archive.open(info) as stream:
                    payloads[name] = stream.read(_MAX_SEED_BYTES + 1)
                if len(payloads[name]) != info.file_size:
                    raise ValueError("交付包数据长度不正确")
            elif name == "delivery-manifest.json" or name.startswith(("mods/", "data/mod_dbs/")):
                ignored.append(name)
            else:
                raise ValueError(f"交付包包含未允许文件: {name}")
    roster = payloads.get("config/sunbird-roster.json")
    employees: list[dict] = []
    if roster is not None:
        document = json.loads(roster)
        raw = document.get("employees") if isinstance(document, dict) else None
        if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
            raise ValueError("交付花名册格式不正确")
        employees = raw
    if not payloads:
        raise ValueError("交付包不含可用的模板或花名册")
    workspace.root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    preserved: list[str] = []
    for archive_name, content in payloads.items():
        filename = _SEED_FILES[archive_name]
        target = workspace.file_path(filename)
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            preserved.append(filename)
        else:
            written.append(filename)
    # Existing owner data wins even if a user intentionally removed every row.
    initialized = initialize_roster_once(employees) if roster is not None else False
    return {
        "extracted_files": written,
        "preserved_files": preserved,
        "ignored_legacy_files": ignored,
        "roster_initialized": initialized,
    }


async def _resolve_version(pkg_id: str, version: str) -> str:
    if str(version or "").strip():
        return version.strip()
    response = await catalog_get_json(f"/packages/by-id/{pkg_id}/versions")
    rows = response.get("versions") or []
    if not isinstance(rows, list) or not rows:
        return ""
    first = rows[0]
    return (
        str(first.get("version") or "").strip()
        if isinstance(first, dict)
        else str(first or "").strip()
    )


async def install_customer_delivery_seed_package(
    *,
    request: Request,
    mod_id: str,
    industry_id: str = "",
    market_token: str = "",
    account_username: str = "",
) -> dict[str, Any]:
    """Authentication and entitlement precede download, with no global seed fallback."""
    owner = authenticated_owner(request)
    require_attendance_conversion(request)
    mid = str(mod_id or "").strip()
    delivery = delivery_for_account_custom_mod(mid, industry_id) or delivery_for_runtime_mod(
        mid, account_username=account_username
    )
    package = delivery_seed_package_for_mod(mid, industry_id, account_username=account_username)
    if not delivery or delivery.get("runtime_mod_id") != _MOD_ID or not package:
        raise HTTPException(403, "当前账号未授权此交付种子包")
    package_id = str(package.get("pkg_id") or "").strip()
    version = await _resolve_version(package_id, str(package.get("version") or ""))
    if not package_id or not version:
        raise HTTPException(409, "交付种子包缺少 pkg_id/version")
    from app.fastapi_routes.market_account import resolve_valid_market_access_token
    from app.infrastructure.auth.dependencies import session_id_from_request

    # Never accept a different account's token from a mobile request body.
    token = str(
        await resolve_valid_market_access_token(session_id_from_request(request)) or ""
    ).strip()
    if not token:
        raise HTTPException(409, "缺少市场登录凭证，无法下载账号专属交付种子包")
    entitlement = str(package.get("account_mod_id") or mid)
    endpoint = f"/api/enterprise/customer-delivery-seeds/{quote(package_id, safe='')}/{quote(version, safe='')}/download?mod_id={quote(entitlement, safe='')}"
    authorization = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    with tempfile.TemporaryDirectory(prefix="xcagi-owner-seed-") as temporary:
        archive = Path(temporary) / "seed.zip"
        await catalog_download_to(endpoint, archive, headers={"Authorization": authorization})
        with owner_context(owner):
            result = extract_customer_delivery_seed(archive)
    return {
        "success": True,
        "message": "交付数据已检查；已有名单和模板保持不变",
        "mod_id": mid,
        "owner_scope": owner,
        "applied": bool(result["extracted_files"] or result["roster_initialized"]),
        "package": {
            "pkg_id": package_id,
            "version": version,
            "artifact": package.get("artifact"),
        },
        **result,
    }
