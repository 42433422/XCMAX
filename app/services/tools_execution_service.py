"""工具执行与订单解析服务。

Phase 4 由 ``app.services.archive_tools_legacy`` 更名而来,内容不变,
只是摆脱 "archive_" 命名噪音。后续 (Phase 4B) 计划与 ``app.legacy.tools``
去重合并到 ``app.application.tools.*``。
"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar

from app.http.json_response import json_response

from app.services.tools_payload_legacy import dispatch_legacy_tool_payload
from app.services.tools_workflow_registered import execute_registered_workflow_tool

logger = logging.getLogger(__name__)

_tool_execute_headers: ContextVar[dict[str, str] | None] = ContextVar("tool_execute_headers", default=None)


def set_tool_execute_headers(headers: dict[str, str] | None) -> None:
    """供 FastAPI 路由在调用 execute_tool_from_payload 前注入请求头（如 X-User-ID）。"""
    _tool_execute_headers.set(headers)


def _hdr(name: str, default: str = "") -> str:
    h = _tool_execute_headers.get()
    if not h:
        return default
    for k, v in h.items():
        if k.lower() == name.lower():
            return str(v) if v is not None else default
    return default


def _j(data: dict, status: int = 200):
    return json_response(data, status)


CANONICAL_ACTIONS = {
    "view",
    "list",
    "query",
    "create",
    "update",
    "delete",
    "batch_delete",
    "import",
    "export",
    "analyze",
    "extract",
    "preview",
    "execute",
}

ACTION_ALIASES = {
    "查找": "query",
    "查询": "query",
    "搜索": "query",
    "search": "query",
    "find": "query",
    "add": "create",
    "新增": "create",
    "添加": "create",
    "create": "create",
    "modify": "update",
    "edit": "update",
    "更新": "update",
    "删除": "delete",
    "remove": "delete",
    "del": "delete",
    "删除批量": "batch_delete",
    "batch-delete": "batch_delete",
    "batch_delete": "batch_delete",
    "导入": "import",
    "导出": "export",
    "分析": "analyze",
    "提取": "extract",
    "执行": "execute",
    "exec": "execute",
    "run": "execute",
}

REQUIRED_PARAMS_BY_TOOL_ACTION = {
    ("products", "create"): ["name_or_model", "unit_name"],
    ("products", "update"): ["id"],
    ("products", "delete"): ["id"],
    ("materials", "create"): ["name"],
    ("materials", "update"): ["id"],
    ("materials", "delete"): ["id"],
    ("materials", "batch_delete"): ["ids"],
    ("shipment_records", "update"): ["id"],
    ("shipment_records", "delete"): ["id"],
    ("template_extract", "extract"): ["file_path"],
    ("print", "print_label"): ["file_path"],
    ("print", "print_document"): ["file_path"],
    ("printer_list", "set_default"): ["printer_name"],
    ("wechat", "refresh_contact_cache"): [],
    ("wechat", "refresh_messages_cache"): [],
}


def _normalize_action(action: str, params: dict | None = None) -> str:
    raw = str(action or "").strip()
    if not raw:
        return "view"
    lowered = raw.lower()
    normalized = ACTION_ALIASES.get(raw) or ACTION_ALIASES.get(lowered) or lowered
    if normalized in CANONICAL_ACTIONS:
        return normalized
    if params and str(params.get("action") or "").strip():
        nested = str(params.get("action")).strip()
        nested_lower = nested.lower()
        mapped = ACTION_ALIASES.get(nested) or ACTION_ALIASES.get(nested_lower) or nested_lower
        if mapped in CANONICAL_ACTIONS:
            return mapped
    return normalized


def _validate_required_params(tool_id: str, action: str, params: dict | None) -> tuple[bool, str]:
    required = REQUIRED_PARAMS_BY_TOOL_ACTION.get((str(tool_id or "").strip(), str(action or "").strip()), [])
    if not required:
        return True, ""
    payload = dict(params or {})
    missing = []
    for key in required:
        value = payload.get(key)
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
            continue
        if isinstance(value, list) and len(value) == 0:
            missing.append(key)
            continue
    if missing:
        return False, f"缺少参数：{', '.join(missing)}"
    return True, ""


def get_workflow_tool_registry() -> dict:
    """供动态工作流规划器使用的工具注册表（schema + risk + availability）。"""
    return {
        "customers": {
            "description": "购买单位管理",
            "availability": "shared",
            "actions": {
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "ensure_exists": {
                    "risk": "medium",
                    "idempotent": True,
                    "required_params": ["unit_name"],
                    "availability": "shared",
                },
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["unit_name"],
                    "availability": "shared",
                },
            },
        },
        "products": {
            "description": "产品管理",
            "availability": "shared",
            "actions": {
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "exists": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["name_or_model", "unit_name"],
                    "availability": "shared",
                },
            },
        },
        "materials": {
            "description": "原材料仓库与列表管理",
            "availability": "shared",
            "actions": {
                "list": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "create": {"risk": "medium", "idempotent": False, "required_params": ["name"], "availability": "shared"},
                "update": {"risk": "medium", "idempotent": False, "required_params": ["id"], "availability": "shared"},
                "delete": {"risk": "high", "idempotent": False, "required_params": ["id"], "availability": "shared"},
                "batch_delete": {"risk": "high", "idempotent": False, "required_params": ["ids"], "availability": "shared"},
                "export": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
            },
        },
        "shipment_records": {
            "description": "出货记录管理",
            "availability": "shared",
            "actions": {
                "list": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "update": {"risk": "medium", "idempotent": False, "required_params": ["id"], "availability": "shared"},
                "delete": {"risk": "high", "idempotent": False, "required_params": ["id"], "availability": "shared"},
                "export": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
            },
        },
        "business_docking": {
            "description": "业务对接与模板网格提取",
            "availability": "shared",
            "actions": {
                "view": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "extract": {"risk": "low", "idempotent": True, "required_params": ["file_path"], "availability": "shared"},
                "preview": {"risk": "low", "idempotent": True, "required_params": ["file_path"], "availability": "shared"},
            },
        },
        "template_preview": {
            "description": "模板预览与管理",
            "availability": "shared",
            "actions": {
                "view": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "list": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "create": {"risk": "medium", "idempotent": False, "required_params": [], "availability": "shared"},
            },
        },
        "wechat": {
            "description": "微信联系人与消息缓存管理",
            "availability": "shared",
            "actions": {
                "view": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "list": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "refresh_contact_cache": {"risk": "medium", "idempotent": True, "required_params": [], "availability": "shared"},
                "refresh_messages_cache": {"risk": "medium", "idempotent": True, "required_params": [], "availability": "shared"},
            },
        },
        "print": {
            "description": "标签与文档打印",
            "availability": "shared",
            "actions": {
                "view": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "list": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "print_label": {"risk": "high", "idempotent": False, "required_params": ["file_path"], "availability": "shared"},
                "print_document": {"risk": "high", "idempotent": False, "required_params": ["file_path"], "availability": "shared"},
                "test": {"risk": "low", "idempotent": True, "required_params": ["printer_name"], "availability": "shared"},
            },
        },
        "printer_list": {
            "description": "打印机列表与默认打印机设置",
            "availability": "shared",
            "actions": {
                "view": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "list": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "set_default": {"risk": "medium", "idempotent": False, "required_params": ["printer_name"], "availability": "shared"},
            },
        },
        "settings": {
            "description": "系统设置与运行环境配置",
            "availability": "shared",
            "actions": {
                "view": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "query": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "get_system_info": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "get_startup_config": {"risk": "low", "idempotent": True, "required_params": [], "availability": "shared"},
                "enable_startup": {"risk": "medium", "idempotent": False, "required_params": [], "availability": "shared"},
                "disable_startup": {"risk": "medium", "idempotent": False, "required_params": [], "availability": "shared"},
            },
        },
        "normal_slot_dispatch": {
            "description": "普通版槽位：产品查询浮窗、发货单编号预览（与 /api/ai/unified_chat 同源）",
            "availability": "normal_only",
            "actions": {
                "product_query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "normal_only",
                },
                "shipment_preview": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "normal_only",
                },
            },
        },
        "excel_analysis": {
            "description": "Excel文件智能分析：读取内容、分析结构、统计汇总、自然语言查询",
            "availability": "shared",
            "actions": {
                "read": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "structure": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path", "question"],
                    "availability": "shared",
                },
                "statistics": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
            },
        },
    }


def _parse_order_text(order_text: str) -> dict:
    """
    解析订单文本，提取单位名和产品信息
    
    支持的格式：
    - "发货单七彩乐园 1 桶 9803 规格 12"
    - "送货单公司名称 2 箱产品 A 规格 100"
    - 等
    
    Returns:
        {
            "success": True/False,
            "unit_name": "单位名称",
            "products": [
                {
                    "name": "产品名称",
                    "quantity_tins": 桶数，
                    "tin_spec": 每桶规格，
                    "model_number": "型号"
                }
            ],
            "message": "错误消息（如果有）"
        }
    """
    try:
        import re

        original_text = (order_text or "").strip()

        # 统一移除“发货单/送货单/出货单”关键词本身，避免“关键词在句尾”时把正文截空
        # 例如：“打印七彩乐园9803规格12要3桶发货单”旧逻辑会得到空串。
        text = original_text
        for kw in ["发货单", "送货单", "出货单"]:
            text = text.replace(kw, " ")

        # 轻量清洗：把常见中文标点当作分隔符
        text = (
            text.replace('。', ' ')
            .replace('，', ' ')
            .replace(',', ' ')
            .replace('、', ' ')
            .replace('：', ' ')
            .replace(':', ' ')
        )

        # 归一化粒子：允许“的规格 / 的型号 / 的桶”等 ASR 文本形式
        text = text.replace('的规格', '规格')
        slot_text = (
            original_text.replace('。', ' ')
            .replace('，', ' ')
            .replace(',', ' ')
            .replace('、', ' ')
            .replace('：', ' ')
            .replace(':', ' ')
            .replace('的规格', '规格')
        )
        
        if not text:
            return {
                "success": False,
                "message": "订单文本格式不正确，缺少内容"
            }

        def _parse_cn_number(token: str):
            """解析阿拉伯数字/常见中文数字（支持二十八、三十、十、三桶中的三）。"""
            import re
            t = (token or "").strip()
            if not t:
                return None
            if re.fullmatch(r"\d+(?:\.\d+)?", t):
                return float(t) if "." in t else int(t)

            m = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
            if t in m:
                return m[t]
            if t == "十":
                return 10
            if re.fullmatch(r"[一二两三四五六七八九]十", t):
                return m[t[0]] * 10
            if re.fullmatch(r"十[一二三四五六七八九]", t):
                return 10 + m[t[1]]
            if re.fullmatch(r"[一二两三四五六七八九]十[一二三四五六七八九]", t):
                return m[t[0]] * 10 + m[t[2]]
            return None

        def _cleanup_unit_name(raw: str) -> str:
            import re
            s = (raw or "").strip()
            # 去掉口语填充词/命令词，保留真实单位名
            s = re.sub(r"^(哎|嗯|啊|呃)[，,\s]*", "", s)
            s = re.sub(r"^(帮我|给我|请)?\s*打印(一下)?", "", s)
            s = re.sub(r"^(把|给)?", "", s)
            # 去掉增删改前缀动作词，避免把“再加/减少/删掉/改成”误当单位名
            s = re.sub(
                r"^(再加|还要|继续加|再补|加上|增加|加|减少|减去|减|删掉|删除|去掉|移除|改成|改为|改)\s*",
                "",
                s,
            )
            s = s.replace("发货单", "").replace("送货单", "").replace("出货单", "")
            for token in [
                "打印一下", "打印", "给我", "帮我", "一下", "哎", "嗯", "啊", "呃",
                "桶", "要", "来", "拿", "再加", "还要", "继续加", "再补", "减少",
                "减去", "减", "删掉", "删除", "去掉", "移除", "改成", "改为",
            ]:
                s = s.replace(token, "")
            # 避免把型号 token 残留到单位名中（支持 9000A）
            s = re.sub(r"[0-9A-Za-z-]{3,16}", "", s)
            s = re.sub(r"\s+", "", s)
            s = s.rstrip("的").strip()
            return s

        def _build_missing_prompt(unit_name=None, model_number=None, tin_spec=None, quantity_tins=None):
            missing = []
            if not unit_name:
                missing.append("单位")
            if not quantity_tins:
                missing.append("桶数")
            if not model_number:
                missing.append("编号/型号")
            if not tin_spec:
                missing.append("规格")
            if not missing:
                return None
            recognized = []
            if unit_name:
                recognized.append(f"单位 {unit_name}")
            if model_number:
                recognized.append(f"编号 {model_number}")
            if tin_spec:
                recognized.append(f"规格 {tin_spec}")
            recognized_text = ("（已识别：" + "，".join(recognized) + "）") if recognized else ""
            if missing == ["桶数"]:
                return f"还缺少桶数，请告诉我需要多少桶？{recognized_text}"
            if missing == ["单位"]:
                return f"还缺少单位名称，请补充购买单位。{recognized_text}"
            if missing == ["规格"]:
                return f"还缺少规格，请补充规格数值。{recognized_text}"
            if missing == ["编号/型号"]:
                return f"还缺少编号/型号，请补充。{recognized_text}"
            return f"还缺少{'、'.join(missing)}，请补充。{recognized_text}"

        # 槽位解析（任意语序口语）
        # 示例：给我打印七彩乐园发货单，编号9803，规格二十八，一共三桶
        # 先从全句提取 编号/规格/桶数，再从剩余文本抽单位名
        slot_model = None
        slot_spec = None
        slot_qty_tins = None

        model_token_pattern = r"[0-9A-Za-z-]{3,16}"
        m_model = re.search(rf"(?:编号|型号)\s*(?:是)?\s*[:：]?\s*({model_token_pattern})", slot_text)
        if m_model:
            slot_model = (m_model.group(1) or "").strip().upper()
        else:
            # 兜底：取“规格”前最近的数字串作为型号（如 9803规格28）
            m_model2 = re.search(rf"({model_token_pattern})\s*(?:的)?\s*规格", slot_text)
            if m_model2:
                slot_model = (m_model2.group(1) or "").strip().upper()

        # 规格支持阿拉伯数字与中文数字，并兼容"规格12要3桶/规格二十八三桶"等连读口语
        if "规格" in slot_text:
            after_spec = slot_text.split("规格", 1)[1]
            number_token_pattern = r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九零〇])"
            qty_token_pattern = r"(?:\d+|[一二两三四五六七八九十零〇两]+)"

            # 优先匹配"规格XX(要|来|拿)?三桶"这类连读
            m_spec_qty = re.search(
                rf"^\s*[:：]?\s*({number_token_pattern})(?:\s*(?:要|来|拿|共|一共|总共)?\s*({qty_token_pattern})\s*桶)?",
                after_spec,
            )
            if m_spec_qty:
                spec_num = _parse_cn_number(m_spec_qty.group(1))
                if spec_num is not None:
                    slot_spec = float(spec_num)
                if m_spec_qty.group(2):
                    qty_num = _parse_cn_number(m_spec_qty.group(2))
                    if qty_num is not None:
                        slot_qty_tins = int(qty_num)
            else:
                # 兜底：只提取规格
                m_spec = re.search(r"^\s*[:：]?\s*(\d+(?:\.\d+)?)", after_spec)
                if m_spec:
                    spec_num = _parse_cn_number(m_spec.group(1))
                    if spec_num is not None:
                        slot_spec = float(spec_num)
                else:
                    m_spec_cn = re.search(r"^\s*[:：]?\s*([一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九零〇])", after_spec)
                    if m_spec_cn:
                        spec_num = _parse_cn_number(m_spec_cn.group(1))
                        if spec_num is not None:
                            slot_spec = float(spec_num)

        # 如果规格连读已经提取了桶数，就不再重复提取（支持“要3桶/来3桶/拿3桶”）
        if slot_qty_tins is None:
            m_qty = re.search(r"(?:一共|总共|共|要|来|拿)?\s*(\d+|[一二两三四五六七八九十零〇两]+)\s*桶", slot_text)
            if m_qty:
                qty_num = _parse_cn_number(m_qty.group(1))
                if qty_num is not None:
                    slot_qty_tins = int(qty_num)
        # 单位名：移除命令词+关键槽位片段后取前半段
        unit_candidate = slot_text
        unit_candidate = re.sub(r"(发货单|送货单|出货单)", " ", unit_candidate)
        unit_candidate = re.sub(rf"(?:编号|型号)\s*(?:是)?\s*[:：]?\s*{model_token_pattern}", " ", unit_candidate)
        unit_candidate = re.sub(r"规格\s*[:：]?\s*(?:\d+(?:\.\d+)?|[一二两三四五六七八九十零〇两]+)(?:\s*(?:\d+|[一二两三四五六七八九十零〇两]+)\s*桶)?", " ", unit_candidate)
        unit_candidate = re.sub(r"(?:一共|总共|共|要|来|拿)?\s*(?:\d+|[一二两三四五六七八九十零〇两]+)\s*桶", " ", unit_candidate)
        unit_candidate = re.sub(r"[0-9A-Za-z-]{3,16}", " ", unit_candidate)
        unit_candidate = re.sub(r"[，,\s]+", " ", unit_candidate).strip()
        slot_unit = _cleanup_unit_name(unit_candidate)
        if not slot_unit:
            m_unit = re.search(r"(?:打印(?:一下)?)\s*([^，,。]+?)\s*的?\s*(?:发货单|送货单|出货单)", slot_text)
            if not m_unit:
                m_unit = re.search(r"([^，,。]+?)\s*的?\s*(?:发货单|送货单|出货单)", slot_text)
            if m_unit:
                slot_unit = _cleanup_unit_name(m_unit.group(1))
        if not slot_unit:
            m_unit3 = re.search(r"([^，,。0-9]+?)的(?:发货单|送货单|出货单)", slot_text)
            if m_unit3:
                slot_unit = _cleanup_unit_name(m_unit3.group(1))
        if not slot_unit:
            for bill_kw in ["发货单", "送货单", "出货单"]:
                if bill_kw in slot_text:
                    slot_unit = _cleanup_unit_name(slot_text.split(bill_kw)[0])
                    if slot_unit:
                        break
        if not slot_unit:
            # 最后兜底：提取“打印一下XX发货单”中 XX
            m_unit4 = re.search(r"打印(?:一下)?\s*([^，,。]+?)\s*(?:发货单|送货单|出货单)", slot_text)
            if m_unit4:
                slot_unit = _cleanup_unit_name(m_unit4.group(1))

        # 「发货单蕊芯1一桶9806…」类句式：桶数 1 会残留在单位尾部成「蕊芯1」，导致购买单位匹配失败
        if slot_unit and slot_qty_tins is not None:
            try:
                qt = int(slot_qty_tins)
            except (TypeError, ValueError):
                qt = None
            if qt is not None and qt > 0:
                tu = str(slot_unit).strip()
                tail = str(qt)
                if tu.endswith(tail) and len(tu) > len(tail):
                    pref = tu[: -len(tail)].strip()
                    if pref and re.search(r"[\u4e00-\u9fa5A-Za-z]", pref):
                        slot_unit = pref

        # 仅在口语槽位信号较强时才走该分支，避免覆盖原有“1桶酒吧零三规格28”成功路径
        slot_mode_trigger = (
            ("编号" in slot_text or "型号" in slot_text or "一共" in slot_text or "总共" in slot_text or "共" in slot_text)
            or re.search(rf"{model_token_pattern}\s*(?:的)?\s*规格", slot_text)
            or re.search(r"(?:要|来|拿)\s*(?:\d+|[一二两三四五六七八九十零〇两]+)\s*桶", slot_text)
        )
        # 多产品句式（如“1桶9803规格23，2桶9000A规格23”）不走单槽位直返，交给后面的多产品解析。
        multi_product_hint = len(
            re.findall(r"(?:\d+|[一二两三四五六七八九十零〇]+)\s*桶\s*[0-9A-Za-z-]+\s*规格\s*\d+(?:\.\d+)?", slot_text)
        ) >= 2
        if slot_mode_trigger and (slot_model or slot_spec or slot_qty_tins) and not multi_product_hint:
            # 缺项追问（不中断工作流）
            missing_prompt = _build_missing_prompt(
                unit_name=slot_unit,
                model_number=slot_model,
                tin_spec=int(slot_spec) if isinstance(slot_spec, float) and slot_spec.is_integer() else slot_spec,
                quantity_tins=slot_qty_tins,
            )
            if missing_prompt:
                return {"success": False, "message": missing_prompt}

            # 完整则直接返回，避免后续固定顺序正则再失败
            return {
                "success": True,
                "unit_name": slot_unit,
                "products": [{
                    "name": "",
                    "model_number": str(slot_model),
                    "quantity_tins": int(slot_qty_tins),
                    "tin_spec": float(slot_spec),
                }]
            }
        
        # -----------------------------
        # 归一化解析用的小工具
        # -----------------------------
        CHINESE_DIGIT_MAP = {
            "零": "0", "〇": "0",
            "一": "1",
            "二": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
            "八": "8",
            "九": "9",
            "两": "2",
        }

        # ASR 误读片段到数字片段的“分段纠错映射”
        # 例如：酒吧零三 -> (酒吧->98) + (零三->03) -> 9803
        ASR_MODEL_SEGMENT_MAP = {
            "酒吧": "98",
        }

        def _normalize_trailing_unit_name(name: str) -> str:
            # 例如：七彩乐园的 -> 七彩乐园
            return (name or "").strip().rstrip("的").strip()

        def _normalize_chinese_digits(token: str) -> str:
            """
            把“零三/一/两”等这种“逐位数字串”转成阿拉伯数字串，保留前导零（如 零三 -> 03）。
            """
            token = (token or "").strip()
            if not token:
                return ""

            # 纯阿拉伯数字：直接返回
            if re.fullmatch(r"\d+(?:\.\d+)?", token):
                return token

            # 仅由中文数字字符组成（逐位映射）
            if all(ch in CHINESE_DIGIT_MAP for ch in token):
                return "".join(CHINESE_DIGIT_MAP[ch] for ch in token)

            # 兜底：在 token 内提取中文数字字符并逐位映射
            digits = []
            for ch in token:
                if ch in CHINESE_DIGIT_MAP:
                    digits.append(CHINESE_DIGIT_MAP[ch])
            return "".join(digits)

        def _normalize_quantity_token(quantity_token: str):
            """
            把数量（如“一”）归一为整数桶数。
            """
            quantity_token = (quantity_token or "").strip()
            if not quantity_token:
                return None
            if re.fullmatch(r"\d+", quantity_token):
                return int(quantity_token)
            digits = _normalize_chinese_digits(quantity_token)
            if digits.isdigit():
                return int(digits)
            return None

        def _normalize_model_number_token(model_token: str) -> str:
            """
            把型号 token 归一为统一型号字符串（数字/字母/连字符）。
            - 支持 ASR 误读分段（如 酒吧->98）
            - 支持中文数字逐位映射（零三->03）
            """
            token = (model_token or "").strip()
            if not token:
                return ""

            # 已是常见型号形态，直接标准化（去空格、转大写）
            compact = re.sub(r"\s+", "", token)
            if re.fullmatch(r"[0-9A-Za-z-]+", compact):
                return compact.upper()

            # 逐段纠错：把已知误读片段先替换为数字片段
            for k, v in ASR_MODEL_SEGMENT_MAP.items():
                if k in token:
                    token = token.replace(k, v)

            # 按字符归一：保留数字/字母/连字符，中文数字映射为阿拉伯数字
            out: list[str] = []
            for ch in token:
                if ch.isdigit():
                    out.append(ch)
                elif ch in CHINESE_DIGIT_MAP:
                    out.append(CHINESE_DIGIT_MAP[ch])
                elif ch.isalpha():
                    out.append(ch.upper())
                elif ch == "-":
                    out.append(ch)
            return "".join(out)

        # -----------------------------
        # 多产品解析：支持 "发货单七彩乐园1桶9803规格23，2桶9000A规格23"
        # -----------------------------
        multi_pattern = r'(\d+|[一二两三四五六七八九十零〇]+)\s*桶\s*([0-9A-Za-z-]+)\s*规格\s*(\d+(?:\.\d+)?)'
        multi_matches = list(re.finditer(multi_pattern, slot_text))
        if multi_matches:
            products = []
            for m in multi_matches:
                qty = _parse_cn_number(m.group(1))
                model = (m.group(2) or "").strip().upper()
                spec = float(m.group(3))
                if model:
                    products.append({
                        "name": "",
                        "model_number": model,
                        "quantity_tins": int(qty) if qty else 1,
                        "tin_spec": spec
                    })

            if products:
                prefix_text = slot_text[:multi_matches[0].start()]
                for kw in ["发货单", "送货单", "出货单", "货单", "打印", "打单", "开单", "帮我", "给我", "请", "一下"]:
                    prefix_text = prefix_text.replace(kw, " ")
                unit_candidate = _cleanup_unit_name(prefix_text)
                if not unit_candidate:
                    unit_candidate = _cleanup_unit_name(text.split()[0] if text.split() else "")

                if unit_candidate:
                    return {
                        "success": True,
                        "unit_name": unit_candidate,
                        "products": products
                    }

        # -----------------------------
        # 简单解析：按"桶"、"规格"分割
        # -----------------------------
        patterns = [
            # 模式 1: "七彩乐园 1 桶 9803 规格 12"
            # 允许数量/型号为中文数字/ASR token，且允许“的规格”
            r'^([^\d]+?)(\d+|[一二三四五六七八九十零〇两]+)\s*桶\s*(.+?)\s*规格\s*(\d+(?:\.\d+)?)',
            # 模式 2: "七彩乐园 1 桶 9803"
            r'^([^\d]+?)(\d+|[一二三四五六七八九十零〇两]+)\s*桶\s*(.+)$',
            # 模式 3: "七彩乐园 2 箱产品 A"
            r'^([^\d]+?)(\d+|[一二三四五六七八九十零〇两]+)\s*(箱 | 件)\s*(.+)',
            # 模式 4: "公司 A 3 公斤材料 B"
            r'^([^\d]+?)(\d+(?:\.\d+)?|[一二三四五六七八九十零〇两]+)\s*(公斤|kg)\s*(.+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                if len(groups) >= 3:
                    unit_name = _normalize_trailing_unit_name(groups[0])
                    
                    # 判断是否是数字开头（型号）还是单位
                    unit_or_measure = (groups[2] or "").strip()
                    if unit_or_measure in ['箱', '件', '公斤', 'kg']:
                        # 模式 3 或 4
                        try:
                            # 箱/件：尽量解析为整数；公斤/kg：允许小数（并支持中文数字）
                            if unit_or_measure in ['箱', '件']:
                                quantity = float(_normalize_quantity_token(groups[1]) or 0)
                            else:
                                token = (groups[1] or "").strip()
                                if re.fullmatch(r"\d+(?:\.\d+)?", token):
                                    quantity = float(token)
                                else:
                                    digits = _normalize_chinese_digits(token)
                                    quantity = float(digits) if digits else float(token)
                        except:
                            quantity = 1
                        
                        product_name = groups[3].strip() if len(groups) > 3 else "产品"
                        
                        result = {
                            "success": True,
                            "unit_name": unit_name,
                            "products": [{
                                "name": product_name,
                                "tin_spec": 10.0,  # 默认规格
                            }]
                        }
                        
                        if '公斤' in unit_or_measure or 'kg' in unit_or_measure:
                            result["products"][0]["quantity_kg"] = quantity
                        else:
                            result["products"][0]["quantity_tins"] = int(quantity) if unit_or_measure in ['箱', '件'] else quantity
                        
                        return result
                    else:
                        # 模式 1 或 2: "七彩乐园 1 桶 9803 规格 12"
                        try:
                            quantity = _normalize_quantity_token(groups[1])
                            if quantity is None:
                                return {
                                    "success": False,
                                    "message": "解析数字失败（数量无法识别）"
                                }

                            model_number = _normalize_model_number_token(groups[2])
                            if not model_number:
                                return {
                                    "success": False,
                                    "message": "解析数字失败（型号无法识别）"
                                }

                            spec = float(groups[3]) if len(groups) > 3 else 10.0
                        except:
                            return {
                                "success": False,
                                "message": "解析数字失败"
                            }
                        
                        # name 留空，让后续数据库匹配来填充正确的产品名称
                        return {
                            "success": True,
                            "unit_name": unit_name,
                            "products": [{
                                "name": "",  # 留空，等待数据库匹配
                                "model_number": model_number,
                                "quantity_tins": quantity,
                                "tin_spec": spec,
                            }]
                        }
        
        # 弱匹配：打印/报型号+规格，但缺少“桶/箱/件/公斤/kg”数量容器时
        # 例如：打印一下七彩乐园的9803规格28（用户只给了型号与规格，没有桶数）
        # 目标：让系统追问“需要多少桶？”，而不是忽略或走产品流程。
        has_container_qty = any(k in text for k in ["桶", "箱", "件", "公斤", "kg"])
        if not has_container_qty:
            m = re.search(rf'([^\d]+?)\s*({model_token_pattern})\s*规格\s*(\d+(?:\.\d+)?)', text)
            if m:
                unit_part = m.group(1)
                model_token = m.group(2)
                spec_token = m.group(3)

                unit_name = _normalize_trailing_unit_name(unit_part)
                # 去掉可能出现在 unit_part 前缀的口语/指令词（如“打印一下七彩乐园的”）
                unit_name = re.sub(r'^(帮我|给我)?打印(一下)?|^打单|^开单', '', unit_name).strip()
                model_number = _normalize_model_number_token(model_token)
                tin_spec = float(spec_token)

                if unit_name and model_number and tin_spec is not None:
                    spec_display = int(tin_spec) if tin_spec.is_integer() else tin_spec
                    return {
                        "success": False,
                        "message": f"还缺少桶数（数量）。已识别：{unit_name} / {model_number} / 规格 {spec_display}。请告诉我需要多少桶？"
                    }

        # AI 结构化抽取兜底：规则仍失败时尝试从口语中抽取 unit/model/spec/qty
        try:
            import json
            import os

            import httpx

            api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            if api_key:
                prompt = (
                    "请从下面中文订单口语中抽取 JSON 字段："
                    "unit_name, model_number, tin_spec, quantity_tins。"
                    "仅返回 JSON，不要解释，不要 markdown。\n"
                    f"文本：{text}"
                )
                with httpx.Client(timeout=8.0) as client:
                    resp = client.post(
                        "https://api.deepseek.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "deepseek-chat",
                            "messages": [
                                {"role": "system", "content": "你是结构化信息抽取助手，只输出 JSON。"},
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0.0,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = (
                            (data.get("choices") or [{}])[0]
                            .get("message", {})
                            .get("content", "")
                            .strip()
                        )
                        # 兼容 ```json ... ``` 包裹
                        content = re.sub(r"^```json\s*|^```\s*|```$", "", content).strip()
                        parsed = json.loads(content) if content else {}
                        ai_unit = _cleanup_unit_name(str(parsed.get("unit_name", "")).strip())
                        ai_model = str(parsed.get("model_number", "")).strip()
                        ai_spec_raw = str(parsed.get("tin_spec", "")).strip()
                        ai_qty_raw = str(parsed.get("quantity_tins", "")).strip()
                        ai_spec = _parse_cn_number(ai_spec_raw) if ai_spec_raw else None
                        ai_qty = _parse_cn_number(ai_qty_raw) if ai_qty_raw else None

                        missing_prompt = _build_missing_prompt(
                            unit_name=ai_unit,
                            model_number=ai_model or None,
                            tin_spec=ai_spec,
                            quantity_tins=int(ai_qty) if ai_qty else None,
                        )
                        if missing_prompt:
                            return {"success": False, "message": missing_prompt}

                        if ai_unit and ai_model and ai_spec and ai_qty:
                            return {
                                "success": True,
                                "unit_name": ai_unit,
                                "products": [{
                                    "name": "",
                                    "model_number": ai_model,
                                    "quantity_tins": int(ai_qty),
                                    "tin_spec": float(ai_spec),
                                }],
                            }
        except Exception as ai_err:
            logger.warning(f"AI 结构化抽取兜底失败，回退规则流程: {ai_err}")

        # 如果所有模式都不匹配，尝试简单分割
        parts = text.split()
        if len(parts) >= 2:
            unit_name = parts[0].strip()
            return {
                "success": True,
                "unit_name": unit_name,
                "products": [{
                    "name": " ".join(parts[1:]),
                    "quantity_tins": 1,
                    "tin_spec": 10.0,
                }]
            }
        
        return {
            "success": False,
            "message": f"无法解析订单文本：{order_text}，请使用格式：发货单 + 单位名 + 数量 + 桶 + 型号 + 规格"
        }
        
    except Exception as e:
        logger.error(f"解析订单文本失败：{e}")
        return {
            "success": False,
            "message": f"解析失败：{str(e)}"
        }



def execute_tool_from_payload(data):
    """供 FastAPI 调用；返回 Werkzeug JSON Response。"""
    return _execute_tool_from_payload_inner(data)


def _execute_tool_from_payload_inner(data):
    """execute_tool 实现体。"""
    try:
        # 详细日志：记录请求数据
        logger.info(f"[DEBUG] /api/tools/execute 收到请求 - data: {data}")
        
        if not data:
            logger.error(f"[DEBUG] /api/tools/execute 请求数据为空")
            return _j({"success": False, "message": "未收到数据"}, 400)
        
        tool_id = data.get('tool_id')
        action = _normalize_action(data.get('action', 'view'), data.get('params') or {})
        params = data.get('params') or {}

        valid, err_msg = _validate_required_params(str(tool_id or "").strip(), action, params)
        if not valid:
            return _j({
                "success": False,
                "error_code": "missing_required_params",
                "message": err_msg,
            }, 400)

        # 新版统一 dispatcher：优先处理注册表中的工作流动作
        registry = get_workflow_tool_registry()
        if tool_id in registry and action in registry[tool_id].get("actions", {}):
            routed = execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
            status_code = 200 if routed.get("success") else 400
            return _j(routed, status_code)
        
        # 记录关键参数
        logger.info(f"[DEBUG] tool_id={tool_id}, action={action}, params_keys={list(params.keys())}")
        if 'order_text' in params:
            logger.info(f"[DEBUG] order_text={params.get('order_text')[:200] if params.get('order_text') else None}")
        
        return dispatch_legacy_tool_payload(
            tool_id,
            action,
            params,
            json_response_fn=_j,
            hdr_getter=_hdr,
            parse_order_text_fn=_parse_order_text,
        )
        
    except Exception as e:
        logger.error(f"执行工具失败: {e}")
        return _j({"success": False, "message": str(e)}, 500)
