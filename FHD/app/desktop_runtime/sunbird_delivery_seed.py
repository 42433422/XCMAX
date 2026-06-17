"""太阳鸟交付：首次启动将预置花名册写入主库 products/customers。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ROSTER_FILENAME = "sunbird-roster.json"
APPLIED_MARKER = "sunbird-roster.applied"


def _roster_candidates(data_root: Path) -> list[Path]:
    root = data_root.resolve()
    return [
        root / "config" / ROSTER_FILENAME,
        root.parent / "config" / ROSTER_FILENAME,
    ]


def _marker_path(data_root: Path) -> Path:
    return data_root.resolve() / "config" / APPLIED_MARKER


def apply_sunbird_roster_seed_if_needed(data_root: Path | None = None) -> bool:
    """若存在 sunbird-roster.json 且未应用，则写入主库人员/部门。返回是否执行了写入。"""
    if data_root is None:
        try:
            from app.desktop_runtime.paths import get_desktop_data_dir

            data_root = get_desktop_data_dir()
        except RECOVERABLE_ERRORS:
            return False

    root = Path(data_root).resolve()
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


__all__ = ["apply_sunbird_roster_seed_if_needed"]
