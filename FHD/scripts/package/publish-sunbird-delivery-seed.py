#!/usr/bin/env python3
"""Build and register the SUNBIRD customer delivery seed package.

The package is stored in MODstore's lightweight /v1 catalog:
``modstore_server/catalog_data/packages.json`` + ``catalog_data/files``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__).resolve()
ROOT = _SCRIPT_PATH.parents[2] if len(_SCRIPT_PATH.parents) > 2 else Path.cwd()
DEFAULT_MODSTORE_ROOT = ROOT.parent / "成都修茈科技有限公司" / "MODstore_deploy"

PACKAGE_ID = "sunbird-delivery-seed"
DEFAULT_VERSION = "1.0.0"
ARTIFACT = "customer_delivery_seed"

PACKAGE_REQUIRED_FILES = (
    "config/sunbird-roster.json",
    "data/mod_dbs/taiyangniao_pro.db",
    "424/考勤-2026-3月份考勤统计表.xlsx",
)
PACKAGE_MOD_IDS = ("attendance-industry",)


def _resolve_mod_source(mod_id: str) -> Path:
    candidates = (
        ROOT / "mods" / mod_id,
        ROOT / "XCAGI" / "mods" / mod_id,
        ROOT / "build" / "staged-industry-seeds-enterprise" / mod_id,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise SystemExit(f"missing mod source: {mod_id}")


def _stage_customer_mods(seed_root: Path) -> None:
    mods_dest = seed_root / "mods"
    mods_dest.mkdir(parents=True, exist_ok=True)
    for mod_id in PACKAGE_MOD_IDS:
        src = _resolve_mod_source(mod_id)
        dst = mods_dest / mod_id
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def _iter_package_files(seed_root: Path) -> list[str]:
    files: list[str] = list(PACKAGE_REQUIRED_FILES)
    # 只打包当前声明的共享运行模块，忽略 staging 中残留的退役客户系统。
    for mod_id in PACKAGE_MOD_IDS:
        mods_root = seed_root / "mods" / mod_id
        for path in sorted(mods_root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            files.append(path.relative_to(seed_root).as_posix())
    return files


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_zip(seed_root: Path, out_dir: Path, version: str) -> Path:
    _stage_customer_mods(seed_root)
    package_files = _iter_package_files(seed_root)
    missing = [rel for rel in PACKAGE_REQUIRED_FILES if not (seed_root / rel).is_file()]
    if missing:
        raise SystemExit("missing seed files: " + ", ".join(missing))
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{PACKAGE_ID}-{version}.zip"
    manifest = {
        "schema_version": 1,
        "delivery_id": "customer-taiyangniao",
        "customer_account": "SUNBIRD",
        "customer_name": "太阳鸟",
        "artifact": ARTIFACT,
        "pkg_id": PACKAGE_ID,
        "version": version,
        "apply": "sunbird_roster",
        "contents": package_files,
        "built_at": datetime.now(UTC).isoformat(),
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "delivery-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        for rel in package_files:
            zf.write(seed_root / rel, rel)
    return zip_path


def _upsert_package(modstore_root: Path, zip_path: Path, version: str) -> dict[str, Any]:
    catalog_dir = modstore_root / "modstore_server" / "catalog_data"
    files_dir = catalog_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    packages_path = catalog_dir / "packages.json"
    stored_filename = zip_path.name
    dest = files_dir / stored_filename
    if zip_path.resolve() != dest.resolve():
        shutil.copy2(zip_path, dest)

    if packages_path.is_file():
        data = json.loads(packages_path.read_text(encoding="utf-8"))
    else:
        data = {"packages": []}
    rows = [
        r
        for r in data.get("packages") or []
        if not (
            str((r or {}).get("id") or "") == PACKAGE_ID
            and str((r or {}).get("version") or "") == version
        )
    ]
    record = {
        "id": PACKAGE_ID,
        "version": version,
        "artifact": ARTIFACT,
        "name": "太阳鸟交付种子数据",
        "description": "SUNBIRD 标准客户端定制功能数据：花名册、共享考勤库与太阳鸟专属转换模板。",
        "author": "成都修茈科技有限公司",
        "industry": "饰品包装",
        "customer_account": "SUNBIRD",
        "delivery_id": "customer-taiyangniao",
        "account_mod_id": "taiyangniao-pro",
        "stored_filename": stored_filename,
        "sha256": _sha256(dest),
        "file_size": dest.stat().st_size,
        "download_path": f"/v1/packages/{PACKAGE_ID}/{version}/download",
        "commerce": {"mode": "free", "product_id": None, "sku": None},
        "license": {"type": "account_entitlement", "verify_url": None},
        "created_at": datetime.now(UTC).isoformat(),
    }
    rows.append(record)
    data["packages"] = rows
    packages_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--seed-root", default=str(ROOT / "delivery" / "sunbird-seed"))
    parser.add_argument("--modstore-root", default=str(DEFAULT_MODSTORE_ROOT))
    parser.add_argument("--out-dir", default=str(ROOT / "build" / "sunbird-delivery"))
    parser.add_argument("--zip-path", default="", help="register an already built zip")
    args = parser.parse_args()

    version = str(args.version or DEFAULT_VERSION).strip()
    modstore_root = Path(args.modstore_root).expanduser().resolve()

    if args.zip_path:
        zip_path = Path(args.zip_path).expanduser().resolve()
        if not zip_path.is_file():
            raise SystemExit(f"zip not found: {zip_path}")
    else:
        seed_root = Path(args.seed_root).expanduser().resolve()
        out_dir = Path(args.out_dir).expanduser().resolve()
        zip_path = _build_zip(seed_root, out_dir, version)
    record = _upsert_package(modstore_root, zip_path, version)
    print(
        json.dumps(
            {"ok": True, "zip": str(zip_path), "package": record},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
