# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.openapi_connector_runtime")


def _safe_timeout(value: _facade().Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _facade()._DEFAULT_TIMEOUT
    return max(_facade()._TIMEOUT_MIN, min(_facade()._TIMEOUT_MAX, v))


def _resolve_full_url(base_url: str, path: str, *, override: _facade().Optional[str] = None) -> str:
    base = (override or base_url or "").strip()
    if not base:
        if path.startswith(("http://", "https://")):
            return path
        raise _facade().OutboundBlocked("连接器未配置 base_url，且 operation path 不是绝对 URL")
    path_parts = _facade().urlparse(path)
    if path_parts.scheme or path_parts.netloc:
        raise _facade().OutboundBlocked("operation path 不得覆盖连接器 host")
    if not base.endswith("/"):
        base = base + "/"
    rel = path.lstrip("/")
    resolved = _facade().urljoin(base, rel)
    base_parts = _facade().urlparse(base)
    resolved_parts = _facade().urlparse(resolved)
    if (
        resolved_parts.scheme.lower() != base_parts.scheme.lower()
        or resolved_parts.hostname != base_parts.hostname
        or resolved_parts.port != base_parts.port
    ):
        raise _facade().OutboundBlocked("operation path 不得覆盖连接器 origin")
    return resolved


def _apply_path_params(
    path: str,
    params: _facade().Dict[str, _facade().Any],
    spec_params: _facade().List[_facade().Mapping[str, _facade().Any]],
) -> str:
    out = path
    consumed: _facade().List[str] = []
    for spec in spec_params:
        if str(spec.get("in") or "").lower() != "path":
            continue
        name = str(spec.get("name") or "")
        if not name:
            continue
        token = "{" + name + "}"
        if token not in out:
            continue
        if name not in params:
            raise ValueError(f"缺少 path 参数: {name}")
        value = params[name]
        out = out.replace(token, _facade()._format_path_value(value))
        consumed.append(name)
    for name in consumed:
        params.pop(name, None)
    return out


def _format_path_value(value: _facade().Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return _facade().quote(str(value), safe="")


def _split_params(
    raw_params: _facade().Mapping[str, _facade().Any],
    spec_params: _facade().List[_facade().Mapping[str, _facade().Any]],
) -> _facade().Tuple[
    _facade().Dict[str, _facade().Any],
    _facade().Dict[str, _facade().Any],
    _facade().Dict[str, str],
]:
    """根据 OpenAPI parameters 把传入参数拆成 path / query / header。"""
    path_params: _facade().Dict[str, _facade().Any] = {}
    query_params: _facade().Dict[str, _facade().Any] = {}
    header_params: _facade().Dict[str, str] = {}
    locations = {str(p.get("name") or ""): str(p.get("in") or "").lower() for p in spec_params}
    required_missing: _facade().List[str] = []
    for name, value in (raw_params or {}).items():
        loc = locations.get(name, "query")
        if loc == "path":
            path_params[name] = value
        elif loc == "header":
            if value is not None:
                header_params[name] = str(value)
        elif loc == "cookie":
            continue
        else:
            query_params[name] = value
    for spec in spec_params:
        if not bool(spec.get("required")):
            continue
        name = str(spec.get("name") or "")
        loc = str(spec.get("in") or "").lower()
        if (
            loc == "path"
            and name not in path_params
            or (loc == "query" and name not in query_params)
            or (loc == "header" and name not in header_params)
        ):
            required_missing.append(f"{loc}:{name}")
    if required_missing:
        raise ValueError(f"缺少必填参数: {', '.join(required_missing)}")
    return (path_params, query_params, header_params)


def _redact_headers(
    headers: _facade().Mapping[str, _facade().Any],
) -> _facade().Dict[str, str]:
    out: _facade().Dict[str, str] = {}
    for k, v in (headers or {}).items():
        key = str(k)
        if _facade()._SENSITIVE_HEADER_PATTERNS.search(key):
            out[key] = "***"
        else:
            value = str(v)
            out[key] = value[:120] + ("…" if len(value) > 120 else "")
    return out


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"…(+{len(text) - limit} chars)"


def _summarize_request(
    method: str,
    url: str,
    params: _facade().Mapping[str, _facade().Any],
    headers: _facade().Mapping[str, _facade().Any],
    body: _facade().Any,
) -> str:
    payload: _facade().Dict[str, _facade().Any] = {
        "method": method,
        "url": url,
        "params": dict(params or {}),
        "headers": _facade()._redact_headers(headers or {}),
    }
    if body is not None:
        try:
            payload["body"] = _facade().json.loads(_facade().json.dumps(body, default=str))
        except (TypeError, ValueError):
            payload["body"] = repr(body)
    return _facade()._truncate(
        _facade().json.dumps(payload, ensure_ascii=False),
        _facade()._MAX_REQUEST_SUMMARY,
    )


def _summarize_response(
    resp: _facade().Optional[_facade().httpx.Response],
    parsed_body: _facade().Any,
    error: str,
) -> str:
    info: _facade().Dict[str, _facade().Any] = {}
    if resp is not None:
        info["status_code"] = resp.status_code
        info["headers"] = _facade()._redact_headers(dict(resp.headers))
    if parsed_body is not None:
        try:
            info["body"] = _facade().json.loads(_facade().json.dumps(parsed_body, default=str))
        except (TypeError, ValueError):
            info["body"] = repr(parsed_body)
    if error:
        info["error"] = error
    return _facade()._truncate(
        _facade().json.dumps(info, ensure_ascii=False), _facade()._MAX_RESPONSE_SUMMARY
    )


def _load_runtime_context(
    session, *, connector_id: int, user_id: int, operation_id: str
) -> _facade().Tuple[
    _facade().OpenApiConnector,
    _facade().OpenApiOperation,
    _facade().Optional[_facade().OpenApiCredential],
]:
    connector = (
        session.query(_facade().OpenApiConnector)
        .filter(
            _facade().OpenApiConnector.id == connector_id,
            _facade().OpenApiConnector.user_id == user_id,
        )
        .first()
    )
    if not connector:
        raise LookupError(f"连接器不存在或无权访问: {connector_id}")
    if connector.status == "disabled":
        raise PermissionError(f"连接器 {connector_id} 已被禁用")
    op = (
        session.query(_facade().OpenApiOperation)
        .filter(
            _facade().OpenApiOperation.connector_id == connector_id,
            _facade().OpenApiOperation.operation_id == operation_id,
        )
        .first()
    )
    if not op:
        raise LookupError(f"operation 不存在: {operation_id}")
    if not op.enabled:
        raise PermissionError(f"operation 已被禁用: {operation_id}")
    credential = (
        session.query(_facade().OpenApiCredential)
        .filter(
            _facade().OpenApiCredential.connector_id == connector_id,
            _facade().OpenApiCredential.user_id == user_id,
        )
        .first()
    )
    return (connector, op, credential)


def _record_log(
    session,
    *,
    user_id: int,
    connector_id: int,
    operation_id: str,
    method: str,
    path: str,
    status_code: _facade().Optional[int],
    duration_ms: float,
    request_summary: str,
    response_summary: str,
    error: str,
    source: str,
) -> None:
    try:
        entry = _facade().OpenApiCallLog(
            user_id=user_id,
            connector_id=connector_id,
            operation_id=operation_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            request_summary=request_summary,
            response_summary=response_summary,
            error=error,
            source=source,
            created_at=_facade().datetime.now(_facade().UTC),
        )
        session.add(entry)
        session.commit()
    except _facade().BOUNDARY_ERRORS:
        _facade().logger.warning("openapi connector log persist failed")
        try:
            session.rollback()
        except _facade().BOUNDARY_ERRORS:
            pass


def call_generated_operation(
    *,
    connector_id: int,
    user_id: int,
    operation_id: str,
    params: _facade().Optional[_facade().Mapping[str, _facade().Any]] = None,
    body: _facade().Any = None,
    headers: _facade().Optional[_facade().Mapping[str, str]] = None,
    timeout: float = _facade()._DEFAULT_TIMEOUT,
    source: str = "manual",
    base_url_override: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    """生成产物里的客户端函数最终都调用这里。

    返回 ``{ok, status_code, body, headers, error, duration_ms}``，不抛异常。
    """
    from modstore_server.openapi_connector_execution import execute_generated_operation

    return execute_generated_operation(
        connector_id=connector_id,
        user_id=user_id,
        operation_id=operation_id,
        params=params,
        body=body,
        headers=headers,
        timeout=timeout,
        source=source,
        base_url_override=base_url_override,
    )
