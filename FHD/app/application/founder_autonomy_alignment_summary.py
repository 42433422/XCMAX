"""Public-safe alignment evidence fields for the founder autonomy snapshot."""

from __future__ import annotations

from typing import Any, Mapping

from app.application.founder_autonomy_support import _as_float, _as_int, _as_list


def build_alignment_live_summary(
    autonomy_audit: Mapping[str, Any],
    *,
    audit_available: bool,
    audit_total: int,
    prohibited_miss: bool,
    veto_rate: float,
) -> dict[str, Any]:
    """Keep aggregate alignment observability separate from score calculation."""

    return {
        "veto_rate": veto_rate,
        "autonomy_audit_authoritative": audit_available,
        "autonomy_audit_count": audit_total,
        "prohibited_miss_status": autonomy_audit.get("prohibited_miss_evidence_status")
        or ("detected" if prohibited_miss else "unknown"),
        "prohibited_posthoc_coverage_rate": _as_float(autonomy_audit.get("posthoc_coverage_rate")),
        "prohibited_posthoc_allow_count": _as_int(autonomy_audit.get("allow_count")),
        "prohibited_posthoc_conclusive_count": _as_int(
            autonomy_audit.get("posthoc_conclusive_count")
        ),
        "prohibited_posthoc_uncovered_count": _as_int(
            autonomy_audit.get("posthoc_uncovered_count")
        ),
        "prohibited_posthoc_uncovered_contracts": _as_list(
            autonomy_audit.get("posthoc_uncovered_contracts")
        ),
    }


__all__ = ["build_alignment_live_summary"]
