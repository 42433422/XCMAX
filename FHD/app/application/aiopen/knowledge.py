"""Read-only knowledge queries over the runtime operation catalog.

检索复用已锁定依赖 ``scikit-learn`` 的 TF-IDF（BSD-3-Clause），按字符 n-gram
切分以兼容中文，不额外引入分词器。索引按目录签名缓存，目录变化时重建。
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from .catalog_builder import find_operation, get_catalog, load_glossary

_INDEX_LOCK = threading.Lock()
_INDEX: dict[str, Any] = {"signature": None, "vectorizer": None, "matrix": None, "entries": []}

_SEMANTIC_KEYS = ("when_to_use", "returns", "side_effects", "preconditions", "examples", "related")

# 通用动作词按风险级别补齐：只降低动作词的区分度，业务域别名仍然决定排序。
_ACTION_ALIASES = {
    "read": ("查询", "查看", "列表", "详情", "搜索"),
    "write": ("创建", "新增", "新建", "保存", "更新", "修改"),
    "danger": ("删除", "作废", "撤销", "批量"),
}


def _document(entry: dict[str, Any], glossary: dict[str, list[str]]) -> str:
    parts = [
        str(entry.get("operation_id") or ""),
        str(entry.get("tool_name") or ""),
        str(entry.get("path") or ""),
        str(entry.get("summary") or ""),
        " ".join(str(tag) for tag in entry.get("tags") or []),
    ]
    # 路由摘要多为英文或占位，中文别名让「创建客户」这类意图命中正确的域；
    # 别名重复两次以提高业务域权重，动作词只做弱提示。
    domain = str(entry.get("domain") or "")
    parts.extend(glossary.get(domain, []) * 2)
    parts.extend(_ACTION_ALIASES.get(str(entry.get("risk") or "read"), ()))
    semantics = entry.get("semantics") if isinstance(entry.get("semantics"), dict) else {}
    for key in _SEMANTIC_KEYS:
        value = semantics.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _signature(entries: list[dict[str, Any]]) -> tuple[str, ...]:
    glossary = load_glossary()
    return tuple(_document(entry, glossary) for entry in entries)


def _index(entries: list[dict[str, Any]]) -> tuple[Any, Any] | None:
    signature = _signature(entries)
    with _INDEX_LOCK:
        if _INDEX["signature"] == signature and _INDEX["vectorizer"] is not None:
            return _INDEX["vectorizer"], _INDEX["matrix"]
        if not signature:
            return None
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(1, 2), lowercase=True, max_features=20000
        )
        matrix = vectorizer.fit_transform(list(signature))
        _INDEX.update(
            signature=signature, vectorizer=vectorizer, matrix=matrix, entries=list(entries)
        )
        return vectorizer, matrix


def _rank(entries: list[dict[str, Any]], query: str) -> list[tuple[float, dict[str, Any]]]:
    indexed = _index(entries)
    if indexed is None:
        return []
    from sklearn.metrics.pairwise import linear_kernel

    vectorizer, matrix = indexed
    scores = linear_kernel(vectorizer.transform([query]), matrix).ravel()
    order = scores.argsort()[::-1]
    ranked = [
        (float(scores[index]), entries[int(index)])
        for index in order
        if float(scores[int(index)]) > 0.0
    ]
    return ranked


def _search_item(score: float, entry: dict[str, Any]) -> dict[str, Any]:
    semantics = entry.get("semantics") if isinstance(entry.get("semantics"), dict) else {}
    item = {
        "operation_id": entry.get("operation_id"),
        "method": entry.get("method"),
        "path": entry.get("path"),
        "risk": entry.get("risk"),
        "scope": entry.get("scope"),
        "toolset": entry.get("toolset"),
        "summary": entry.get("summary"),
        "described": bool(semantics),
        "score": round(score, 4),
    }
    if semantics.get("when_to_use"):
        item["when_to_use"] = semantics["when_to_use"]
    return item


def knowledge_search(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    query = str((args or {}).get("query") or "").strip()
    if not query:
        return {"success": False, "message": "query 不能为空", "code": "INVALID_ARGUMENT"}
    try:
        limit = max(1, min(int((args or {}).get("limit") or 10), 50))
    except (TypeError, ValueError):
        limit = 10
    domain = str((args or {}).get("domain") or "").strip().lower()
    entries = list(get_catalog(app).get("operations") or [])
    if domain:
        entries = [entry for entry in entries if str(entry.get("domain")) == domain]
    if not entries:
        return {"success": True, "query": query, "count": 0, "items": []}
    ranked = _rank(entries, query)[:limit]
    return {
        "success": True,
        "query": query,
        "count": len(ranked),
        "items": [_search_item(score, entry) for score, entry in ranked],
    }


def operation_describe(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    operation_id = str((args or {}).get("operation_id") or "").strip()
    if not operation_id:
        return {"success": False, "message": "operation_id 不能为空", "code": "INVALID_ARGUMENT"}
    entry = find_operation(get_catalog(app), operation_id)
    if entry is None:
        return {
            "success": False,
            "code": "OPERATION_NOT_FOUND",
            "message": f"目录中不存在 operation：{operation_id}",
        }
    return {"success": True, "operation": entry}


def catalog_coverage(app: Any) -> dict[str, Any]:
    entries = list(get_catalog(app).get("operations") or [])
    total = len(entries)
    risks = Counter(str(entry.get("risk") or "read") for entry in entries)
    toolsets = Counter(str(entry.get("toolset") or "root") for entry in entries)
    described = sum(1 for entry in entries if entry.get("described"))
    summarized = sum(1 for entry in entries if str(entry.get("summary") or "").strip())
    return {
        "success": True,
        "operations": {
            "total": total,
            "by_risk": dict(sorted(risks.items())),
            "with_summary": summarized,
            "described": described,
        },
        "ratios": {
            "summarized": round(summarized / total, 4) if total else 0.0,
            "described": round(described / total, 4) if total else 0.0,
        },
        "toolsets": dict(sorted(toolsets.items())),
    }
