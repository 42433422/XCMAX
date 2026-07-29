"""Historical receipt matching for idempotent production callbacks."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping


def _normalized_sha(value: Any) -> str:
    return str(value or "").strip().lower()


def completed_receipt(
    rows: Iterable[Mapping[str, Any]],
    *,
    merge_sha: str,
    environment: str,
    workflow_run_id: str,
    requested_run_id: str = "",
) -> Dict[str, Any] | None:
    """Match the exact callback first, then a redeploy of the same loop."""

    normalized = [dict(raw) if isinstance(raw, Mapping) else {} for raw in reversed(list(rows))]

    def _matches_scope(row: Mapping[str, Any]) -> bool:
        return (
            row.get("event") == "post_deploy_verified"
            and row.get("ok") is True
            and row.get("identity_verified") is True
            and _normalized_sha(row.get("merge_sha")) == merge_sha
            and str(row.get("environment") or "").lower() == environment
        )

    exact = next(
        (
            row
            for row in normalized
            if _matches_scope(row) and str(row.get("workflow_run_id") or "") == workflow_run_id
        ),
        None,
    )
    if exact is not None:
        return exact

    requested_run_id = str(requested_run_id or "").strip()
    if not requested_run_id:
        return None
    return next(
        (
            row
            for row in normalized
            if _matches_scope(row) and str(row.get("run_id") or "").strip() == requested_run_id
        ),
        None,
    )
