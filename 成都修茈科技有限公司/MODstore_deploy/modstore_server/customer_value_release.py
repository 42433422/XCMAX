"""Read desktop publication identities from the existing release catalog."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from modstore_server.download_release import load_release
from modstore_server.integrations.repository_packages import load_repository_module
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _platform(value: Any) -> str:
    value = str(value or "").strip().lower()
    return {"darwin": "macos", "win32": "windows"}.get(value, value)


def desktop_publications() -> dict[str, Any]:
    """No server SHA, upload hint or historical prose can promote an installer.

    The installation protocol has no architecture or package digest. An identity
    shared by multiple architectures qualifies only if every matching catalog
    artifact is published; a candidate cannot borrow another platform's proof.
    """
    source = "download_release.release_history.deliveries"
    try:
        catalog = load_release()
        contract = load_repository_module("xcagi_common.release_catalog")
        if contract.release_inventory_errors(catalog):
            return {"source": source, "available": False, "identities": set()}
        groups: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
        for release in catalog["release_history"]:
            for artifact in release.get("deliveries", []):
                if artifact["product"] != "xcagi" or artifact["sku"] != "enterprise":
                    continue
                channel = {"stable-ota": "stable"}.get(artifact["channel"], artifact["channel"])
                if channel != "stable":
                    continue
                groups[
                    (
                        release["version"],
                        _platform(artifact["platform"]),
                        channel,
                        artifact["source_sha"],
                    )
                ].append(artifact["state"])
        identities = {
            identity for identity, states in groups.items() if set(states) == {"published"}
        }
        return {"source": source, "available": True, "identities": identities}
    except RECOVERABLE_ERRORS:
        return {"source": source, "available": False, "identities": set()}


def published_installation(receipt: Any, publications: dict[str, Any]) -> bool:
    """Match the authenticated receipt to its desktop version/platform/channel."""
    version = str(receipt.installed_version or "").strip()
    sha = str(receipt.installed_build_sha or "").strip().lower()
    return bool(
        publications["available"]
        and receipt.status == "installed"
        and str(receipt.target_version or "").strip() == version
        and str(receipt.target_build_sha or "").strip().lower() == sha
        and (version, _platform(receipt.platform), str(receipt.channel), sha)
        in publications["identities"]
    )
