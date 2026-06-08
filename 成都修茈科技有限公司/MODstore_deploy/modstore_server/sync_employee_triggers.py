"""YAML subscribes 声明 → DB EmployeeTriggerBinding 同步。

启动时全量同步，员工包注册/更新时单包同步。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_event_types() -> frozenset:
    try:
        from modstore_server.integrations.ops_action_handlers import EVENT_TYPES

        return EVENT_TYPES
    except Exception:
        return frozenset()


def sync_triggers_for_manifest(manifest: Dict[str, Any], *, session=None) -> int:
    """从单个 manifest dict 同步 triggers 到 EmployeeTriggerBinding。

    可传入外部 session（调用方负责 commit），或自行创建 session。
    返回 upsert 数量。
    """
    from modstore_server.models import EmployeeTriggerBinding, get_session_factory

    pack_id = str((manifest.get("identity") or {}).get("id") or manifest.get("id") or "").strip()
    if not pack_id:
        logger.warning("sync_triggers: manifest missing id, skip")
        return 0

    EVENT_TYPES = _get_event_types()
    triggers = manifest.get("triggers") or {}
    if not isinstance(triggers, dict):
        return 0

    # 收集所有需要绑定的 event_keys
    event_keys: List[str] = []

    standard_keys = ("on_error", "on_quality_fail", "on_coverage_miss")
    for yk in standard_keys:
        if yk in EVENT_TYPES and bool(triggers.get(yk)):
            event_keys.append(yk)

    subs = triggers.get("subscribes")
    if isinstance(subs, list):
        for raw in subs:
            ev_key = str(raw or "").strip()
            if not ev_key:
                continue
            base = ev_key.split(":", 1)[0].strip()
            if base in EVENT_TYPES:
                event_keys.append(ev_key)

    # change_request.result 自订阅（每个员工自动订阅自己的 CR 结果）
    cr_result_key = f"change_request.result:{pack_id}"
    if "change_request.result" in EVENT_TYPES and cr_result_key not in event_keys:
        event_keys.append(cr_result_key)

    if not event_keys:
        return 0

    def _do_sync(sess) -> int:
        n = 0
        for ev_key in event_keys:
            row = (
                sess.query(EmployeeTriggerBinding)
                .filter(
                    EmployeeTriggerBinding.employee_id == pack_id,
                    EmployeeTriggerBinding.event_type == ev_key,
                )
                .first()
            )
            if row:
                row.is_active = True
            else:
                sess.add(
                    EmployeeTriggerBinding(
                        employee_id=pack_id,
                        event_type=ev_key,
                        is_active=True,
                    )
                )
            n += 1
        return n

    if session is not None:
        return _do_sync(session)

    sf = get_session_factory()
    with sf() as sess:
        n = _do_sync(sess)
        sess.commit()
    return n


def sync_all_employee_triggers() -> int:
    """全量同步：遍历所有已注册员工包，读取其 manifest 并同步 triggers 到 DB。"""
    try:
        import zipfile

        from modstore_server.models import CatalogItem, EmployeeTriggerBinding, get_session_factory

        sf = get_session_factory()
        total = 0
        with sf() as session:
            rows = session.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack").all()
            for row in rows:
                try:
                    manifest: Dict[str, Any] = {"id": str(row.pkg_id or ""), "triggers": {}}
                    fn = (row.stored_filename or "").strip()
                    if fn:
                        from modstore_server.catalog_store import files_dir

                        p = files_dir() / fn
                        if p.exists():
                            with zipfile.ZipFile(p, "r") as z:
                                if "manifest.json" in z.namelist():
                                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                    n = sync_triggers_for_manifest(manifest, session=session)
                    total += n
                except Exception:
                    logger.exception("sync_triggers: failed for pack %s", row.pkg_id)
            session.commit()
        logger.info("sync_all_employee_triggers: upserted %d bindings", total)
        return total
    except Exception:
        logger.exception("sync_all_employee_triggers failed")
        return 0


__all__ = ["sync_triggers_for_manifest", "sync_all_employee_triggers"]
