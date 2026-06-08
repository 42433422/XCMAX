"""OpenAPI 3.x 文档解析与摘要。

只做结构化校验和元数据提取，不执行 spec 中的任何代码。
不依赖 ``openapi-spec-validator``：使用最小化校验保证零额外依赖也能跑。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

try:  # YAML 是可选依赖；缺失时仅支持 JSON spec
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None  # type: ignore[assignment]


SUPPORTED_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")

# JSON Schema 摘要时保留的关键字（避免把巨大的递归 schema 全量塞进库）
_SCHEMA_KEYS = (
    "type",
    "format",
    "enum",
    "default",
    "description",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "items",
    "properties",
    "required",
    "oneOf",
    "anyOf",
    "allOf",
    "additionalProperties",
    "nullable",
)

_MAX_SCHEMA_DEPTH = 6
_MAX_PROPERTIES = 64


class OpenApiParseError(ValueError):
    """OpenAPI 文档解析或校验失败。"""


@dataclass(frozen=True)
class ParsedParameter:
    name: str
    location: str  # query | path | header | cookie
    required: bool
    schema: Dict[str, Any]
    description: str = ""


@dataclass(frozen=True)
class ParsedOperation:
    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    tags: Tuple[str, ...]
    parameters: Tuple[ParsedParameter, ...]
    request_body_schema: Optional[Dict[str, Any]]
    request_body_required: bool
    request_body_content_type: str
    response_schema: Optional[Dict[str, Any]]
    response_status: str
    generated_symbol: str

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "description": self.description,
            "tags": list(self.tags),
            "parameters": [
                {
                    "name": p.name,
                    "in": p.location,
                    "required": p.required,
                    "schema": p.schema,
                    "description": p.description,
                }
                for p in self.parameters
            ],
            "request_body": (
                {
                    "required": self.request_body_required,
                    "content_type": self.request_body_content_type,
                    "schema": self.request_body_schema,
                }
                if self.request_body_schema is not None
                else None
            ),
            "response": {
                "status": self.response_status,
                "schema": self.response_schema,
            },
            "generated_symbol": self.generated_symbol,
        }


@dataclass(frozen=True)
class ParsedSpec:
    title: str
    version: str
    base_url: str
    spec_hash: str
    raw: Dict[str, Any] = field(repr=False)
    operations: Tuple[ParsedOperation, ...]


# ---------------------------------------------------------------------------
# Spec loading & basic validation
# ---------------------------------------------------------------------------


def load_spec(text: str) -> Dict[str, Any]:
    """从字符串载入 spec，自动尝试 JSON 与 YAML。"""
    s = (text or "").strip()
    if not s:
        raise OpenApiParseError("OpenAPI 文档为空")
    try:
        data = json.loads(s)
    except (ValueError, TypeError):
        if yaml is None:
            raise OpenApiParseError("无法解析为 JSON，且当前环境未安装 PyYAML，无法解析 YAML")
        try:
            data = yaml.safe_load(s)
        except Exception as exc:  # noqa: BLE001
            raise OpenApiParseError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise OpenApiParseError("OpenAPI 文档必须为对象")
    return data


def compute_spec_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _validate_basic(spec: Mapping[str, Any]) -> None:
    if not isinstance(spec, Mapping):
        raise OpenApiParseError("文档不是对象")
    version = str(spec.get("openapi") or "").strip()
    if not version.startswith("3."):
        raise OpenApiParseError(f"仅支持 OpenAPI 3.x，当前 openapi 字段为 {version!r}")
    info = spec.get("info") or {}
    if not isinstance(info, Mapping) or not str(info.get("title") or "").strip():
        raise OpenApiParseError("缺少 info.title")
    paths = spec.get("paths")
    if not isinstance(paths, Mapping) or not paths:
        raise OpenApiParseError("paths 必须为非空对象")


# ---------------------------------------------------------------------------
# Reference resolution (limited & safe)
# ---------------------------------------------------------------------------


def _resolve_ref(spec: Mapping[str, Any], ref: str, *, _seen: Optional[set] = None) -> Any:
    """只解析同文档内 ``#/...`` 形式的 $ref，外部引用忽略后留原样。"""
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    seen = _seen or set()
    if ref in seen:
        return None
    seen = seen | {ref}
    parts = ref[2:].split("/")
    cur: Any = spec
    for part in parts:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    if isinstance(cur, Mapping) and "$ref" in cur:
        return _resolve_ref(spec, str(cur.get("$ref") or ""), _seen=seen)
    return cur


