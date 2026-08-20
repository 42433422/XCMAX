"""报表配置工具执行器。

报表配置存储：使用 data_dir 下的 JSON 文件（``reports/report_configs.json``），
避免新建数据库表（遵循"优先用现有表，不要新建表除非必要"原则）。

提供：
- ``configure_report``：新建/更新报表配置（日期范围、分组维度、图表类型等）
- ``list_report_configs``：列出所有报表配置
- ``delete_report_config``：按 config_id 删除报表配置

与 ``app/fastapi_routes/reports.py`` 现有只读报表端点配合：报表端点负责生成报表数据，
本工具负责持久化"用户希望以何种参数生成报表"的配置。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _configs_path() -> str:
    """返回报表配置 JSON 文件路径，确保父目录存在。"""
    from app.utils.path_io.path_utils import get_data_dir

    cfg_dir = os.path.join(get_data_dir(), "reports")
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "report_configs.json")


def _load_configs() -> list[dict[str, Any]]:
    """读取现有配置列表。文件不存在或损坏时返回空列表。"""
    path = _configs_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except RECOVERABLE_ERRORS:
        logger.warning("读取报表配置文件失败: %s", path, exc_info=True)
        return []


def _save_configs(configs: list[dict[str, Any]]) -> None:
    """落盘配置列表（原子写入：先写 .tmp 再 rename）。"""
    path = _configs_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


_VALID_REPORT_TYPES = {"sales", "inventory", "inventory_transactions", "purchase", "dashboard"}
_VALID_CHART_TYPES = {"bar", "line", "pie", "table", "scatter"}
_VALID_GROUP_BY = {
    "product",
    "customer",
    "supplier",
    "category",
    "warehouse",
    "month",
    "week",
    "day",
}


def configure_report(args: dict[str, Any]) -> dict[str, Any]:
    """新建或更新报表配置。

    Required args:
        report_type: 报表类型（sales/inventory/inventory_transactions/purchase/dashboard）
        config: 配置 dict，可包含 date_range / group_by / chart_type / filters / name 等字段

    Optional args:
        config_id: 若提供则更新现有配置；否则新建
        confirm: 写操作二次确认（默认 False）
    """
    report_type = str(args.get("report_type") or "").strip().lower()
    if report_type not in _VALID_REPORT_TYPES:
        return {
            "success": False,
            "error": "invalid_report_type",
            "message": f"report_type 必须是 {sorted(_VALID_REPORT_TYPES)} 之一",
        }

    config = args.get("config") or {}
    if not isinstance(config, dict) or not config:
        return {"success": False, "error": "config must be a non-empty dict"}

    # 字段校验
    chart_type = config.get("chart_type")
    if chart_type is not None and str(chart_type) not in _VALID_CHART_TYPES:
        return {
            "success": False,
            "error": "invalid_chart_type",
            "message": f"chart_type 必须是 {sorted(_VALID_CHART_TYPES)} 之一",
        }

    group_by = config.get("group_by")
    if group_by is not None and str(group_by) not in _VALID_GROUP_BY:
        return {
            "success": False,
            "error": "invalid_group_by",
            "message": f"group_by 必须是 {sorted(_VALID_GROUP_BY)} 之一",
        }

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": "配置报表为写操作，请显式传 confirm=true 再调用",
            "report_type": report_type,
            "preview_config": config,
        }

    config_id = str(args.get("config_id") or "").strip()
    configs = _load_configs()

    try:
        if config_id:
            updated = False
            for item in configs:
                if str(item.get("config_id") or "") == config_id:
                    item["report_type"] = report_type
                    item["config"] = config
                    item["updated_at"] = int(time.time())
                    updated = True
                    break
            if not updated:
                return {"success": False, "error": "config_not_found", "config_id": config_id}
            _save_configs(configs)
            return {
                "success": True,
                "message": "报表配置已更新",
                "config_id": config_id,
                "report_type": report_type,
                "config": config,
            }

        # 新建
        new_id = str(uuid.uuid4())
        new_entry = {
            "config_id": new_id,
            "report_type": report_type,
            "config": config,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        configs.append(new_entry)
        _save_configs(configs)
        return {
            "success": True,
            "message": "报表配置已创建",
            "config_id": new_id,
            "report_type": report_type,
            "config": config,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("configure_report 失败: %s", e)
        return {"success": False, "error": str(e)}


def list_report_configs(args: dict[str, Any]) -> dict[str, Any]:
    """列出所有报表配置，可按 report_type 过滤。

    Optional args:
        report_type: 若提供则只返回该类型的配置
    """
    report_type = str(args.get("report_type") or "").strip().lower() or None
    try:
        configs = _load_configs()
        if report_type:
            configs = [c for c in configs if str(c.get("report_type") or "").lower() == report_type]
        return {
            "success": True,
            "data": configs,
            "count": len(configs),
            "filter_report_type": report_type,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("list_report_configs 失败: %s", e)
        return {"success": False, "error": str(e), "data": []}


def delete_report_config(args: dict[str, Any]) -> dict[str, Any]:
    """按 config_id 删除报表配置。

    Required args:
        config_id: 配置 ID

    Optional args:
        confirm: 高危操作二次确认（默认 False）
    """
    config_id = str(args.get("config_id") or "").strip()
    if not config_id:
        return {"success": False, "error": "config_id is required"}

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"删除报表配置 {config_id} 为高危操作，请显式传 confirm=true 再调用",
            "config_id": config_id,
        }

    try:
        configs = _load_configs()
        new_configs = [c for c in configs if str(c.get("config_id") or "") != config_id]
        if len(new_configs) == len(configs):
            return {"success": False, "error": "config_not_found", "config_id": config_id}
        _save_configs(new_configs)
        return {
            "success": True,
            "message": f"报表配置 {config_id} 已删除",
            "config_id": config_id,
            "deleted_count": len(configs) - len(new_configs),
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("delete_report_config 失败: %s", e)
        return {"success": False, "error": str(e), "config_id": config_id}


__all__ = [
    "configure_report",
    "list_report_configs",
    "delete_report_config",
]
