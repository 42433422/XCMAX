from __future__ import annotations

import json
import logging
import os

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_TEMPLATE_SCOPE_REQUIRED_TERMS_CACHE = None
_TEMPLATE_SCOPE_SUBSYSTEM_KEYS = {
    "orders": "orders",
    "shipmentRecords": "shipment-records",
    "products": "products",
    "materials": "materials",
    "customers": "customers",
}
_DEFAULT_TEMPLATE_SCOPE_RULES = {
    "orders": {
        "templateType": "出货明细",
        "requiredTerms": ["产品型号", "产品名称", "数量", "单价", "金额"],
    },
    "shipmentRecords": {
        "templateType": "出货记录",
        "requiredTerms": ["购买单位", "产品名称", "型号", "数量", "单价", "金额"],
    },
    "products": {
        "templateType": "产品目录",
        "requiredTerms": ["产品型号", "产品名称", "规格", "单价"],
    },
    "materials": {
        "templateType": "原材料",
        "requiredTerms": [
            "原材料编码",
            "名称",
            "分类",
            "规格",
            "单位",
            "库存数量",
            "单价",
            "供应商",
        ],
    },
    "customers": {
        "templateType": "客户",
        "requiredTerms": ["客户名称", "联系人", "电话", "地址"],
    },
    "shipmentSummary": {
        "templateType": "汇总统计",
        "requiredTerms": ["金额总计", "金额合计", "金额"],
    },
    "salesReport": {
        "templateType": "销售报表",
        "requiredTerms": ["销售金额", "实收款", "下欠款金额"],
    },
    "custom": {
        "templateType": "自定义模板",
        "requiredTerms": [],
    },
}


def _load_template_scope_required_terms():
    default_rules = {
        scope_key: list((meta or {}).get("requiredTerms") or [])
        for scope_key, meta in _DEFAULT_TEMPLATE_SCOPE_RULES.items()
    }
    config_path = str(os.environ.get("XCAGI_TEMPLATE_SCOPE_RULES_PATH") or "").strip()
    if not config_path:
        return default_rules
    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = json.load(f) or {}
        merged = dict(default_rules)
        for scope_key, rule in config_data.items():
            if isinstance(rule, dict) and "requiredTerms" in rule:
                merged[scope_key] = list((rule or {}).get("requiredTerms") or [])
        return merged
    except RECOVERABLE_ERRORS:
        return default_rules


def _get_template_scope_required_terms():
    global _TEMPLATE_SCOPE_REQUIRED_TERMS_CACHE
    if _TEMPLATE_SCOPE_REQUIRED_TERMS_CACHE is None:
        _TEMPLATE_SCOPE_REQUIRED_TERMS_CACHE = _load_template_scope_required_terms()
    return _merge_industry_subsystem_required_terms(
        _TEMPLATE_SCOPE_REQUIRED_TERMS_CACHE,
        _get_request_industry_subsystems(),
    )


def _merge_industry_subsystem_required_terms(base_rules, subsystems):
    """Overlay template terms with the current industry's real subsystem fields."""
    merged = {scope: list(terms or []) for scope, terms in (base_rules or {}).items()}
    if not isinstance(subsystems, dict):
        return merged
    for scope_key, subsystem_key in _TEMPLATE_SCOPE_SUBSYSTEM_KEYS.items():
        subsystem = subsystems.get(subsystem_key)
        if not isinstance(subsystem, dict):
            continue
        fields = subsystem.get("fields")
        if not isinstance(fields, list):
            continue
        labels = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            merged[scope_key] = labels
    return merged


def _get_request_industry_subsystems():
    """Resolve per-request industry schema; background work keeps generic rules."""
    try:
        from app.infrastructure.request_context import get_current_request
        from resources.config.industry_config import get_industry_profile

        request = get_current_request()
        industry_id = str(getattr(getattr(request, "state", None), "industry_id", "") or "").strip()
        if not industry_id:
            return {}
        try:
            from app.application.tenant_workspace_prefs import (
                get_selected_industry_id,
                resolve_workspace_owner_id,
            )
            from app.infrastructure.auth.dependencies import resolve_session_user

            user = resolve_session_user(request)
            if user is not None:
                owner_id = resolve_workspace_owner_id(request, user)
                saved_industry_id = str(get_selected_industry_id(owner_id) or "").strip()
                if saved_industry_id:
                    industry_id = saved_industry_id
        except RECOVERABLE_ERRORS:
            logger.debug("workspace industry preference unavailable; use request industry", exc_info=True)
        profile = get_industry_profile(industry_id)
        subsystems = getattr(profile, "subsystems", {})
        return subsystems if isinstance(subsystems, dict) else {}
    except RECOVERABLE_ERRORS:
        logger.debug("industry template schema unavailable; use generic terms", exc_info=True)
        return {}


