#!/usr/bin/env python3
"""显式 autonomy callback：运行态事件回写 approval ledger / ingest。

契约符号（供搜索与验收）:
  - autonomy_callback
  - report_callback
  - deploy_callback

设计：
  - 统一走 POST /api/ops/autonomy/actions/ingest（复用 _approval_ledger_client）
  - fail-open：网络/鉴权/依赖缺失只打 stderr，不阻断主流程
  - deploy_dispatch 失败后的 freeze_manifest 除流程内嵌外，必须经 deploy_callback 通知

用法::

    from autonomy_callback import deploy_callback, report_callback

    deploy_callback(
        "freeze_manifest",
        {"environment": "staging", "triggered_by": "loop:…:deploy:staging", "ok": True},
        source="self_maintenance",
        action_id="loop:…:freeze:staging",
    )
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_CI_SCRIPTS = Path(__file__).resolve().parents[1] / "ci"
if str(_CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CI_SCRIPTS))

try:
    from _approval_ledger_client import post_to_approval_ledger
except ImportError:  # pragma: no cover
    post_to_approval_ledger = None  # type: ignore[assignment]


def autonomy_callback(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "autonomy",
    action_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """通用回调：把 event_type + payload 写入 approval ledger。"""
    if not event_type or not isinstance(payload, dict):
        print(
            f"[autonomy_callback] invalid args event_type={event_type!r}",
            file=sys.stderr,
        )
        return None
    if post_to_approval_ledger is None:
        print(
            "[autonomy_callback] post_to_approval_ledger unavailable, skip",
            file=sys.stderr,
        )
        return None

    body = dict(payload)
    body.setdefault("callback_event", event_type)
    try:
        return post_to_approval_ledger(
            action=str(event_type),
            payload=body,
            source=source,
            action_id=action_id,
        )
    except Exception as exc:  # pragma: no cover
        print(f"[autonomy_callback] error: {exc!r}", file=sys.stderr)
        return None


def report_callback(
    report_kind: str,
    payload: dict[str, Any],
    *,
    source: str = "autonomy",
    action_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """报告类回调（ledger / audit / metrics 摘要等）。"""
    kind = (report_kind or "generic").strip() or "generic"
    return autonomy_callback(
        f"report:{kind}",
        payload,
        source=source,
        action_id=action_id,
    )


def deploy_callback(
    phase: str,
    payload: dict[str, Any],
    *,
    source: str = "self_maintenance",
    action_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """部署类回调（dispatch_ok / dispatch_failed / freeze_manifest / …）。"""
    phase_name = (phase or "unknown").strip() or "unknown"
    return autonomy_callback(
        f"deploy:{phase_name}",
        payload,
        source=source,
        action_id=action_id,
    )


__all__ = [
    "autonomy_callback",
    "report_callback",
    "deploy_callback",
]
