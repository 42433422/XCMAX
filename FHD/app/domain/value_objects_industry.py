"""
值对象行业配置访问层（只读化）

为 value_objects 提供行业配置的轻量级访问。
行业上下文从请求中间件（IndustryContextMiddleware）注入的 request.state.industry_id
读取，无请求上下文时回退到 industry_config.get_current_industry()。

不再维护模块级可变状态（_current_industry / 缓存），set_current_industry 已移除。
"""

from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS


def get_current_industry() -> str:
    """获取当前行业 ID。

    优先从请求上下文（request.state.industry_id，由 IndustryContextMiddleware 注入）
    读取；无请求上下文时回退到 industry_config.get_current_industry()。
    """
    try:
        from app.infrastructure.request_context import get_current_request

        request = get_current_request()
        if request is not None:
            industry_id = getattr(request.state, "industry_id", None)
            if industry_id:
                return str(industry_id)
    except RECOVERABLE_ERRORS:
        pass

    try:
        from resources.config.industry_config import get_current_industry as _cfg_current

        return _cfg_current()
    except RECOVERABLE_ERRORS:
        # 统一兜底为「通用」，与 IndustryContextMiddleware / 前端 DEFAULT_INDUSTRY 一致
        return "通用"


def get_current_industry_config() -> dict[str, Any]:
    """获取当前行业的完整单位配置（按需从 industry_config 加载）。"""
    industry_id = get_current_industry()
    try:
        from resources.config.industry_config import get_industry_profile

        profile = get_industry_profile(industry_id)
        units = profile.units
        if isinstance(units, dict) and units:
            return units
    except RECOVERABLE_ERRORS:
        pass
    # 兜底：涂料默认单位
    return {
        "primary": "桶",
        "secondary": "kg",
        "primary_label": "桶数",
        "secondary_label": "公斤",
        "spec_label": "规格",
        "primary_field": "tins",
        "secondary_field": "kg",
        "spec_field": "spec_per_tin",
        "conversion": {
            "桶_to_kg": 20.0,
        },
    }


def get_current_industry_fields() -> dict[str, str]:
    """获取当前行业的字段配置（按需从 industry_config 加载）。"""
    industry_id = get_current_industry()
    try:
        from resources.config.industry_config import get_industry_profile

        profile = get_industry_profile(industry_id)
        fields = profile.quantity_fields
        if isinstance(fields, dict) and fields:
            return fields
    except RECOVERABLE_ERRORS:
        pass
    # 兜底：涂料默认字段
    return {
        "primary_field": "tins",
        "secondary_field": "kg",
        "spec_field": "spec_per_tin",
    }


def get_primary_field_name() -> str:
    """获取当前行业的主数量字段名"""
    fields = get_current_industry_fields()
    return fields.get("primary_field", "tins")


def get_secondary_field_name() -> str:
    """获取当前行业的辅助数量字段名"""
    fields = get_current_industry_fields()
    return fields.get("secondary_field", "kg")


def get_spec_field_name() -> str:
    """获取当前行业的规格字段名"""
    fields = get_current_industry_fields()
    return fields.get("spec_field", "spec_per_tin")


def get_current_subsystem_schema(menu_key: str) -> dict[str, Any]:
    """获取当前行业下某子系统(菜单键)的行业感知 schema 描述符。

    读取当前行业 profile 的 ``subsystems[menu_key]``，形如
    ``{label, visible, entity, fields: [{key, label, type, ...}], rules}``。
    这是后端 mapper/校验/单据生成读取「该行业该子系统有哪些字段/语义/规则」的 SSOT 门面。
    无声明时返回空 dict（调用方据此回退默认字段/标签，向后兼容旧 Mod）。
    """
    industry_id = get_current_industry()
    try:
        from resources.config.industry_config import get_industry_profile

        profile = get_industry_profile(industry_id)
        subsystems = getattr(profile, "subsystems", None)
        if isinstance(subsystems, dict):
            schema = subsystems.get(menu_key)
            if isinstance(schema, dict):
                return schema
    except RECOVERABLE_ERRORS:
        pass
    return {}


def reload_config():
    """重新加载配置（委托给 industry_config）。"""
    try:
        from resources.config.industry_config import reload_industry_config

        reload_industry_config()
    except RECOVERABLE_ERRORS:
        pass


__all__ = [
    "get_current_industry",
    "get_current_industry_config",
    "get_current_industry_fields",
    "get_current_subsystem_schema",
    "get_primary_field_name",
    "get_secondary_field_name",
    "get_spec_field_name",
    "reload_config",
]
