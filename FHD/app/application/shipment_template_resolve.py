"""打单意图 → 模版库选模版（生产级解析）。

优先级：
1. 显式 ``template_id``（db:/fs:/shipment …）
2. 用户偏好 / 槽位 ``preferred``（id 或名称）
3. 显式 ``template_name``（路径 / 文件名 / 库内名称）
4. 按客户名匹配版式模版（名称含 unit_name）
5. 按意图默认类型打分（布局优先，数据表降权）
6. TemplateStore.get_default_for_type
7. 回退 None（交 legacy DEFAULT_TEMPLATE；strict 时失败）

环境变量：
- ``XCAGI_SHIPMENT_TEMPLATE_STRICT=1``：无可用模版时不回退 legacy
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTENT_TEMPLATE_TYPES: dict[str, tuple[str, ...]] = {
    "shipment_generate": ("发货单", "出货明细", "出货记录", "Excel"),
    "shipment": ("发货单", "出货明细", "出货记录", "Excel"),
    "delivery": ("发货单", "出货明细", "Excel"),
    "orders": ("出货明细", "发货单", "Excel"),
}

_SHIPMENT_NAME_HINTS = ("发货", "送货", "出货", "shipment", "delivery")
_LAYOUT_EXTS = {".xlsx", ".xls", ".xlsm"}
_DATA_SCOPES = frozenset({"products", "materials", "customers", "salesReport"})


def shipment_template_strict_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("XCAGI_SHIPMENT_TEMPLATE_STRICT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def clear_template_list_cache() -> None:
    """Compatibility hook.

    Template lists used to be held in one process-global cache.  That cache
    had no tenant/owner key and could expose a prior request's list to another
    user.  Lists are intentionally read fresh now; the individual DB queries
    are small and every access remains scoped by the caller.
    """

    return None


def _get_template_store():
    try:
        from app.bootstrap import get_template_app_service

        svc = get_template_app_service()
        store = getattr(svc, "_template_service", None)
        if store is not None:
            return store
    except RECOVERABLE_ERRORS:
        pass
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore
    from app.utils.path_utils import get_app_data_dir

    return FileSystemTemplateStore(base_dir=get_app_data_dir())


def _normalize_unit_token(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"(有限责任公司|有限公司|公司|家私|家具|商贸|贸易|建材|装饰)", "", text)
    text = re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)
    return text


def _is_layout_file(path: str) -> bool:
    return Path(path).suffix.lower() in _LAYOUT_EXTS


def _row_active(row: dict[str, Any]) -> bool:
    flag = row.get("is_active", 1)
    return flag not in (0, False, "0", "false", "False")


def _list_templates_cached(store: Any) -> list[dict[str, Any]]:
    try:
        return list(store.list_templates() or [])
    except RECOVERABLE_ERRORS:
        return []


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


def _score_template(
    row: dict[str, Any],
    *,
    preferred_types: tuple[str, ...],
    unit_name: str = "",
) -> int:
    if not _row_active(row):
        return -1
    path = str(row.get("path") or "")
    if not path or not os.path.isfile(path) or not _is_layout_file(path):
        return -1

    score = 0
    ttype = str(row.get("template_type") or "").strip()
    name = str(row.get("name") or row.get("filename") or "").lower()
    scope = str(row.get("business_scope") or "").strip()

    if ttype in preferred_types:
        score += 100 - preferred_types.index(ttype) * 10
    if any(h in name for h in _SHIPMENT_NAME_HINTS):
        score += 30
    if str(row.get("source") or "") == "db":
        score += 20
    if scope in _DATA_SCOPES:
        score -= 40
    if ttype in {"Excel", "PPTX", "PDF"} and "发货" not in preferred_types[:1]:
        score -= 5

    unit_token = _normalize_unit_token(unit_name)
    name_token = _normalize_unit_token(name)
    if unit_token and name_token:
        if unit_token == name_token or unit_token in name_token or name_token in unit_token:
            score += 80

    try:
        score += min(int(row.get("db_id") or 0), 50)
    except (TypeError, ValueError):
        pass
    return score


def _result(
    *,
    ok: bool,
    path: str | None = None,
    template_id: str | None = None,
    template_name: str | None = None,
    template_type: str | None = None,
    source: str | None = None,
    reason: str,
    error_code: str | None = None,
    score: int | None = None,
    unit_name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "path": path,
        "template_id": template_id,
        "template_name": template_name,
        "template_type": template_type,
        "source": source,
        "reason": reason,
        "error_code": error_code or (None if ok else reason),
    }
    if score is not None:
        payload["score"] = score
    if unit_name:
        payload["unit_name"] = unit_name
    return payload


def _match_row_by_name(rows: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    key = needle.lower().strip()
    if not key:
        return None
    for row in rows:
        name = str(row.get("name") or "").lower()
        filename = str(row.get("filename") or "").lower()
        rid = str(row.get("id") or "").lower()
        if key in {name, filename, rid}:
            path = str(row.get("path") or "")
            if path and os.path.isfile(path) and _is_layout_file(path) and _row_active(row):
                return row
    return None


def _best_unit_template(
    rows: list[dict[str, Any]],
    *,
    preferred_types: tuple[str, ...],
    unit_name: str,
) -> tuple[dict[str, Any] | None, int]:
    """Select only a real customer-name match, never a generic default."""

    unit_token = _normalize_unit_token(unit_name)
    if not unit_token:
        return None, -1
    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        score = _score_template(row, preferred_types=preferred_types, unit_name=unit_name)
        name_token = _normalize_unit_token(str(row.get("name") or row.get("filename") or ""))
        unit_hit = bool(
            name_token
            and (unit_token == name_token or unit_token in name_token or name_token in unit_token)
        )
        if unit_hit and score > best_score:
            best_score = score
            best = row
    return best, best_score


def _template_row_result(
    row: dict[str, Any],
    *,
    unit_name: str,
    score: int,
    source: str | None = None,
) -> dict[str, Any]:
    path = str(row.get("path") or "")
    return _result(
        ok=True,
        path=path,
        template_id=str(row.get("id") or ""),
        template_name=row.get("name") or Path(path).name,
        template_type=row.get("template_type"),
        source=source or row.get("source") or "unit_match",
        reason=f"unit_match:{unit_name}",
        score=score,
        unit_name=unit_name,
    )


def _log_template_usage(
    template_id: str | None,
    *,
    action: str,
    result_text: str,
) -> None:
    tid = str(template_id or "").strip()
    db_id: int | None = None
    if tid.startswith("db:"):
        try:
            db_id = int(tid.split(":", 1)[1])
        except ValueError:
            db_id = None
    elif tid.isdigit():
        db_id = int(tid)
    if db_id is None:
        return
    try:
        from sqlalchemy import text

        from app.db.session import get_db

        with get_db() as db:
            db.execute(
                text(
                    """
                    INSERT INTO template_usage_log (template_id, action, result)
                    VALUES (:template_id, :action, :result)
                    """
                ),
                {
                    "template_id": db_id,
                    "action": action[:64],
                    "result": str(result_text or "")[:500],
                },
            )
            db.commit()
    except RECOVERABLE_ERRORS as exc:
        logger.debug("template_usage_log skip: %s", exc)


def log_template_usage(
    template_id: str | None,
    *,
    action: str,
    result_text: str,
) -> None:
    """对外审计入口（generate 成功后写入 template_usage_log）。"""
    _log_template_usage(template_id, action=action, result_text=result_text)


def resolve_shipment_template(
    *,
    template_id: str | None = None,
    template_name: str | None = None,
    preferred: str | None = None,
    unit_name: str | None = None,
    owner_user_id: int | None = None,
    intent: str = "shipment_generate",
    strict: bool | None = None,
    log_usage: bool = False,
) -> dict[str, Any]:
    """解析打单应使用的模版文件。"""
    tid = str(template_id or "").strip()
    tname = str(template_name or "").strip()
    pref = str(preferred or "").strip()
    unit = str(unit_name or "").strip()
    intent_key = str(intent or "shipment_generate").strip() or "shipment_generate"
    preferred_types = _INTENT_TEMPLATE_TYPES.get(
        intent_key, _INTENT_TEMPLATE_TYPES["shipment_generate"]
    )
    strict_mode = shipment_template_strict_enabled(strict)
    scoped_owner_user_id = _current_owner_user_id(owner_user_id)

    # An opaque preview-layout reference is not a persisted template.  It can
    # only resolve through the current tenant + authenticated owner and becomes
    # a one-use temporary workbook during this confirmed generation request.
    if tid.startswith("etl-preview:"):
        run_id = tid.split(":", 1)[1].strip()
        preview = _resolve_preview_layout_candidate(
            owner_user_id=scoped_owner_user_id,
            unit_name=unit,
            run_id=run_id or None,
        )
        if preview:
            return preview
        return _result(
            ok=False,
            template_id=tid,
            reason="preview_template_not_found",
            error_code="ETL_PREVIEW_TEMPLATE_NOT_FOUND",
            unit_name=unit or None,
        )

    # Private ETL layouts never enter the tenant-wide generic template store.
    # Resolve an opaque ``etl:<uuid>`` only against the authenticated owner's
    # own tenant-scoped record before considering any legacy IDs.
    if tid.startswith("etl:"):
        row = _resolve_private_layout_id(tid, scoped_owner_user_id)
        if row:
            path = str(row["path"])
            out = _result(
                ok=True,
                path=path,
                template_id=str(row["id"]),
                template_name=row.get("name") or Path(path).name,
                template_type=row.get("template_type"),
                source="etl_private",
                reason="resolved_private_etl_template_id",
                unit_name=unit or None,
            )
            return out
        return _result(
            ok=False,
            template_id=tid,
            reason="private_template_not_found",
            error_code="ETL_PRIVATE_TEMPLATE_NOT_FOUND",
            unit_name=unit or None,
        )

    private_rows = _private_layout_rows(scoped_owner_user_id)

    # Priority for the upload -> same-customer bill loop:
    # explicit user selection (handled above) > a saved personal layout for
    # this customer > an unsaved ETL preview layout > generic/shared defaults.
    # A generic template must not hide the layout the user just extracted, but
    # a deliberately saved personal customer layout remains authoritative.
    if not tid and not tname and not pref and unit:
        private_unit, private_unit_score = _best_unit_template(
            private_rows,
            preferred_types=preferred_types,
            unit_name=unit,
        )
        if private_unit is not None and private_unit_score >= 0:
            return _template_row_result(
                private_unit,
                unit_name=unit,
                score=private_unit_score,
                source="etl_private",
            )
        preview = _resolve_preview_layout_candidate(
            owner_user_id=scoped_owner_user_id,
            unit_name=unit,
        )
        if preview:
            return preview

    try:
        store = _get_template_store()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("模版库不可用，打单回退 legacy: %s", exc)
        if not tid and not tname and not pref:
            preview = _resolve_preview_layout_candidate(
                owner_user_id=scoped_owner_user_id,
                unit_name=unit,
            )
            if preview:
                return preview
        return _result(
            ok=False,
            path=tname or None,
            template_id=tid or None,
            template_name=tname or None,
            reason="store_unavailable",
            error_code="TEMPLATE_STORE_UNAVAILABLE",
            unit_name=unit or None,
        )

    # 1) template_id
    if tid:
        path = store.resolve_template_file(tid)
        if path and os.path.isfile(path) and _is_layout_file(path):
            out = _result(
                ok=True,
                path=path,
                template_id=tid,
                template_name=Path(path).name,
                source="template_id",
                reason="resolved_by_id",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(tid, action="resolve", result_text=out["reason"])
            return out
        if strict_mode:
            return _result(
                ok=False,
                template_id=tid,
                reason="template_id_not_found",
                error_code="TEMPLATE_ID_NOT_FOUND",
                unit_name=unit or None,
            )

    # 1.5) 用户偏好 / 槽位 preferred（可是 id 或名称）
    if pref and not tid:
        if pref.startswith("etl:"):
            row = _resolve_private_layout_id(pref, scoped_owner_user_id)
            if row:
                path = str(row["path"])
                return _result(
                    ok=True,
                    path=path,
                    template_id=str(row["id"]),
                    template_name=row.get("name") or Path(path).name,
                    template_type=row.get("template_type"),
                    source="etl_private",
                    reason="resolved_private_etl_preference_id",
                    unit_name=unit or None,
                )
            if strict_mode:
                return _result(
                    ok=False,
                    template_id=pref,
                    reason="private_template_not_found",
                    error_code="ETL_PRIVATE_TEMPLATE_NOT_FOUND",
                    unit_name=unit or None,
                )
        if pref.startswith(("db:", "fs:", "shipment")) or pref.isdigit():
            path = store.resolve_template_file(
                pref if pref.startswith(("db:", "fs:")) else f"db:{pref}"
            )
            if path and os.path.isfile(path) and _is_layout_file(path):
                out = _result(
                    ok=True,
                    path=path,
                    template_id=pref if pref.startswith("db:") else f"db:{pref}",
                    template_name=Path(path).name,
                    source="user_preference",
                    reason="resolved_by_preference_id",
                    unit_name=unit or None,
                )
                if log_usage:
                    _log_template_usage(
                        out["template_id"], action="resolve", result_text=out["reason"]
                    )
                return out
        rows = private_rows + _list_templates_cached(store)
        row = _match_row_by_name(rows, pref)
        if row:
            path = str(row["path"])
            out = _result(
                ok=True,
                path=path,
                template_id=str(row.get("id") or ""),
                template_name=row.get("name") or Path(path).name,
                template_type=row.get("template_type"),
                source="user_preference",
                reason="resolved_by_preference_name",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(out["template_id"], action="resolve", result_text=out["reason"])
            return out

    # 2) 显式路径 / 文件名
    if tname:
        as_path = Path(tname).expanduser()
        if as_path.is_file() and _is_layout_file(str(as_path)):
            from app.infrastructure.tenant_scope import current_tenant_id

            private_path = _safe_private_layout_path(
                as_path,
                tenant_id=current_tenant_id(),
                owner_user_id=scoped_owner_user_id,
            )
            if _is_any_private_layout_path(as_path) and not private_path:
                return _result(
                    ok=False,
                    template_name=tname,
                    reason="private_template_path_forbidden",
                    error_code="ETL_PRIVATE_TEMPLATE_FORBIDDEN",
                    unit_name=unit or None,
                )
            out = _result(
                ok=True,
                path=private_path or str(as_path.resolve()),
                template_id=tid or None,
                template_name=as_path.name,
                source="explicit_path",
                reason="resolved_by_path",
                unit_name=unit or None,
            )
            return out
        rows = private_rows + _list_templates_cached(store)
        row = _match_row_by_name(rows, tname)
        if row:
            path = str(row["path"])
            out = _result(
                ok=True,
                path=path,
                template_id=str(row.get("id") or ""),
                template_name=row.get("name") or Path(path).name,
                template_type=row.get("template_type"),
                source=row.get("source") or "name_match",
                reason="resolved_by_name",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(out["template_id"], action="resolve", result_text=out["reason"])
            return out
        # 交给 legacy 按文件名搜索（非 strict）
        if not strict_mode:
            return _result(
                ok=True,
                path=tname,
                template_id=tid or None,
                template_name=tname,
                source="legacy_name",
                reason="passthrough_filename",
                unit_name=unit or None,
            )
        return _result(
            ok=False,
            template_name=tname,
            reason="template_name_not_found",
            error_code="TEMPLATE_NAME_NOT_FOUND",
            unit_name=unit or None,
        )

    rows = private_rows + _list_templates_cached(store)

    # 3) 客户名匹配版式
    if unit:
        best_unit: dict[str, Any] | None = None
        best_unit_score = -1
        for row in rows:
            score = _score_template(row, preferred_types=preferred_types, unit_name=unit)
            # 仅当客户名真正命中才走本分支（避免被通用高分抢走）
            name_token = _normalize_unit_token(str(row.get("name") or row.get("filename") or ""))
            unit_token = _normalize_unit_token(unit)
            unit_hit = bool(
                unit_token
                and name_token
                and (
                    unit_token == name_token or unit_token in name_token or name_token in unit_token
                )
            )
            if unit_hit and score > best_unit_score:
                best_unit_score = score
                best_unit = row
        if best_unit and best_unit_score >= 0:
            path = str(best_unit.get("path") or "")
            out = _result(
                ok=True,
                path=path,
                template_id=str(best_unit.get("id") or ""),
                template_name=best_unit.get("name") or Path(path).name,
                template_type=best_unit.get("template_type"),
                source=best_unit.get("source") or "unit_match",
                reason=f"unit_match:{unit}",
                score=best_unit_score,
                unit_name=unit,
            )
            if log_usage:
                _log_template_usage(out["template_id"], action="resolve", result_text=out["reason"])
            return out

    # 4) 意图默认打分
    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        score = _score_template(row, preferred_types=preferred_types, unit_name=unit)
        if score > best_score:
            best_score = score
            best = row
    if best and best_score >= 0:
        path = str(best.get("path") or "")
        out = _result(
            ok=True,
            path=path,
            template_id=str(best.get("id") or ""),
            template_name=best.get("name") or Path(path).name,
            template_type=best.get("template_type"),
            source=best.get("source") or "intent_default",
            reason=f"intent_default:{intent_key}",
            score=best_score,
            unit_name=unit or None,
        )
        if log_usage:
            _log_template_usage(out["template_id"], action="resolve", result_text=out["reason"])
        return out

    # 5) Store 官方默认
    for ttype in preferred_types:
        try:
            row = store.get_default_for_type(ttype)
        except RECOVERABLE_ERRORS:
            row = None
        if (
            row
            and row.get("path")
            and os.path.isfile(str(row["path"]))
            and _is_layout_file(str(row["path"]))
        ):
            out = _result(
                ok=True,
                path=str(row["path"]),
                template_id=str(row.get("id") or ""),
                template_name=row.get("name") or Path(str(row["path"])).name,
                template_type=row.get("template_type") or ttype,
                source=row.get("source") or "store_default",
                reason=f"store_default:{ttype}",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(out["template_id"], action="resolve", result_text=out["reason"])
            return out

    # A detected delivery-note layout is usable only when the user has not
    # selected a persisted template and no persisted/default layout resolved.
    # It stays out of the template library and is deleted after this confirmed
    # document generation.  This closes upload -> preview -> one document
    # without turning an unexecuted ETL preview into master/template data.
    if not tid and not tname and not pref:
        preview = _resolve_preview_layout_candidate(
            owner_user_id=scoped_owner_user_id,
            unit_name=unit,
        )
        if preview:
            return preview

    return _result(
        ok=False,
        path=None,
        template_id=None,
        template_name=None,
        reason="no_template_found",
        error_code="TEMPLATE_NOT_FOUND",
        unit_name=unit or None,
    )


def resolve_products_for_unit(unit_name: str, *, limit: int = 1) -> list[dict[str, Any]]:
    """打单缺产品明细时，用该客户最近出货记录明细兜底。"""
    name = str(unit_name or "").strip()
    if not name:
        return []
    try:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
        getter = getattr(svc, "get_latest_products_for_unit", None)
        if callable(getter):
            rows = getter(name, limit=limit)
            if isinstance(rows, list) and rows:
                return list(rows)
        orders = svc.get_orders(20) or []
        unit_token = _normalize_unit_token(name)
        for order in orders:
            if not isinstance(order, dict):
                continue
            customer = str(
                order.get("customer_name")
                or order.get("unit_name")
                or order.get("purchase_unit")
                or ""
            ).strip()
            cust_token = _normalize_unit_token(customer)
            if customer and (
                customer == name
                or name in customer
                or customer in name
                or (unit_token and cust_token and unit_token in cust_token)
            ):
                items = order.get("products") or order.get("items") or []
                if isinstance(items, list) and items:
                    return list(items)
    except RECOVERABLE_ERRORS as exc:
        logger.debug("resolve_products_for_unit failed: %s", exc, exc_info=True)
    return []
