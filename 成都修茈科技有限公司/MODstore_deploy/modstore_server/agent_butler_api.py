# isort: skip_file
# ruff: noqa: E402, F401
"""AI 数字管家 Butler — 专用后端 API。

提供：
- POST /api/agent/butler/chat        非流式对话（透传到 LLM + 注入 system prompt + tool schemas）
- POST /api/agent/butler/chat/stream SSE 流式版本
- POST /api/agent/butler/actions     操作审计落库
- GET  /api/agent/butler/skills      查询 butler 类型技能列表
- PATCH /api/agent/butler/skills/:id 更新技能激活状态

Phase 5 TODO: evolution endpoint — 进化引擎暂不实现
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Session

from modstore_server.all_hands_report import (
    MAX_ALL_HANDS_EMPLOYEES,
    clamp_all_hands_max_employees,
)
from modstore_server.admin_employee_autonomy_helpers import _require_admin_or_internal
from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    calculate_charge,
    enforce_risk_limits,
    estimate_preauthorization,
    new_request_id,
    save_failure_log,
    save_success_log,
    usage_from_response,
)
from modstore_server.llm_chat_proxy import chat_dispatch, chat_dispatch_stream
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.market_shared import _public_contact_client_key
from modstore_server.models import (
    Base,
    ChatConversation,
    ChatMessage,
    DailyDigestRecord,
    LlmCallLog,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent/butler", tags=["butler"])

# ─── Butler 操作审计表 ─────────────────────────────────────────────────


from modstore_server.agent_butler_api_part01 import (
    ButlerAction as ButlerAction,
    _json_loads_default as _json_loads_default,
    _daily_digest_record_to_dict as _daily_digest_record_to_dict,
    butler_daily_digest_records as butler_daily_digest_records,
    butler_daily_digest_record_detail as butler_daily_digest_record_detail,
    _dd_repo_root as _dd_repo_root,
    _dd_list_dir as _dd_list_dir,
    butler_daily_digest_artifacts as butler_daily_digest_artifacts,
)

# ─── Butler system prompt + tool schemas ─────────────────────────────


BUTLER_SYSTEM_PROMPT = """你是「XC AGI 数字管家」，叫小C，是这个平台的老熟人，平时帮用户处理点杂事、指指路。

你的性格和说话方式：
- 像真人同事一样聊天，口语化、自然，别用「尊敬的用户」「您好」「竭诚为您服务」这种客服腔
- 每次回复简短，一两句话说完，不要列清单、不要分点、不要长篇大论
- 有自己的态度，热心但不当舔狗，可以吐槽可以开玩笑
- 你就是你这个人，不是 AI、不是模型、不是机器人，别暴露身份

你的核心职责：
1. 帮用户导航到任意页面（plans/ai-store/wallet/recharge/account/workbench-shell 等路由）
2. 读取当前页面内容并回答问题
3. 帮用户在 AI 市场中搜索员工
4. 引导用户完成充值、购买会员等操作（高风险操作必须让用户明确确认）
5. 主动发现并建议适合用户的功能和员工
6. 当用户在 Mod / 工作流 / 员工编辑页，且明确说要「新增」「加一个」「改」「优化」「完善」某功能时，
   调用 enhance_current_page 工具，让 vibe-coding 自动改写文件。
   brief 字段必须清晰描述要做的改动（例如"在 workflow_employees 里加一个微信群推送员工"）。
   不要替用户做不可逆决定，不要在用户没有明确意图时自动调用此工具。

可识别的编辑页路由：
- /workbench/mod/<mod_id>         → target_type=mod, target_id=<mod_id>
- /workbench/shell/workflow/<id>  → target_type=workflow, target_id=<id>
- /workbench/shell/employee/<id>  → target_type=employee, target_id=<id>

操作原则：
- 低风险（导航、读取）：直接执行
- 中风险（填写表单、点击）：展示预览，用户可取消
- 高风险（支付、删除、vibe-coding 改文件）：必须用户明确确认，不可自动执行

