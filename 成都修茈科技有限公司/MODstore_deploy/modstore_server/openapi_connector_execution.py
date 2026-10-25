"""Execute generated OpenAPI operations through the runtime facade.

The facade is resolved at call time so patches to its HTTP client and outbound
safety hook keep controlling the complete request lifecycle.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from modstore_server.operational_errors import BOUNDARY_ERRORS


def execute_generated_operation(
    *,
    connector_id: int,
    user_id: int,
    operation_id: str,
    params: Optional[Mapping[str, Any]],
    body: Any,
    headers: Optional[Mapping[str, str]],
    timeout: float,
    source: str,
    base_url_override: Optional[str],
) -> Dict[str, Any]:
    """Run one generated operation while preserving facade patch points."""
    from modstore_server import openapi_connector_runtime as runtime

    safe_timeout = runtime._safe_timeout(timeout)
    safe_source = (source or "manual").strip().lower() or "manual"
    sf = runtime.get_session_factory()
    started = runtime.time.perf_counter()
    method = "GET"
    full_url = ""
    request_summary = ""
    status_code: Optional[int] = None
    parsed_body: Any = None
    response_headers: Dict[str, str] = {}
    with sf() as session:
        try:
            connector, operation, credential = runtime._load_runtime_context(
                session,
                connector_id=connector_id,
                user_id=user_id,
                operation_id=operation_id,
            )
            method = (operation.method or "GET").upper()
            try:
                spec_params = (
                    runtime.json.loads(operation.request_schema or "{}").get("parameters") or []
                )
            except (TypeError, ValueError):
                spec_params = []
            if not isinstance(spec_params, list):
                spec_params = []

            mutable_params = dict(params or {})
            path_params, query_params, header_params = runtime._split_params(
                mutable_params, spec_params
            )
            applied_path = runtime._apply_path_params(operation.path, path_params, spec_params)
            full_url = runtime._resolve_full_url(
                connector.base_url, applied_path, override=base_url_override
            )
            target = runtime.pin_url_outbound_safe(full_url)

            outgoing_headers: Dict[str, str] = dict(header_params)
            for key, value in (headers or {}).items():
                if str(key).lower() != "host":
                    outgoing_headers[str(key)] = str(value)

            outgoing_query: Dict[str, Any] = dict(query_params)
            if credential is not None:
                payload = runtime.decrypt_credential_payload(
                    credential.auth_type, credential.config_encrypted
                )
                runtime._apply_auth(
                    payload.auth_type,
                    payload.config,
                    headers=outgoing_headers,
                    params=outgoing_query,
                )

            json_body: Any = None
            data_body: Any = None
            if body is not None and method not in ("GET", "HEAD", "DELETE"):
                try:
                    runtime.json.dumps(body)
                    json_body = body
                    outgoing_headers.setdefault("Content-Type", "application/json")
                except (TypeError, ValueError):
                    data_body = body

            request_summary = runtime._summarize_request(
                method, full_url, outgoing_query, outgoing_headers, body
            )
            with runtime.httpx.Client(
                timeout=safe_timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                outgoing_headers["Host"] = target.host_header
                # The request URL is pinned to the public IP validated above;
                # Host/SNI preserve the original TLS authority without a
                # second DNS lookup. lgtm[py/full-ssrf]
                request = client.build_request(
                    method,
                    target.request_url,
                    params=outgoing_query or None,
                    headers=outgoing_headers or None,
                    json=json_body,
                    data=data_body,
                    extensions={"sni_hostname": target.server_hostname},
                )
                response = client.send(request)
            status_code = response.status_code
            response_headers = {str(k): str(v) for k, v in response.headers.items()}
            raw_bytes = response.content[: runtime._MAX_RESPONSE_BYTES]
            try:
                text_body = raw_bytes.decode(response.encoding or "utf-8", errors="replace")
            except (LookupError, AttributeError):
                text_body = raw_bytes.decode("utf-8", errors="replace")
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" in content_type:
                try:
                    parsed_body = runtime.json.loads(text_body)
                except (ValueError, TypeError):
                    parsed_body = text_body
            else:
                parsed_body = text_body
            response_summary = runtime._summarize_response(response, parsed_body, "")
            return _finalize(
                runtime,
                session,
                user_id=user_id,
                connector_id=connector_id,
                operation_id=operation_id,
                method=method,
                full_url=full_url,
                status_code=status_code,
                request_summary=request_summary,
                response_summary=response_summary,
                duration_ms=round((runtime.time.perf_counter() - started) * 1000, 3),
                response_headers=response_headers,
                parsed_body=parsed_body,
                error_text="",
                source=safe_source,
                ok=200 <= response.status_code < 400,
            )
        except runtime.OutboundBlocked:
            error_text = "outbound_blocked"
        except (LookupError, PermissionError):
            error_text = "unavailable"
        except ValueError:
            error_text = "validation_error"
        except runtime.httpx.HTTPError:
            error_text = "http_error"
        except BOUNDARY_ERRORS:  # noqa: BLE001
            runtime.logger.warning("openapi connector call crashed")
            error_text = "internal_error"
        response_summary = runtime._summarize_response(None, None, error_text)
        return _finalize(
            runtime,
            session,
            user_id=user_id,
            connector_id=connector_id,
            operation_id=operation_id,
            method=method,
            full_url=full_url,
            status_code=status_code,
            request_summary=request_summary,
            response_summary=response_summary,
            duration_ms=round((runtime.time.perf_counter() - started) * 1000, 3),
            response_headers={},
            parsed_body=None,
            error_text=error_text,
            source=safe_source,
            ok=False,
        )


def _finalize(
    runtime: Any,
    session: Any,
    *,
    user_id: int,
    connector_id: int,
    operation_id: str,
    method: str,
    full_url: str,
    status_code: Optional[int],
    request_summary: str,
    response_summary: str,
    duration_ms: float,
    response_headers: Mapping[str, str],
    parsed_body: Any,
    error_text: str,
    source: str,
    ok: bool,
) -> Dict[str, Any]:
    parsed_path = runtime.urlparse(full_url).path or full_url
    runtime._record_log(
        session,
        user_id=user_id,
        connector_id=connector_id,
        operation_id=operation_id,
        method=method,
        path=parsed_path[:512],
        status_code=status_code,
        duration_ms=duration_ms,
        request_summary=request_summary,
        response_summary=response_summary,
        error=error_text,
        source=source,
    )
    return {
        "ok": ok,
        "status_code": status_code,
        "body": parsed_body,
        "headers": dict(response_headers or {}),
        "error": error_text,
        "duration_ms": duration_ms,
        "operation_id": operation_id,
        "url": full_url,
        "method": method,
    }
