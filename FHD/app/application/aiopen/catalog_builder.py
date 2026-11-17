"""Build the AIOPEN operation catalog from the live FastAPI application.

路由表是能力事实源：目录从应用 OpenAPI 生成，不手工维护。
语义（何时用、副作用、前置条件）来自 ``overlay/operations.yaml``，与代码同仓评审。
"""

from __future__ import annotations

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
    "batch",
    "bulk",
    "purge",
    "destroy",
    "rollback",
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
_OVERLAY_PATH = Path(__file__).with_name("overlay") / "operations.yaml"

_CACHE_LOCK = threading.Lock()
_SCHEMA_CACHE: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()
_CATALOG_CACHE: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()
_OVERLAY_LOCK = threading.Lock()
_OVERLAY_CACHE: dict[str, Any] = {"mtime": None, "entries": {}}


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


def load_overlay() -> dict[str, dict[str, Any]]:
    """读取语义 overlay；按文件 mtime 缓存，缺失或损坏时返回空字典。"""
    try:
        mtime = _OVERLAY_PATH.stat().st_mtime
    except OSError:
        return {}
    with _OVERLAY_LOCK:
        if _OVERLAY_CACHE["mtime"] == mtime:
            return dict(_OVERLAY_CACHE["entries"])
        try:
            raw = yaml.safe_load(_OVERLAY_PATH.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            raw = {}
        entries: dict[str, dict[str, Any]] = {}
        for item in raw.get("operations") or []:
            if not isinstance(item, dict):
                continue
            operation_id = str(item.get("operation_id") or "").strip()
            if operation_id:
                entries[operation_id] = {k: v for k, v in item.items() if k != "operation_id"}
        _OVERLAY_CACHE["mtime"] = mtime
        _OVERLAY_CACHE["entries"] = entries
        return dict(entries)


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
