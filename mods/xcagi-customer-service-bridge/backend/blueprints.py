"""客服业务页桥接 Mod — FHD/mods 薄壳，委托 XCAGI/mods 全量 API。"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CUSTOMER_SERVICE_BRIDGE_MOD_ID = "xcagi-customer-service-bridge"


def _rebuild_pydantic_models(mod) -> None:
    """importlib 动态加载 + ``from __future__ import annotations`` 时需 rebuild，否则 OpenAPI 生成失败。"""
    try:
        from pydantic import BaseModel
    except ImportError:
        return
    ns = vars(mod)
    for attr in list(ns.values()):
        if not isinstance(attr, type) or not issubclass(attr, BaseModel) or attr is BaseModel:
            continue
        try:
            attr.model_rebuild(_types_namespace=ns)
        except Exception:
            logger.debug("model_rebuild skipped for %s", attr, exc_info=True)


def _load_full_blueprints_module():
    fhd_root = Path(__file__).resolve().parents[3]
    full_path = fhd_root / "XCAGI" / "mods" / "xcagi-customer-service-bridge" / "backend" / "blueprints.py"
    if not full_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("xcagi_cs_bridge_blueprints_full", full_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _rebuild_pydantic_models(mod)
    return mod


def register_fastapi_routes(app, mod_id: str) -> None:
    full = _load_full_blueprints_module()
    if full is not None and hasattr(full, "register_fastapi_routes"):
        full.register_fastapi_routes(app, mod_id)
        logger.info("xcagi-customer-service-bridge registered via XCAGI/mods full blueprints: %s", mod_id)
        return

    from fastapi import APIRouter

    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"customer-service-bridge-{mod_id}"])

    @router.get("/status")
    def status():
        from app.mod_sdk.customer_service_pages_compat import list_customer_service_pages_registry

        return {
            "success": True,
            "data": {
                "ok": True,
                "mod_id": mod_id,
                "registry": list_customer_service_pages_registry(),
                "note": "stub-only; XCAGI/mods blueprints missing",
            },
        }

    app.include_router(router)
    logger.warning("xcagi-customer-service-bridge stub only (XCAGI/mods blueprints not found): %s", mod_id)


def mod_init() -> None:
    full = _load_full_blueprints_module()
    if full is not None and hasattr(full, "mod_init"):
        full.mod_init()
        return
    logger.info("xcagi-customer-service-bridge mod_init (stub)")
