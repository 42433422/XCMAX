"""Deterministically compare two catalog snapshots without mutating either side."""

from __future__ import annotations

from typing import Any


def _index(items: Any, label: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    if not isinstance(items, list):
        return {}, [f"{label}_not_array"]
    result: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{label}[{index}]_not_object")
            continue
        package_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if not package_id or not version or not status:
            errors.append(f"{label}[{index}]_incomplete")
            continue
        if package_id in result:
            errors.append(f"{label}[{index}]_duplicate:{package_id}")
            continue
        result[package_id] = {"version": version, "status": status}
    return result, errors


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    primary, primary_errors = _index(payload.get("primary_catalog"), "primary_catalog")
    partner, partner_errors = _index(payload.get("partner_catalog"), "partner_catalog")
    errors = primary_errors + partner_errors
    differences: list[dict[str, Any]] = []

    for package_id in sorted(set(primary) | set(partner)):
        left = primary.get(package_id)
        right = partner.get(package_id)
        if left is None:
            differences.append({"id": package_id, "kind": "missing_in_primary"})
            continue
        if right is None:
            differences.append({"id": package_id, "kind": "missing_in_partner"})
            continue
        if left["version"] != right["version"]:
            differences.append(
                {
                    "id": package_id,
                    "kind": "version_mismatch",
                    "primary": left["version"],
                    "partner": right["version"],
                }
            )
        if left["status"] != right["status"]:
            differences.append(
                {
                    "id": package_id,
                    "kind": "status_mismatch",
                    "primary": left["status"],
                    "partner": right["status"],
                }
            )

    consistent = not errors and not differences
    return {
        "ok": True,
        "status": "approved" if consistent else "rejected",
        "summary": (
            f"已只读比对主目录 {len(primary)} 项与伙伴目录 {len(partner)} 项；"
            f"发现 {len(differences)} 个漂移和 {len(errors)} 个输入问题。"
        ),
        "consistent": consistent,
        "differences": differences,
        "input_errors": errors,
        "evidence": [
            "input.primary_catalog",
            "input.partner_catalog",
            "id/version/status",
        ],
        "read_only": True,
        "side_effects": [],
    }