def _summarize_schema(
    spec: Mapping[str, Any], schema: Any, *, depth: int = 0
) -> Optional[Dict[str, Any]]:
    if schema is None:
        return None
    if not isinstance(schema, Mapping):
        return None
    if "$ref" in schema:
        resolved = _resolve_ref(spec, str(schema.get("$ref") or ""))
        if resolved is None:
            return {"$ref": str(schema.get("$ref") or "")}
        schema = resolved
    if depth >= _MAX_SCHEMA_DEPTH:
        # 防止 schema 自循环把摘要打爆
        return {"type": str(schema.get("type") or "object"), "truncated": True}
    out: Dict[str, Any] = {}
    for key in _SCHEMA_KEYS:
        if key not in schema:
            continue
        value = schema[key]
        if key == "properties" and isinstance(value, Mapping):
            props_out: Dict[str, Any] = {}
            for i, (name, sub) in enumerate(value.items()):
                if i >= _MAX_PROPERTIES:
                    props_out["__truncated__"] = True
                    break
                props_out[str(name)] = _summarize_schema(spec, sub, depth=depth + 1)
            out["properties"] = props_out
        elif key == "items":
            out["items"] = _summarize_schema(spec, value, depth=depth + 1)
        elif key in ("oneOf", "anyOf", "allOf") and isinstance(value, list):
            out[key] = [_summarize_schema(spec, s, depth=depth + 1) for s in value[:8]]
        elif key == "additionalProperties" and isinstance(value, Mapping):
            out[key] = _summarize_schema(spec, value, depth=depth + 1)
        else:
            try:
                json.dumps(value, ensure_ascii=False)
                out[key] = value
            except (TypeError, ValueError):
                out[key] = str(value)
    return out


# ---------------------------------------------------------------------------
# Operation extraction
# ---------------------------------------------------------------------------


_SAFE_SYMBOL_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _slugify_symbol(parts: List[str]) -> str:
    raw = "_".join(p for p in parts if p).strip("_")
    if not raw:
        raw = "operation"
    sym = _SAFE_SYMBOL_RE.sub("_", raw).strip("_")
    if not sym:
        sym = "operation"
    if sym[0].isdigit():
        sym = "op_" + sym
    return sym[:80]


def _operation_id_from_path(method: str, path: str, used: set) -> str:
    cleaned = re.sub(r"\{[^}]+\}", "", path)
    parts = [method.lower()] + [p for p in cleaned.split("/") if p]
    base = _slugify_symbol(parts) or "operation"
    candidate = base
    idx = 2
    while candidate in used:
        candidate = f"{base}_{idx}"
        idx += 1
    return candidate


def _extract_base_url(spec: Mapping[str, Any]) -> str:
    servers = spec.get("servers")
    if isinstance(servers, list):
        for srv in servers:
            if isinstance(srv, Mapping):
                url = str(srv.get("url") or "").strip()
                if url:
                    return url
    return ""


