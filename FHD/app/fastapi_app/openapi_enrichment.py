"""OpenAPI schema 后处理：补齐 description、tags 与 2xx 响应 schema（供 --strict 守门）。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

_DOC_METHODS = frozenset({"get", "post", "put", "patch", "delete"})

_DEFAULT_TAG = "xcagi"

_GENERIC_JSON_RESPONSE: dict[str, Any] = {
    "description": "Successful response",
    "content": {
        "application/json": {
            "schema": {"type": "object", "additionalProperties": True},
        }
    },
}

_PLAIN_TEXT_RESPONSE: dict[str, Any] = {
    "description": "Successful response",
    "content": {
        "text/plain": {
            "schema": {"type": "string"},
        }
    },
}


def _response_has_schema(response: dict[str, Any]) -> bool:
    content = response.get("content") or {}
    if not isinstance(content, dict):
        return False
    for media in content.values():
        if isinstance(media, dict) and media.get("schema"):
            return True
    return False


def enrich_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """为缺元数据的 operation 填入默认值，不改变已有显式注解。"""
    paths = schema.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            method_l = (method or "").lower()
            if method_l not in _DOC_METHODS or not isinstance(op, dict):
                continue

            if not op.get("tags"):
                if path == "/metrics":
                    op["tags"] = ["monitoring"]
                elif path.startswith("/api/neurobus/"):
                    op["tags"] = ["neurobus"]
                else:
                    op["tags"] = [_DEFAULT_TAG]

            summary = str(op.get("summary") or "").strip()
            if not summary:
                summary = f"{method.upper()} {path}"
                op["summary"] = summary

            if not str(op.get("description") or "").strip():
                op["description"] = summary

            responses = op.setdefault("responses", {})
            if not isinstance(responses, dict):
                continue

            has_schema = False
            for code, resp in responses.items():
                if not isinstance(resp, dict):
                    continue
                if str(code).startswith("2") or code == "default":
                    if _response_has_schema(resp):
                        has_schema = True
                        break

            if not has_schema:
                template = _PLAIN_TEXT_RESPONSE if path == "/metrics" else _GENERIC_JSON_RESPONSE
                if "200" not in responses:
                    responses["200"] = dict(template)
                else:
                    resp = responses["200"]
                    if isinstance(resp, dict) and not _response_has_schema(resp):
                        merged = dict(template)
                        merged["description"] = resp.get("description") or merged["description"]
                        responses["200"] = merged

    return schema


def install_openapi_enrichment(app: FastAPI) -> None:
    """包装 ``app.openapi``，在生成后统一 enrich。"""

    def enriched_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        schema = enrich_openapi_schema(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = enriched_openapi  # type: ignore[method-assign]
