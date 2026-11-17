"""Build the AIOPEN operation catalog from the live FastAPI application.

路由表是能力事实源：目录从应用 OpenAPI 生成，不手工维护。
语义（何时用、副作用、前置条件）来自 ``overlay/operations.yaml``，与代码同仓评审。
"""

from __future__ import annotations

import json
import re
import threading
import weakref
from pathlib import Path
from typing import Any

import yaml

# 内部控制面不进入开放目录，也不可被 api_call 之外的通道发现。
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/api/aiopen",
    "/api/admin",
    "/api/keys",
    "/api/qclaw",
    "/internal",
    "/metrics",
    "/static",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/xcmax-dashboard",
)

_DANGER_MARKERS = (
    "delete",
    "remove",
    "refund",
    "publish",
    "grant",
    "revoke",
    "reset",
    "impersonate",
    "purge",
    "destroy",
    "rollback",
    "batch-delete",
    "bulk-delete",
    "clear-all",
    "clear_all",
)

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})
_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

# 命中任一即可判定为内部控制面/运行时通道，不进入开放目录。
_BLOCKED_SEGMENTS = frozenset(
    {
        "admin",
        "internal",
        "debug",
        "diagnostics",
        "db-tools",
        "control",
        "xcmax",
        "desktop",
        "agent-tools",
    }
)

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")
_OVERLAY_DIR = Path(__file__).with_name("overlay")
_OVERLAY_PATH = _OVERLAY_DIR / "operations.yaml"
_OVERLAY_GENERATED_DIR = _OVERLAY_DIR / "generated"

_CACHE_LOCK = threading.Lock()
_SCHEMA_CACHE: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()
_CATALOG_CACHE: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()
_OVERLAY_LOCK = threading.Lock()
_OVERLAY_CACHE: dict[str, Any] = {"signature": None, "entries": {}, "glossary": {}}


def _slug(value: str) -> str:
    return _WORD_SPLIT.sub("_", str(value or "").strip().lower()).strip("_")


def operation_path_segments(path: str) -> list[str]:
    segments = [part for part in str(path or "").strip("/").split("/") if part]
    if segments and segments[0] == "api":
        segments = segments[1:]
    if segments and segments[0] in {"v1", "v2", "v3"}:
        segments = segments[1:]
    return segments


def is_excluded_path(path: str) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    if any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in EXCLUDED_PREFIXES
    ):
        return True
    segments = {part.lower() for part in normalized.strip("/").split("/")}
    return bool(segments & _BLOCKED_SEGMENTS)


def classify_risk(method: str, path: str) -> str:
    """确定性风险分级；语义 overlay 不参与风险判定。"""
    verb = str(method or "").upper()
    lowered = str(path or "").lower()
    if verb == "DELETE" or any(marker in lowered for marker in _DANGER_MARKERS):
        return "danger"
    if verb in _WRITE_METHODS:
        return "write"
    return "read"


def _domain_of(segments: list[str]) -> str:
    return _slug(segments[0]) if segments else "root"


def _action_of(segments: list[str], method: str) -> str:
    static = [part for part in segments if not part.startswith("{")]
    if len(static) <= 1:
        return {
            "GET": "list",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }.get(str(method or "").upper(), "call")
    return _slug(static[-1])


def _summary_of(operation: dict[str, Any], method: str, path: str) -> str:
    summary = str(operation.get("summary") or "").strip()
    if summary:
        return summary
    description = str(operation.get("description") or "").strip()
    if description:
        return description.splitlines()[0].strip()
    return f"{method} {path}"


def _unique(base: str, taken: set[str], suffix: str = "") -> str:
    if base not in taken:
        taken.add(base)
        return base
    candidate = f"{base}{suffix}"
    index = 2
    while candidate in taken:
        candidate = f"{base}{suffix}_{index}"
        index += 1
    taken.add(candidate)
    return candidate


