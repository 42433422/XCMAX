"""租户级模板库偏好：内置模板可隐藏但不可删除安装资源。"""

from __future__ import annotations

import json
import os
from typing import Any

from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

_PREFERENCES_FILE = "template_preferences.json"


def _preferences_path() -> str | None:
    tenant_id = current_tenant_id()
    if tenant_id is None:
        return None
    root = os.path.join(get_app_data_dir(), "tenants", str(tenant_id))
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, _PREFERENCES_FILE)


def _read() -> dict[str, Any]:
    path = _preferences_path()
    if path is None or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict[str, Any]) -> None:
    path = _preferences_path()
    if path is None:
        return
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def hidden_template_ids() -> set[str]:
    return set(_string_list(_read().get("hidden_template_ids")))


def hidden_template_paths() -> set[str]:
    return set(_string_list(_read().get("hidden_template_paths")))


def hide_templates(*, ids: list[str] | None = None, paths: list[str] | None = None) -> int:
    """记录隐藏项，返回本次新增数量；重复隐藏不重复计数。"""
    data = _read()
    current_ids = set(_string_list(data.get("hidden_template_ids")))
    current_paths = set(_string_list(data.get("hidden_template_paths")))
    added = 0
    for value in ids or []:
        text = str(value or "").strip()
        if text and text not in current_ids:
            current_ids.add(text)
            added += 1
    for value in paths or []:
        text = str(value or "").strip()
        if text and text not in current_paths:
            current_paths.add(text)
            added += 1
    if added:
        data["hidden_template_ids"] = sorted(current_ids)
        data["hidden_template_paths"] = sorted(current_paths)
        try:
            _write(data)
        except RECOVERABLE_ERRORS:
            return 0
    return added
