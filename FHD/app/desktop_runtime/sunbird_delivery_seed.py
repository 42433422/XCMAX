"""太阳鸟交付：首次启动同步业务文件并写入主库 products/customers。"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ROSTER_FILENAME = "sunbird-roster.json"
APPLIED_MARKER = "sunbird-roster.applied"
SEED_ROOT_ENV = "XCAGI_SUNBIRD_SEED_ROOT"
SEED_DIRS = ("424", "data/mod_dbs")
SEED_FILES = (f"config/{ROSTER_FILENAME}",)


def _repo_seed_root() -> Path:
    return Path(__file__).resolve().parents[2] / "delivery" / "sunbird-seed"


def _seed_root_candidates(data_root: Path) -> list[Path]:
    root = data_root.resolve()
    raw_env = (os.environ.get(SEED_ROOT_ENV) or "").strip()
    candidates: list[Path] = []
    if raw_env:
        candidates.append(Path(raw_env).expanduser())
    candidates.extend(
        [
            root,
            root.parent,
            _repo_seed_root(),
        ]
    )

    out: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except RECOVERABLE_ERRORS:
            continue
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _has_seed_payload(path: Path) -> bool:
    return any((path / rel).exists() for rel in (*SEED_DIRS, *SEED_FILES))


def _roster_candidates(data_root: Path) -> list[Path]:
    root = data_root.resolve()
    return [
        root / "config" / ROSTER_FILENAME,
        root.parent / "config" / ROSTER_FILENAME,
    ]


def _marker_path(data_root: Path) -> Path:
    return data_root.resolve() / "config" / APPLIED_MARKER


def _copy_missing_file(src: Path, dst: Path) -> bool:
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_missing_tree(src: Path, dst: Path) -> int:
    if not src.is_dir():
        return 0
    copied = 0
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        if _copy_missing_file(item, dst / rel):
            copied += 1
    return copied


def sync_sunbird_delivery_files(data_root: Path | None = None) -> int:
    """把太阳鸟交付种子文件补齐到桌面工作区；只复制缺失文件。"""
    if data_root is None:
        try:
            from app.desktop_runtime.paths import get_desktop_data_dir

            data_root = get_desktop_data_dir()
        except RECOVERABLE_ERRORS:
            return 0

    root = Path(data_root).resolve()
    copied = 0
    for seed_root in _seed_root_candidates(root):
        if seed_root == root or not _has_seed_payload(seed_root):
            continue
        for rel in SEED_DIRS:
            copied += _copy_missing_tree(seed_root / rel, root / rel)
        for rel in SEED_FILES:
            src = seed_root / rel
            if src.is_file() and _copy_missing_file(src, root / rel):
                copied += 1
    if copied:
        logger.info("太阳鸟交付文件已补齐到桌面工作区：%s 个文件", copied)
    return copied


def apply_sunbird_roster_seed_if_needed(data_root: Path | None = None) -> bool:
    """若存在 sunbird-roster.json 且未应用，则写入主库人员/部门。返回是否执行了写入。"""
    if data_root is None:
        try:
            from app.desktop_runtime.paths import get_desktop_data_dir

            data_root = get_desktop_data_dir()
        except RECOVERABLE_ERRORS:
            return False

    root = Path(data_root).resolve()
    sync_sunbird_delivery_files(root)
    marker = _marker_path(root)
    if marker.is_file():
        return False

    roster_file: Path | None = None
    for candidate in _roster_candidates(root):
        if candidate.is_file():
            roster_file = candidate
            break
    if roster_file is None:
        return False

    try:
        raw = json.loads(roster_file.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS as exc:
        logger.warning("读取太阳鸟花名册失败 %s: %s", roster_file, exc)
        return False

    employees = raw.get("employees") if isinstance(raw, dict) else None
    if not isinstance(employees, list) or not employees:
        logger.warning("太阳鸟花名册无 employees: %s", roster_file)
        return False

    try:
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        ensure_sqlite_enterprise_business_bootstrap(
            database_url=os.environ.get("DATABASE_URL") or None,
            swallow_errors=True,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("太阳鸟花名册导入前补表跳过: %s", exc)

    try:
        from app.db.models.customer import Customer
        from app.db.models.product import Product
        from app.db.session import get_db
    except RECOVERABLE_ERRORS as exc:
        logger.warning("太阳鸟花名册导入跳过（主库模型不可用）: %s", exc)
        return False

    prod_rows = 0
    cust_rows = 0
    seen_dept: set[str] = set()

    try:
        with get_db() as db:
            existing_products = (
                db.query(Product).filter(Product.is_active == 1).count()  # type: ignore[arg-type]
            )
            if existing_products > 0:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("skipped:products_already_present\n", encoding="utf-8")
                logger.info("太阳鸟花名册跳过：主库已有 %s 条人员", existing_products)
                return False

            for row in employees:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                dept = str(row.get("dept") or "").strip()
                grp = str(row.get("group") or "").strip()
                if not name:
                    continue
                model_number = f"{dept}::{name}" if dept else name
                db.add(
                    Product(
                        model_number=model_number,
                        name=name,
                        specification=grp or None,
                        unit=dept or "个",
                        price=0,
                        is_active=1,
                    )
                )
                prod_rows += 1
                if dept and dept not in seen_dept:
                    seen_dept.add(dept)
                    db.add(
                        Customer(
                            customer_name=dept,
                            contact_person="",
                            contact_phone="",
                            contact_address="",
                        )
                    )
                    cust_rows += 1
            db.commit()
    except RECOVERABLE_ERRORS as exc:
        logger.exception("太阳鸟花名册写入主库失败: %s", exc)
        return False

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {"products": prod_rows, "customers": cust_rows, "source": str(roster_file)},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    logger.info("太阳鸟花名册已写入主库：products=%s customers=%s", prod_rows, cust_rows)
    return True


__all__ = ["apply_sunbird_roster_seed_if_needed", "sync_sunbird_delivery_files"]
