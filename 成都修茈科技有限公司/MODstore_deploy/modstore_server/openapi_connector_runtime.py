# ruff: noqa: E402, F401, I001

"""OpenAPI 连接器运行时：参数校验、鉴权注入、SSRF 限制、httpx 调用与日志。

调用约定：
    call_generated_operation(connector_id, user_id, operation_id, params, body, headers, timeout, source)

由生成产物 :mod:`modstore_server.openapi_connector_codegen` 中的 client.py 调用。
"""
from __future__ import annotations
import base64
import ipaddress
import json
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse, urlunparse
import httpx
from modstore_server.llm_crypto import decrypt_secret, encrypt_secret
from modstore_server.models import OpenApiCallLog, OpenApiConnector, OpenApiCredential, OpenApiOperation
from modstore_server.models import get_session_factory as get_session_factory
from modstore_server.operational_errors import BOUNDARY_ERRORS
from modstore_server.openapi_connector_runtime_merged import OutboundBlocked as OutboundBlocked, CredentialPayload as CredentialPayload, PinnedOutboundTarget as PinnedOutboundTarget, _apply_auth as _apply_auth, _ip_is_blocked as _ip_is_blocked, assert_url_outbound_safe as assert_url_outbound_safe, decrypt_credential_payload as decrypt_credential_payload, encrypt_credential_payload as encrypt_credential_payload, pin_url_outbound_safe as pin_url_outbound_safe, _oauth_client_credentials_token as _oauth_client_credentials_token, _apply_path_params as _apply_path_params, _format_path_value as _format_path_value, _load_runtime_context as _load_runtime_context, _record_log as _record_log, _redact_headers as _redact_headers, _resolve_full_url as _resolve_full_url, _safe_timeout as _safe_timeout, _split_params as _split_params, _summarize_request as _summarize_request, _summarize_response as _summarize_response, _truncate as _truncate, call_generated_operation as call_generated_operation
logger = logging.getLogger(__name__)
_MAX_REQUEST_SUMMARY = 1500
_MAX_RESPONSE_SUMMARY = 2000
_MAX_RESPONSE_BYTES = 256 * 1024
_DEFAULT_TIMEOUT = 30.0
SUPPORTED_AUTH_TYPES = ('none', 'api_key', 'bearer', 'basic', 'oauth2_client_credentials')
_SENSITIVE_HEADER_PATTERNS = re.compile('(authorization|api[-_]?key|x[-_]?api[-_]?key|x[-_]?auth[-_]?token|cookie|set-cookie|secret|token)', re.IGNORECASE)
_BLOCKED_HOSTS = {'localhost', 'metadata.google.internal', 'metadata.googleapis.com'}
_OAUTH_TOKEN_CACHE: Dict[Tuple[str, str], Tuple[str, float]] = {}
_OAUTH_LOCK = threading.Lock()
_TIMEOUT_MIN = 1.0
_TIMEOUT_MAX = 60.0