def _overlay_files() -> list[Path]:
    """人工维护的 operations.yaml + 已审核入库的 generated/*（yaml 或 jsonl）。"""
    files = [_OVERLAY_PATH]
    if _OVERLAY_GENERATED_DIR.is_dir():
        files.extend(sorted(_OVERLAY_GENERATED_DIR.glob("*.yaml")))
        files.extend(sorted(_OVERLAY_GENERATED_DIR.glob("*.jsonl")))
    return files


def _read_overlay_file(path: Path) -> dict[str, Any]:
    """读取单个 overlay 文件；jsonl 每行一条记录，用于大规模语义的紧凑存储。"""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".jsonl":
        return yaml.safe_load(text) or {}
    operations: list[Any] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            operations.append(item)
    return {"operations": operations}


def _overlay_signature(files: list[Path]) -> tuple[tuple[str, float], ...]:
    signature: list[tuple[str, float]] = []
    for path in files:
        try:
            signature.append((path.name, path.stat().st_mtime))
        except OSError:
            signature.append((path.name, 0.0))
    return tuple(signature)


def _overlay_document() -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """读取 overlay（按文件签名缓存）：返回 operation 语义与业务域词汇表。

    草稿目录 ``overlay/drafts`` 不参与加载；人工审核后把条目移入
    ``overlay/generated/*.yaml`` 才会生效。
    """
    files = _overlay_files()
    signature = _overlay_signature(files)
    with _OVERLAY_LOCK:
        if _OVERLAY_CACHE["signature"] == signature:
            return dict(_OVERLAY_CACHE["entries"]), dict(_OVERLAY_CACHE["glossary"])
        entries: dict[str, dict[str, Any]] = {}
        glossary: dict[str, list[str]] = {}
        for path in files:
            try:
                raw = _read_overlay_file(path)
            except (OSError, yaml.YAMLError):
                continue
            for item in raw.get("operations") or []:
                if not isinstance(item, dict):
                    continue
                operation_id = str(item.get("operation_id") or "").strip()
                if operation_id:
                    entries[operation_id] = {
                        k: v for k, v in item.items() if k != "operation_id"
                    }
            for domain, aliases in (raw.get("glossary") or {}).items():
                key = _slug(str(domain))
                if key and isinstance(aliases, list):
                    known = glossary.setdefault(key, [])
                    known.extend(
                        str(alias).strip() for alias in aliases if str(alias).strip()
                    )
        _OVERLAY_CACHE["signature"] = signature
        _OVERLAY_CACHE["entries"] = entries
        _OVERLAY_CACHE["glossary"] = glossary
        return dict(entries), dict(glossary)


def load_overlay() -> dict[str, dict[str, Any]]:
    """读取 operation 语义 overlay；缺失或损坏时返回空字典。"""
    return _overlay_document()[0]


def load_glossary() -> dict[str, list[str]]:
    """读取业务域中文词汇表；仅用于检索，不改变目录。"""
    return _overlay_document()[1]


def openapi_schema(app: Any) -> dict[str, Any]:
    """按应用实例缓存 OpenAPI（弱引用，避免测试中实例复用导致串数据）。"""
    with _CACHE_LOCK:
        cached = _SCHEMA_CACHE.get(app)
    if cached is not None:
        return cached
    schema = app.openapi() or {}
    with _CACHE_LOCK:
        _SCHEMA_CACHE[app] = schema
    return schema


def _parameter_specs(parameters: Any) -> list[dict[str, Any]]:
    """保留 path/query/header 参数的最小结构，供执行层组包。"""
    specs: list[dict[str, Any]] = []
    for item in parameters or []:
        if not isinstance(item, dict):
            continue
        location = str(item.get("in") or "")
        name = str(item.get("name") or "").strip()
        if not name or location not in {"path", "query", "header"}:
            continue
        schema = item.get("schema") if isinstance(item.get("schema"), dict) else {}
        specs.append(
            {
                "name": name,
                "in": location,
                "required": bool(item.get("required")),
                "type": str(schema.get("type") or "string"),
                "enum": [str(value) for value in schema.get("enum") or [] if value is not None],
            }
        )
    return specs


