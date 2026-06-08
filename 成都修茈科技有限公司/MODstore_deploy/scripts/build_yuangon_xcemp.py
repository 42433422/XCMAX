#!/usr/bin/env python3
"""Pack a yuangon employee directory into market_files/*.xcemp."""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[2]
YUANGON = REPO_ROOT / "yuangon"
MARKET_FILES = REPO_ROOT / "MODstore_deploy" / "modstore_server" / "market_files"


def _find_employee_dir(employee_id: str) -> Path:
    matches = list(YUANGON.rglob(f"{employee_id}/employee.yaml"))
    if not matches:
        raise SystemExit(f"employee not found: {employee_id}")
    return matches[0].parent


def _load_employee_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {}
    # minimal fallback without PyYAML
    out: dict = {"id": path.parent.name, "version": "1.0.0", "name": path.parent.name}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("id:"):
            out["id"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("version:"):
            out["version"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("name:"):
            out["name"] = line.split(":", 1)[1].strip().strip('"')
    return out


def _manifest_from_employee(emp: dict, pack_id: str) -> dict:
    version = str(emp.get("version") or "1.0.0")
    name = str(emp.get("name") or pack_id)
    description = str(emp.get("domain") or emp.get("description") or "")
    return {
        "artifact": "employee_pack",
        "id": pack_id,
        "name": name,
        "version": version,
        "description": description,
        "scope": "global",
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "employee": {
            "id": pack_id,
            "label": name,
            "area": str(emp.get("area") or ""),
        },
        "scope_globs": emp.get("scope_globs") or [],
        "forbidden_globs": emp.get("forbidden_globs") or [],
        "skills": emp.get("skills") or [],
    }


def build_xcemp(employee_id: str, *, out_dir: Path | None = None) -> Path:
    pack_dir = _find_employee_dir(employee_id)
    emp = _load_employee_yaml(pack_dir / "employee.yaml")
    pack_id = str(emp.get("id") or employee_id)
    version = str(emp.get("version") or "1.0.0")
    manifest = _manifest_from_employee(emp, pack_id)

    dest = out_dir or MARKET_FILES
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"{pack_id}-{version}.xcemp"

    allowed_suffixes = {
        ".json", ".md", ".py", ".yaml", ".yml", ".txt",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{pack_id}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        for path in sorted(pack_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(pack_dir).as_posix()
            if "__pycache__" in rel.split("/"):
                continue
            if path.suffix.lower() not in allowed_suffixes:
                continue
            zf.write(path, f"{pack_id}/{rel}")

    out_path.write_bytes(buf.getvalue())
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("employee_id", nargs="+", help="yuangon employee id(s)")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    for eid in args.employee_id:
        path = build_xcemp(eid, out_dir=args.out_dir)
        print(path, file=sys.stderr)


if __name__ == "__main__":
    main()
