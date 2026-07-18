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


def build_effective_registry(contract: dict[str, Any]) -> dict[str, Any]:
    inputs = contract["inputs"]
    resolution = contract["resolution"]
    manifest_root = _repo_path(str(inputs["manifest_root"]))
    manifest_paths = sorted(manifest_root.glob(str(inputs["manifest_glob"])))
    if not manifest_root.is_dir() or not manifest_paths:
        raise ValueError(f"no employee manifests found under {manifest_root}")
    normalization = dict(resolution.get("key_normalization") or {})
    sources = list(resolution["sources"])
    employees: list[dict[str, Any]] = []
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
        employees.append(
            {
                "employee_id": employee_id,
                "manifest": str(manifest_path.relative_to(REPO_ROOT)),
                "effective_capabilities": capabilities,
            }
        )

    contract_bytes = CONTRACT.read_bytes()
    return {
        "_generated": "Do not edit; run employee_capabilities_ssot.py --apply.",
        "schema_version": int(contract.get("schema_version") or 1),
        "contract": str(CONTRACT.relative_to(REPO_ROOT)),
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "merge_strategy": resolution["merge_strategy"],
        "summary": {
            "employee_count": len(employees),
            "effective_capability_count": effective_count,
            "source_declaration_counts": source_counts,
        },
        "employees": employees,
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
