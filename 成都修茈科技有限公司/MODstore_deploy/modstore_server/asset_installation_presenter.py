"""Response serialization for durable desktop asset-install commands."""

from __future__ import annotations

from urllib.parse import quote

from modstore_server.db.catalog import CatalogItem
from modstore_server.db.delivery_commerce import AssetInstallCommand


def serialize_install_command(
    row: AssetInstallCommand,
    item: CatalogItem | None = None,
) -> dict:
    payload = {
        "id": int(row.id),
        "purchase_id": int(row.purchase_id),
        "catalog_id": int(row.catalog_id),
        "installation_id": str(row.installation_id or ""),
        "source": str(row.source or ""),
        "status": str(row.status or ""),
        "attempt_count": int(row.attempt_count or 0),
        "error": str(row.error or ""),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "claimed_at": row.claimed_at.isoformat() if row.claimed_at else "",
        "completed_at": row.completed_at.isoformat() if row.completed_at else "",
    }
    if item is not None:
        payload["asset"] = {
            "pkg_id": str(item.pkg_id or ""),
            "version": str(item.version or ""),
            "name": str(item.name or ""),
            "artifact": str(item.artifact or "mod"),
            "sha256": str(item.sha256 or ""),
            "download_path": (
                f"/api/asset-installations/commands/{int(row.id)}/download"
                f"?installation_id={quote(str(row.installation_id or ''), safe='')}"
            ),
        }
    return payload


__all__ = ["serialize_install_command"]
