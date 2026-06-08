"""购买员工包后的可选自动部署：Catalog 中的 zip → 本地 Mod 库 → XCAGI ``mods/_employees``。

启用方式：环境变量 ``MODSTORE_AUTO_DEPLOY_XCAGI=1``（或 ``true``/``yes``/``on``），
并配置与 ``/api/sync/push`` 相同的 XCAGI 根目录（``XCAGI_ROOT`` / 持久化 repo 配置）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def try_auto_deploy_after_purchase(*, item_id: int, order_kind: str) -> dict:
    """在 Python ``_fulfill_paid_order`` 成功后调用；幂等与失败均不打断主流程。"""
    if not _env_truthy("MODSTORE_AUTO_DEPLOY_XCAGI"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_AUTO_DEPLOY_XCAGI disabled"}
    kind = (order_kind or "").strip().lower()
    if kind != "item" or not item_id:
        return {"ok": True, "skipped": True, "reason": "not item order"}

    from modman.repo_config import resolved_xcagi
    from modman.store import deploy_to_xcagi, import_zip
    from modstore_server.catalog_store import files_dir
    from modstore_server.infrastructure import library_paths
    from modstore_server.models import CatalogItem, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            return {"ok": False, "error": "catalog item not found"}
        if (item.artifact or "").strip() != "employee_pack":
            return {"ok": True, "skipped": True, "reason": "not employee_pack"}
        pkg_id = (item.pkg_id or "").strip()
        fn = (item.stored_filename or "").strip()
        if not pkg_id or not fn:
            return {"ok": False, "error": "missing pkg_id or stored_filename"}
        zip_path = files_dir() / fn
        if not zip_path.is_file():
            return {"ok": False, "error": f"package file missing: {zip_path}"}

    cfg = library_paths.cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        logger.warning("MODSTORE_AUTO_DEPLOY_XCAGI: XCAGI root not configured")
        return {"ok": False, "error": "XCAGI root not configured"}

    library = library_paths.lib()
    try:
        import_zip(zip_path, library, replace=True)
        deployed = deploy_to_xcagi([pkg_id], library, Path(xc), replace=True)
        logger.info("MODSTORE_AUTO_DEPLOY_XCAGI deployed %s -> %s", deployed, xc)
        return {"ok": True, "deployed": deployed, "xcagi_root": str(xc)}
    except Exception as e:
        logger.exception("MODSTORE_AUTO_DEPLOY_XCAGI failed")
        return {"ok": False, "error": str(e)}
