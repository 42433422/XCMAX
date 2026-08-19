# ruff: noqa: E402, F401
"""独立 AI 客服编排层。

对话优先：寒暄 / 一般咨询只回复不建单；规则 + LLM 识别意图后，
仅在用户明确升级（提交工单/转人工等），或业务材料已齐可自动受理时建单。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server import custom_delivery_incident_policy as delivery_policy
from modstore_server.customer_service_tools import (
    audit,
    build_action,
    enqueue_customer_service_event,
    execute_action,
    execute_matching_integrations,
    json_dumps,
    json_loads,
)
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceDecision,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)

ORDER_RE = re.compile(r"(?:订单号|order[_ -]?no|订单)[:：\s]*([A-Za-z0-9_-]{6,64})", re.I)
CATALOG_RE = re.compile(r"(?:商品\s*ID|catalog[_ -]?id|商品)[:：\s#]*([0-9]{1,12})", re.I)
LLM_PROVIDER_RE = re.compile(r"(?:厂商|provider)\s*[:：]\s*([a-z0-9_-]+)", re.I)
LLM_MODEL_RE = re.compile(r"(?:模型|model)\s*[:：]\s*(\S+)", re.I)
LLM_SLASH_RE = re.compile(r"\b([a-z0-9_-]{2,32})\s*/\s*([^\s,，。]{1,120})", re.I)
GREETING_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|hey|在吗|早上好|上午好|下午好|晚上好|你好呀|您好呀)"
    r"[!！。.?？~\s]*$",
    re.I,
)
ESCALATE_RE = re.compile(
    r"转人工|人工客服|提交工单|创建工单|升级处理|要工单|找人工|处理不了|没解决",
)
TICKET_INTENTS = frozenset(
    {"refund", "catalog_complaint", "catalog_review", "account_support", "llm_extension"}
)
KNOWN_INTENTS = frozenset(
    {
        "greeting",
        "general",
        "product_issue",
        "refund",
        "catalog_complaint",
        "catalog_review",
        "account_support",
        "llm_extension",
    }
)
# 无自动办结动作、只登记跟进的意图
FOLLOWUP_INTENTS = frozenset({"general", "greeting", "account_support", "product_issue"})
# 问题归属：平台宿主 / 市场上架软件 / 账号定制线（宿主入门第三步定制 Mod/员工）
ISSUE_DOMAINS = frozenset({"platform", "software", "custom"})
ISSUE_DOMAIN_LABELS = {
    "platform": "平台",
    "software": "软件",
    "custom": "客户定制",
}


from modstore_server.customer_service_orchestrator_part01 import (
    _parse_domain_clarify_reply as _parse_domain_clarify_reply,
)


_INTENT_CLASSIFY_PROMPT = """你是 MODstore 客服意图分类器。只根据语义判断，不要死磕关键词。
只输出一行 JSON，不要其它文字、不要解释、不要思考过程。
字段：intent, need_ticket, confidence, reason, issue_domain。
intent 只能是：greeting|general|product_issue|refund|catalog_complaint|catalog_review|account_support|llm_extension。
issue_domain 只能是：platform|software|custom（仅故障/投诉类需要；闲聊可省略或填 platform）。
规则：
- 寒暄/闲聊 → greeting，need_ticket=false
- 界面/显示/功能故障、看不清/看不见、打不开、报错、白屏、按钮无效、主题/模式显示异常等产品缺陷反馈 → product_issue，need_ticket=false（除非用户明确要求提交工单/转人工）
- 商品抄袭/侵权/无法下载等商品侧投诉 → catalog_complaint
- 怎么买、会员权益、报价、使用方法等非故障咨询 → general，need_ticket=false
- 退款 → refund；上架/合规审核 → catalog_review；余额/权益未到账 → account_support；申请开通新模型 → llm_extension
- 用户明确要转人工或提交工单 → need_ticket=true（intent 仍按问题内容选，不要因为「提交工单」四字就改成 general）
issue_domain：
- platform：干净宿主本身（主题/登录/会员/钱包/通用壳/对话）
- software：市场上架的通用 Mod/员工包/商品（有具体商品或软件名）
- custom：客户定制线——账号绑定的定制功能 Mod 或定制员工（宿主入门第三步定制线交付，非公开市场上架）
confidence 为 0~1。"""


from modstore_server.customer_service_orchestrator_part02 import (
    _enrich_cs_context as _enrich_cs_context,
    ensure_session as ensure_session,
    handle_customer_message as handle_customer_message,
    extract_fields as extract_fields,
    is_greeting as is_greeting,
    wants_ticket_escalation as wants_ticket_escalation,
    should_create_ticket as should_create_ticket,
    infer_intent as infer_intent,
    classify_customer_intent as classify_customer_intent,
    _parse_intent_json as _parse_intent_json,
    _llm_classify_intent as _llm_classify_intent,
    _chat_only_reply as _chat_only_reply,
)


from modstore_server.customer_service_orchestrator_part03 import (
    choose_standard as choose_standard,
    ensure_ticket as ensure_ticket,
    decide as decide,
    missing_fields as missing_fields,
    humanize_field_names as humanize_field_names,
    _attach_image_to_ticket as _attach_image_to_ticket,
    plan_actions as plan_actions,
    _maybe_dispatch_employee_followup as _maybe_dispatch_employee_followup,
)


_RAW_STRUCTURE_RE = re.compile(
    r"(\(hybrid\)|\[hybrid\]|template_name|template_scope|\"fields\"\s*:|\{[\"']fields)",
    re.I,
)


from modstore_server.customer_service_orchestrator_part04 import (
    _looks_like_raw_kb_line as _looks_like_raw_kb_line,
    _human_kb_tips as _human_kb_tips,
    _display_name_for_user as _display_name_for_user,
    _summarize_user_issue as _summarize_user_issue,
    _looks_like_forbidden_privilege_request as _looks_like_forbidden_privilege_request,
    _refuse_forbidden_privilege_reply as _refuse_forbidden_privilege_reply,
    _looks_like_product_issue as _looks_like_product_issue,
    _looks_like_concrete_issue as _looks_like_concrete_issue,
    _ack_concrete_issue_reply as _ack_concrete_issue_reply,
    _xiaoc_general_reply as _xiaoc_general_reply,
    build_reply as build_reply,
    resolve_issue_domain as resolve_issue_domain,
    title_for_intent as title_for_intent,
    _is_escalate_only as _is_escalate_only,
    _peek_prior_user_issue as _peek_prior_user_issue,
    _resolve_issue_text_for_reply as _resolve_issue_text_for_reply,
    _enrich_extracted_from_prior_issue as _enrich_extracted_from_prior_issue,
    subject_type_for_intent as subject_type_for_intent,
    session_payload as session_payload,
)


TICKET_LIFECYCLE_STEPS: tuple[tuple[int, str], ...] = (
    (1, "已收到"),
    (2, "处理中"),
    (3, "有结果"),
    (4, "待补充"),
    (5, "已完成"),
)


from modstore_server.customer_service_orchestrator_part05 import (
    ticket_lifecycle_stage as ticket_lifecycle_stage,
    _summarize_incident_team_rows as _summarize_incident_team_rows,
    apply_customer_ticket_incident_progress as apply_customer_ticket_incident_progress,
    ticket_lifecycle_payload as ticket_lifecycle_payload,
    ticket_payload as ticket_payload,
    decision_payload as decision_payload,
    action_payload as action_payload,
)