def _content_schema(content: Any, spec: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    if not isinstance(content, Mapping):
        return None, ""
    preferred = ("application/json", "application/x-www-form-urlencoded", "multipart/form-data")
    for ct in preferred:
        if ct in content and isinstance(content[ct], Mapping):
            schema = content[ct].get("schema")
            return _summarize_schema(spec, schema), ct
    for ct, body in content.items():
        if isinstance(body, Mapping):
            return _summarize_schema(spec, body.get("schema")), str(ct)
    return None, ""


def _select_response_schema(
    responses: Any, spec: Mapping[str, Any]
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not isinstance(responses, Mapping):
        return None, ""
    preferred = ["200", "201", "202", "default"]
    for code in preferred + [c for c in responses.keys() if c not in preferred]:
        body = responses.get(code)
        if not isinstance(body, Mapping):
            continue
        if "$ref" in body:
            resolved = _resolve_ref(spec, str(body.get("$ref") or ""))
            if isinstance(resolved, Mapping):
                body = resolved
        schema, _ = _content_schema(body.get("content"), spec)
        if schema is not None:
            return schema, str(code)
    return None, ""


def _merge_parameters(
    path_item_params: Any, op_params: Any, spec: Mapping[str, Any]
) -> List[ParsedParameter]:
    out: Dict[Tuple[str, str], ParsedParameter] = {}
    for source in (path_item_params, op_params):
        if not isinstance(source, list):
            continue
        for raw in source:
            if isinstance(raw, Mapping) and "$ref" in raw:
                raw = _resolve_ref(spec, str(raw.get("$ref") or "")) or {}
            if not isinstance(raw, Mapping):
                continue
            name = str(raw.get("name") or "").strip()
            location = str(raw.get("in") or "").strip().lower()
            if not name or location not in ("query", "path", "header", "cookie"):
                continue
            schema = _summarize_schema(spec, raw.get("schema")) or {}
            required = bool(raw.get("required") or location == "path")
            description = str(raw.get("description") or "")[:512]
            out[(name, location)] = ParsedParameter(
                name=name,
                location=location,
                required=required,
                schema=schema,
                description=description,
            )
    return list(out.values())


def parse_operations(spec: Mapping[str, Any]) -> List[ParsedOperation]:
    operations: List[ParsedOperation] = []
    used_ids: set = set()
    used_symbols: set = set()
    paths = spec.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, Mapping):
            continue
        path_params = path_item.get("parameters")
        for method in SUPPORTED_METHODS:
            op = path_item.get(method)
            if not isinstance(op, Mapping):
                continue
            raw_id = str(op.get("operationId") or "").strip()
            if raw_id and raw_id not in used_ids:
                operation_id = raw_id
            else:
                operation_id = _operation_id_from_path(method, path, used_ids)
            used_ids.add(operation_id)

            symbol = _slugify_symbol([operation_id])
            base_symbol = symbol
            idx = 2
            while symbol in used_symbols:
                symbol = f"{base_symbol}_{idx}"
                idx += 1
            used_symbols.add(symbol)

            params = _merge_parameters(path_params, op.get("parameters"), spec)

            request_body_schema: Optional[Dict[str, Any]] = None
            request_body_content_type = ""
            request_body_required = False
            rb = op.get("requestBody")
            if isinstance(rb, Mapping):
                if "$ref" in rb:
                    rb = _resolve_ref(spec, str(rb.get("$ref") or "")) or {}
                request_body_required = bool(rb.get("required"))
                request_body_schema, request_body_content_type = _content_schema(
                    rb.get("content"), spec
                )

            response_schema, response_status = _select_response_schema(op.get("responses"), spec)

            tags_raw = op.get("tags") or []
            tags = tuple(
                str(t).strip() for t in tags_raw if isinstance(t, (str, int)) and str(t).strip()
            )

            operations.append(
                ParsedOperation(
                    operation_id=operation_id,
                    method=method.upper(),
                    path=str(path),
                    summary=str(op.get("summary") or "")[:512],
                    description=str(op.get("description") or "")[:2000],
                    tags=tags,
                    parameters=tuple(params),
                    request_body_schema=request_body_schema,
                    request_body_required=request_body_required,
                    request_body_content_type=request_body_content_type,
                    response_schema=response_schema,
                    response_status=response_status,
                    generated_symbol=symbol,
                )
            )
    return operations


def parse_spec(text: str) -> ParsedSpec:
    spec = load_spec(text)
    _validate_basic(spec)
    info = spec.get("info") or {}
    return ParsedSpec(
        title=str(info.get("title") or "").strip(),
        version=str(info.get("version") or "").strip(),
        base_url=_extract_base_url(spec),
        spec_hash=compute_spec_hash(text),
        raw=dict(spec),
        operations=tuple(parse_operations(spec)),
    )
