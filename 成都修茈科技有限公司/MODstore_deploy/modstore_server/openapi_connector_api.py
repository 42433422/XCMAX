"""OpenAPI 连接器 REST API。

闭环：导入 spec -> 解析 operation -> 配置鉴权 -> 服务端试调用 -> 发布工作流节点 -> 查日志。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_crypto import fernet_configured
from modstore_server.models import (
    OpenApiCallLog,
    OpenApiConnector,
    OpenApiCredential,
    OpenApiOperation,
    User,
    Workflow,
    WorkflowNode,
)
from modstore_server.openapi_connector_codegen import (
    cleanup_old_versions,
    default_artifacts_root,
    generate_client_files,
)
from modstore_server.openapi_connector_parser import (
    OpenApiParseError,
    ParsedSpec,
    parse_spec,
)
from modstore_server.openapi_connector_runtime import (
    SUPPORTED_AUTH_TYPES,
    OutboundBlocked,
    assert_url_outbound_safe,
    call_generated_operation,
    decrypt_credential_payload,
    encrypt_credential_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/openapi-connectors", tags=["openapi-connectors"])

_KEEP_VERSIONS = 2
_SPEC_FETCH_TIMEOUT = 20.0
_MAX_SPEC_BYTES = 4 * 1024 * 1024  # 4MB


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ImportConnectorBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    spec_text: Optional[str] = Field(None, max_length=2_000_000)
    spec_url: Optional[str] = Field(None, max_length=2048)
    base_url_override: Optional[str] = Field(None, max_length=512)


class CredentialBody(BaseModel):
    auth_type: str = Field(..., min_length=1, max_length=32)
    config: Dict[str, Any] = Field(default_factory=dict)


class OperationToggleBody(BaseModel):
    enabled: bool


class TestCallBody(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0


class PublishWorkflowNodeBody(BaseModel):
    workflow_id: int = Field(..., ge=1)
    operation_id: str = Field(..., min_length=1, max_length=128)
    name: Optional[str] = Field(None, max_length=256)
    input_mapping: Dict[str, Any] = Field(default_factory=dict)
    output_mapping: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(30, ge=1, le=120)
    retry_count: int = Field(0, ge=0, le=5)
    position_x: float = 0.0
    position_y: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec_text_from_request(body: ImportConnectorBody) -> str:
    if body.spec_text and body.spec_text.strip():
        return body.spec_text
    url = (body.spec_url or "").strip()
    if not url:
        raise HTTPException(400, "必须提供 spec_text 或 spec_url")
    try:
        assert_url_outbound_safe(url)
    except OutboundBlocked as exc:
        raise HTTPException(400, f"spec_url 不安全: {exc}") from exc
    try:
        with httpx.Client(
            timeout=_SPEC_FETCH_TIMEOUT, trust_env=False, follow_redirects=False
        ) as client:
            resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(400, f"拉取 spec 失败: {exc}") from exc
    if len(resp.content) > _MAX_SPEC_BYTES:
        raise HTTPException(400, "spec 过大（>4MB）")
    return resp.text


def _serialize_connector(c: OpenApiConnector) -> Dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description or "",
        "base_url": c.base_url or "",
        "title": c.title or "",
        "spec_version": c.spec_version or "",
        "spec_hash": c.spec_hash or "",
        "status": c.status or "ready",
        "operation_count": int(c.operation_count or 0),
        "generated_version": int(c.generated_version or 0),
        "last_error": c.last_error or "",
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_operation(op: OpenApiOperation) -> Dict[str, Any]:
    try:
        request_schema = json.loads(op.request_schema or "{}")
    except (TypeError, ValueError):
        request_schema = {}
    try:
        response_schema = json.loads(op.response_schema or "{}")
    except (TypeError, ValueError):
        response_schema = {}
    try:
        tags = json.loads(op.tags or "[]")
    except (TypeError, ValueError):
        tags = []
    return {
        "operation_id": op.operation_id,
        "method": op.method,
        "path": op.path,
        "summary": op.summary or "",
        "tags": tags if isinstance(tags, list) else [],
        "request_schema": request_schema,
        "response_schema": response_schema,
        "generated_symbol": op.generated_symbol or "",
        "enabled": bool(op.enabled),
    }


def _credential_view(cred: Optional[OpenApiCredential]) -> Dict[str, Any]:
    if cred is None:
        return {"auth_type": "none", "configured": False, "config_preview": {}}
    preview: Dict[str, Any] = {}
    try:
        decrypted = decrypt_credential_payload(cred.auth_type, cred.config_encrypted)
        for key, value in decrypted.config.items():
            if key in {"key", "api_key", "token", "client_secret", "password"}:
                preview[key] = "***"
            else:
                v = str(value)
                preview[key] = v[:120] + ("…" if len(v) > 120 else "")
    except (ValueError, RuntimeError):
        preview = {"__error__": "解密失败"}
    return {
        "auth_type": cred.auth_type,
        "configured": cred.auth_type != "none" and bool(cred.config_encrypted),
        "config_preview": preview,
        "updated_at": cred.updated_at.isoformat() if cred.updated_at else None,
    }


def _persist_parsed_spec(
    db: Session,
    *,
    user: User,
    body: ImportConnectorBody,
    parsed: ParsedSpec,
) -> OpenApiConnector:
    name = body.name.strip()
    existing = (
        db.query(OpenApiConnector)
        .filter(OpenApiConnector.user_id == user.id, OpenApiConnector.name == name)
        .first()
    )
    base_url = (body.base_url_override or parsed.base_url or "").strip()
    if existing:
        connector = existing
        connector.description = body.description or connector.description or ""
        connector.base_url = base_url
        connector.spec_hash = parsed.spec_hash
        connector.spec_version = parsed.version
        connector.title = parsed.title
        connector.status = "ready"
        connector.last_error = ""
        connector.generated_version = int(connector.generated_version or 0) + 1
        connector.operation_count = len(parsed.operations)
        connector.updated_at = datetime.now(timezone.utc)
    else:
        connector = OpenApiConnector(
            user_id=user.id,
            name=name,
            description=body.description or "",
            base_url=base_url,
            spec_hash=parsed.spec_hash,
            spec_version=parsed.version,
            title=parsed.title,
            status="ready",
            generated_version=1,
            operation_count=len(parsed.operations),
        )
        db.add(connector)
    db.flush()

    if existing:
        db.query(OpenApiOperation).filter(OpenApiOperation.connector_id == connector.id).delete()
        db.flush()

    for op in parsed.operations:
        db.add(
            OpenApiOperation(
                connector_id=connector.id,
                operation_id=op.operation_id,
                method=op.method,
                path=op.path,
                summary=op.summary,
                tags=json.dumps(list(op.tags), ensure_ascii=False),
                request_schema=json.dumps(
                    {
                        "parameters": [
                            {
                                "name": p.name,
                                "in": p.location,
                                "required": p.required,
                                "schema": p.schema,
                            }
                            for p in op.parameters
                        ],
                        "request_body": (
                            {
                                "required": op.request_body_required,
                                "content_type": op.request_body_content_type,
                                "schema": op.request_body_schema,
                            }
                            if op.request_body_schema is not None
                            else None
                        ),
                    },
                    ensure_ascii=False,
                ),
                response_schema=json.dumps(
                    {
                        "status": op.response_status,
                        "schema": op.response_schema,
                    },
                    ensure_ascii=False,
                ),
                generated_symbol=op.generated_symbol,
                enabled=True,
            )
        )
    db.commit()
    db.refresh(connector)
    return connector


def _generate_artifacts(connector: OpenApiConnector, parsed: ParsedSpec) -> None:
    try:
        generate_client_files(
            parsed,
            connector_id=int(connector.id),
            version=int(connector.generated_version or 1),
        )
    except OSError as exc:
        logger.warning("openapi connector codegen failed: %s", exc)
        return
    keep = list(
        range(
            max(1, int(connector.generated_version or 1)) - _KEEP_VERSIONS + 1,
            int(connector.generated_version or 1) + 1,
        )
    )
    cleanup_old_versions(int(connector.id), keep_versions=keep)


def _fetch_connector_or_404(db: Session, user: User, connector_id: int) -> OpenApiConnector:
    row = (
        db.query(OpenApiConnector)
        .filter(OpenApiConnector.id == connector_id, OpenApiConnector.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(404, "连接器不存在或无权访问")
    return row


def _fetch_operation_or_404(db: Session, connector_id: int, operation_id: str) -> OpenApiOperation:
    row = (
        db.query(OpenApiOperation)
        .filter(
            OpenApiOperation.connector_id == connector_id,
            OpenApiOperation.operation_id == operation_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "operation 不存在")
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/import", summary="导入或更新 OpenAPI 连接器")
async def import_connector(
    body: ImportConnectorBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if not fernet_configured():
        raise HTTPException(503, "服务端未配置 MODSTORE_LLM_MASTER_KEY，无法保存连接器鉴权")
    spec_text = _spec_text_from_request(body)
    if len(spec_text) > _MAX_SPEC_BYTES:
        raise HTTPException(400, "spec 过大（>4MB）")
    try:
        parsed = parse_spec(spec_text)
    except OpenApiParseError as exc:
        raise HTTPException(400, f"OpenAPI 解析失败: {exc}") from exc
    if not parsed.operations:
        raise HTTPException(400, "OpenAPI 中没有可用的 operation")
    connector = _persist_parsed_spec(db, user=user, body=body, parsed=parsed)
    _generate_artifacts(connector, parsed)
    operations = (
        db.query(OpenApiOperation)
        .filter(OpenApiOperation.connector_id == connector.id)
        .order_by(OpenApiOperation.id.asc())
        .all()
    )
    return {
        "connector": _serialize_connector(connector),
        "operations": [_serialize_operation(op) for op in operations],
    }


@router.get("/", summary="列出当前用户的连接器")
async def list_connectors(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(OpenApiConnector)
        .filter(OpenApiConnector.user_id == user.id)
        .order_by(OpenApiConnector.id.desc())
        .all()
    )
    return {"items": [_serialize_connector(r) for r in rows]}


@router.get("/{connector_id}", summary="获取连接器详情与 operation 列表")
async def get_connector(
    connector_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    connector = _fetch_connector_or_404(db, user, connector_id)
    operations = (
        db.query(OpenApiOperation)
        .filter(OpenApiOperation.connector_id == connector.id)
        .order_by(OpenApiOperation.id.asc())
        .all()
    )
    credential = (
        db.query(OpenApiCredential)
        .filter(
            OpenApiCredential.connector_id == connector.id,
            OpenApiCredential.user_id == user.id,
        )
        .first()
    )
    return {
        "connector": _serialize_connector(connector),
        "operations": [_serialize_operation(op) for op in operations],
        "credential": _credential_view(credential),
    }


@router.delete("/{connector_id}", summary="删除连接器及其 operation/凭据/日志")
async def delete_connector(
    connector_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    connector = _fetch_connector_or_404(db, user, connector_id)
    db.query(OpenApiCallLog).filter(OpenApiCallLog.connector_id == connector.id).delete()
    db.query(OpenApiCredential).filter(OpenApiCredential.connector_id == connector.id).delete()
    db.query(OpenApiOperation).filter(OpenApiOperation.connector_id == connector.id).delete()
    db.delete(connector)
    db.commit()
    cleanup_old_versions(int(connector_id), keep_versions=())
    return {"ok": True}


@router.put("/{connector_id}/credentials", summary="保存连接器鉴权配置")
async def put_credentials(
    connector_id: int,
    body: CredentialBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    connector = _fetch_connector_or_404(db, user, connector_id)
    auth_type = (body.auth_type or "").strip().lower()
    if auth_type not in SUPPORTED_AUTH_TYPES:
        raise HTTPException(400, f"不支持的 auth_type: {auth_type}")
    if not fernet_configured():
        raise HTTPException(503, "服务端未配置 MODSTORE_LLM_MASTER_KEY，无法保存连接器鉴权")
    try:
        ciphertext = encrypt_credential_payload(auth_type, body.config or {})
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = (
        db.query(OpenApiCredential)
        .filter(
            OpenApiCredential.connector_id == connector.id,
            OpenApiCredential.user_id == user.id,
        )
        .first()
    )
    if row:
        row.auth_type = auth_type
        row.config_encrypted = ciphertext
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = OpenApiCredential(
            user_id=user.id,
            connector_id=connector.id,
            auth_type=auth_type,
            config_encrypted=ciphertext,
        )
        db.add(row)
    db.commit()
    return {"ok": True, "credential": _credential_view(row)}


@router.delete("/{connector_id}/credentials", summary="清除连接器鉴权配置")
async def delete_credentials(
    connector_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    connector = _fetch_connector_or_404(db, user, connector_id)
    row = (
        db.query(OpenApiCredential)
        .filter(
            OpenApiCredential.connector_id == connector.id,
            OpenApiCredential.user_id == user.id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.patch("/{connector_id}/operations/{operation_id}", summary="启用/禁用 operation")
async def patch_operation(
    connector_id: int,
    operation_id: str,
    body: OperationToggleBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _fetch_connector_or_404(db, user, connector_id)
    op = _fetch_operation_or_404(db, connector_id, operation_id)
    op.enabled = bool(body.enabled)
    op.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "operation": _serialize_operation(op)}


@router.post("/{connector_id}/operations/{operation_id}/test", summary="服务端试调用 operation")
async def test_operation(
    connector_id: int,
    operation_id: str,
    body: TestCallBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _fetch_connector_or_404(db, user, connector_id)
    _fetch_operation_or_404(db, connector_id, operation_id)
    result = call_generated_operation(
        connector_id=connector_id,
        user_id=user.id,
        operation_id=operation_id,
        params=body.params,
        body=body.body,
        headers=body.headers,
        timeout=body.timeout,
        source="manual",
    )
    return result


@router.post("/{connector_id}/publish-workflow-node", summary="把 operation 发布为工作流节点")
async def publish_workflow_node(
    connector_id: int,
    body: PublishWorkflowNodeBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    connector = _fetch_connector_or_404(db, user, connector_id)
    op = _fetch_operation_or_404(db, connector_id, body.operation_id)
    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == body.workflow_id, Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise HTTPException(404, "workflow 不存在或无权访问")
    config: Dict[str, Any] = {
        "connector_id": connector_id,
        "operation_id": op.operation_id,
        "method": op.method,
        "path": op.path,
        "input_mapping": body.input_mapping or {},
        "output_mapping": body.output_mapping or {},
        "timeout_seconds": body.timeout_seconds,
        "retry_count": body.retry_count,
    }
    name = (body.name or "").strip() or f"{connector.name}.{op.operation_id}"
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_type="openapi_operation",
        name=name[:256],
        config=json.dumps(config, ensure_ascii=False),
        position_x=float(body.position_x),
        position_y=float(body.position_y),
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return {
        "ok": True,
        "node": {
            "id": node.id,
            "workflow_id": node.workflow_id,
            "node_type": node.node_type,
            "name": node.name,
            "config": config,
            "position_x": node.position_x,
            "position_y": node.position_y,
        },
    }


@router.get("/{connector_id}/logs", summary="查看调用记录")
async def list_logs(
    connector_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _fetch_connector_or_404(db, user, connector_id)
    rows = (
        db.query(OpenApiCallLog)
        .filter(
            OpenApiCallLog.connector_id == connector_id,
            OpenApiCallLog.user_id == user.id,
        )
        .order_by(OpenApiCallLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "operation_id": r.operation_id,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "duration_ms": r.duration_ms,
                "request_summary": r.request_summary,
                "response_summary": r.response_summary,
                "error": r.error,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


__all__ = ["router"]
