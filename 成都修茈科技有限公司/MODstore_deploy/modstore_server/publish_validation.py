"""上架校验门禁 + 失败自动回滚 + 告警。

T-C12：``PATCH /api/admin/catalog/{item_id}`` 切换 ``is_public=True`` 时
必须先通过 :func:`validate_catalog_publish`；任何校验失败 → 调用
:func:`apply_publish_rollback` 把商品状态退回安全默认（``is_public=False``
/``compliance_status='disabled'``/``rank_score=0.0``/``delist_reason``）
并通过 ``incident_bus.publish`` 发 ``log.anomaly`` 告警。

设计原则：
- 安全默认 = 不可见 + 不可重试上架（除非运维显式 reset compliance_status）。
- 告警 best-effort，失败不阻断回滚主流程（与 auto_rollback.py 一致）。
- 校验纯函数化，便于单测；副作用集中在 :func:`apply_publish_rollback`。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# compliance_status 取值集合（与 models_catalog.py 默认 'approved' 对齐）。
# 'disabled' = T-C12 自动回滚标记；'delisted' = 管理员手动下架（DELETE 路径）。
DISABLED_STATUSES = frozenset({"disabled", "delisted"})


def validate_catalog_publish(item: Any) -> Optional[str]:
    """校验商品是否可上架。返回 ``None`` 表示通过，否则返回失败原因（短字符串）。

    校验维度（最小闭环，避免与 package_sandbox_audit 重复）：
    1. ``compliance_status`` 不在 :data:`DISABLED_STATUSES` 中——已被自动回滚
       或手动下架的商品必须先显式 reset 才能重新上架，防止 cron 反复重试。
    2. ``stored_filename`` 非空——上架必须有真实产物文件。
    3. ``sha256`` 非空——产物必须可追溯完整性。
    4. ``name`` 非空——市场展示必需字段。

    注意：``is_public`` 当前值不参与校验——本函数只判断"能否切到 True"，
    不判断"当前是否已 True"。调用方负责在切 True 之前调用本函数。
    """
    status = (getattr(item, "compliance_status", "") or "").strip().lower()
    if status in DISABLED_STATUSES:
        return f"compliance_status={status}（需先 reset 才能重新上架）"

    if not (getattr(item, "stored_filename", "") or "").strip():
        return "stored_filename 缺失（无产物文件）"

    if not (getattr(item, "sha256", "") or "").strip():
        return "sha256 缺失（产物完整性不可追溯）"

    if not (getattr(item, "name", "") or "").strip():
        return "name 缺失"

    return None


def apply_publish_rollback(item: Any, *, reason: str) -> Dict[str, Any]:
    """把商品状态强制退回安全默认。返回变更摘要 dict。

    必须在已经持 DB session 的上下文中调用；调用方负责 ``session.commit()``。

    安全默认：
    - ``is_public = False``
    - ``compliance_status = 'disabled'``
    - ``rank_score = 0.0``
    - ``delist_reason = "publish_validation_failed: <reason>"``（截断 500 字符）
    """
    reason_text = str(reason or "").strip()[:500] or "unknown"
    delist_reason = f"publish_validation_failed: {reason_text}"

    before = {
        "is_public": bool(getattr(item, "is_public", False)),
        "compliance_status": getattr(item, "compliance_status", ""),
        "rank_score": float(getattr(item, "rank_score", 0.0) or 0.0),
    }

    item.is_public = False
    item.compliance_status = "disabled"
    item.rank_score = 0.0
    item.delist_reason = delist_reason

    after = {
        "is_public": False,
        "compliance_status": "disabled",
        "rank_score": 0.0,
        "delist_reason": delist_reason,
    }
    return {"before": before, "after": after, "reason": reason_text}


def publish_failure_alert(
    *,
    item_id: int,
    pkg_id: str,
    version: str,
    reason: str,
    rollback: Dict[str, Any],
) -> Dict[str, Any]:
    """发 ``log.anomaly`` 告警。best-effort：失败仅 log，不抛异常。

    与 :func:`auto_rollback._publish_alert` 同构，便于运维统一在
    ``incident_bus`` 事件流里追溯 publish/auto-rollback 两类失败。
    """
    try:
        from modstore_server.incident_bus import publish

        published = publish(
            "log.anomaly",
            {
                "title": "MODstore 上架校验失败 → 自动回滚",
                "scope": "modstore.publish",
                "item_id": int(item_id),
                "pkg_id": str(pkg_id or ""),
                "version": str(version or ""),
                "reason": str(reason)[:500],
                "rolled_back_from": rollback.get("before"),
                "rolled_back_to": rollback.get("after"),
                "rollback_ok": True,
            },
            source="publish-validation:catalog",
        )
        return {"ok": True, "published": bool(published)}
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "publish_validation: alert publish failed item_id=%s pkg_id=%s",
            item_id,
            pkg_id,
        )
        return {"ok": False, "error": str(exc)[:300]}
