"""Daily-digest persistence bridge for release-train state."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def attach_release_train_to_digest(record_id: int, bump_result: Dict[str, Any]) -> None:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        with get_session_factory()() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return
            row.release_train_before = str(bump_result.get("before") or "")
            row.release_train_after = str(bump_result.get("after") or "")
            row.release_kind = str(bump_result.get("kind") or "daily")
            session.commit()
    except Exception:
        logger.exception("release_train: attach to digest record_id=%s failed", record_id)


def release_train_context_for_digest(
    record_id: int,
    *,
    snapshot_public: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        with get_session_factory()() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return {}
            before = (row.release_train_before or "").strip()
            after = (row.release_train_after or "").strip()
            kind = (row.release_kind or "").strip()
            if not after:
                snapshot = snapshot_public()
                current = snapshot.get("current")
                return {
                    "release_train": current,
                    "release_train_before": before or current,
                    "release_train_after": current,
                    "release_kind": kind or "daily",
                }
            return {
                "release_train": after,
                "release_train_before": before,
                "release_train_after": after,
                "release_kind": kind or "daily",
            }
    except Exception:
        logger.exception("release_train: context for digest record_id=%s failed", record_id)
        snapshot = snapshot_public()
        return {
            "release_train": snapshot.get("current"),
            "release_train_before": snapshot.get("current"),
            "release_train_after": snapshot.get("current"),
            "release_kind": "daily",
        }
