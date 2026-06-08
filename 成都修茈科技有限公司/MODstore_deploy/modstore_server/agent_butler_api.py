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

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Session

from modstore_server.all_hands_report import MAX_ALL_HANDS_EMPLOYEES, clamp_all_hands_max_employees
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


class ButlerAction(Base):
    """管家操作审计记录。"""

    __tablename__ = "butler_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    route = Column(String(512), default="")
    action = Column(String(64), nullable=False, index=True)
    args_json = Column(Text, default="{}")
    risk = Column(String(16), default="low")
    status = Column(String(16), default="success", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def _json_loads_default(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return default


def _daily_digest_record_to_dict(
    row: DailyDigestRecord, *, include_body: bool = False
) -> Dict[str, Any]:
    vibe_meta: Dict[str, Any] = {}
    line_dispatch: Dict[str, Any] = {}
    line_execute: Dict[str, Any] = {}
    try:
        raw_meta = getattr(row, "vibe_prep_meta_json", "") or ""
        if raw_meta.strip().startswith("{"):
            vibe_meta = json.loads(raw_meta)
    except Exception:
        vibe_meta = {}
    try:
        raw_dispatch = getattr(row, "vibe_prep_line_dispatch_json", "") or ""
        if raw_dispatch.strip().startswith("{"):
            line_dispatch = json.loads(raw_dispatch)
    except Exception:
        line_dispatch = {}
    try:
        raw_exec = getattr(row, "vibe_line_execute_json", "") or ""
        if raw_exec.strip().startswith("{"):
            line_execute = json.loads(raw_exec)
    except Exception:
        line_execute = {}
    data: Dict[str, Any] = {
        "id": row.id,
        "day": row.day,
        "subject": row.subject,
        "body_text": row.body_text,
        "meeting_minutes_html": row.meeting_minutes_html,
        "vibe_prep_updates_md": getattr(row, "vibe_prep_updates_md", "") or "",
        "vibe_prep_patches_md": getattr(row, "vibe_prep_patches_md", "") or "",
        "vibe_prep_pw_md": getattr(row, "vibe_prep_pw_md", "") or "",
        "vibe_prep_ps_md": getattr(row, "vibe_prep_ps_md", "") or "",
        "vibe_prep_app_md": getattr(row, "vibe_prep_app_md", "") or "",
        "vibe_prep_sr_md": getattr(row, "vibe_prep_sr_md", "") or "",
        "vibe_prep_meta": vibe_meta,
        "vibe_prep_line_dispatch": line_dispatch,
        "vibe_line_execute": line_execute,
        "recipients": _json_loads_default(row.recipients_json, []),
        "delivery": _json_loads_default(row.delivery_json, []),
        "delivered": bool(row.delivered),
        "source": row.source,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else "",
    }
    if include_body:
        data["body_html"] = row.body_html
    return data


@router.get("/daily-digests")
async def butler_daily_digest_records(
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """列出服务器已落库的每日摘要邮件副本（管理员）。"""
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可查看每日摘要记录")
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, int(offset or 0))
    rows = (
        db.query(DailyDigestRecord)
        .order_by(DailyDigestRecord.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )
    total = db.query(DailyDigestRecord.id).count()
    return {
        "success": True,
        "data": [_daily_digest_record_to_dict(row, include_body=False) for row in rows],
        "total": total,
    }


@router.get("/daily-digests/{record_id}")
async def butler_daily_digest_record_detail(
    record_id: int,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """读取单条每日摘要完整 HTML 副本（管理员）。"""
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可查看每日摘要记录")
    row = db.get(DailyDigestRecord, record_id)
    if row is None:
        raise HTTPException(404, "每日摘要记录不存在")
    return {"success": True, "data": _daily_digest_record_to_dict(row, include_body=True)}


def _dd_repo_root():
    import os as _os
    from pathlib import Path as _Path

    mono = (
        _os.environ.get("XCMAX_MONOREPO_ROOT") or _os.environ.get("MODSTORE_REPO_ROOT") or ""
    ).strip()
    if mono:
        return _Path(mono).expanduser().resolve()
    return _Path(__file__).resolve().parent.parent


def _dd_list_dir(d, exts):
    import os as _os
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    out = []
    if not d:
        return out
    try:
        if not d.is_dir():
            return out
    except Exception:
        return out
    # 用 os.scandir 逐项处理，单条编码/IO 异常不影响整体（非 UTF-8 locale 下 CJK 名容错）
    try:
        entries = list(_os.scandir(str(d)))
    except Exception:
        return out
    for ent in entries:
        try:
            name = ent.name  # surrogateescape 可能存在，json 时再兜底
            suffix = _os.path.splitext(name)[1].lower()
            if not ent.is_file() or (exts and suffix not in exts):
                continue
            st = ent.stat()
            out.append(
                {
                    "name": name.encode("utf-8", "replace").decode("utf-8"),
                    "path": str(d / name).encode("utf-8", "replace").decode("utf-8"),
                    "bytes": st.st_size,
                    "mtime": _dt.fromtimestamp(st.st_mtime, _tz.utc).isoformat(),
                }
            )
        except Exception:
            continue
    out.sort(key=lambda x: x["name"])
    return out


@router.get("/daily-digests/{record_id}/artifacts")
async def butler_daily_digest_artifacts(
    record_id: int,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """日更闭环各阶段「结果文件」清单：截图 PNG / PPT / digest HTML / 会议 / Vibe MD / release_train 历史 / 容灾备份。"""
    import os as _os

    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可查看阶段结果文件")
    row = db.get(DailyDigestRecord, record_id)
    if row is None:
        raise HTTPException(404, "每日摘要记录不存在")

    day = str(getattr(row, "day", "") or "")
    repo = _dd_repo_root()
    stages = []

    # SW/SS/SA — 三端截图 PNG（复用 surface_audit 自身的 _save_dir，路径口径一致）
    try:
        from modstore_server.daily_digest_surface_audit import _save_dir as _sa_save_dir

        png_dir = _sa_save_dir(day)
        pngs = _dd_list_dir(png_dir, {".png", ".jpg", ".jpeg", ".webp"})
        stages.append(
            {
                "node": "SW/SS/SA",
                "label": "三端截图巡检",
                "kind": "image_dir",
                "dir": str(png_dir) if png_dir else "",
                "count": len(pngs),
                "files": pngs,
            }
        )
    except Exception as exc:  # noqa: BLE001
        stages.append({"node": "SW/SS/SA", "label": "三端截图巡检", "error": str(exc)[:200]})

    # PPTX — 三端 PPT（复用 surface_ppt 自身的 _save_dir）
    try:
        from modstore_server.daily_digest_surface_ppt import _save_dir as _pp_save_dir

        ppt_dir = _pp_save_dir(day)
        ppts = _dd_list_dir(ppt_dir, {".pptx"})
        stages.append(
            {
                "node": "PPTX",
                "label": "三端→PPT 附件",
                "kind": "file_dir",
                "dir": str(ppt_dir),
                "count": len(ppts),
                "files": ppts,
            }
        )
    except Exception as exc:  # noqa: BLE001
        stages.append({"node": "PPTX", "label": "三端→PPT 附件", "error": str(exc)[:200]})

    # M — 会议摘要
    stages.append(
        {
            "node": "M",
            "label": "员工大会→会议摘要",
            "kind": "html_field",
            "bytes": len(getattr(row, "meeting_minutes_html", "") or ""),
        }
    )

    # ASM/P — digest HTML 落库
    stages.append(
        {
            "node": "ASM/P",
            "label": "拼装 digest HTML + 落库",
            "kind": "db_record",
            "subject": getattr(row, "subject", ""),
            "delivered": bool(getattr(row, "delivered", False)),
            "body_html_bytes": len(getattr(row, "body_html", "") or ""),
            "body_text_bytes": len(getattr(row, "body_text", "") or ""),
            "detail_api": f"/api/agent/butler/daily-digests/{record_id}",
        }
    )

    # CENT/MAJ/V/L — Vibe 预备 + 产线拆分 MD
    vibe_fields = [
        ("vibe_prep_updates_md", "更新清单"),
        ("vibe_prep_patches_md", "补丁清单"),
        ("vibe_prep_pw_md", "P-W 产线"),
        ("vibe_prep_ps_md", "P-S 产线"),
        ("vibe_prep_sr_md", "S-R 产线"),
        ("vibe_prep_app_md", "P-App 产线"),
    ]
    stages.append(
        {
            "node": "V/L",
            "label": "Vibe 预备 + 四产线拆分",
            "kind": "md_fields",
            "fields": [
                {"field": f, "label": lbl, "bytes": len(getattr(row, f, "") or "")}
                for f, lbl in vibe_fields
            ],
        }
    )

    # RT — release_train 历史
    try:
        from modstore_server.release_train import list_release_train_history, snapshot_public

        stages.append(
            {
                "node": "RT",
                "label": "release_train 四段 + 历史快照",
                "kind": "release_train",
                "before": getattr(row, "release_train_before", ""),
                "after": getattr(row, "release_train_after", ""),
                "release_kind": getattr(row, "release_kind", ""),
                "snapshot": snapshot_public(),
                "history": list_release_train_history(limit=20),
            }
        )
    except Exception as exc:  # noqa: BLE001
        stages.append(
            {"node": "RT", "label": "release_train 四段 + 历史快照", "error": str(exc)[:200]}
        )

    # DR — 容灾备份
    try:
        from modstore_server.daily_backup_job import list_backups

        backups = list_backups(limit=20)
        stages.append(
            {
                "node": "DR",
                "label": "容灾备份（DB + release_train）",
                "kind": "backup_dir",
                "count": len(backups),
                "files": backups,
            }
        )
    except Exception as exc:  # noqa: BLE001
        stages.append({"node": "DR", "label": "容灾备份", "error": str(exc)[:200]})

    return {"success": True, "data": {"record_id": record_id, "day": day, "stages": stages}}


# ─── Butler system prompt + tool schemas ─────────────────────────────


BUTLER_SYSTEM_PROMPT = """你是「XC AGI 数字管家」—— 这个平台的专属 AI 助手，不是用户购买的 AI 员工。

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

回复要简洁友好，不要过多解释。如果需要执行页面操作，使用 function calling 工具。"""


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
                    "query": {"type": "object", "description": "URL query 参数（可选）"},
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
                    "label": {"type": "string", "description": "输入框的 label 或 placeholder"},
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
                    "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]},
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


# ─── 请求/响应模型 ─────────────────────────────────────────────────────


class ButlerMessageDTO(BaseModel):
    role: str
    content: Any  # str 或 list（含图片的多模态）


class ButlerChatDTO(BaseModel):
    messages: List[ButlerMessageDTO]
    conversation_id: Optional[int] = None
    page_context: Optional[str] = Field(None, max_length=4000)
    max_tokens: Optional[int] = Field(None, ge=1, le=8000)


class CorpChatDTO(BaseModel):
    messages: List[ButlerMessageDTO]
    page_id: Optional[str] = Field(None, max_length=64)
    page_context: Optional[str] = Field(None, max_length=3500)
    max_tokens: Optional[int] = Field(512, ge=1, le=2000)


CORP_BUTLER_SYSTEM_PROMPT = """你是成都修茈科技有限公司官网的「AI 管家」咨询助手（官网咨询助手）。

你的职责：
1. 用简洁中文介绍修茈科技的产品与解决方案（AI Excel 单据识别、标签打印、MODstore 智能体市场、XCAGI 工作台等）
2. 引导用户访问对应页面：产品中心、解决方案、客户案例、联系我们、AI 市场（/market/）
3. 回答价格/报价时说明需根据场景定制，引导填写联系表单或登录 AI 市场查看会员方案

限制：
- 不要假装能操作用户浏览器、不要执行跳转/点击/填表等工具
- 不要编造具体合同金额或未公示的资质证照
- 回复控制在 200 字以内，友好专业
- 可提供相对路径链接，如 /contact.html、/services.html、/market/"""


_CORP_CHAT_TIMES: Dict[str, List[float]] = defaultdict(list)
_CORP_CHAT_WINDOW_SEC = int(os.environ.get("BUTLER_CORP_RATE_WINDOW_SEC", "60"))
_CORP_CHAT_LIMIT = int(os.environ.get("BUTLER_CORP_RATE_LIMIT", "12"))


class ButlerActionDTO(BaseModel):
    route: str = ""
    action: str
    args: Optional[Dict[str, Any]] = None
    risk: str = "low"
    status: str = "success"


class ButlerSkillActiveDTO(BaseModel):
    is_active: bool


# ─── 工具函数 ─────────────────────────────────────────────────────────


def _resolve_butler_credentials(db: Session, user_id: int):
    """解析管家使用的 LLM 凭证（复用用户默认偏好）。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "用户不存在")

    prefs: Dict[str, Any] = {}
    raw = getattr(user, "default_llm_json", None) or ""
    if raw.strip():
        try:
            prefs = json.loads(raw)
        except Exception:
            pass

    provider = str(prefs.get("provider") or "").strip()
    model = str(prefs.get("model") or "").strip()

    if not provider or provider not in KNOWN_PROVIDERS:
        # 自动选第一个可用 provider
        for p in KNOWN_PROVIDERS:
            key, _ = resolve_api_key(db, user_id, p)
            if key:
                provider = p
                break
        if not provider:
            raise HTTPException(
                400,
                "未配置可用的 LLM 供应商。请在账户页面 → LLM 设置中配置 API Key，或联系管理员。",
            )

    if not model:
        model = "gpt-4o-mini"  # 合理的多模态默认

    api_key, key_source = resolve_api_key(db, user_id, provider)
    if not api_key:
        raise HTTPException(
            400,
            f"供应商「{provider}」未配置可用 API Key。请在账户页面绑定 API Key。",
        )

    base_url = (
        resolve_base_url(db, user_id, provider)
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    return provider, model, api_key, key_source, base_url


def _build_messages(body: ButlerChatDTO, page_context: str | None) -> List[Dict[str, Any]]:
    """组装最终 messages，注入 system prompt 和页面上下文。"""
    system_content = BUTLER_SYSTEM_PROMPT
    if page_context:
        system_content += f"\n\n当前页面上下文：\n{page_context}"

    msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
    for m in body.messages:
        if m.role == "system":
            continue  # 客户端的 system msg 已合并
        msgs.append({"role": m.role, "content": m.content})
    return msgs


def _corp_chat_rate_allow(client_key: str) -> None:
    now = time.time()
    cutoff = now - _CORP_CHAT_WINDOW_SEC
    bucket = _CORP_CHAT_TIMES[client_key]
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= _CORP_CHAT_LIMIT:
        raise HTTPException(status_code=429, detail="咨询过于频繁，请稍后再试")
    bucket.append(now)


def _resolve_corp_credentials(db: Session):
    """官网公开咨询 LLM 凭证（环境变量或指定系统用户）。"""
    provider = (os.environ.get("BUTLER_CORP_PROVIDER") or "").strip()
    model = (os.environ.get("BUTLER_CORP_MODEL") or "gpt-4o-mini").strip()
    api_key = (os.environ.get("BUTLER_CORP_API_KEY") or "").strip()
    base_url = None

    user_id_raw = (os.environ.get("BUTLER_CORP_USER_ID") or "").strip()
    if not api_key and user_id_raw.isdigit():
        uid = int(user_id_raw)
        if not provider:
            for p in KNOWN_PROVIDERS:
                key, _ = resolve_api_key(db, uid, p)
                if key:
                    provider = p
                    break
        if provider:
            api_key, _ = resolve_api_key(db, uid, provider)
            if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
                base_url = resolve_base_url(db, uid, provider)

    if not provider:
        for p in KNOWN_PROVIDERS:
            if os.environ.get(f"BUTLER_CORP_API_KEY_{p.upper()}"):
                provider = p
                api_key = os.environ.get(f"BUTLER_CORP_API_KEY_{p.upper()}", "").strip()
                break
        if not provider:
            provider = "openai"

    if not api_key:
        qq_key = (os.environ.get("BUTLER_QQ_LLM_API_KEY") or "").strip()
        if qq_key:
            api_key = qq_key
            if not (os.environ.get("BUTLER_CORP_PROVIDER") or "").strip():
                provider = (
                    os.environ.get("BUTLER_QQ_LLM_PROVIDER") or provider or "openai"
                ).strip()
            if not (os.environ.get("BUTLER_CORP_MODEL") or "").strip():
                qq_model = (os.environ.get("BUTLER_QQ_LLM_MODEL") or "").strip()
                if qq_model:
                    model = qq_model
            if base_url is None:
                qq_base = (os.environ.get("BUTLER_QQ_LLM_BASE_URL") or "").strip()
                if qq_base:
                    base_url = qq_base

    if not api_key:
        raise HTTPException(
            503,
            "官网咨询助手暂不可用，请通过联系我们页留言或稍后再试。",
        )

    if base_url is None and provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        base_url = (
            resolve_base_url(db, int(user_id_raw), provider) if user_id_raw.isdigit() else None
        )

    return provider, model, api_key, base_url


def _build_corp_messages(body: CorpChatDTO) -> List[Dict[str, Any]]:
    system_content = CORP_BUTLER_SYSTEM_PROMPT
    if body.page_context:
        system_content += (
            f"\n\n当前页面（{body.page_id or 'unknown'}）上下文：\n{body.page_context[:3500]}"
        )
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
    for m in body.messages:
        if m.role == "system":
            continue
        msgs.append({"role": m.role, "content": m.content})
    return msgs


def _get_or_create_conversation(
    db: Session, user_id: int, conversation_id: int | None, provider: str, model: str
) -> ChatConversation:
    if conversation_id:
        conv = (
            db.query(ChatConversation)
            .filter(ChatConversation.id == conversation_id, ChatConversation.user_id == user_id)
            .first()
        )
        if conv:
            return conv
    conv = ChatConversation(
        user_id=user_id,
        title="数字管家对话",
        provider=provider,
        model=model,
    )
    db.add(conv)
    db.flush()
    return conv


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.post("/corp-chat")
async def butler_corp_chat(
    request: Request,
    body: CorpChatDTO,
    db: Session = Depends(get_db),
):
    """官网公开咨询（无登录、无钱包扣费、无工具调用）。"""
    _corp_chat_rate_allow(_public_contact_client_key(request))
    provider, model, api_key, base_url = _resolve_corp_credentials(db)
    msgs = _build_corp_messages(body)
    if not any(m.get("role") == "user" for m in msgs):
        raise HTTPException(400, "messages 须包含至少一条 user 消息")

    try:
        raw_response = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=msgs,
            max_tokens=body.max_tokens or 512,
        )
        if not raw_response.get("ok"):
            raise RuntimeError(raw_response.get("error") or "corp-chat failed")
        text = (raw_response.get("content") or "").strip()
    except Exception as exc:
        logger.warning("corp-chat LLM failed: %s", exc)
        raise HTTPException(503, "暂时无法回答，请通过联系我们页留言。") from exc

    if not text:
        text = (
            "抱歉，我暂时无法回答这个问题。您可浏览产品中心 /services.html 或留言 /contact.html。"
        )

    return {"success": True, "content": text, "message": text}


# ─── 联系页问卷智能预填 ─────────────────────────────────────────────────

_INTAKE_USER_ROLES = frozenset(
    {"企业负责人", "业务或销售", "运营或行政", "财务", "IT或技术", "其他"}
)
_INTAKE_PRIMARY_GOALS = frozenset(
    {"重复录入太累", "经常出错", "太慢跟不上", "系统各干各的", "想先小试点"}
)
_INTAKE_DIRECTIONS = frozenset({"少做表格单据", "流程更顺", "上AI助手", "和现有系统打通"})
_INTAKE_TIMELINES = frozenset({"2 周内", "1 个月内", "1–3 个月", "季度内", "先评估"})
_INTAKE_BUDGETS = frozenset({"5 万以内", "5–20 万", "20–50 万", "50 万以上"})
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


class CorpIntakeFillDTO(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    current_draft: Optional[Dict[str, Any]] = None
    page_summary: Optional[str] = Field(None, max_length=3500)


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
- budget: 5 万以内、5–20 万、20–50 万、50 万以上
- needIntegration: yes 或 no
- integrationNote, extraNote: 文本

若用户仅提供「公司名称 + 系统/业务类型」，请结合该行业与系统的典型场景推断岗位、流程、痛点与改善方向，尽量填满可推断字段；company 使用用户给出的公司名。禁止编造手机、邮箱、姓名。

禁止输出分析、推理过程或 markdown；回复必须是单个 JSON 对象，首字符为 {，末字符为 }。"""


def _clip_text(val: Any, max_len: int) -> str:
    s = str(val or "").strip()
    return s[:max_len] if s else ""


def _validate_intake_draft(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    if "userRole" in raw:
        v = _clip_text(raw.get("userRole"), 32)
        if v in _INTAKE_USER_ROLES:
            out["userRole"] = v
    if "primaryGoal" in raw:
        v = _clip_text(raw.get("primaryGoal"), 64)
        if v in _INTAKE_PRIMARY_GOALS:
            out["primaryGoal"] = v
    if "directions" in raw:
        dirs = raw.get("directions")
        if isinstance(dirs, list):
            cleaned = []
            for item in dirs[:8]:
                s = _clip_text(item, 64)
                if s in _INTAKE_DIRECTIONS and s not in cleaned:
                    cleaned.append(s)
            if cleaned:
                out["directions"] = cleaned
    if "timeline" in raw:
        v = _clip_text(raw.get("timeline"), 32)
        if v in _INTAKE_TIMELINES:
            out["timeline"] = v
    if "budget" in raw:
        v = _clip_text(raw.get("budget"), 32)
        if v in _INTAKE_BUDGETS:
            out["budget"] = v
    if "needIntegration" in raw:
        v = _clip_text(raw.get("needIntegration"), 8)
        if v in _INTAKE_NEED_INTEGRATION:
            out["needIntegration"] = v
    for key, max_len in _INTAKE_TEXT_LIMITS.items():
        if key in raw:
            v = _clip_text(raw.get(key), max_len)
            if v:
                out[key] = v
    return out


def _parse_intake_llm_json(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else {}
            except Exception:
                pass
    return {}


@router.post("/corp-intake-fill")
async def butler_corp_intake_fill(
    request: Request,
    body: CorpIntakeFillDTO,
    db: Session = Depends(get_db),
):
    """联系页问卷：根据用户描述生成结构化草稿（公开、限流、无工具）。"""
    _corp_chat_rate_allow(_public_contact_client_key(request))
    provider, model, api_key, base_url = _resolve_corp_credentials(db)

    draft_hint = ""
    if body.current_draft:
        try:
            draft_hint = json.dumps(body.current_draft, ensure_ascii=False)[:1500]
        except Exception:
            draft_hint = ""

    user_content = body.message.strip()
    if draft_hint:
        user_content += f"\n\n当前已填草稿（JSON）：{draft_hint}"
    if body.page_summary:
        user_content += f"\n\n页面上下文：{body.page_summary[:2000]}"

    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": CORP_INTAKE_FILL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content[:3500]},
    ]

    try:
        raw_response = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=msgs,
            max_tokens=900,
            response_format={"type": "json_object"},
            forbid_reasoning_fallback=True,
        )
        if not raw_response.get("ok"):
            raise RuntimeError(raw_response.get("error") or "corp-intake-fill failed")
        text = (raw_response.get("content") or "").strip()
    except Exception as exc:
        logger.warning("corp-intake-fill LLM failed: %s", exc)
        raise HTTPException(503, "智能预填暂不可用，请直接在左侧表单填写。") from exc

    parsed = _parse_intake_llm_json(text)
    reply = _clip_text(parsed.get("reply"), 500) or "已根据您的描述整理问卷草稿，请在左侧核对。"
    draft = _validate_intake_draft(parsed.get("draft"))
    if not draft:
        logger.warning(
            "corp-intake-fill empty draft after parse (provider=%s model=%s text_len=%s)",
            provider,
            model,
            len(text),
        )

    return {"success": True, "reply": reply, "draft": draft}


@router.post("/chat")
async def butler_chat(
    request: Request,
    body: ButlerChatDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """非流式 Butler 对话。"""
    provider, model, api_key, key_source, base_url = _resolve_butler_credentials(db, user.id)
    is_byok = key_source == "user_override"
    msgs = _build_messages(body, body.page_context)

    if not msgs:
        raise HTTPException(400, "messages 不能为空")

    request_id = new_request_id()
    enforce_risk_limits(db, user.id, provider, model, msgs, request)

    wallet = JavaWalletClient()
    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth = estimate_preauthorization(db, provider, model, msgs, body.max_tokens)
        hold = await wallet.preauthorize(
            authorization_header(request), preauth, provider, model, request_id
        )

    conv = _get_or_create_conversation(db, user.id, body.conversation_id, provider, model)

    try:
        # 尝试带 tool_choice 的 function calling
        from modstore_server.infrastructure.http_clients import get_external_client
        from modstore_server.llm_chat_proxy import _normalize_openai_base

        tool_resp = None
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            try:
                base = _normalize_openai_base(provider, base_url)
                url = f"{base}/chat/completions"
                req_body: Dict[str, Any] = {
                    "model": model,
                    "messages": msgs,
                    "tools": BUTLER_TOOLS,
                    "tool_choice": "auto",
                }
                if body.max_tokens:
                    req_body["max_tokens"] = body.max_tokens
                r = await get_external_client().post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=req_body,
                    timeout=120.0,
                )
                if r.status_code < 400:
                    tool_resp = r.json()
            except Exception as e:
                logger.warning("butler tool call failed, fallback to plain: %s", e)

        if tool_resp:
            raw_response = tool_resp
            choice0 = (tool_resp.get("choices") or [{}])[0]
            msg = choice0.get("message") or {}
            text = msg.get("content") or ""
            tool_calls_raw = msg.get("tool_calls") or []
            tool_calls = [
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "args": _safe_json(tc.get("function", {}).get("arguments", "{}")),
                }
                for tc in tool_calls_raw
            ]
            usage = tool_resp.get("usage") or {}
        else:
            raw_response = await chat_dispatch(
                provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=msgs,
                max_tokens=body.max_tokens,
            )
            if not raw_response.get("ok"):
                raise RuntimeError(raw_response.get("error") or "butler chat failed")
            text = raw_response.get("content", "")
            tool_calls = []
            usage = raw_response.get("usage") or {}

    except Exception as exc:
        await wallet.release(hold)
        save_failure_log(db, user.id, provider, model, request_id, str(exc), conv.id)
        raise HTTPException(500, f"LLM 调用失败：{exc}")

    usage_obj = usage_from_response({"usage": usage}, msgs, [text])
    charge = calculate_charge(db, provider, model, usage_obj)

    if not is_byok:
        await wallet.settle(
            hold, authorization_header(request), charge, provider, model, request_id
        )

    save_success_log(db, user.id, provider, model, request_id, usage_obj, float(charge), conv.id)

    # 保存对话记录
    db.add(
        ChatMessage(
            conversation_id=conv.id,
            user_id=user.id,
            role="assistant",
            content=text,
            provider=provider,
            model=model,
            charge_amount=float(charge),
        )
    )
    db.commit()

    return {
        "text": text,
        "tool_calls": tool_calls,
        "conversation_id": conv.id,
        "charge_amount": float(charge),
        "billed": not is_byok,
    }


@router.post("/chat/stream")
async def butler_chat_stream(
    request: Request,
    body: ButlerChatDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """SSE 流式 Butler 对话（工具调用降级为非流式）。"""
    provider, model, api_key, key_source, base_url = _resolve_butler_credentials(db, user.id)
    msgs = _build_messages(body, body.page_context)
    is_byok = key_source == "user_override"

    if not msgs:
        raise HTTPException(400, "messages 不能为空")

    request_id = new_request_id()
    enforce_risk_limits(db, user.id, provider, model, msgs, request)
    wallet = JavaWalletClient()

    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth = estimate_preauthorization(db, provider, model, msgs, body.max_tokens)
        hold = await wallet.preauthorize(
            authorization_header(request), preauth, provider, model, request_id
        )

    conv = _get_or_create_conversation(db, user.id, body.conversation_id, provider, model)

    async def event_stream():
        collected = []
        try:
            async for chunk in chat_dispatch_stream(
                provider, api_key, model, msgs, base_url=base_url, max_tokens=body.max_tokens
            ):
                if isinstance(chunk, str):
                    collected.append(chunk)
                    yield f"data: {json.dumps({'text': chunk, 'done': False}, ensure_ascii=False)}\n\n"
                elif isinstance(chunk, dict) and chunk.get("done"):
                    usage = chunk.get("usage") or {}
                    usage_obj = usage_from_response({"usage": usage}, msgs, collected)
                    charge = calculate_charge(db, provider, model, usage_obj)
                    if not is_byok:
                        await wallet.settle(
                            hold, authorization_header(request), charge, provider, model, request_id
                        )
                    full_text = "".join(collected)
                    save_success_log(
                        db, user.id, provider, model, request_id, usage_obj, float(charge), conv.id
                    )
                    db.add(
                        ChatMessage(
                            conversation_id=conv.id,
                            user_id=user.id,
                            role="assistant",
                            content=full_text,
                            provider=provider,
                            model=model,
                            charge_amount=float(charge),
                        )
                    )
                    db.commit()
                    yield f"data: {json.dumps({'text': '', 'done': True, 'conversation_id': conv.id, 'charge_amount': float(charge)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            await wallet.release(hold)
            save_failure_log(db, user.id, provider, model, request_id, str(exc), conv.id)
            yield f"data: {json.dumps({'error': str(exc), 'done': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/actions")
async def record_butler_action(
    body: ButlerActionDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """记录管家操作审计。"""
    try:
        db.add(
            ButlerAction(
                user_id=user.id,
                route=body.route or "",
                action=body.action,
                args_json=json.dumps(body.args or {}, ensure_ascii=False),
                risk=body.risk,
                status=body.status,
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("butler action log failed: %s", exc)
    return {"ok": True}


@router.get("/skills")
async def list_butler_skills(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """返回 butler 类型的 E-Skill 列表（供前端运行时加载）。"""
    try:
        from modstore_server.models import ESkill

        # ESkill 没有 kind 字段，用 domain 字段存 "butler" 作为分类
        rows = db.query(ESkill).filter(ESkill.domain == "butler").all()
        return {
            "items": [
                {
                    "id": r.id,
                    "skill_id": f"eskill_{r.id}",
                    "name": r.name,
                    "description": r.description,
                    "version": str(r.active_version),
                    "kind": "butler",
                    "trigger_keywords": [],
                    "trigger_intent": [],
                    "permission": "execute",
                    "is_active": True,
                    "usage_count": 0,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
        }
    except Exception as exc:
        logger.warning("list butler skills failed: %s", exc)
        return {"items": []}


@router.patch("/skills/{skill_id}")
async def update_butler_skill_active(
    skill_id: int,
    body: ButlerSkillActiveDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """更新 butler 技能激活状态（管理员操作）。"""
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可操作")
    try:
        from modstore_server.models import ESkill

        row = db.query(ESkill).filter(ESkill.id == skill_id).first()
        if not row:
            raise HTTPException(404, "技能不存在")
        # 用 note 字段存 is_active 状态（暂时）
        # TODO: ESkill 表增加 is_active 字段
        db.commit()
        return {"ok": True, "id": skill_id, "is_active": body.is_active}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


# ─── Butler Orchestrate ────────────────────────────────────────────────

from modstore_server.agent_butler_orchestrate import (  # noqa: E402
    ButlerOrchestrateBody as _ButlerOrchestrateBody,
)
from modstore_server.agent_butler_orchestrate import (
    _butler_orchestrate_steps,
    _run_butler_orchestrate_pipeline,
)


@router.post("/orchestrate")
async def butler_orchestrate(
    body: _ButlerOrchestrateBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """启动 vibe-coding 改写管线（异步，返回 session_id 供轮询）。

    前端用 GET /api/workbench/sessions/{session_id} 轮询进度。
    """
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _persist_workbench_session_unlocked,
        _pipeline_task_failsafe,
    )

    sid = uuid.uuid4().hex[:24]
    payload = body.model_dump()
    async with _SESSION_LOCK:
        WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": "butler",
            "status": "running",
            "steps": _butler_orchestrate_steps(),
            "planning_record": {
                "brief": body.brief,
                "target_type": body.target_type,
                "target_id": body.target_id,
            },
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _persist_workbench_session_unlocked(sid)

    task = asyncio.create_task(_run_butler_orchestrate_pipeline(sid, user.id, payload))
    task.add_done_callback(_pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running"}


# ─── 辅助函数 ──────────────────────────────────────────────────────────


def _safe_json(s: Any) -> Dict[str, Any]:
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


# ─── 全员汇报 ─────────────────────────────────────────────────────────


class AllHandsReportDTO(BaseModel):
    """``POST /api/agent/butler/all-hands-report`` 入参。

    - ``employee_ids`` 为空时，从 ``duty_roster`` ∩ ``catalog`` 取全集；
    - ``with_research`` 控制是否做联网 + GitHub 调研（关掉可加快出报告，但失去
      "上网思考自我优化"那一段的真实根据）；
    - ``max_employees`` / ``concurrency`` 两个上限避免一次把平台 LLM bench 配额
      打爆；
    - ``user_question`` 非空时切到 Q&A 模板：每个员工只针对该问题回答（保留
      manifest_signals / recent_failures / yuangon_pack_excerpt 作为根据）；
    - ``synthesize`` 在 ``user_question`` 模式下默认开启，用 bench LLM 合并
      所有员工的答复，输出一段「数字管家综合答复」。
    """

    employee_ids: Optional[List[str]] = None
    with_research: bool = True
    max_employees: int = Field(8, ge=1, le=MAX_ALL_HANDS_EMPLOYEES)
    concurrency: int = Field(2, ge=1, le=4)
    user_question: Optional[str] = Field(default=None, max_length=600)
    synthesize: bool = True


def _all_hands_session_steps(*, with_synthesize: bool = False) -> List[Dict[str, Any]]:
    """与 workbench session 结构对齐的全员汇报阶段。

    ``with_synthesize=True`` 时插入一段「数字管家综合答复」步骤，与
    :func:`modstore_server.all_hands_report.build_all_hands_report` 中的合并阶段
    一一对应。
    """
    steps: List[Dict[str, Any]] = [
        {"id": "prepare", "label": "准备员工清单", "status": "pending", "message": None},
        {"id": "collect", "label": "收集全员汇报", "status": "pending", "message": None},
    ]
    if with_synthesize:
        steps.append(
            {"id": "synthesize", "label": "数字管家综合答复", "status": "pending", "message": None}
        )
    steps.append({"id": "minutes", "label": "生成会议摘要", "status": "pending", "message": None})
    steps.append({"id": "complete", "label": "完成", "status": "pending", "message": None})
    return steps


async def _run_all_hands_report_session(
    sid: str,
    user_id: int,
    payload: Dict[str, Any],
) -> None:
    """后台执行全员汇报，并把结果写入 workbench session。"""
    from modstore_server.all_hands_report import build_all_hands_report, synthesize_meeting_minutes
    from modstore_server.daily_digest import (
        DEFAULT_DIGEST_EMAIL,
        parse_daily_digest_recipient_emails,
    )
    from modstore_server.email_service import send_simple_html_email
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _fail_session,
        _finalize_session_done,
        _persist_workbench_session_unlocked,
        _set_step,
    )

    employee_ids_raw = payload.get("employee_ids")
    employee_ids = employee_ids_raw if isinstance(employee_ids_raw, list) else None
    max_employees = clamp_all_hands_max_employees(payload.get("max_employees"))
    with_research = bool(payload.get("with_research", True))
    concurrency = int(payload.get("concurrency") or 2)
    user_question_raw = payload.get("user_question")
    user_question = str(user_question_raw or "").strip() if user_question_raw else ""
    synthesize_flag = bool(payload.get("synthesize", True)) and bool(user_question)

    await _set_step(sid, "prepare", "running", "正在整理可汇报员工清单…")
    await _set_step(
        sid,
        "prepare",
        "done",
        f"并发 {max(1, min(concurrency, 4))}；最多 {max_employees} 人",
    )
    await _set_step(
        sid,
        "collect",
        "running",
        (
            f"数字管家在向 {max_employees} 名员工发问…"
            if user_question
            else "数字管家正在逐个收集员工汇报（含 manifest/执行流水/可选联网调研）…"
        ),
    )

    def _to_nonneg_int(v: Any) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    async def _on_progress(evt: Dict[str, Any]) -> None:
        stage = str(evt.get("stage") or "").strip().lower()
        total = _to_nonneg_int(evt.get("total"))
        completed = _to_nonneg_int(evt.get("completed"))
        ok_n = _to_nonneg_int(evt.get("ok"))
        err_n = _to_nonneg_int(evt.get("error"))
        if total > 0:
            completed = min(completed, total)
            percent = int(round((completed / total) * 100))
        else:
            percent = 0

        progress = {
            "stage": stage or "collect",
            "total": total,
            "completed": completed,
            "ok": ok_n,
            "error": err_n,
            "percent": max(0, min(percent, 100)),
            "current_employee_id": str(evt.get("employee_id") or ""),
            "current_employee_name": str(evt.get("employee_name") or ""),
            "current_employee_status": str(evt.get("employee_status") or ""),
            "updated_at": str(
                evt.get("updated_at") or datetime.now(timezone.utc).isoformat() + "Z"
            ),
        }

        async with _SESSION_LOCK:
            sess = WORKBENCH_SESSIONS.get(sid)
            if not sess:
                return
            planning = sess.get("planning_record")
            if not isinstance(planning, dict):
                planning = {}
            planning["progress"] = progress
            sess["planning_record"] = planning
            _persist_workbench_session_unlocked(sid)

        if stage == "prepare":
            await _set_step(
                sid,
                "prepare",
                "done",
                f"已准备 {total} 名员工，开始收集汇报（并发 {max(1, min(concurrency, 4))}）",
            )
        elif stage == "employee_done":
            await _set_step(
                sid,
                "collect",
                "running",
                f"已完成 {completed}/{max(total, completed)}（成功 {ok_n}，异常 {err_n}）",
            )

    try:
        report = await build_all_hands_report(
            employee_ids=employee_ids,
            max_employees=max_employees,
            with_research=with_research,
            user_id=user_id,
            concurrency=concurrency,
            progress_cb=_on_progress,
            user_question=user_question or None,
            synthesize=synthesize_flag,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("all-hands-report session failed sid=%s user=%s", sid, user_id)
        await _fail_session(sid, "collect", f"全员汇报失败：{exc}")
        return

    if not bool(report.get("ok", True)):
        await _fail_session(sid, "collect", str(report.get("error") or "全员汇报失败"))
        return

    done_count = len((report.get("employees") or []))
    await _set_step(sid, "collect", "done", f"已收集 {done_count} 名员工汇报")

    if synthesize_flag:
        synth = report.get("synthesized_answer") if isinstance(report, dict) else None
        if isinstance(synth, dict) and (synth.get("markdown") or "").strip():
            cited = synth.get("cited_employees") or []
            cite_count = len(cited) if isinstance(cited, list) else 0
            await _set_step(
                sid,
                "synthesize",
                "done",
                f"综合答复已生成，引用员工 {cite_count} 名",
            )
        else:
            err = ""
            if isinstance(synth, dict):
                err = str(synth.get("error") or "").strip()
            await _set_step(
                sid,
                "synthesize",
                "done",
                f"综合答复跳过：{err}" if err else "综合答复未生成（bench LLM 不可用）",
            )

    await _set_step(sid, "minutes", "running", "正在生成会议摘要…")
    meeting_minutes = await synthesize_meeting_minutes(report=report, user_id=user_id)
    body_text = str(meeting_minutes.get("text") or "").strip()
    minutes_err = str(meeting_minutes.get("error") or "").strip()

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"MODstore 员工大会会议摘要 · {day}"
    recipients = parse_daily_digest_recipient_emails(
        os.environ.get("MODSTORE_DAILY_DIGEST_EMAIL", DEFAULT_DIGEST_EMAIL).strip()
    )
    meeting_minutes_email: Dict[str, Any] = {
        "recipients_count": len(recipients),
        "any_delivered": False,
        "per_to": [],
    }
    if not recipients:
        meeting_minutes_email["skipped_reason"] = "无有效收件人（MODSTORE_DAILY_DIGEST_EMAIL）"
    elif not body_text:
        meeting_minutes_email["skipped_reason"] = "会议摘要正文为空，已跳过发信"
    else:
        html_body = (
            '<html><body style="font-family:sans-serif;padding:20px">'
            '<h2 style="color:#1e293b">员工大会 · 会议摘要</h2>'
            '<pre style="white-space:pre-wrap;font-size:14px;line-height:1.6;color:#334155">'
            f"{html.escape(body_text)}"
            "</pre></body></html>"
        )
        any_delivered = False
        for to_email in recipients:
            result = send_simple_html_email(to_email, subject, html_body)
            deliv = bool(result.get("delivered"))
            if deliv:
                any_delivered = True
            meeting_minutes_email["per_to"].append(
                {
                    "to": to_email,
                    "delivered": deliv,
                    "mode": str(result.get("mode") or ""),
                }
            )
        meeting_minutes_email["any_delivered"] = any_delivered
        logger.info(
            "all-hands meeting minutes email sid=%s recipients=%s any_delivered=%s",
            sid,
            len(recipients),
            any_delivered,
        )

    if body_text and meeting_minutes_email.get("any_delivered"):
        minutes_done_msg = "会议摘要已生成并已发信（每日摘要收件箱）"
    elif body_text and not recipients:
        minutes_done_msg = "会议摘要已生成；无有效早报收件人，未发信"
    elif body_text:
        minutes_done_msg = "会议摘要已生成；SMTP 未配置或邮件未成功投递"
    elif minutes_err:
        minutes_done_msg = f"会议摘要未产出正文：{minutes_err[:120]}"
    else:
        minutes_done_msg = "会议摘要未产出正文"
    await _set_step(sid, "minutes", "done", minutes_done_msg)

    await _set_step(sid, "complete", "running", "正在整理报告输出…")
    await _finalize_session_done(
        sid,
        {
            "type": "all_hands_report",
            "all_hands_report": report,
            "summary": report.get("summary") if isinstance(report, dict) else {},
            "synthesized_answer": (
                report.get("synthesized_answer") if isinstance(report, dict) else None
            ),
            "meeting_minutes": meeting_minutes,
            "meeting_minutes_email": meeting_minutes_email,
            "completed_at": datetime.now(timezone.utc).isoformat() + "Z",
        },
    )


@router.post("/all-hands-report/sessions")
async def butler_all_hands_report_session_start(
    body: AllHandsReportDTO,
    user: User = Depends(_get_current_user),
):
    """启动全员汇报后台任务（秒回 session_id，前端轮询 `/api/workbench/sessions/{id}`）。"""
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可触发全员汇报")

    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _persist_workbench_session_unlocked,
        _pipeline_task_failsafe,
    )

    sid = uuid.uuid4().hex[:24]
    payload = body.model_dump()
    req_ids = payload.get("employee_ids")
    req_count = len(req_ids) if isinstance(req_ids, list) else 0
    user_question_raw = payload.get("user_question")
    user_question_str = str(user_question_raw or "").strip() if user_question_raw else ""
    synth_flag = bool(payload.get("synthesize", True)) and bool(user_question_str)

    async with _SESSION_LOCK:
        WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": "butler_all_hands_report",
            "status": "running",
            "steps": _all_hands_session_steps(with_synthesize=synth_flag),
            "planning_record": {
                "employee_ids_count": req_count,
                "with_research": bool(payload.get("with_research", True)),
                "max_employees": clamp_all_hands_max_employees(payload.get("max_employees")),
                "concurrency": int(payload.get("concurrency") or 2),
                "user_question": user_question_str,
                "synthesize": synth_flag,
                "progress": {
                    "stage": "prepare",
                    "total": 0,
                    "completed": 0,
                    "ok": 0,
                    "error": 0,
                    "percent": 0,
                    "current_employee_id": "",
                    "current_employee_name": "",
                    "current_employee_status": "",
                    "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
                },
            },
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _persist_workbench_session_unlocked(sid)

    task = asyncio.create_task(
        _run_all_hands_report_session(
            sid=sid,
            user_id=int(user.id),
            payload=payload,
        )
    )
    task.add_done_callback(_pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running"}


@router.post("/all-hands-report")
async def butler_all_hands_report(
    body: AllHandsReportDTO,
    user: User = Depends(_get_current_user),
):
    """让数字管家召集全员汇报（**仅管理员**）。

    每个员工会按 ``modstore_server.all_hands_report.ALL_HANDS_TASK_TEMPLATE``
    的固定 4 段结构（架构 / 问题与解决 / 联网调研后的优化 / 待办）输出 Markdown，
    并在 prompt 中显式要求"联动其他岗位"，让汇报互相串起来。
    """
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可触发全员汇报")

    from modstore_server.all_hands_report import build_all_hands_report

    try:
        uq = (body.user_question or "").strip() if body.user_question else ""
        synth = bool(body.synthesize) and bool(uq)
        report = await build_all_hands_report(
            employee_ids=body.employee_ids,
            max_employees=int(body.max_employees),
            with_research=bool(body.with_research),
            user_id=int(user.id),
            user_question=uq or None,
            synthesize=synth,
            concurrency=int(body.concurrency),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("all-hands-report failed user=%s", user.id)
        raise HTTPException(500, f"全员汇报失败：{exc}") from exc
    return report


# ─── 每日摘要 → Vibe-Coding 预备 Markdown ───────────────────────────────────


class DigestVibePrepDTO(BaseModel):
    """``POST .../daily-digests/{id}/vibe-prep/sessions`` 入参。"""

    mode: str = Field("auto", description="auto=轻量快照+合成；manual=逐员工汇报后合成")
    employee_ids: Optional[List[str]] = None
    max_employees: int = Field(52, ge=1, le=MAX_ALL_HANDS_EMPLOYEES)
    concurrency: int = Field(2, ge=1, le=4)


def _vibe_prep_session_steps() -> List[Dict[str, Any]]:
    return [
        {"id": "prepare", "label": "准备员工清单", "status": "pending", "message": None},
        {"id": "collect", "label": "收集员工快照", "status": "pending", "message": None},
        {
            "id": "synthesize",
            "label": "生成更新/补丁 Markdown",
            "status": "pending",
            "message": None,
        },
        {"id": "complete", "label": "完成", "status": "pending", "message": None},
    ]


async def _run_digest_vibe_prep_session(
    sid: str,
    user_id: int,
    digest_row: DailyDigestRecord,
    payload: Dict[str, Any],
) -> None:
    from modstore_server.digest_vibe_prep import build_digest_vibe_prep
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _fail_session,
        _finalize_session_done,
        _persist_workbench_session_unlocked,
        _set_step,
    )

    mode = str(payload.get("mode") or "auto").strip().lower()
    if mode not in ("auto", "manual"):
        mode = "auto"
    employee_ids_raw = payload.get("employee_ids")
    employee_ids = employee_ids_raw if isinstance(employee_ids_raw, list) else None
    max_employees = clamp_all_hands_max_employees(payload.get("max_employees"), default=52)
    concurrency = int(payload.get("concurrency") or 2)

    await _set_step(sid, "prepare", "running", f"模式：{'手动' if mode == 'manual' else '自动'}…")
    await _set_step(
        sid,
        "prepare",
        "done",
        f"{'手动逐岗汇报' if mode == 'manual' else '自动轻量快照'} · 最多 {max_employees} 人",
    )
    await _set_step(sid, "collect", "running", "正在汇总各员工上下文…")

    async def _on_progress(evt: Dict[str, Any]) -> None:
        stage = str(evt.get("stage") or "collect")
        total = int(evt.get("total") or 0)
        completed = int(evt.get("completed") or 0)
        percent = int(round((completed / total) * 100)) if total > 0 else 0
        progress = {
            "stage": stage,
            "mode": str(evt.get("mode") or mode),
            "total": total,
            "completed": completed,
            "percent": max(0, min(percent, 100)),
            "current_employee_id": str(evt.get("employee_id") or ""),
            "current_employee_name": str(evt.get("employee_name") or ""),
            "current_employee_status": str(evt.get("employee_status") or ""),
            "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
        }
        async with _SESSION_LOCK:
            sess = WORKBENCH_SESSIONS.get(sid)
            if not sess:
                return
            planning = sess.get("planning_record")
            if not isinstance(planning, dict):
                planning = {}
            planning["progress"] = progress
            sess["planning_record"] = planning
            _persist_workbench_session_unlocked(sid)
        if stage == "collect":
            await _set_step(
                sid,
                "collect",
                "running",
                f"已收集 {completed}/{max(total, completed)} 名员工",
            )

    try:
        result = await build_digest_vibe_prep(
            digest_day=str(digest_row.day or ""),
            digest_subject=str(digest_row.subject or ""),
            digest_body_html=str(digest_row.body_html or ""),
            digest_body_text=str(digest_row.body_text or ""),
            meeting_minutes_html=str(digest_row.meeting_minutes_html or ""),
            mode=mode,
            employee_ids=employee_ids,
            max_employees=max_employees,
            concurrency=concurrency,
            user_id=user_id,
            record_id=int(digest_row.id or 0),
            progress_cb=_on_progress,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("digest vibe-prep session failed sid=%s", sid)
        await _fail_session(sid, "collect", f"Vibe 预备文档生成失败：{exc}")
        return

    if not result.get("ok"):
        await _fail_session(sid, "synthesize", str(result.get("error") or "合成失败"))
        return

    n = int(result.get("employee_count") or 0)
    await _set_step(sid, "collect", "done", f"已汇总 {n} 名员工")
    await _set_step(sid, "synthesize", "running", "正在生成更新清单与补丁清单…")
    await _set_step(
        sid,
        "synthesize",
        "done",
        f"已生成双 Markdown（模型 {result.get('model') or '—'}）",
    )
    await _set_step(sid, "complete", "running", "正在整理输出…")
    artifact = {
        "type": "digest_vibe_prep",
        "digest_id": int(digest_row.id),
        "digest_day": digest_row.day,
        "digest_subject": digest_row.subject,
        "vibe_prep": result,
        "updates_markdown": result.get("updates_markdown") or "",
        "patches_markdown": result.get("patches_markdown") or "",
        "completed_at": datetime.now(timezone.utc).isoformat() + "Z",
    }
    from modstore_server.digest_vibe_line_dispatch import dispatch_vibe_prep_to_production_lines
    from modstore_server.digest_vibe_prep import persist_vibe_prep_on_digest_record

    persist_vibe_prep_on_digest_record(int(digest_row.id), result)
    dispatch_vibe_prep_to_production_lines(int(digest_row.id), result)
    await _finalize_session_done(sid, artifact)


class DigestLineExecuteDTO(BaseModel):
    """``POST .../daily-digests/{id}/line-execute`` 入参（Phase A 或单产线）。"""

    dispatch_line: str = Field(
        "PHASE-A",
        description="PHASE-A（默认，P-S+P-App 补丁）| P-W | P-S | P-App | S-R",
    )
    force: bool = Field(False, description="忽略同 base_version 幂等跳过")
    list_kinds: Optional[List[str]] = Field(None, description="默认 patches")
    priorities: Optional[List[str]] = Field(None, description="如 P0,P1")


@router.post("/daily-digests/{record_id}/line-execute")
async def butler_digest_line_execute(
    record_id: int,
    body: DigestLineExecuteDTO,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """Phase A：消费产线清单并向对应员工派发子任务（不跑 P3–P9）。"""
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可触发产线清单执行")
    row = db.get(DailyDigestRecord, record_id)
    if row is None:
        raise HTTPException(404, "每日摘要记录不存在")

    import asyncio

    line = str(body.dispatch_line or "PHASE-A").strip().upper().replace("_", "-")
    kinds = body.list_kinds if body.list_kinds else None
    prios = body.priorities if body.priorities else None
    force = bool(body.force)

    if line in ("PHASE-A", "PHASEA", "ALL", "*", ""):
        from modstore_server.digest_daily_line_chain import execute_phase_a_line_chain

        out = await asyncio.to_thread(execute_phase_a_line_chain, int(record_id), force=force)
        return {"success": bool(out.get("ok")), "data": out}

    if line not in ("P-W", "P-S", "P-APP", "S-R"):
        raise HTTPException(400, "dispatch_line 须为 PHASE-A / P-W / P-S / P-App / S-R")
    if line == "P-APP":
        line = "P-App"

    from modstore_server.digest_line_executor import execute_digest_line_work_units

    out = await asyncio.to_thread(
        execute_digest_line_work_units,
        int(record_id),
        dispatch_line=line,
        list_kinds=kinds,
        priorities=prios,
        mode="manual",
        force=force,
    )
    return {"success": bool(out.get("ok")), "data": out}


@router.post("/daily-digests/{record_id}/vibe-prep/sessions")
async def butler_digest_vibe_prep_session_start(
    record_id: int,
    body: DigestVibePrepDTO,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """基于某条每日摘要存档，生成 Vibe-Coding 预备 Markdown（更新 + 补丁）。"""
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "仅管理员可生成 Vibe 预备文档")
    row = db.get(DailyDigestRecord, record_id)
    if row is None:
        raise HTTPException(404, "每日摘要记录不存在")

    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _persist_workbench_session_unlocked,
        _pipeline_task_failsafe,
    )

    sid = uuid.uuid4().hex[:24]
    mode = str(body.mode or "auto").strip().lower()
    if mode not in ("auto", "manual"):
        mode = "auto"
    payload = body.model_dump()

    async with _SESSION_LOCK:
        WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": "digest_vibe_prep",
            "status": "running",
            "steps": _vibe_prep_session_steps(),
            "planning_record": {
                "digest_id": record_id,
                "mode": mode,
                "max_employees": clamp_all_hands_max_employees(body.max_employees, default=52),
                "concurrency": int(body.concurrency or 2),
                "progress": {
                    "stage": "prepare",
                    "mode": mode,
                    "total": 0,
                    "completed": 0,
                    "percent": 0,
                    "current_employee_id": "",
                    "current_employee_name": "",
                    "current_employee_status": "",
                    "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
                },
            },
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _persist_workbench_session_unlocked(sid)

    task = asyncio.create_task(
        _run_digest_vibe_prep_session(
            sid=sid,
            user_id=int(user.id),
            digest_row=row,
            payload=payload,
        )
    )
    task.add_done_callback(_pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running", "digest_id": record_id}


# Phase 5 TODO: evolution endpoint
# def butler_evolution_detect(): ...
# def butler_evolution_generate(): ...
# def butler_evolution_register(): ...
