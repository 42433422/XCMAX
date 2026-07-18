#!/usr/bin/env python3
"""Generate and verify the effective employee capability registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
CONTRACT = FHD_ROOT / "config" / "employee_capability_contract.yaml"
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

from scripts.dev.ssot_plugins.base import load_yaml_document  # noqa: E402


def _repo_path(value: str) -> Path:
    return REPO_ROOT / value


def load_contract() -> dict[str, Any]:
    contract = load_yaml_document(CONTRACT)
    resolution = contract.get("resolution")
    if not isinstance(resolution, dict):
        raise ValueError("resolution must be a mapping")
    if resolution.get("merge_strategy") != "ordered_union_first_definition_wins":
        raise ValueError("unsupported capability merge_strategy")
    sources = resolution.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("resolution.sources must be a non-empty list")
    for source in sources:
        if not isinstance(source, dict) or not all(
            source.get(key) for key in ("name", "path", "label_field", "description_field")
        ):
            raise ValueError("each capability source needs name/path/label_field/description_field")
    inputs = contract.get("inputs")
    if not isinstance(inputs, dict) or not all(
        inputs.get(key) for key in ("manifest_root", "manifest_glob", "employee_roster")
    ):
        raise ValueError("inputs must define manifest_root, manifest_glob, and employee_roster")
    identity = contract.get("identity_resolution")
    if not isinstance(identity, dict):
        raise ValueError("identity_resolution must be a mapping")
    if not identity.get("enterprise_scope"):
        raise ValueError("identity_resolution.enterprise_scope is required")
    if identity.get("enterprise_relation") != "separate_identity_space":
        raise ValueError("enterprise employees must remain a separate identity space")
    scopes = identity.get("manifest_scopes")
    if not isinstance(scopes, dict) or not all(
        scopes.get(key) for key in ("admin_planned_employee", "unrostered_employee_pack")
    ):
        raise ValueError("identity_resolution.manifest_scopes is incomplete")
    return contract


def _value_at_path(document: dict[str, Any], dotted_path: str) -> object:
    current: object = document
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _normalize_key(label: str, normalization: dict[str, Any]) -> str:
    key = label.strip() if normalization.get("trim", True) else label
    if normalization.get("lowercase", True):
        key = key.lower()
    if normalization.get("spaces_to_underscore", True):
        key = key.replace(" ", "_")
    return key


def _source_rows(
    manifest: dict[str, Any], source: dict[str, Any], normalization: dict[str, Any]
) -> list[dict[str, str]]:
    raw = _value_at_path(manifest, str(source["path"]))
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            label = item.strip()
            description = ""
        elif isinstance(item, dict):
            label = str(item.get(str(source["label_field"])) or "").strip()
            description = str(item.get(str(source["description_field"])) or "").strip()
        else:
            continue
        if not label:
            continue
        rows.append(
            {
                "key": _normalize_key(label, normalization),
                "label": label,
                "description": description,
                "source": str(source["name"]),
            }
        )
    return rows


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} root must be an object: {path}")
    return document


def _collect_admin_memberships(
    roster: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    area_memberships: dict[str, list[str]] = {}
    areas = roster.get("areas")
    if not isinstance(areas, dict) or not areas:
        raise ValueError("employee roster areas must be a non-empty mapping")
    for area_id, area in areas.items():
        if not isinstance(area, dict) or not isinstance(area.get("ids"), list):
            raise ValueError(f"employee roster area {area_id!r} must define ids")
        for raw_id in area["ids"]:
            employee_id = str(raw_id or "").strip()
            if employee_id:
                area_memberships.setdefault(employee_id, []).append(str(area_id))

    department_memberships: dict[str, list[str]] = {}
    departments = roster.get("departments")
    if not isinstance(departments, dict) or not departments:
        raise ValueError("employee roster departments must be a non-empty mapping")
    for department_id, department in departments.items():
        if not isinstance(department, dict):
            continue
        canonical_id = str(department.get("five_line_id") or department_id)
        subzones = department.get("subzones")
        if not isinstance(subzones, dict):
            continue
        for subzone in subzones.values():
            if not isinstance(subzone, dict) or not isinstance(subzone.get("ids"), list):
                continue
            for raw_id in subzone["ids"]:
                employee_id = str(raw_id or "").strip()
                memberships = department_memberships.setdefault(employee_id, [])
                if employee_id and canonical_id not in memberships:
                    memberships.append(canonical_id)
    return area_memberships, department_memberships


def _enterprise_employee_rows(
    roster: dict[str, Any], *, identity_scope: str
) -> list[dict[str, str]]:
    raw_layers = roster.get("enterprise_layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ValueError("employee roster enterprise_layers must be a non-empty list")
    layers: dict[str, dict[str, str]] = {}
    for raw_layer in raw_layers:
        if not isinstance(raw_layer, dict):
            continue
        layer_id = str(raw_layer.get("id") or "").strip()
        if layer_id:
            layers[layer_id] = {
                "id": layer_id,
                "code": str(raw_layer.get("code") or "").strip(),
                "label": str(raw_layer.get("label") or layer_id).strip(),
            }
    raw_employees = roster.get("enterprise_employees")
    if not isinstance(raw_employees, dict):
        raise ValueError("employee roster enterprise_employees must be a mapping")
    rows: list[dict[str, str]] = []
    for raw_id, raw_meta in raw_employees.items():
        employee_id = str(raw_id or "").strip()
        if not employee_id or not isinstance(raw_meta, dict):
            raise ValueError("enterprise employee entries need a non-empty id and metadata")
        layer_id = str(raw_meta.get("enterprise_layer") or "").strip()
        if layer_id not in layers:
            raise ValueError(f"enterprise employee {employee_id!r} has unknown layer {layer_id!r}")
        rows.append(
            {
                "employee_id": employee_id,
                "identity_scope": identity_scope,
                "label": str(raw_meta.get("label") or employee_id).strip(),
                "enterprise_layer": layer_id,
                "enterprise_layer_code": layers[layer_id]["code"],
                "enterprise_layer_label": layers[layer_id]["label"],
                "listing": str(raw_meta.get("listing") or "").strip(),
                "source": str(raw_meta.get("source") or "").strip(),
                "mod_id": str(raw_meta.get("mod_id") or "").strip(),
            }
        )
    return sorted(rows, key=lambda row: row["employee_id"])


def build_effective_registry(contract: dict[str, Any]) -> dict[str, Any]:
    inputs = contract["inputs"]
    resolution = contract["resolution"]
    identity_resolution = contract["identity_resolution"]
    manifest_root = _repo_path(str(inputs["manifest_root"]))
    manifest_paths = sorted(manifest_root.glob(str(inputs["manifest_glob"])))
    if not manifest_root.is_dir() or not manifest_paths:
        raise ValueError(f"no employee manifests found under {manifest_root}")
    normalization = dict(resolution.get("key_normalization") or {})
    sources = list(resolution["sources"])
    roster_path = _repo_path(str(inputs["employee_roster"]))
    roster = _load_json_object(roster_path, label="employee roster")
    area_memberships, department_memberships = _collect_admin_memberships(roster)
    enterprise_scope = str(identity_resolution["enterprise_scope"])
    enterprise_employees = _enterprise_employee_rows(roster, identity_scope=enterprise_scope)
    admin_planned_ids = set(area_memberships)
    enterprise_ids = {row["employee_id"] for row in enterprise_employees}
    overlap = sorted(admin_planned_ids & enterprise_ids)
    if overlap:
        raise ValueError(f"admin and enterprise employee identity spaces overlap: {overlap}")

    employee_packs: list[dict[str, Any]] = []
    employee_ids: set[str] = set()
    source_counts = {str(source["name"]): 0 for source in sources}
    effective_count = 0

    for manifest_path in manifest_paths:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid employee manifest {manifest_path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError(f"employee manifest root must be an object: {manifest_path}")
        employee_id = str(manifest.get("id") or manifest_path.parent.name).strip()
        if not employee_id:
            raise ValueError(f"employee manifest missing id: {manifest_path}")
        if employee_id in employee_ids:
            raise ValueError(f"duplicate employee id: {employee_id}")
        if employee_id != manifest_path.parent.name:
            raise ValueError(
                f"employee id/path mismatch: {employee_id!r} != {manifest_path.parent.name!r}"
            )
        employee_ids.add(employee_id)

        effective: dict[str, dict[str, Any]] = {}
        for source in sources:
            rows = _source_rows(manifest, source, normalization)
            source_counts[str(source["name"])] += len(rows)
            for row in rows:
                existing = effective.get(row["key"])
                if existing is None:
                    effective[row["key"]] = {
                        "key": row["key"],
                        "label": row["label"],
                        "description": row["description"],
                        "sources": [row["source"]],
                    }
                elif row["source"] not in existing["sources"]:
                    existing["sources"].append(row["source"])

        capabilities = list(effective.values())
        effective_count += len(capabilities)
        is_admin_planned = employee_id in admin_planned_ids
        employee_packs.append(
            {
                "employee_id": employee_id,
                "identity_scope": (
                    "admin_planned_employee" if is_admin_planned else "unrostered_employee_pack"
                ),
                "admin_roster": {
                    "planned": is_admin_planned,
                    "areas": area_memberships.get(employee_id, []),
                    "departments": department_memberships.get(employee_id, []),
                },
                "manifest": str(manifest_path.relative_to(REPO_ROOT)),
                "effective_capabilities": capabilities,
            }
        )

    missing_admin_manifests = sorted(admin_planned_ids - employee_ids)
    if missing_admin_manifests:
        raise ValueError(
            "admin planned employees missing employee-pack manifests: "
            + ", ".join(missing_admin_manifests)
        )

    contract_bytes = CONTRACT.read_bytes()
    roster_bytes = roster_path.read_bytes()
    admin_pack_count = sum(
        row["identity_scope"] == "admin_planned_employee" for row in employee_packs
    )
    return {
        "_generated": "Do not edit; run employee_capabilities_ssot.py --apply.",
        "schema_version": int(contract.get("schema_version") or 1),
        "contract": str(CONTRACT.relative_to(REPO_ROOT)),
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "employee_roster": str(roster_path.relative_to(REPO_ROOT)),
        "employee_roster_sha256": hashlib.sha256(roster_bytes).hexdigest(),
        "merge_strategy": resolution["merge_strategy"],
        "identity_scope_definitions": dict(identity_resolution["manifest_scopes"])
        | {
            str(identity_resolution["enterprise_scope"]): (
                "企业端四层工作流员工；与管理端编制及员工包 manifest 使用独立身份空间"
            )
        },
        "summary": {
            "employee_pack_manifest_count": len(employee_packs),
            "admin_planned_employee_pack_count": admin_pack_count,
            "unrostered_employee_pack_count": len(employee_packs) - admin_pack_count,
            "enterprise_workflow_employee_count": len(enterprise_employees),
            "effective_capability_count": effective_count,
            "source_declaration_counts": source_counts,
        },
        "employee_packs": employee_packs,
        "enterprise_workflow_employees": enterprise_employees,
    }


def render_python_contract(contract: dict[str, Any]) -> str:
    resolution = contract["resolution"]
    source_specs = [
        (
            tuple(str(source["path"]).split(".")),
            str(source["label_field"]),
            str(source["description_field"]),
        )
        for source in resolution["sources"]
    ]
    normalization = dict(resolution.get("key_normalization") or {})
    source_lines = []
    for path, label_field, description_field in source_specs:
        path_literal = "(" + ", ".join(json.dumps(part) for part in path) + ")"
        source_lines.append(
            f"    ({path_literal}, {json.dumps(label_field)}, {json.dumps(description_field)}),"
        )
    normalization_lines = [
        f"    {json.dumps(key)}: {value!r}," for key, value in normalization.items()
    ]
    return "\n".join(
        [
            '"""Generated from config/employee_capability_contract.yaml; do not edit."""',
            "",
            "from __future__ import annotations",
            "",
            "CAPABILITY_SOURCE_SPECS = (",
            *source_lines,
            ")",
            f"CAPABILITY_MERGE_STRATEGY = {json.dumps(resolution['merge_strategy'])}",
            "CAPABILITY_KEY_NORMALIZATION = {",
            *normalization_lines,
            "}",
            "",
        ]
    )


def expected_outputs() -> dict[Path, str]:
    contract = load_contract()
    generated = contract["generated"]
    inventory = build_effective_registry(contract)
    return {
        _repo_path(str(generated["python_contract"])): render_python_contract(contract),
        _repo_path(str(generated["effective_registry"])): json.dumps(
            inventory, ensure_ascii=False, indent=2
        )
        + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail when generated outputs drift")
    mode.add_argument("--apply", action="store_true", help="write generated outputs")
    args = parser.parse_args(argv)

    try:
        outputs = expected_outputs()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"employee-capabilities: invalid SSOT contract: {exc}", file=sys.stderr)
        return 1

    drifted = [
        path
        for path, expected in outputs.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != expected
    ]
    if not drifted:
        print("employee-capabilities: generated contract and effective registry are current")
        return 0
    if args.check:
        for path in drifted:
            print(f"employee-capabilities: DRIFT {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    for path in drifted:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[path], encoding="utf-8")
        print(f"employee-capabilities: updated {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
