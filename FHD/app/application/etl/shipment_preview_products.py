"""Product matching helpers for shipment ETL preview candidates."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Callable, cast

from app.application.etl.service_support import load_json
from app.db.models.etl import EtlRun, EtlRunRow
from app.utils.operational_errors import RECOVERABLE_ERRORS

PREVIEW_READY = "preview_ready"
PRODUCT_ACTIONS = frozenset({"new", "update"})
PARENTHETICAL_CUSTOMER_ALIAS_RE = re.compile(r"[（(][^）)]*[）)]")

PRODUCT_PREVIEW_WARNING = (
    "产品信息来自尚未执行的 ETL 预演候选，仅用于本次已确认的发货单；未写入产品库。"
)


def normalize_customer_name(value: Any) -> str:
    """Normalize the conservative customer aliases accepted by shipment mode."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = PARENTHETICAL_CUSTOMER_ALIAS_RE.sub("", text)
    text = re.sub(r"(有限责任公司|有限公司|公司|家私|家具|商贸|贸易|建材|装饰)", "", text)
    return re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)


def normalize_product_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)


def valid_owner_and_tenant(owner_user_id: int | None, tenant_id: Any) -> tuple[int, int] | None:
    try:
        owner = int(owner_user_id) if owner_user_id is not None else 0
    except (TypeError, ValueError):
        return None
    if owner <= 0 or tenant_id is None:
        return None
    try:
        return int(tenant_id), owner
    except (TypeError, ValueError):
        return None


def row_is_valid_candidate(row: EtlRunRow) -> dict[str, Any] | None:
    if str(row.final_action or "").strip().lower() not in PRODUCT_ACTIONS:
        return None
    issues = load_json(row.validation_json, None)
    if not isinstance(issues, list) or issues:
        return None
    normalized = load_json(row.normalized_json, None)
    return normalized if isinstance(normalized, dict) else None


def candidate_customer_name(normalized: dict[str, Any]) -> str:
    for key in ("customer_name", "purchase_unit", "unit_name"):
        value = str(normalized.get(key) or "").strip()
        if value:
            return value
    return ""


def candidate_product_name(normalized: dict[str, Any]) -> str:
    for key in ("name", "product_name"):
        value = str(normalized.get(key) or "").strip()
        if value:
            return value
    return ""


def candidate_price(normalized: dict[str, Any]) -> float | None:
    value = normalized.get("price")
    if value in (None, ""):
        value = normalized.get("unit_price")
    if value in (None, ""):
        return None
    try:
        price = float(str(value).replace(",", "").replace("￥", "").replace("¥", ""))
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price >= 0 else None


def candidate_specification(normalized: dict[str, Any]) -> float | None:
    value = normalized.get("specification")
    if value in (None, ""):
        value = normalized.get("tin_spec")
    if value in (None, ""):
        return None
    try:
        specification = float(str(value).replace(",", "").replace("KG", "").replace("kg", ""))
    except (TypeError, ValueError):
        return None
    return specification if math.isfinite(specification) and specification > 0 else None


def candidate_source_date(row: EtlRunRow) -> str:
    provenance = load_json(row.provenance_json, {})
    if not isinstance(provenance, dict):
        return ""
    value = str(provenance.get("source_date") or provenance.get("order_date") or "").strip()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return ""


def preview_runs(
    db: Any,
    *,
    tenant_id: int,
    owner_user_id: int,
    target_type: str,
) -> list[EtlRun]:
    return cast(
        "list[EtlRun]",
        db.query(EtlRun)
        .filter(
            EtlRun.tenant_id == tenant_id,
            EtlRun.owner_user_id == owner_user_id,
            EtlRun.target_type == target_type,
            EtlRun.status == PREVIEW_READY,
        )
        .order_by(EtlRun.updated_at.desc(), EtlRun.created_at.desc(), EtlRun.id.desc())
        .limit(50)
        .all(),
    )


