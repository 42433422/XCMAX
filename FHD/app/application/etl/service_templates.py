"""Private immutable ETL template versions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError, EtlNotFound
from app.application.etl.service_support import (
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    dump_json,
    load_json,
    new_id,
)
from app.application.etl.targets import get_adapter
from app.db.models.etl import EtlTemplate, EtlTemplateVersion
from app.infrastructure.tenant_scope import tenant_id_for_write


class TemplateServiceMixin:
    def create_template(
        self,
        db: Session,
        *,
        owner_user_id: int,
        name: str,
        target_type: str,
        draft: dict[str, Any],
        source_features: dict[str, Any] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        adapter = get_adapter(target_type)
        self._validate_draft(draft, adapter)
        template = EtlTemplate(
            id=new_id(),
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            name=str(name or "").strip()[:160],
            target_type=target_type,
            current_version=1,
            description=str(description or "").strip() or None,
        )
        if not template.name:
            raise EtlError("ETL_TEMPLATE_NAME_REQUIRED", "模板名称不能为空")
        version = self._build_version(
            template=template,
            owner_user_id=owner_user_id,
            version=1,
            draft=draft,
            source_features=source_features or {},
        )
        db.add_all([template, version])
        db.flush()
        return self.template_dict(template, version)

    def update_template(
        self,
        db: Session,
        *,
        template_id: str,
        owner_user_id: int,
        draft: dict[str, Any],
        source_features: dict[str, Any] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        template = self._owned_template(db, template_id, owner_user_id)
        self._validate_draft(draft, get_adapter(template.target_type))
        next_version = template.current_version + 1
        version = self._build_version(
            template=template,
            owner_user_id=owner_user_id,
            version=next_version,
            draft=draft,
            source_features=source_features or {},
        )
        if name is not None and str(name).strip():
            template.name = str(name).strip()[:160]
        if description is not None:
            template.description = str(description).strip() or None
        template.current_version = next_version
        db.add(version)
        db.flush()
        return self.template_dict(template, version)

    def _build_version(
        self,
        *,
        template: EtlTemplate,
        owner_user_id: int,
        version: int,
        draft: dict[str, Any],
        source_features: dict[str, Any],
    ) -> EtlTemplateVersion:
        return EtlTemplateVersion(
            id=new_id(),
            template_id=template.id,
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            version=version,
            target_type=template.target_type,
            source_features_json=dump_json(source_features),
            field_mappings_json=dump_json(draft.get("field_mappings") or []),
            validation_rules_json=dump_json(draft.get("validation_rules") or []),
            match_keys_json=dump_json(draft.get("match_keys") or []),
            allowed_update_fields_json=dump_json(draft.get("allowed_update_fields") or []),
            action_rules_json=dump_json(draft.get("action_rules") or {}),
        )

    def list_templates(self, db: Session, *, owner_user_id: int) -> list[dict[str, Any]]:
        # Print layouts share the private ETL persistence namespace for tenant
        # and owner isolation, but their fields describe a document layout —
        # never an import mapping. The document resolver reads them directly.
        templates = (
            db.query(EtlTemplate)
            .filter(
                EtlTemplate.owner_user_id == owner_user_id,
                EtlTemplate.is_active.is_(True),
                or_(
                    EtlTemplate.description.is_(None),
                    EtlTemplate.description != ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
                ),
            )
            .order_by(EtlTemplate.updated_at.desc())
            .all()
        )
        result = []
        for template in templates:
            version = self._current_version(db, template, owner_user_id)
            result.append(self.template_dict(template, version))
        return result

    def get_template(self, db: Session, *, template_id: str, owner_user_id: int) -> dict[str, Any]:
        template = self._owned_template(db, template_id, owner_user_id)
        return self.template_dict(
            template,
            self._current_version(db, template, owner_user_id),
        )

    def template_versions(
        self, db: Session, *, template_id: str, owner_user_id: int
    ) -> list[dict[str, Any]]:
        template = self._owned_template(db, template_id, owner_user_id)
        versions = (
            db.query(EtlTemplateVersion)
            .filter(
                EtlTemplateVersion.template_id == template.id,
                EtlTemplateVersion.owner_user_id == owner_user_id,
            )
            .order_by(EtlTemplateVersion.version.desc())
            .all()
        )
        return [self.template_dict(template, version) for version in versions]

    def delete_template(self, db: Session, *, template_id: str, owner_user_id: int) -> None:
        template = self._owned_template(db, template_id, owner_user_id)
        template.is_active = False

    def template_dict(self, template: EtlTemplate, version: EtlTemplateVersion) -> dict[str, Any]:
        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "target_type": template.target_type,
            "current_version": template.current_version,
            "version": {
                "id": version.id,
                "number": version.version,
                "source_features": load_json(version.source_features_json, {}),
                "field_mappings": load_json(version.field_mappings_json, []),
                "validation_rules": load_json(version.validation_rules_json, []),
                "match_keys": load_json(version.match_keys_json, []),
                "allowed_update_fields": load_json(version.allowed_update_fields_json, []),
                "action_rules": load_json(version.action_rules_json, {}),
                "created_at": (version.created_at.isoformat() if version.created_at else None),
            },
        }

    def _owned_template(self, db: Session, template_id: str, owner_user_id: int) -> EtlTemplate:
        template = (
            db.query(EtlTemplate)
            .filter(
                EtlTemplate.id == template_id,
                EtlTemplate.owner_user_id == owner_user_id,
                EtlTemplate.is_active.is_(True),
            )
            .first()
        )
        if template is None:
            raise EtlNotFound("模板")
        return template

    def _current_version(
        self, db: Session, template: EtlTemplate, owner_user_id: int
    ) -> EtlTemplateVersion:
        version = (
            db.query(EtlTemplateVersion)
            .filter(
                EtlTemplateVersion.template_id == template.id,
                EtlTemplateVersion.owner_user_id == owner_user_id,
                EtlTemplateVersion.version == template.current_version,
            )
            .first()
        )
        if version is None:
            raise EtlError("ETL_TEMPLATE_VERSION_MISSING", "模板版本不存在", status_code=409)
        return version
