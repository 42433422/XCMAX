"""Safe product-identity helpers shared by ETL parsers and adapters.

A customer may legitimately sell several products with the same name when their
models are known.  A row without a model, however, cannot safely be merged
with (or added beside) a row that has one.  These helpers make that uncertainty
an explicit validation error instead of guessing and creating a duplicate.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

MODEL_AMBIGUITY_CODE = "ETL_PRODUCT_MODEL_AMBIGUITY"
MODEL_AMBIGUITY_MESSAGE = (
    "同一客户同一产品同时出现有型号和无型号的记录，无法安全判断是否为同一产品；"
    "请补全型号或拆分后重新预演"
)


def product_name_key(data: dict[str, Any], *, unit_field: str = "unit") -> tuple[str, str]:
    """Return the same conservative customer/product key used by DB matching."""
    return (
        str(data.get(unit_field) or "").strip(),
        str(data.get("name") or "").strip(),
    )


def model_token(value: Any) -> str:
    return str(value or "").strip().casefold()


def validation_issue() -> dict[str, Any]:
    """Build the stable public issue returned by preview APIs."""
    return {
        "code": MODEL_AMBIGUITY_CODE,
        "field": "model_number",
        "severity": "error",
        "message": MODEL_AMBIGUITY_MESSAGE,
    }


def provenance_validation_issues(provenance: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Read parser-produced blocking issues without trusting arbitrary shapes."""
    raw_issues = (provenance or {}).get("validation_issues")
    if not isinstance(raw_issues, list):
        return []
    issues: list[dict[str, Any]] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()[:128]
        message = str(raw.get("message") or "").strip()[:500]
        if not code or not message:
            continue
        issues.append(
            {
                "code": code,
                "field": str(raw.get("field") or "").strip()[:160],
                "severity": str(raw.get("severity") or "error").strip()[:32] or "error",
                "message": message,
            }
        )
    return issues


def source_model_ambiguity_issues(
    rows: Iterable[dict[str, Any]],
    *,
    unit_field: str,
) -> dict[int, list[dict[str, Any]]]:
    """Mark every source row in a mixed model/no-model identity group.

    The result is keyed by the input row index so a parser can retain the two
    original rows and let the normal preview UI show both as blocking errors.
    """
    grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for index, data in enumerate(rows):
        key = product_name_key(data, unit_field=unit_field)
        if not all(key):
            continue
        grouped[key].append((index, model_token(data.get("model_number"))))

    result: dict[int, list[dict[str, Any]]] = {}
    for candidates in grouped.values():
        has_model = any(model for _index, model in candidates)
        has_missing_model = any(not model for _index, model in candidates)
        if not (has_model and has_missing_model):
            continue
        for index, _model in candidates:
            result.setdefault(index, []).append(validation_issue())
    return result


def candidate_model_token(candidate: Any) -> str:
    """Read a model from ORM rows or preview-state dictionaries."""
    if isinstance(candidate, dict):
        if "model_number" in candidate:
            return model_token(candidate.get("model_number"))
        after = candidate.get("after")
        if isinstance(after, dict):
            return model_token(after.get("model_number"))
    return model_token(getattr(candidate, "model_number", ""))


def database_model_ambiguity_issue(
    data: dict[str, Any],
    candidates: Iterable[Any],
    *,
    exact_match: bool,
) -> dict[str, Any] | None:
    """Fail closed if a missing model would select or create an uncertain row.

    An exact model match remains safe.  Everything else involving a known
    model-less candidate and a mismatched / absent model requires user repair.
    """
    incoming_model = model_token(data.get("model_number"))
    known_models = [candidate_model_token(candidate) for candidate in candidates]
    if not known_models:
        return None
    if not incoming_model and any(known_models):
        return validation_issue()
    if incoming_model and not exact_match and any(not model for model in known_models):
        return validation_issue()
    return None
