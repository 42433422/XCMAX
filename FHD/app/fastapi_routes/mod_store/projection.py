"""Catalog shape, visibility and request text normalization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def is_extension_row(d: dict[str, Any]) -> bool:
    mid = str(d.get("id") or "").strip()
    if not mid or mid.lower() == "all":
        return False
    t = str(d.get("type") or "mod").strip().lower()
    if t in ("category", "template", "shell_seed"):
        return False
    return True


def filter_rows(
    rows: list[dict[str, Any]],
    q: str | None = None,
    author: str | None = None,
    installed: bool | None = None,
) -> list[dict[str, Any]]:
    out = rows
    if q and str(q).strip():
        k = str(q).strip().lower()
        out = [
            r
            for r in out
            if k in (r.get("name") or "").lower()
            or k in (r.get("id") or "").lower()
            or k in (r.get("description") or "").lower()
        ]
    if author and str(author).strip():
        a = str(author).strip().lower()
        out = [r for r in out if a in (r.get("author") or "").lower()]
    if installed is True:
        out = [r for r in out if r.get("is_installed")]
    elif installed is False:
        out = [r for r in out if not r.get("is_installed")]
    return out


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def split_package_file(package_file: str) -> tuple[str, str]:
    raw = safe_text(package_file)
    if ":" in raw:
        mid, version = raw.split(":", 1)
        return (mid.strip(), version.strip())
    return (raw, "")


def item_to_mod_info(
    d: dict[str, Any],
    *,
    base_url: Callable[[], str],
    is_extension: Callable[[dict[str, Any]], bool] = is_extension_row,
) -> dict[str, Any]:
    mid = str(d.get("id") or "").strip()
    name = str(d.get("name") or mid or "未命名").strip() or mid
    ver = str(d.get("version") or "1.0.0").strip() or "1.0.0"
    author = str(d.get("author") or "—").strip() or "—"
    desc = str(d.get("description") or "").strip()
    installed = is_extension(d)
    return {
        "id": mid,
        "name": name,
        "version": ver,
        "author": author,
        "description": desc,
        "package_file": None,
        "is_installed": installed,
        "download_count": 0,
        "total_downloads": 0,
        "avg_rating": 0.0,
        "rating_count": 0,
        "created_at": None,
        "dependencies": {},
        "source": "local",
        "catalog_base_url": base_url(),
    }


def remote_to_mod_info(
    d: dict[str, Any], installed_ids: set[str], *, base_url: Callable[[], str]
) -> dict[str, Any]:
    mid = str(d.get("id") or d.get("pkg_id") or "").strip()
    version = str(d.get("version") or "1.0.0").strip() or "1.0.0"
    name = str(d.get("name") or mid or "未命名").strip() or mid
    raw_commerce = d.get("commerce")
    commerce: dict[str, Any] = dict(raw_commerce) if isinstance(raw_commerce, dict) else {}
    download_url = str(d.get("download_url") or "").strip()
    from app.mod_sdk.host_foundation import catalog_store_collection

    row_out = {
        "id": mid,
        "pkg_id": mid,
        "name": name,
        "version": version,
        "author": str(
            (d or {}).get("author") or d.get("publisher") or commerce.get("seller") or "—"
        ).strip()
        or "—",
        "description": str(d.get("description") or "").strip(),
        "package_file": f"{mid}:{version}",
        "download_url": download_url,
        "is_installed": mid in installed_ids,
        "download_count": int(d.get("download_count") or d.get("total_downloads") or 0),
        "total_downloads": int(d.get("total_downloads") or d.get("download_count") or 0),
        "avg_rating": float(d.get("avg_rating") or 0.0),
        "rating_count": int(d.get("rating_count") or 0),
        "created_at": d.get("created_at") or d.get("updated_at"),
        "dependencies": d.get("dependencies") if isinstance(d.get("dependencies"), dict) else {},
        "artifact": d.get("artifact") or "mod",
        "sha256": d.get("sha256"),
        "commerce": commerce,
        "license": d.get("license"),
        "source": "remote",
        "catalog_base_url": base_url(),
        "store_collection": str(
            (d or {}).get("store_collection") or commerce.get("collection") or ""
        ).strip(),
        "public_listing": bool(d.get("public_listing")),
    }
    if not row_out["store_collection"]:
        row_out["store_collection"] = catalog_store_collection(row_out)
    return row_out


def inject_host_foundation_row(available: list[dict[str, Any]], installed_ids: set[str]) -> None:
    from app.mod_sdk.host_foundation import (
        HOST_FOUNDATION_EMPLOYEE_PACK_ID,
        host_foundation_catalog_row,
        is_host_foundation_pack_installed,
        is_infrastructure_mod_hidden_from_store,
    )

    if any(str(r.get("id") or "") == HOST_FOUNDATION_EMPLOYEE_PACK_ID for r in available):
        return
    installed = (
        HOST_FOUNDATION_EMPLOYEE_PACK_ID in installed_ids or is_host_foundation_pack_installed()
    )
    available.insert(0, host_foundation_catalog_row(installed=installed))
    i = 0
    while i < len(available):
        mid = str(available[i].get("id") or "").strip()
        row = available[i]
        listed = bool(row.get("public_listing")) if isinstance(row, dict) else False
        if (
            mid != HOST_FOUNDATION_EMPLOYEE_PACK_ID
            and is_infrastructure_mod_hidden_from_store(mid)
            and (not listed)
        ):
            available.pop(i)
            continue
        i += 1
