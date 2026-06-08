#!/usr/bin/env python3
"""Seed CSV 全量读取 + CSV 生成员工包到 catalog，可选设为公开市场可见。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


PACKS: List[Dict[str, str]] = [
    {
        "pack_id": "csv-full-read-employee",
        "name": "CSV 全量读取员",
        "brief": (
            "CSV全量读取员工：上传 .csv 文件，使用 direct_python 解析为结构化 data.json，"
            "包含 columns、rows、row_count、meta，禁止 LLM 编造行列。"
        ),
    },
    {
        "pack_id": "csv-generate-employee",
        "name": "CSV 生成员",
        "brief": (
            "CSV生成员工：上传 .json（含 columns 与 rows）写出 outputs/output.csv，"
            "使用 direct_python，禁止编造表格数据。"
        ),
    },
]


def _build_pack(
    pack_id: str, brief: str, *, spec: Dict[str, str]
) -> tuple[Dict[str, Any], Dict[str, Any], bytes, Path]:
    from modstore_server.csv_tabular_runtime import (
        build_csv_generate_rule_spec,
        build_csv_read_rule_spec,
        is_csv_generate,
        render_csv_generate_convert_module,
        render_csv_read_convert_module,
    )
    from modstore_server.employee_asset_pipeline import (
        _normalize_manifest,
        materialize_asset_employee_pack,
    )

    is_generate = str(pack_id or "").endswith("-generate-employee")
    rule_spec = (
        build_csv_generate_rule_spec(brief) if is_generate else build_csv_read_rule_spec(brief)
    )
    rule_spec["pack_id"] = pack_id
    asset_manifest = {
        "session_id": "seed",
        "user_id": 0,
        "root": "",
        "assets": [],
        "templates": [],
        "example_inputs": [],
        "expected_outputs": [],
        "rules": [],
    }
    from modstore_server.employee_asset_pipeline import _fallback_manifest

    manifest = _normalize_manifest(_fallback_manifest(brief, rule_spec), brief, rule_spec)
    manifest["id"] = pack_id
    display_name = str(spec.get("name") or manifest.get("name") or pack_id).strip()
    manifest["name"] = display_name
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    ident = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
    ident["id"] = pack_id
    v2["identity"] = ident
    manifest["employee_config_v2"] = v2
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    emp["id"] = pack_id
    emp["label"] = display_name
    manifest["employee"] = emp
    rows = manifest.get("workflow_employees")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                row["label"] = display_name
                row["panel_title"] = display_name

    convert_py = (
        render_csv_generate_convert_module() if is_generate else render_csv_read_convert_module()
    )
    pack_dir, raw_zip = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest=asset_manifest,
        generated_convert_py=convert_py,
    )
    return manifest, rule_spec, raw_zip, pack_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed CSV read/generate employee packs")
    parser.add_argument(
        "--set-public", action="store_true", help="设置 catalog_items.is_public=true"
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同 pkg_id 记录")
    parser.add_argument("--dry-run", action="store_true", help="仅构建包，不写 catalog")
    args = parser.parse_args()

    from modstore_server.catalog_store import append_package
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_asset_pipeline import mirror_catalog_file_to_market_files
    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path
    from modstore_server.models import CatalogItem, User, get_session_factory

    session_factory = get_session_factory()
    with session_factory() as db:
        author = (
            db.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
        )  # noqa: E712
        author = author or db.query(User).order_by(User.id.asc()).first()
        if not author:
            print("No user in DB", file=sys.stderr)
            return 3
        author_id = int(author.id)

    lib = modstore_library_path()
    ok_count = 0
    for spec in PACKS:
        pack_id = spec["pack_id"]
        brief = spec["brief"]
        try:
            manifest, rule_spec, raw_zip, pack_dir = _build_pack(pack_id, brief, spec=spec)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: build failed: {exc}")
            continue

        with session_factory() as db:
            exists = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if exists and not args.force and not args.dry_run:
            print(f"[SKIP] {pack_id}: already in catalog (use --force)")
            continue

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(raw_zip)
            zip_tmp = Path(tmp.name)
        try:
            import_zip(zip_tmp, lib, replace=True)
        finally:
            zip_tmp.unlink(missing_ok=True)

        (lib / pack_id / "rule_spec.json").write_text(
            json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if args.dry_run:
            print(f"[OK] {pack_id}: built under {pack_dir}")
            ok_count += 1
            continue

        rec = {
            "id": pack_id,
            "name": str(manifest.get("name") or pack_id),
            "version": str(manifest.get("version") or "1.0.0"),
            "description": str(manifest.get("description") or "")[:2000],
            "artifact": "employee_pack",
            "industry": "数据处理",
            "security_level": "enterprise",
            "is_public": bool(args.set_public),
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "enterprise", "verify_url": None},
        }
        tmp_xcemp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
                tmp.write(raw_zip)
                tmp_xcemp = Path(tmp.name)
            saved = append_package(rec, tmp_xcemp)
            with session_factory() as db:
                upsert_catalog_item_from_xc_package_dict(db, saved, author_id=author_id)
                row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
                if row:
                    if args.set_public:
                        row.is_public = True
                    row.industry = rec["industry"]
                    row.price = 0.0
                    row.artifact = "employee_pack"
                    row.compliance_status = "approved"
                    row.name = str(spec.get("name") or manifest.get("name") or pack_id)[:256]
                    row.security_level = "enterprise"
                    row.license_scope = "enterprise"
                    db.commit()
                    try:
                        mirror_catalog_file_to_market_files(row.stored_filename)
                    except Exception:  # noqa: BLE001
                        pass
            pub = " public" if args.set_public else ""
            print(f"[SEED] {pack_id}: v{rec['version']}{pub}")
            ok_count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: catalog: {exc}")
        finally:
            if tmp_xcemp:
                tmp_xcemp.unlink(missing_ok=True)

    print(f"done: seeded={ok_count}/{len(PACKS)}")
    return 0 if ok_count == len(PACKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