def resolve_product_candidate_outcome(
    *,
    owner_user_id: int | None,
    unit_name: str,
    product_name: str,
    get_database: Callable[[], Any],
    valid_scope: Callable[[int | None], tuple[int, int] | None],
    get_preview_runs: Callable[..., list[EtlRun]],
    validate_row: Callable[[EtlRunRow], dict[str, Any] | None],
) -> dict[str, Any]:
    scope = valid_scope(owner_user_id)
    normalized_unit = normalize_customer_name(unit_name)
    normalized_product = normalize_product_name(product_name)
    if scope is None or not normalized_unit or not normalized_product:
        return {"status": "unavailable", "candidate": None}
    tenant_id, owner = scope
    try:
        with get_database() as db:
            matches: list[dict[str, Any]] = []
            runs = get_preview_runs(
                db,
                tenant_id=tenant_id,
                owner_user_id=owner,
                target_type="customer_products",
            )
            for run_rank, run in enumerate(runs):
                rows = (
                    db.query(EtlRunRow)
                    .filter(
                        EtlRunRow.run_id == run.id,
                        EtlRunRow.tenant_id == tenant_id,
                        EtlRunRow.owner_user_id == owner,
                    )
                    .order_by(
                        EtlRunRow.source_sheet.asc(),
                        EtlRunRow.source_row.asc(),
                        EtlRunRow.id.asc(),
                    )
                    .all()
                )
                for row in rows:
                    normalized = validate_row(row)
                    if normalized is None:
                        continue
                    candidate_unit = candidate_customer_name(normalized)
                    candidate_name = candidate_product_name(normalized)
                    if (
                        normalize_customer_name(candidate_unit) != normalized_unit
                        or normalize_product_name(candidate_name) != normalized_product
                    ):
                        continue
                    matches.append(
                        {
                            "run": run,
                            "run_rank": run_rank,
                            "row": row,
                            "name": candidate_name,
                            "model_number": str(normalized.get("model_number") or "")
                            .strip()
                            .upper(),
                            "price": candidate_price(normalized),
                            "specification": candidate_specification(normalized),
                            "source_date": candidate_source_date(row),
                        }
                    )
            if not matches:
                return {"status": "not_found", "candidate": None}
            dated = [match for match in matches if match["source_date"]]
            if dated:
                newest_date = max(str(match["source_date"]) for match in dated)
                finalists = [match for match in dated if match["source_date"] == newest_date]
            else:
                newest_run_rank = min(int(match["run_rank"]) for match in matches)
                finalists = [
                    match for match in matches if int(match["run_rank"]) == newest_run_rank
                ]
            identities = {
                (
                    normalize_product_name(str(match["name"])),
                    str(match["model_number"]),
                    match["price"],
                    match["specification"],
                )
                for match in finalists
            }
            if len(identities) != 1:
                return {"status": "conflict", "candidate": None}
            finalist = sorted(
                finalists,
                key=lambda match: (
                    int(match["run_rank"]),
                    str(match["row"].source_sheet or ""),
                    int(match["row"].source_row),
                    int(match["row"].id or 0),
                ),
            )[0]
            row = finalist["row"]
            candidate_name = str(finalist["name"])
            model_number = str(finalist["model_number"])
            price = finalist["price"]
            specification = finalist["specification"]
            source_date = str(finalist["source_date"])
            return {
                "status": "resolved",
                "candidate": {
                    "name": candidate_name,
                    "model_number": model_number,
                    "price": price,
                    "specification": specification,
                    "source_date": source_date or None,
                    "unit_name": str(unit_name or "").strip(),
                    "warning": PRODUCT_PREVIEW_WARNING,
                    "provenance": {
                        "kind": "etl_preview_product_candidate",
                        "run_id": str(finalist["run"].id),
                        "source_sheet": str(row.source_sheet or ""),
                        "source_row": int(row.source_row),
                        "source_date": source_date or None,
                        "resolved_product": {
                            "name": candidate_name,
                            "model_number": model_number,
                            "unit_price": price,
                            "specification": specification,
                        },
                    },
                },
            }
    except RECOVERABLE_ERRORS:
        return {"status": "unavailable", "candidate": None}
    return {"status": "not_found", "candidate": None}
