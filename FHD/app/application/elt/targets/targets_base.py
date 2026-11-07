"""ETL target adapter contracts and serialisation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.application.elt.errors import EltError


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def strict_decimal(value: Any) -> Decimal | None:
    """Exact numeric value; None/blank stay None, booleans are never numbers."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise EltError("ELT_NUMBER_INVALID", f"布尔值不能当作数字: {value}")
    if isinstance(value, Decimal):
        return value
    # Excel stores doubles but shows 15 significant digits; that is the business value.
    text = format(value, ".15g") if isinstance(value, float) else str(value)
    try:
        number = Decimal(text.strip().replace(",", ""))
    except ArithmeticError as exc:
        raise EltError("ELT_NUMBER_INVALID", f"数字格式不正确: {value}") from exc
    if not number.is_finite():
        raise EltError("ELT_NUMBER_INVALID", f"数字格式不正确: {value}")
    return number


@dataclass(frozen=True, slots=True)
class TargetField:
    key: str
    label: str
    type: str = "string"
    required: bool = False
    aliases: tuple[str, ...] = ()
    updatable: bool = False
    scale: int | None = None


@dataclass(slots=True)
class PreviewDecision:
    action: str
    match_ref: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    issues: list[dict[str, Any]] | None = None
    reason: str = ""


class TargetAdapter:
    type = ""
    label = ""
    reversible = False
    actions: tuple[str, ...] = ("new", "skip")
    fields: tuple[TargetField, ...] = ()
    default_match_keys: tuple[str, ...] = ()
    allow_dynamic_fields = False

    def capability(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "fields": [asdict(field) for field in self.fields],
            "required_fields": [field.key for field in self.fields if field.required],
            "default_match_keys": list(self.default_match_keys),
            "supported_actions": list(self.actions),
            "reversible": self.reversible,
            "allow_dynamic_fields": self.allow_dynamic_fields,
        }

    def validate(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for field in self.fields:
            if field.required and data.get(field.key) in (None, ""):
                issues.append(
                    {
                        "code": "ELT_REQUIRED_FIELD_MISSING",
                        "field": field.key,
                        "severity": "error",
                        "message": f"{field.label}不能为空",
                    }
                )
            elif field.type in {"number", "integer"}:
                issues.extend(self._numeric_issues(field, data.get(field.key)))
        return issues

    @staticmethod
    def _numeric_issues(field: TargetField, value: Any) -> list[dict[str, Any]]:
        try:
            number = strict_decimal(value)
        except EltError as exc:
            return [{"code": exc.code, "field": field.key, "severity": "error", "message": exc.message}]
        if number is None:
            return []
        scale = 0 if field.type == "integer" else field.scale
        exponent = number.normalize().as_tuple().exponent
        if scale is not None and isinstance(exponent, int) and -exponent > scale:
            return [
                {
                    "code": "ELT_NUMBER_PRECISION_EXCEEDED",
                    "field": field.key,
                    "severity": "error",
                    "message": f"{field.label}最多保留 {scale} 位小数，拒绝擅自舍入: {value}",
                }
            ]
        return []

    def preview(
        self,
        db: Session,
        data: dict[str, Any],
        *,
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> PreviewDecision:
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        return PreviewDecision("new", after=json_safe(data), reason="no_duplicate")

    def execute_row(
        self,
        db: Session,
        data: dict[str, Any],
        *,
        action: str,
        match_ref: str,
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        raise EltError("ELT_TARGET_NOT_IMPLEMENTED", f"{self.label}暂不可执行")

    def rollback_row(
        self,
        db: Session,
        *,
        match_ref: str,
        before: dict[str, Any],
        after: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        raise EltError("ELT_TARGET_NOT_REVERSIBLE", f"{self.label}不可撤销")

    def execute_batch(self, rows: Any, context: dict[str, Any]) -> dict[str, Any]:
        raise EltError("ELT_TARGET_NOT_IMPLEMENTED", f"{self.label}不支持批量执行")