def _request_body_spec(request_body: Any) -> dict[str, Any] | None:
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content") if isinstance(request_body.get("content"), dict) else {}
    media = content.get("application/json") if isinstance(content, dict) else None
    schema = media.get("schema") if isinstance(media, dict) else None
    if not isinstance(schema, dict):
        return {"required": bool(request_body.get("required")), "schema": None}
    return {
        "required": bool(request_body.get("required")),
        "schema": {
            "type": str(schema.get("type") or "object"),
            "ref": str(schema.get("$ref") or ""),
            "required": [str(name) for name in schema.get("required") or []],
            "properties": list((schema.get("properties") or {}).keys())
            if isinstance(schema.get("properties"), dict)
            else [],
        },
    }


def build_operations(app: Any) -> list[dict[str, Any]]:
    """从 OpenAPI paths 生成 operation 目录；控制面与内部路由直接排除。"""
    overlay = load_overlay()
    paths = openapi_schema(app).get("paths") or {}
    operations: list[dict[str, Any]] = []
    taken: set[str] = set()
    taken_tools: set[str] = set()
    for path, methods in paths.items():
        if not isinstance(methods, dict) or is_excluded_path(path):
            continue
        segments = operation_path_segments(path)
        domain = _domain_of(segments)
        for raw_method, operation in methods.items():
            method = str(raw_method or "").upper()
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            action = _action_of(segments, method)
            operation_id = _unique(f"{domain}.{action}", taken, f"_{method.lower()}")
            risk = classify_risk(method, path)
            parameters = operation.get("parameters")
            entry: dict[str, Any] = {
                "operation_id": operation_id,
                "tool_name": _unique(
                    f"{domain}_{action}", taken_tools, f"_{method.lower()}"
                ),
                "method": method,
                "path": path,
                "domain": domain,
                "toolset": domain,
                "tags": [str(tag) for tag in operation.get("tags") or [domain]],
                "summary": _summary_of(operation, method, path),
                "risk": risk,
                "scope": f"{risk}:{domain}",
                "path_params": [
                    str(item.get("name"))
                    for item in parameters or []
                    if isinstance(item, dict) and item.get("in") == "path"
                ],
                "parameters": _parameter_specs(parameters),
                "request_body": _request_body_spec(operation.get("requestBody")),
                "endpoint": str(operation.get("operationId") or ""),
                "described": operation_id in overlay,
            }
            semantics = overlay.get(operation_id)
            if semantics:
                entry["semantics"] = semantics
            operations.append(entry)
    operations.sort(key=lambda item: (item["domain"], item["path"], item["method"]))
    return operations


def build_catalog(app: Any) -> dict[str, Any]:
    operations = build_operations(app)
    return {
        "success": True,
        "transport": "runtime",
        "excluded_prefixes": list(EXCLUDED_PREFIXES),
        "count": len(operations),
        "operations": operations,
    }


def get_catalog(app: Any) -> dict[str, Any]:
    with _CACHE_LOCK:
        cached = _CATALOG_CACHE.get(app)
    if cached is not None:
        return cached
    catalog = build_catalog(app)
    with _CACHE_LOCK:
        _CATALOG_CACHE[app] = catalog
    return catalog


def find_operation(catalog: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    target = str(operation_id or "").strip().lower()
    for entry in catalog.get("operations") or []:
        if str(entry.get("operation_id") or "").lower() == target:
            return entry
    return None


def entity_schema(app: Any, entity: str) -> dict[str, Any] | None:
    """从应用 OpenAPI 的 components.schemas 读取实体字段字典。"""
    target = str(entity or "").strip().lower()
    if not target:
        return None
    schema = openapi_schema(app)
    schemas = ((schema or {}).get("components") or {}).get("schemas") or {}
    for name, payload in schemas.items():
        if str(name).lower() == target:
            return {"entity": name, "schema": payload}
    return None
