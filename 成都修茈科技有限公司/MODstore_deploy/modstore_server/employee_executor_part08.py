# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def list_employees() -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """列出可展示的员工包：合并数据库 ``catalog_items`` 与仅存在于 ``packages.json`` 的登记。

    - ``source`` = ``catalog``：数据库中有 ``artifact=employee_pack`` 行（执行与权限以此为准）。
    - ``source`` = ``v1_catalog``：仅本地 XC catalog（``/v1/packages``）中存在，需管理员同步入库后方可稳定执行。

    同一逻辑 ``pkg_id`` 只保留一行；数据库优先于 JSON（按 :func:`~modstore_server.catalog_store.norm_pkg_id` 去重）。
    """
    from modstore_server import catalog_store
    from modstore_server.models import CatalogItem

    merged_by_norm: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    sf = _facade().get_session_factory()
    with sf() as session:
        employees = session.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack").all()
        for e in employees:
            nid = catalog_store.norm_pkg_id(e.pkg_id)
            if not nid:
                continue
            merged_by_norm[nid] = {
                "id": e.pkg_id,
                "name": e.name,
                "version": e.version,
                "description": e.description,
                "price": e.price,
                "industry": e.industry,
                "created_at": e.created_at.isoformat() if e.created_at else "",
                "source": "catalog",
            }
    try:
        pending_norm_raw: _facade().Dict[str, str] = {}
        for r in catalog_store.load_store().get("packages") or []:
            if not isinstance(r, dict):
                continue
            if str(r.get("artifact") or "").strip().lower() != "employee_pack":
                continue
            nid = catalog_store.norm_pkg_id(r.get("id"))
            if not nid or nid in merged_by_norm:
                continue
            rid = str(r.get("id")).strip()
            if rid:
                pending_norm_raw.setdefault(nid, rid)
        for _nid, raw_id in pending_norm_raw.items():
            versions = catalog_store.list_versions(raw_id)
            best = versions[0] if versions else None
            if not isinstance(best, dict):
                continue
            pid = str(best.get("id") or raw_id).strip()
            merged_by_norm[_nid] = {
                "id": pid,
                "name": str(best.get("name") or pid),
                "version": best.get("version"),
                "description": best.get("description"),
                "price": 0.0,
                "industry": str(best.get("industry") or "通用"),
                "created_at": str(best.get("created_at") or ""),
                "source": "v1_catalog",
            }
    except Exception as ex:
        _facade().logger.warning("list_employees: merge packages.json failed: %s", ex)
    out = list(merged_by_norm.values())
    out.sort(key=lambda x: str(x.get("name") or x.get("id") or "").lower())
    return out