def _normalize_term(value):
    return str(value or "").strip().replace(" ", "").lower()


_TERM_EQUIVALENTS = {
    "产品型号": ["产品型号", "型号", "产品编码"],
    "型号": ["型号", "产品型号", "产品编码"],
    "规格": ["规格", "规格型号", "规格/kg"],
    "规格型号": ["规格型号", "规格", "规格/kg"],
    "价格": ["价格", "单价", "单价/元"],
    "单价": ["单价", "价格", "单价/元"],
    "金额": ["金额", "金额/元", "金额合计", "总金额", "金额总计"],
    "金额总计": ["金额总计", "金额合计", "总金额", "金额", "合计金额"],
    "金额合计": ["金额合计", "金额总计", "总金额", "金额", "合计金额"],
    "销售金额": ["销售金额", "销售额", "销售总额", "营业额"],
    "实收款": ["实收款", "实收", "已收款", "实收金额"],
    "下欠款金额": ["下欠款金额", "下欠款", "欠款", "应收余额", "欠款金额"],
    "数量": ["数量", "数量(kg)", "数量/kg", "数量/件", "数量/桶", "库存数量"],
    "电话": ["电话", "联系电话", "手机号"],
    "购买单位": ["购买单位", "单位", "单位名称", "客户名称", "厂名"],
    "客户名称": ["客户名称", "购买单位", "单位名称", "厂名"],
}


def _get_equivalent_normalized_terms(term: str):
    key = str(term or "").strip()
    aliases = _TERM_EQUIVALENTS.get(key) or [key]
    normalized = [_normalize_term(v) for v in aliases if _normalize_term(v)]
    normalized_key = _normalize_term(key)
    if normalized_key and normalized_key not in normalized:
        normalized.append(normalized_key)
    return normalized


def _has_equivalent_term(extracted_terms: set, required_term: str) -> bool:
    if not isinstance(extracted_terms, set):
        return False
    candidates = _get_equivalent_normalized_terms(required_term)
    return any(candidate in extracted_terms for candidate in candidates)


def _validate_required_terms(cells: dict, fields: list, template_scope: str):
    required_terms = _get_template_scope_required_terms().get(template_scope) or []
    if not required_terms:
        return True, []

    extracted = set()
    for f in fields or []:
        extracted.add(_normalize_term(f.get("label")))
        extracted.add(_normalize_term(f.get("name")))
        extracted.add(_normalize_term(f.get("value")))
    for cell_info in (cells or {}).values():
        extracted.add(_normalize_term((cell_info or {}).get("value")))

    missing_terms = [term for term in required_terms if not _has_equivalent_term(extracted, term)]
    return len(missing_terms) == 0, missing_terms


def _build_scope_template_type_map():
    map_result = {}
    for scope_key, meta in _DEFAULT_TEMPLATE_SCOPE_RULES.items():
        template_type = str((meta or {}).get("templateType") or "").strip()
        if template_type:
            map_result[template_type] = scope_key
    # 历史/旧数据兼容别名
    legacy_aliases = {
        "发货单": "orders",
        "出货明细": "orders",
        "产品清单": "products",
        "产品目录": "products",
        "原材料清单": "materials",
        "原材料": "materials",
        "客户清单": "customers",
        "客户": "customers",
        "汇总统计": "shipmentSummary",
        "销售报表": "salesReport",
    }
    for label, scope_key in legacy_aliases.items():
        map_result.setdefault(label, scope_key)
    return map_result


def _infer_business_scope(template_type: str):
    text = str(template_type or "").strip()
    if not text:
        return ""
    return _build_scope_template_type_map().get(text, "")
