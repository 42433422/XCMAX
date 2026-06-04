"""AI 数据库 Schema 字段索引:从 ``resources/config/ai_db_field_index.json`` 读,
提供 ``match_excel_import_roles_from_field_index`` / ``price_column_buckets_for_keys``。

这两个函数被 ``app.application.ai_chat_app_service`` 兜底导入(没有时回退
到空映射 / 空桶);本模块独立存在的好处是:测试可以 ``mock.patch`` 单独覆盖
它的返回值,而不必拉起整张 JSON 表或整个 chat 服务。
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Iterable

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None
_CONFIG_PATH_HINTS = (
    "XCAGI/resources/config/ai_db_field_index.json",
    "resources/config/ai_db_field_index.json",
    "app/resources/config/ai_db_field_index.json",
)

_ROLE_TO_COLUMN = {
    "unit_name": ("unit",),
    "product_name": ("name",),
    "model_number": ("model_number",),
    "unit_price": ("price",),
}


def _resolve_config_path() -> str | None:
    """从常见候选位置 + ``XCAGI_CONFIG_DIR`` 环境变量找 ``ai_db_field_index.json``。"""
    env_dir = os.environ.get("XCAGI_CONFIG_DIR")
    candidates: list[str] = []
    if env_dir:
        candidates.append(os.path.join(env_dir, "ai_db_field_index.json"))
    for hint in _CONFIG_PATH_HINTS:
        candidates.append(hint)
        candidates.append(os.path.abspath(hint))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _load_index() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        path = _resolve_config_path()
        if not path:
            _CACHE = {"tables": []}
            return _CACHE
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {"tables": []}
        if not isinstance(data, dict):
            data = {"tables": []}
        _CACHE = data
        return _CACHE


def _table(name: str) -> dict[str, Any]:
    for tbl in _load_index().get("tables", []) or []:
        if isinstance(tbl, dict) and tbl.get("name") == name:
            return tbl
    return {}


def _columns(table_name: str) -> list[dict[str, Any]]:
    return list(_table(table_name).get("columns", []) or [])


def _column_synonyms(col: dict[str, Any]) -> list[str]:
    syn: list[str] = []
    syn.extend(col.get("excel_synonyms_zh") or [])
    syn.extend(col.get("api_aliases") or [])
    syn.append(col.get("name") or "")
    return [str(s).strip() for s in syn if str(s or "").strip()]


def _normalize_keys(keys: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for k in keys or ():
        s = str(k or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _match_column(key: str, columns: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not key:
        return None
    k_norm = re.sub(r"\s+", "", key).lower()
    for col in columns:
        for syn in _column_synonyms(col):
            s_norm = re.sub(r"\s+", "", syn).lower()
            if not s_norm:
                continue
            if s_norm == k_norm or s_norm in k_norm or k_norm in s_norm:
                return col
    return None


def match_excel_import_roles_from_field_index(keys: list[str]) -> dict[str, str]:
    """把 Excel 表头映射到 ``{unit_name, product_name, model_number, unit_price}`` 四角色。

    - 未命中:该角色空字符串。
    - 表头可能多于四个,先取最像的列;冲突时按四角色顺序后写覆盖。
    """
    cols = _columns("products")
    result = {"unit_name": "", "product_name": "", "model_number": "", "unit_price": ""}
    seen_roles: set[str] = set()
    for k in _normalize_keys(keys):
        col = _match_column(k, cols)
        if not col:
            continue
        col_name = col.get("name")
        for role, candidates in _ROLE_TO_COLUMN.items():
            if role in seen_roles:
                continue
            if col_name in candidates:
                result[role] = k
                seen_roles.add(role)
                break
    return result


def price_column_buckets_for_keys(
    keys: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """把价格相关表头分桶:``(单列, 调价前, 调价后)``;无法识别返回空桶。"""
    cols = _columns("products")
    single: list[str] = []
    before: list[str] = []
    after: list[str] = []
    for k in _normalize_keys(keys):
        col = _match_column(k, cols)
        if not col or col.get("name") != "price":
            continue
        kl = k.lower()
        if "调价前" in k or "原价" in k:
            before.append(k)
        elif "调价后" in k or "新价" in k:
            after.append(k)
        else:
            single.append(k)
    return single, before, after


def reload_index() -> None:
    """清空缓存,让下一次调用重新读盘;测试 / 配置热更新用。"""
    global _CACHE
    with _LOCK:
        _CACHE = None
