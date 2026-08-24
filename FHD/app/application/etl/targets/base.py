"""ETL target adapter contracts and serialisation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError


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


@dataclass(frozen=True, slots=True)
class TargetField:
    key: str
    label: str
    type: str = "string"
    required: bool = False
    aliases: tuple[str, ...] = ()
    updatable: bool = False


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
    execution_integrity_verifiable = False

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
            "execution_integrity_verifiable": self.execution_integrity_verifiable,
        }

    def validate(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for field in self.fields:
            if field.required and data.get(field.key) in (None, ""):
                issues.append(
                    {
                        "code": "ETL_REQUIRED_FIELD_MISSING",
                        "field": field.key,
                        "severity": "error",
                        "message": f"{field.label}不能为空",
                    }
                )
        return issues

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
        raise EtlError("ETL_TARGET_NOT_IMPLEMENTED", f"{self.label}暂不可执行")

    def rollback_row(
        self,
        db: Session,
        *,
        match_ref: str,
        before: dict[str, Any],
        after: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        raise EtlError("ETL_TARGET_NOT_REVERSIBLE", f"{self.label}不可撤销")

    def verify_execution_row(
        self,
        db: Session,
        *,
        match_ref: str,
        before: dict[str, Any],
        after: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """Verify that a successful receipt still resolves to its persisted target."""
        if self.execution_integrity_verifiable:
            raise EtlError(
                "ETL_EXECUTION_VERIFIER_MISSING",
                f"{self.label}缺少执行结果校验器，不能标记为成功",
                status_code=500,
            )

    def execute_batch(self, rows: Any, context: dict[str, Any]) -> dict[str, Any]:
        raise EtlError("ETL_TARGET_NOT_IMPLEMENTED", f"{self.label}不支持批量执行")
