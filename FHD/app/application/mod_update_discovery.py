"""Compare installed Mods with versioned public and caller-owned packages."""

from __future__ import annotations

import re
from typing import Any

_RELEASE = re.compile(r"[vV]?(\d+(?:\.\d+){1,3})\Z")


def release_version(value: Any) -> tuple[int, ...] | None:
    match = _RELEASE.fullmatch(str(value or "").strip())
    if not match:
        return None
    parts = tuple(int(part) for part in match[1].split("."))
    return parts + (0,) * (4 - len(parts))


def available_updates(
    installed: dict[str, dict[str, Any]],
    public_rows: list[dict[str, Any]],
    private_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Private identities never fall back to a public package of the same name."""
    private_ids = {str(row.get("id") or row.get("pkg_id") or "") for row in private_rows}
    choices: dict[str, dict[str, Any]] = {}
    for source, rows in (("public_catalog", public_rows), ("private_mod_sync", private_rows)):
        for row in rows:
            if source == "private_mod_sync" and row.get("installable") is False:
                continue
            mid = str(row.get("id") or row.get("pkg_id") or "").strip()
            local = installed.get(mid)
            if not local or (source == "public_catalog" and mid in private_ids):
                continue
            remote_version = release_version(row.get("version"))
            local_version = release_version(local.get("version"))
            if remote_version is None or local_version is None or remote_version <= local_version:
                continue
            previous = choices.get(mid)
            if previous and remote_version <= (release_version(previous["new_version"]) or ()):
                continue
            version = str(row["version"])
            choices[mid] = {
                "mod_id": mid,
                "current_version": str(local["version"]),
                "new_version": version,
                "package_file": f"{mid}:{version}",
                "name": str(row.get("name") or local.get("name") or mid),
                "source": source,
                "package_sha256": str(row.get("package_sha256") or row.get("sha256") or ""),
            }
    return [choices[mid] for mid in sorted(choices)]