回复要简洁自然。如果需要执行页面操作，使用 function calling 工具。"""


BUTLER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "跳转到指定路由页面",
            "parameters": {
                "type": "object",
                "properties": {
                    "route": {
                        "type": "string",
                        "description": "路由名称或路径，如 plans/ai-store/wallet/recharge/account/workbench-shell",
                    },
                    "query": {
                        "type": "object",
                        "description": "URL query 参数（可选）",
                    },
                },
                "required": ["route"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "点击页面上的按钮或链接（中风险，需用户确认）",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "按钮文字或 aria-label"},
                    "selector": {"type": "string", "description": "CSS 选择器（可选）"},
                },
                "required": ["label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "填写表单输入框（中风险，需用户确认）",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "输入框的 label 或 placeholder",
                    },
                    "value": {"type": "string", "description": "要填入的值"},
                },
                "required": ["label", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "滚动页面",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "top", "bottom"],
                    },
                    "px": {"type": "integer", "description": "滚动像素（可选）"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取并返回当前页面内容摘要",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enhance_current_page",
            "description": (
                "用 vibe-coding 自动改写用户当前正在编辑的 Mod / 工作流 / 员工。"
                "仅在用户明确说要新增/优化/修改某个功能时使用，不用于纯导航或读取页面。"
                "执行前会向用户展示高风险确认，用户同意后才开始改写。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {
                        "type": "string",
                        "description": "要做的改动的清晰描述，例如 '在 manifest.workflow_employees 中加一个会员推送员工'",
                    },
                    "scope": {
                        "type": "string",
                        "enum": [
                            "auto",
                            "manifest",
                            "backend",
                            "frontend",
                            "workflow_graph",
                            "employee_prompt",
                        ],
                        "description": "可选，限定改动范围；不确定时写 auto",
                    },
                },
                "required": ["brief"],
            },
        },
    },
]

# 管理端 is_admin 会话：本人只读 + 运维更新推送（服务端执行，不回前端 click）
ADMIN_READONLY_TOOL_NAMES = frozenset(
    {
        "get_my_account_snapshot",
        "get_my_wallet",
        "get_my_orders",
        "get_my_tickets",
        "get_ops_update_brief",
    }
)

ADMIN_READONLY_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_account_snapshot",
            "description": "读取当前登录管理员本人的账户快照（称呼/角色/会员档/套餐），仅本人",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_wallet",
            "description": "读取当前用户本人钱包余额与最近几笔流水摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最近流水条数，默认 5，最大 20",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_orders",
            "description": "读取当前用户本人最近支付订单列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "条数，默认 8，最大 20",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_tickets",
            "description": "读取当前用户本人客服工单（即使管理员也不返回他人工单）",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "条数，默认 8，最大 20",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ops_update_brief",
            "description": "运维更新推送：最近日更摘要 + release_train 版本快照（只读）",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "日更条数，默认 3，最大 5",
                    }
                },
            },
        },
    },
]


from modstore_server.agent_butler_api_part02 import (
    _butler_tools_for_user as _butler_tools_for_user,
    _clip_tool_text as _clip_tool_text,
    _execute_admin_readonly_tool as _execute_admin_readonly_tool,
    _partition_butler_tool_calls as _partition_butler_tool_calls,
    ButlerMessageDTO as ButlerMessageDTO,
    ButlerChatDTO as ButlerChatDTO,
    CorpChatDTO as CorpChatDTO,
    CorpTtsDTO as CorpTtsDTO,
    CorpTranslateDTO as CorpTranslateDTO,
)

CORP_BUTLER_SYSTEM_PROMPT = """你是成都修茈科技有限公司官网的「AI 管家」，叫小C，平时在这边帮忙接待访客。

你的性格和说话方式：
- 像真人前台一样聊天，口语化、自然，别用「尊敬的用户」「您好」「竭诚为您服务」这种客服腔
- 每次回复简短，一两句话说完，不要列清单、不要分点、不要长篇大论
- 有自己的态度，热情但不谄媚，可以 casual 地介绍公司
- 你就是你这个人，不是 AI、不是模型、不是机器人，别暴露身份

你能做的事：
- 介绍修茈科技的产品（AI Excel 单据识别、标签打印、MODstore 智能体市场、XCAGI 工作台等）
- 引导用户去产品中心、解决方案、客户案例、联系我们、AI 市场（/market/）
- 价格/报价问题说明需根据场景定制，引导填写联系表单或登录 AI 市场查看会员方案

