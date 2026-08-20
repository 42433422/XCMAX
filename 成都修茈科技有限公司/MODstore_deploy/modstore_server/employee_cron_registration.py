"""Resolve scheduled employee candidates from catalog and reviewed duty SSOTs."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def build_employee_cron_candidates(
    *,
    profiles: Iterable[dict[str, Any]] | None,
    work_contracts: dict[str, dict[str, Any]],
    load_employee_pack: Callable[[Any, str], dict[str, Any]],
    session_factory: Callable[[], Any],
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Return catalog and contract employees with the best reviewed manifest.

    Catalog visibility is a delivery concern and may lag the internal duty
    roster. A missing catalog row must not silently remove a reviewed cron
    assignment, while catalog-only employees keep their existing manifest path.
    """

    from modstore_server.duty_workforce_contracts import load_reviewed_duty_manifest

    profile_ids = {
        str(profile.get("id") or "").strip()
        for profile in (profiles or [])
        if str(profile.get("id") or "").strip()
    }
    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for employee_id in sorted(profile_ids | set(work_contracts)):
        contract = work_contracts.get(employee_id) or {}
        manifest: dict[str, Any] = {}
        if employee_id in profile_ids:
            try:
                with session_factory() as session:
                    pack = load_employee_pack(session, employee_id)
                if isinstance(pack.get("manifest"), dict):
                    manifest = pack["manifest"]
            except RECOVERABLE_ERRORS:
                logger.warning(
                    "catalog manifest unavailable for %s; trying reviewed duty SSOT",
                    employee_id,
                    exc_info=True,
                )
        if not manifest and contract:
            try:
                manifest = load_reviewed_duty_manifest(employee_id)
            except RECOVERABLE_ERRORS:
                logger.warning(
                    "reviewed duty manifest unavailable for %s",
                    employee_id,
                    exc_info=True,
                )
        candidates.append((employee_id, manifest, contract))
    return candidates


__all__ = ["build_employee_cron_candidates"]
