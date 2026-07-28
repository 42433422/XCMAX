"""开箱 / 演示用初始单据模板种子（幂等）。

目标：
1. 把仓库内 ``resources/templates`` 的发货单 Excel、价格表 Word 复制到运行时目录
2. 写入 ``templates`` 表，便于模板库与默认模板解析开箱即用

不覆盖用户已有同名文件或同 ``template_key`` 记录。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

SEED_SHIPMENT_KEY = "SEED_SHIPMENT_DEFAULT"
SEED_PRICE_LIST_KEY = "SEED_PRICE_LIST_DEFAULT"

_SHIPMENT_FILENAME = "发货单模板.xlsx"
_SHIPMENT_LEGACY_ALIAS = "尹玉华1.xlsx"
_PRICE_LIST_FILENAME = "price_list_default.docx"


def bundled_templates_dir() -> Path:
    from app.utils.path_utils import get_resource_path

    return Path(get_resource_path("templates"))


def _runtime_templates_dir() -> Path:
    from app.utils.path_utils import get_app_data_dir

    return Path(get_app_data_dir()) / "templates"


def _runtime_price_list_dir() -> Path:
    from app.utils.path_utils import get_app_data_dir

    return Path(get_app_data_dir()) / "424" / "document_templates"


def _repo_price_list_dir() -> Path | None:
    from app.utils.path_utils import resolve_fhd_repo_root

    root = resolve_fhd_repo_root()
    if root is None:
        return None
    return root / "424" / "document_templates"


def _copy_if_missing(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def sync_bundled_template_files() -> dict[str, Any]:
    """把内置模板复制到运行时目录（仅补缺失）。"""
    src_dir = bundled_templates_dir()
    runtime_tpl = _runtime_templates_dir()
    runtime_price = _runtime_price_list_dir()
    copied: list[str] = []

    shipment_src = src_dir / _SHIPMENT_FILENAME
    price_src = src_dir / _PRICE_LIST_FILENAME
    legacy_src = src_dir / _SHIPMENT_LEGACY_ALIAS
    if not legacy_src.is_file() and shipment_src.is_file():
        legacy_src = shipment_src

    for src, dst in (
        (shipment_src, runtime_tpl / _SHIPMENT_FILENAME),
        (legacy_src, runtime_tpl / _SHIPMENT_LEGACY_ALIAS),
        (price_src, runtime_tpl / _PRICE_LIST_FILENAME),
        (price_src, runtime_price / _PRICE_LIST_FILENAME),
    ):
        if _copy_if_missing(src, dst):
            copied.append(str(dst))

    # 兼容价目表注册表相对仓库路径解析
    repo_price_dir = _repo_price_list_dir()
    if repo_price_dir is not None and price_src.is_file():
        if _copy_if_missing(price_src, repo_price_dir / _PRICE_LIST_FILENAME):
            copied.append(str(repo_price_dir / _PRICE_LIST_FILENAME))

    # legacy 生成器优先找 resources/ai_assistant/uploads
    try:
        from app.utils.path_utils import get_resource_path

        uploads = Path(get_resource_path("ai_assistant", "uploads"))
        for src, name in (
            (shipment_src, _SHIPMENT_FILENAME),
            (legacy_src, _SHIPMENT_LEGACY_ALIAS),
        ):
            if _copy_if_missing(src, uploads / name):
                copied.append(str(uploads / name))
    except RECOVERABLE_ERRORS as exc:
        logger.debug("复制到 ai_assistant/uploads 跳过: %s", exc)

    return {
        "copied_count": len(copied),
        "copied": copied,
        "shipment_path": str(runtime_tpl / _SHIPMENT_FILENAME),
        "price_list_path": str(runtime_price / _PRICE_LIST_FILENAME),
    }


def _seed_specs(runtime_paths: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "template_key": SEED_SHIPMENT_KEY,
            "template_name": "演示发货单模板",
            "template_type": "发货单",
            "category": "excel",
            "file_path": runtime_paths["shipment_path"],
            "business_scope": "",
            "fields": [
                {"label": "购买单位"},
                {"label": "产品型号"},
                {"label": "产品名称"},
                {"label": "数量"},
                {"label": "规格"},
                {"label": "单价"},
                {"label": "金额"},
            ],
        },
        {
            "template_key": SEED_PRICE_LIST_KEY,
            "template_name": "演示产品价格表",
            "template_type": "价格表",
            "category": "word",
            "file_path": runtime_paths["price_list_path"],
            "business_scope": "",
            "fields": [
                {"label": "客户名称"},
                {"label": "型号"},
                {"label": "名称"},
                {"label": "规格"},
                {"label": "单价"},
            ],
        },
    ]


def _insert_template_row(spec: dict[str, Any]) -> str:
    """返回 inserted / skipped / failed。"""
    from sqlalchemy import text

    from app.db.session import get_db

    key = str(spec["template_key"])
    file_path = str(spec.get("file_path") or "").strip()
    if not file_path or not Path(file_path).is_file():
        return "failed"

    analyzed_data = {
        "category": spec.get("category") or "excel",
        "source": "seed_initial",
        "business_scope": spec.get("business_scope") or "",
        "fields": spec.get("fields") or [],
        "preview_data": {"seed": True, "demo": True},
    }
    business_rules = {
        "business_scope": spec.get("business_scope") or "",
        "source": "seed_initial",
        "is_demo_seed": True,
    }

    try:
        from sqlalchemy.exc import SQLAlchemyError
    except ImportError:  # pragma: no cover
        SQLAlchemyError = Exception  # type: ignore[misc,assignment]

    try:
        with get_db() as db:
            existing = db.execute(
                text(
                    "SELECT id, original_file_path, is_active "
                    "FROM templates WHERE template_key = :k LIMIT 1"
                ),
                {"k": key},
            ).fetchone()
            if existing:
                old_path = str(getattr(existing, "original_file_path", "") or "").strip()
                needs_path_fix = (not old_path) or (not Path(old_path).is_file())
                needs_reactivate = int(getattr(existing, "is_active", 1) or 0) != 1
                if needs_path_fix or needs_reactivate:
                    db.execute(
                        text(
                            """
                            UPDATE templates
                            SET original_file_path = :p,
                                is_active = 1,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :id
                            """
                        ),
                        {"p": file_path, "id": existing.id},
                    )
                    db.commit()
                    return "repaired"
                return "skipped"

            db.execute(
                text(
                    """
                    INSERT INTO templates (
                        template_key, template_name, template_type,
                        original_file_path, analyzed_data, editable_config,
                        zone_config, merged_cells_config, style_config,
                        business_rules, is_active
                    ) VALUES (
                        :template_key, :template_name, :template_type,
                        :original_file_path, :analyzed_data, :editable_config,
                        :zone_config, :merged_cells_config, :style_config,
                        :business_rules, :is_active
                    )
                    """
                ),
                {
                    "template_key": key,
                    "template_name": spec["template_name"],
                    "template_type": spec["template_type"],
                    "original_file_path": file_path,
                    "analyzed_data": json.dumps(analyzed_data, ensure_ascii=False),
                    "editable_config": json.dumps(
                        analyzed_data.get("fields") or [], ensure_ascii=False
                    ),
                    "zone_config": "{}",
                    "merged_cells_config": "{}",
                    "style_config": "{}",
                    "business_rules": json.dumps(business_rules, ensure_ascii=False),
                    "is_active": 1,
                },
            )
            db.commit()
            return "inserted"
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        logger.warning("初始模板入库失败 %s: %s", key, exc)
        return "failed"


def ensure_initial_document_templates() -> dict[str, Any]:
    """幂等：同步文件 + 入库。启动与测试均可调用。"""
    try:
        from app.db.init_db import init_template_tables, init_template_tables_for_engine

        init_template_tables()
        try:
            from app.db import engine as main_engine

            init_template_tables_for_engine(main_engine)
        except RECOVERABLE_ERRORS as engine_exc:
            logger.debug("主库 templates 表初始化跳过: %s", engine_exc)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("初始化 templates 表失败，跳过模板种子: %s", exc)
        return {"success": False, "message": str(exc)}

    files = sync_bundled_template_files()
    inserted: list[str] = []
    repaired: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for spec in _seed_specs(files):
        status = _insert_template_row(spec)
        key = str(spec["template_key"])
        if status == "inserted":
            inserted.append(key)
        elif status == "repaired":
            repaired.append(key)
        elif status == "skipped":
            skipped.append(key)
        else:
            failed.append(key)

    result = {
        "success": not failed,
        "copied_count": int(files.get("copied_count") or 0),
        "inserted": inserted,
        "repaired": repaired,
        "skipped": skipped,
        "failed": failed,
        "shipment_path": files.get("shipment_path"),
        "price_list_path": files.get("price_list_path"),
    }
    if inserted or repaired or files.get("copied_count"):
        logger.info(
            "初始单据模板种子完成: copied=%s inserted=%s repaired=%s skipped=%s failed=%s",
            result["copied_count"],
            inserted,
            repaired,
            skipped,
            failed,
        )
    return result


__all__ = [
    "SEED_SHIPMENT_KEY",
    "SEED_PRICE_LIST_KEY",
    "bundled_templates_dir",
    "sync_bundled_template_files",
    "ensure_initial_document_templates",
]