限制：
- 不要假装能操作用户浏览器、不要执行跳转/点击/填表等工具
- 不要编造具体合同金额或未公示的资质证照
- 回复控制在 200 字以内
- 可提供相对路径链接，如 /contact.html、/services.html、/market/"""


_CORP_CHAT_TIMES: Dict[str, List[float]] = defaultdict(list)
_CORP_CHAT_WINDOW_SEC = int(os.environ.get("BUTLER_CORP_RATE_WINDOW_SEC", "60"))
_CORP_CHAT_LIMIT = int(os.environ.get("BUTLER_CORP_RATE_LIMIT", "12"))


from modstore_server.agent_butler_api_part03 import (
    ButlerActionDTO as ButlerActionDTO,
    ButlerSkillActiveDTO as ButlerSkillActiveDTO,
    _resolve_butler_credentials as _resolve_butler_credentials,
    _build_messages as _build_messages,
    _corp_chat_rate_allow as _corp_chat_rate_allow,
    _resolve_corp_credentials as _resolve_corp_credentials,
    _build_corp_messages as _build_corp_messages,
    _get_or_create_conversation as _get_or_create_conversation,
    CsSsotRetrieveDTO as CsSsotRetrieveDTO,
    butler_cs_ssot_policy as butler_cs_ssot_policy,
    butler_cs_ssot_retrieve as butler_cs_ssot_retrieve,
    butler_corp_chat as butler_corp_chat,
    butler_corp_translate as butler_corp_translate,
    butler_corp_tts as butler_corp_tts,
)

# ─── 联系页问卷智能预填 ─────────────────────────────────────────────────

_INTAKE_USER_ROLES = frozenset(
    {"企业负责人", "业务或销售", "运营或行政", "财务", "IT或技术", "其他"}
)
_INTAKE_PRIMARY_GOALS = frozenset(
    {"重复录入太累", "经常出错", "太慢跟不上", "系统各干各的", "想先小试点"}
)
_INTAKE_DIRECTIONS = frozenset(
    {"少做表格单据", "流程更顺", "上AI助手", "和现有系统打通"}
)
_INTAKE_TIMELINES = frozenset({"2 周内", "1 个月内", "1–3 个月", "季度内", "先评估"})
_INTAKE_BUDGETS = frozenset(
    {
        "1–5 万",
        "5–10 万",
        "10–50 万",
        "50–100 万",
        "5 万以内",
        "5–20 万",
        "20–50 万",
        "50 万以上",
    }
)
_INTAKE_NEED_INTEGRATION = frozenset({"yes", "no"})

_INTAKE_TEXT_LIMITS: Dict[str, int] = {
    "industry": 128,
    "roleSummary": 2000,
    "manualSteps": 4000,
    "painGoals": 2000,
    "sampleDesc": 1000,
    "name": 128,
    "phone": 64,
    "email": 256,
    "company": 256,
    "integrationNote": 500,
    "extraNote": 2000,
}


from modstore_server.agent_butler_api_part04 import (
    CorpIntakeFillDTO as CorpIntakeFillDTO,
)

CORP_INTAKE_FILL_SYSTEM_PROMPT = """你是成都修茈科技官网联系页「需求小问卷」填表助手。

根据用户自然语言描述，输出 JSON（不要 markdown 代码块），格式严格为：
{"reply": "给用户的中文说明（80字内）", "draft": { ... }}

draft 字段名与含义（不确定则省略，禁止编造手机/邮箱/姓名）：
- userRole: 单选，必须从以下取值之一：企业负责人、业务或销售、运营或行政、财务、IT或技术、其他
- industry, roleSummary: 文本
- primaryGoal: 单选：重复录入太累、经常出错、太慢跟不上、系统各干各的、想先小试点
- directions: 字符串数组，每项只能是：少做表格单据、流程更顺、上AI助手、和现有系统打通
- manualSteps, painGoals, sampleDesc: 文本
- name, phone, email, company: 仅当用户明确提供时才填写
- timeline: 2 周内、1 个月内、1–3 个月、季度内、先评估
- budget: 1–5 万、5–10 万、10–50 万、50–100 万
- needIntegration: yes 或 no
- integrationNote, extraNote: 文本

若用户仅提供「公司名称 + 系统/业务类型」，请结合该行业与系统的典型场景推断岗位、流程、痛点与改善方向，尽量填满可推断字段；company 使用用户给出的公司名。禁止编造手机、邮箱、姓名。

禁止输出分析、推理过程或 markdown；回复必须是单个 JSON 对象，首字符为 {，末字符为 }。"""


from modstore_server.agent_butler_api_part05 import (
    _clip_text as _clip_text,
    _validate_intake_draft as _validate_intake_draft,
    _parse_intake_llm_json as _parse_intake_llm_json,
    butler_corp_intake_fill as butler_corp_intake_fill,
    butler_chat as butler_chat,
    butler_chat_stream as butler_chat_stream,
    record_butler_action as record_butler_action,
    list_butler_skills as list_butler_skills,
    update_butler_skill_active as update_butler_skill_active,
)

# ─── Butler Orchestrate ────────────────────────────────────────────────

from modstore_server.agent_butler_orchestrate import (  # noqa: E402
    ButlerOrchestrateBody as _ButlerOrchestrateBody,
)
from modstore_server.agent_butler_orchestrate import (
    _butler_orchestrate_steps,
    _run_butler_orchestrate_pipeline,
)


from modstore_server.agent_butler_api_part06 import (
    butler_orchestrate as butler_orchestrate,
    _safe_json as _safe_json,
    AllHandsReportDTO as AllHandsReportDTO,
    _all_hands_session_steps as _all_hands_session_steps,
    _run_all_hands_report_session as _run_all_hands_report_session,
    butler_all_hands_report_session_start as butler_all_hands_report_session_start,
    butler_all_hands_report as butler_all_hands_report,
    DigestVibePrepDTO as DigestVibePrepDTO,
    _vibe_prep_session_steps as _vibe_prep_session_steps,
    _run_digest_vibe_prep_session as _run_digest_vibe_prep_session,
    DigestLineExecuteDTO as DigestLineExecuteDTO,
    butler_digest_line_execute as butler_digest_line_execute,
    butler_digest_vibe_prep_session_start as butler_digest_vibe_prep_session_start,
)

# Phase 5 TODO: evolution endpoint
# def butler_evolution_detect(): ...
# def butler_evolution_generate(): ...
# def butler_evolution_register(): ...
