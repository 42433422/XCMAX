"""Deterministic founder-autonomy scorecard evidence analysis."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

_FAILED_STATUSES = {"fail", "failed", "missing", "blocked", "not_met", "unmet"}


def _load_scorecard(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("scorecard", payload.get("founder_autonomy_scorecard_json", payload))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("scorecard must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("scorecard must be a JSON object")
    return raw


def _failed(node: Dict[str, Any]) -> bool:
    status = str(node.get("status") or "").strip().lower().replace("-", "_")
    if status in _FAILED_STATUSES:
        return True
    return any(node.get(key) is False for key in ("passed", "ok", "met"))


def _receipt(node: Dict[str, Any]) -> str:
    for key in ("missing_receipt", "required_receipt", "evidence_receipt", "receipt"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return "missing"


def _collect(value: Any, path: Tuple[str, ...], out: List[Dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if _failed(value):
            name = str(
                value.get("name")
                or value.get("gate")
                or value.get("id")
                or (path[-1] if path else "gate")
            )
            receipt = _receipt(value)
            out.append(
                {
                    "gate": name[:200],
                    "path": ".".join(path)[:500],
                    "status": str(value.get("status") or "failed")[:80],
                    "missing_receipt": receipt,
                    "recommendation": (
                        f"Close gate {name[:200]} with immutable evidence: {receipt}"
                    ),
                }
            )
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                _collect(child, path + (str(key),), out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                _collect(child, path + (str(index),), out)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _collect_projection_dimensions(scorecard: Dict[str, Any], out: List[Dict[str, Any]]) -> None:
    """Recognize the public projection contract, whose dimensions are not `failed` nodes."""

    dimensions = scorecard.get("dimensions")
    if not isinstance(dimensions, list):
        return
    for index, raw in enumerate(dimensions):
        if not isinstance(raw, dict):
            continue
        progress = _number(raw.get("progress"))
        remaining = _number(raw.get("remaining"))
        incomplete = (progress is not None and progress < 100) or (
            remaining is not None and remaining > 0
        )
        if not incomplete:
            continue
        dimension_id = str(raw.get("id") or f"dimension-{index}").strip()
        label = str(raw.get("label") or dimension_id).strip()
        next_gap = str(raw.get("next_gap") or "missing immutable gate evidence").strip()
        progress_text = f"{progress:g}" if progress is not None else "unknown"
        out.append(
            {
                "gate": label[:200],
                "path": f"dimensions.{index}",
                "status": str(raw.get("status") or "incomplete")[:80],
                "missing_receipt": next_gap[:500],
                "recommendation": (
                    f"Close dimension {dimension_id} ({progress_text}/100) with immutable "
                    f"evidence for: {next_gap[:300]}"
                ),
            }
        )


def analyze_scorecard(payload: Dict[str, Any]) -> Dict[str, Any]:
    scorecard = _load_scorecard(payload)
    found: List[Dict[str, Any]] = []
    _collect_projection_dimensions(scorecard, found)
    _collect(scorecard, (), found)
    unique: List[Dict[str, Any]] = []
    seen = set()
    for row in found:
        key = (row["path"], row["gate"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    warnings = [] if unique else ["No failed evidence gate was found in the supplied scorecard."]
    summary = (
        f"Found {len(unique)} failed evidence gate(s); highest priority: {unique[0]['gate']}"
        if unique
        else "No failed evidence gate found."
    )
    return {"summary": summary, "failed_gates": unique, "warnings": warnings}
