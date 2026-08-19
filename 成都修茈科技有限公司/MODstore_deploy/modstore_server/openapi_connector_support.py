"""DTOs, serialization and lookup helpers for OpenAPI connectors."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.models import OpenApiConnector, OpenApiCredential, OpenApiOperation, User
from modstore_server.openapi_connector_runtime import (
    OutboundBlocked,
    assert_url_outbound_safe,
    decrypt_credential_payload,
)

SPEC_FETCH_TIMEOUT = 20.0
MAX_SPEC_BYTES = 4 * 1024 * 1024


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


def spec_text_from_request(body: ImportConnectorBody) -> str:
    if body.spec_text and body.spec_text.strip():
        return body.spec_text
    url = (body.spec_url or "").strip()
    if not url:
        raise HTTPException(400, "必须提供 spec_text 或 spec_url")
    try:
        assert_url_outbound_safe(url)
    except OutboundBlocked as error:
        raise HTTPException(400, f"spec_url 不安全: {error}") from error
    try:
        with httpx.Client(
            timeout=SPEC_FETCH_TIMEOUT, trust_env=False, follow_redirects=False
        ) as client:
            response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise HTTPException(400, f"拉取 spec 失败: {error}") from error
    if len(response.content) > MAX_SPEC_BYTES:
        raise HTTPException(400, "spec 过大（>4MB）")
    return response.text


def serialize_connector(connector: OpenApiConnector) -> Dict[str, Any]:
    return {
        "id": connector.id,
        "name": connector.name,
        "description": connector.description or "",
        "base_url": connector.base_url or "",
        "title": connector.title or "",
        "spec_version": connector.spec_version or "",
        "spec_hash": connector.spec_hash or "",
        "status": connector.status or "ready",
        "operation_count": int(connector.operation_count or 0),
        "generated_version": int(connector.generated_version or 0),
        "last_error": connector.last_error or "",
        "created_at": connector.created_at.isoformat() if connector.created_at else None,
        "updated_at": connector.updated_at.isoformat() if connector.updated_at else None,
    }


def serialize_operation(operation: OpenApiOperation) -> Dict[str, Any]:
    try:
        request_schema = json.loads(operation.request_schema or "{}")
    except (TypeError, ValueError):
        request_schema = {}
    try:
        response_schema = json.loads(operation.response_schema or "{}")
    except (TypeError, ValueError):
        response_schema = {}
    try:
        tags = json.loads(operation.tags or "[]")
    except (TypeError, ValueError):
        tags = []
    return {
        "operation_id": operation.operation_id,
        "method": operation.method,
        "path": operation.path,
        "summary": operation.summary or "",
        "tags": tags if isinstance(tags, list) else [],
        "request_schema": request_schema,
        "response_schema": response_schema,
        "generated_symbol": operation.generated_symbol or "",
        "enabled": bool(operation.enabled),
    }


def credential_view(credential: Optional[OpenApiCredential]) -> Dict[str, Any]:
    if credential is None:
        return {"auth_type": "none", "configured": False, "config_preview": {}}
    preview: Dict[str, Any] = {}
    try:
        decrypted = decrypt_credential_payload(credential.auth_type, credential.config_encrypted)
        for key, value in decrypted.config.items():
            if key in {"key", "api_key", "token", "client_secret", "password"}:
                preview[key] = "***"
            else:
                rendered = str(value)
                preview[key] = rendered[:120] + ("…" if len(rendered) > 120 else "")
    except (ValueError, RuntimeError):
        preview = {"__error__": "解密失败"}
    return {
        "auth_type": credential.auth_type,
        "configured": credential.auth_type != "none" and bool(credential.config_encrypted),
        "config_preview": preview,
        "updated_at": credential.updated_at.isoformat() if credential.updated_at else None,
    }


def fetch_connector_or_404(database: Session, user: User, connector_id: int) -> OpenApiConnector:
    row = (
        database.query(OpenApiConnector)
        .filter(OpenApiConnector.id == connector_id, OpenApiConnector.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(404, "连接器不存在或无权访问")
    return row


def fetch_operation_or_404(
    database: Session, connector_id: int, operation_id: str
) -> OpenApiOperation:
    row = (
        database.query(OpenApiOperation)
        .filter(
            OpenApiOperation.connector_id == connector_id,
            OpenApiOperation.operation_id == operation_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "operation 不存在")
    return row
