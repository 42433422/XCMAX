"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def _current_owner_user_id(explicit_owner_user_id: int | None = None) -> int | None:
    """Resolve the authenticated desktop user's id without accepting a guess.

    Private ETL layouts must never fall back to a tenant-wide default.  Direct
    service callers can pass the id explicitly; HTTP callers receive it from
    the request context established by ``IndustryContextMiddleware``.
    """

    if explicit_owner_user_id is not None:
        try:
            value = int(explicit_owner_user_id)
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None
    try:
        from app.infrastructure.request_context import get_current_request

        request = get_current_request()
        value = getattr(getattr(request, "state", None), "user_id", None)
        value = int(value) if value is not None else None
        return value if value and value > 0 else None
    except (ImportError, TypeError, ValueError, AttributeError):
        return None


def _private_layout_root(tenant_id: int, owner_user_id: int) -> Path:
    from app.utils.path_utils import get_app_data_dir

    return (
        Path(get_app_data_dir()).resolve()
        / "tenants"
        / str(int(tenant_id))
        / "document_templates"
        / str(int(owner_user_id))
    ).resolve()


def _safe_private_layout_path(
    value: str | os.PathLike[str] | None,
    *,
    tenant_id: int | None,
    owner_user_id: int | None,
) -> str | None:
    """Return an existing layout only when it lives under this user's root."""

    if tenant_id is None or owner_user_id is None:
        return None
    try:
        candidate = Path(value or "").expanduser().resolve()
        root = _private_layout_root(tenant_id, owner_user_id)
    except (OSError, TypeError, ValueError):
        return None
    if root not in candidate.parents:
        return None
    if not candidate.is_file() or not _is_layout_file(str(candidate)):
        return None
    return str(candidate)


def _is_any_private_layout_path(value: str | os.PathLike[str] | None) -> bool:
    """Whether a path points into any tenant's owner-scoped layout directory."""

    try:
        candidate = Path(value or "").expanduser().resolve()
        parts = candidate.parts
        marker = "document_templates"
        if marker not in parts:
            return False
        index = parts.index(marker)
        return index >= 2 and len(parts) > index + 2 and parts[index - 2] == "tenants"
    except (OSError, TypeError, ValueError):
        return False


def _private_layout_rows(owner_user_id: int | None) -> list[dict[str, Any]]:
    """Read only this tenant + user's ETL-promoted shipment layouts."""

    if owner_user_id is None:
        return []
    try:
        from app.application.etl.service_support import load_json
        from app.db.models.etl import EtlTemplate, EtlTemplateVersion
        from app.db.session import get_db
        from app.infrastructure.tenant_scope import current_tenant_id

        tenant_id = current_tenant_id()
        if tenant_id is None:
            return []
        with get_db() as db:
            templates = (
                db.query(EtlTemplate)
                .filter(
                    EtlTemplate.id.is_not(None),
                    EtlTemplate.tenant_id == int(tenant_id),
                    EtlTemplate.owner_user_id == int(owner_user_id),
                    EtlTemplate.target_type == "shipment_records",
                    EtlTemplate.is_active.is_(True),
                    EtlTemplate.description == "ETL_SHIPMENT_DOCUMENT_TEMPLATE",
                )
                .order_by(EtlTemplate.updated_at.desc())
                .all()
            )
            rows: list[dict[str, Any]] = []
            for template in templates:
                version = (
                    db.query(EtlTemplateVersion)
                    .filter(
                        EtlTemplateVersion.template_id == template.id,
                        EtlTemplateVersion.tenant_id == int(tenant_id),
                        EtlTemplateVersion.owner_user_id == int(owner_user_id),
                        EtlTemplateVersion.version == template.current_version,
                    )
                    .first()
                )
                if version is None:
                    continue
                features = load_json(version.source_features_json, {})
                meta = (
                    features.get("shipment_document_template") if isinstance(features, dict) else {}
                )
                if not isinstance(meta, dict):
                    continue
                path = _safe_private_layout_path(
                    meta.get("file_path"),
                    tenant_id=int(tenant_id),
                    owner_user_id=int(owner_user_id),
                )
                if not path:
                    continue
                rows.append(
                    {
                        "id": f"etl:{template.id}",
                        "name": str(template.name or ""),
                        "path": path,
                        "file_path": path,
                        "filename": Path(path).name,
                        "template_type": "发货单",
                        "category": "excel",
                        "source": "etl_private",
                        "is_active": 1,
                        "version": int(version.version),
                        "updated_at": getattr(template, "updated_at", None),
                    }
                )
            return rows
    except RECOVERABLE_ERRORS:
        logger.warning("读取私有 ETL 发货单版式失败", exc_info=True)
        return []


def _resolve_private_layout_id(
    template_id: str, owner_user_id: int | None
) -> dict[str, Any] | None:
    normalized = str(template_id or "").strip()
    if not normalized.startswith("etl:"):
        return None
    return next(
        (row for row in _private_layout_rows(owner_user_id) if row["id"] == normalized), None
    )


def _preview_layout_result(
    candidate: dict[str, Any],
    *,
    unit_name: str,
) -> dict[str, Any]:
    """Convert one trusted ETL preview layout into resolver metadata.

    ``cleanup_path`` remains an internal key.  The shipment application service
    removes it after the synchronous workbook generator consumes the temporary
    file; it is never promoted to a saved template.
    """

    path = str(candidate.get("path") or "")
    out = _result(
        ok=True,
        path=path,
        template_id=str(candidate.get("template_id") or ""),
        template_name=str(candidate.get("name") or Path(path).name),
        template_type="发货单",
        source="etl_preview_candidate",
        reason="resolved_etl_preview_layout_candidate",
        unit_name=unit_name or None,
    )
    out["warning"] = str(candidate.get("warning") or "")
    out["provenance"] = (
        dict(candidate.get("provenance")) if isinstance(candidate.get("provenance"), dict) else {}
    )
    out["_cleanup_path"] = str(candidate.get("cleanup_path") or path)
    return out


def _resolve_preview_layout_candidate(
    *,
    owner_user_id: int | None,
    unit_name: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Materialize a one-use, owner-scoped ETL preview layout.

    It is deliberately a final fallback after private/persisted templates.  A
    source upload is re-validated by the ETL helper; no caller-supplied path or
    unscoped run can reach the workbook generator.
    """

    if owner_user_id is None or not str(unit_name or "").strip():
        return None
    try:
        from app.application.etl.shipment_preview_fallback import (
            materialize_preview_layout_candidate,
        )

        candidate = materialize_preview_layout_candidate(
            owner_user_id=owner_user_id,
            unit_name=unit_name,
            run_id=run_id,
        )
    except RECOVERABLE_ERRORS:
        return None
    if not isinstance(candidate, dict) or not str(candidate.get("path") or "").strip():
        return None
    return _preview_layout_result(candidate, unit_name=unit_name)


sync_module_functions(
    target=globals(),
    source_module="app.application.shipment_template_resolve",
    function_names=(
        "_current_owner_user_id",
        "_private_layout_root",
        "_safe_private_layout_path",
        "_is_any_private_layout_path",
        "_private_layout_rows",
        "_resolve_private_layout_id",
        "_preview_layout_result",
        "_resolve_preview_layout_candidate",
    ),
)
