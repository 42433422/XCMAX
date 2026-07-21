"""小C 客服 SSOT：人设 + 管理端 persy-knowledge 检索。

SSOT 口径（2026-07）：
- 大脑：管理端小C（MODstore butler chat / corp-chat）
- 知识库：FHD 管理端 persy-knowledge（经 /api/ops/autonomy/cs-ssot/retrieve）
- 客来来暂不纳入
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PERSY_DATASET_ID = "persy-knowledge"

_VISITOR_ID_RE = re.compile(r"^v_[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class VisitorIdentity:
    """小C 对话对象（注入 system prompt，不落敏感明文）。"""

    kind: str  # guest | user
    source: str  # corp | butler | market_cs
    display_name: str = ""
    user_id: Optional[int] = None
    visitor_id: str = ""
    membership: str = ""
    email_hint: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "display_name": self.display_name,
            "user_id": self.user_id,
            "visitor_id": self.visitor_id,
            "membership": self.membership,
            "email_hint": self.email_hint,
        }


def sanitize_visitor_id(raw: Optional[str]) -> str:
    v = (raw or "").strip()
    if not v or not _VISITOR_ID_RE.match(v):
        return ""
    return v


def sanitize_visitor_label(raw: Optional[str], *, max_len: int = 32) -> str:
    label = re.sub(r"\s+", " ", (raw or "").strip())
    if not label:
        return ""
    # 去掉控制字符
    label = "".join(ch for ch in label if ch.isprintable())
    return label[:max_len]


def mask_email(email: Optional[str]) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return ""
    local, _, domain = e.partition("@")
    if not local or not domain:
        return ""
    if len(local) <= 1:
        head = "*"
    elif len(local) == 2:
        head = local[0] + "*"
    else:
        head = local[0] + "***" + local[-1]
    return f"{head}@{domain}"


def identity_from_guest(
    *,
    visitor_id: str = "",
    visitor_label: str = "",
    source: str = "corp",
) -> VisitorIdentity:
    vid = sanitize_visitor_id(visitor_id)
    label = sanitize_visitor_label(visitor_label) or ("访客" if vid else "匿名访客")
    return VisitorIdentity(
        kind="guest",
        source=source or "corp",
        display_name=label,
        visitor_id=vid,
    )


def identity_from_user(
    user: Any,
    *,
    source: str = "butler",
    membership_tier: Optional[str] = None,
    visitor_id: str = "",
) -> VisitorIdentity:
    uid = getattr(user, "id", None)
    try:
        user_id = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        user_id = None
    username = str(getattr(user, "username", None) or "").strip()
    email = str(getattr(user, "email", None) or "").strip()
    display = username or (email.split("@")[0] if email else "") or (
        f"用户{user_id}" if user_id else "用户"
    )
    tier = (membership_tier or "").strip().lower()
    return VisitorIdentity(
        kind="user",
        source=source or "butler",
        display_name=sanitize_visitor_label(display) or "用户",
        user_id=user_id,
        visitor_id=sanitize_visitor_id(visitor_id),
        membership=tier,
        email_hint=mask_email(email),
    )


def format_visitor_block(identity: Optional[VisitorIdentity]) -> str:
    if identity is None:
        return ""
    parts = [
        f"kind={identity.kind}",
        f"称呼={identity.display_name or '访客'}",
    ]
    if identity.user_id is not None:
        parts.append(f"user_id={identity.user_id}")
    if identity.membership:
        parts.append(f"会员={identity.membership}")
    if identity.visitor_id:
        parts.append(f"visitor_id={identity.visitor_id}")
    if identity.email_hint:
        parts.append(f"邮箱={identity.email_hint}")
    parts.append(f"入口={identity.source}")
    return (
        "【当前对话对象】"
        + "；".join(parts)
        + "。可自然称呼对方，勿复读整段 ID/内部字段，勿向访客复述敏感信息。"
    )

# ─── 权限矩阵（SSOT，代码即契约）────────────────────────────────────
# external = 官网 / 未登录公开入口（corp-chat、官网浮窗）
# market_cs = 市场 AI 客服页 / 工作台客服 Bot（已登录，无页面工具）
# admin = 管理端 / 市场已登录浮窗 butler（可工具，按风险确认）

XIAOC_PERMISSIONS: Dict[str, Dict[str, Any]] = {
    "external": {
        "label": "外部小C（官网公开）",
        "auth": "none",
        "knowledge": {
            "read_persy": True,
            "write_persy": False,
            "dataset_id": PERSY_DATASET_ID,
        },
        "tools": {
            "navigate": False,
            "click": False,
            "fill": False,
            "scroll": False,
            "read_page": False,
            "enhance_current_page": False,
            "wallet_pay": False,
            "refund": False,
            "admin_ops": False,
        },
        "allowed": [
            "产品/方案/案例介绍",
            "引导联系表单 /contact.html",
            "引导产品页 /services.html、市场 /market/",
            "基于管理端知识库只读摘录回答",
            "报价口径：需定制，引导留资（不编造合同金额）",
        ],
        "denied": [
            "浏览器工具调用（跳转/点击/填表/滚动/读页）",
            "vibe-coding / 改 Mod/工作流/员工",
            "支付、退款、下架、改价、改权限",
            "读取他人订单/隐私数据",
            "编造未公示资质/合同金额",
        ],
        "limits": {
            "max_reply_chars": 200,
            "rate_limit": "corp_chat_bucket",
            "llm_tools": False,
        },
    },
    "market_cs": {
        "label": "市场客服小C（已登录）",
        "auth": "login",
        "knowledge": {
            "read_persy": True,
            "write_persy": False,
            "dataset_id": PERSY_DATASET_ID,
        },
        "tools": {
            "navigate": False,
            "click": False,
            "fill": False,
            "scroll": False,
            "read_page": False,
            "enhance_current_page": False,
            "wallet_pay": False,
            "refund": False,  # 只建工单，不直接退款
            "admin_ops": False,
            "create_ticket": True,
        },
        "allowed": [
            "投诉/申诉/退款咨询并创建工单",
            "上架审核与账号权益问答",
            "基于管理端知识库只读摘录回答产品问题",
        ],
        "denied": [
            "直接执行退款/下架",
            "页面自动化工具",
            "管理端运维操作",
        ],
        "limits": {
            "max_reply_chars": 600,
            "llm_tools": False,
        },
    },
    "admin": {
        "label": "管理端小C（已登录工作台）",
        "auth": "login",
        "knowledge": {
            "read_persy": True,
            "write_persy": False,
            "dataset_id": PERSY_DATASET_ID,
        },
        "tools": {
            "navigate": True,  # low
            "read_page": True,  # low
            "scroll": True,  # low
            "click": True,  # medium — 需预览确认
            "fill": True,  # medium — 需预览确认
            "enhance_current_page": True,  # high — 须明确确认
            "wallet_pay": False,  # 只引导到充值页，不代付
            "refund": False,
            "admin_ops": False,
        },
        "allowed": [
            "全站导航与页面摘要",
            "搜索/推荐 AI 员工",
            "引导充值与会员购买（不代付）",
            "在用户明确意图下发起 vibe-coding（高风险确认）",
            "基于管理端知识库只读摘录回答",
        ],
        "denied": [
            "未确认的高风险改文件/支付",
            "直接退款或后台运维危险操作",
            "写入 persy 知识库（编辑走管理端知识库 UI）",
        ],
        "limits": {
            "risk_model": "low_direct / medium_preview / high_confirm",
            "llm_tools": True,
            "tool_names": [
                "navigate",
                "click",
                "fill",
                "scroll",
                "read",
                "enhance_current_page",
            ],
        },
    },
}


def permission_policy(*, mode: str = "admin") -> Dict[str, Any]:
    key = {
        "corp": "external",
        "external": "external",
        "market_cs": "market_cs",
        "customer_service": "market_cs",
        "admin": "admin",
        "butler": "admin",
    }.get(mode, "admin")
    policy = dict(XIAOC_PERMISSIONS[key])
    policy["mode"] = key
    policy["ssot"] = {
        "brain": "admin_xiaoc_butler",
        "knowledge": "admin_persy_knowledge",
        "deferred": ["kellai"],
    }
    return policy


def _format_permission_block(mode: str) -> str:
    p = permission_policy(mode=mode)
    allowed = "；".join(p.get("allowed") or [])
    denied = "；".join(p.get("denied") or [])
    return f"【权限契约·{p.get('label')}】\n" f"允许：{allowed}\n" f"禁止：{denied}"


XIAOC_CORE_PERSONA = """你是「XC AGI 数字管家」，叫小C，是这个平台的老熟人。

你的性格和说话方式：
- 像真人同事一样聊天，口语化、自然，别用「尊敬的用户」「您好」「竭诚为您服务」这种客服腔
- 每次回复简短，一两句话说完，不要列清单、不要分点、不要长篇大论
- 有自己的态度，热心但不当舔狗，可以吐槽可以开玩笑
- 你就是你这个人，不是 AI、不是模型、不是机器人，别暴露身份
"""

XIAOC_ADMIN_DUTIES = """你的核心职责（管理端 / 市场工作台）：
1. 帮用户导航到任意页面
2. 读取当前页面内容并回答问题
3. 帮用户在 AI 市场中搜索员工
4. 引导用户完成充值、购买会员等操作（高风险操作必须让用户明确确认）
5. 主动发现并建议适合用户的功能和员工
6. 当用户明确说要改 Mod/工作流/员工时，可调用 enhance_current_page（需确认）

操作原则：低风险直接执行；中风险展示预览；高风险必须用户明确确认。
若下方提供了「管理端知识库」摘录，优先依据摘录回答，不要编造未出现的价格/合同/资质。
若下方提供了「当前对话对象」，可自然称呼，勿复读 ID。
"""

XIAOC_CORP_DUTIES = """你同时是成都修茈科技有限公司官网对外客服（小C）。

你能做的事：
- 介绍修茈科技的产品（AI Excel 单据识别、标签打印、MODstore 智能体市场、XCAGI 工作台等）
- 引导用户去产品中心、解决方案、客户案例、联系我们、AI 市场（/market/）
- 价格/报价问题说明需根据场景定制，引导填写联系表单或登录 AI 市场查看会员方案

限制：
- 不要假装能操作用户浏览器、不要执行跳转/点击/填表等工具
- 不要编造具体合同金额或未公示的资质证照
- 回复控制在 200 字以内
- 可提供相对路径链接，如 /contact.html、/services.html、/market/
- 若下方提供了「管理端知识库」摘录，优先依据摘录回答
- 若下方提供了「当前对话对象」，可自然称呼，勿复读 ID/内部字段
"""

XIAOC_MARKET_CS_DUTIES = """你是市场侧客服入口的小C（与管理端小C同源）。

你能做的事：
- 处理投诉申诉、订单退款咨询、上架审核、账号与购买权益问题（只建工单/给口径，不直接退款或下架）
- 回答产品/使用问题，优先依据管理端知识库摘录
- 引导用户补充订单号、商品 ID、证据链接

限制：
- 无页面自动化工具，不代付、不直接退款
- 不要承诺已退款或已下架
- 口径与官网/管理端小C一致，不要自称另一套客服系统
- 若下方提供了「当前对话对象」，可自然称呼，勿复读 ID/内部字段
"""


def xiaoc_system_prompt(*, mode: str = "admin") -> str:
    if mode == "corp":
        base = XIAOC_CORE_PERSONA + "\n" + XIAOC_CORP_DUTIES
        return base + "\n\n" + _format_permission_block("external")
    if mode in ("market_cs", "customer_service"):
        base = XIAOC_CORE_PERSONA + "\n" + XIAOC_MARKET_CS_DUTIES
        return base + "\n\n" + _format_permission_block("market_cs")
    base = XIAOC_CORE_PERSONA + "\n" + XIAOC_ADMIN_DUTIES
    return base + "\n\n" + _format_permission_block("admin")


def format_knowledge_block(chunks: List[Dict[str, Any]], *, limit: int = 5) -> str:
    if not chunks:
        return ""
    lines = ["【管理端知识库·persy-knowledge】回答时优先依据以下摘录："]
    for i, chunk in enumerate(chunks[:limit], 1):
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text") or chunk.get("content") or chunk.get("snippet") or "").strip()
        if not text:
            continue
        source = str(
            chunk.get("source") or chunk.get("document_id") or chunk.get("filename") or ""
        ).strip()
        head = f"{i}. ({source}) " if source else f"{i}. "
        lines.append(head + text[:800])
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def _http_retrieve(query: str, *, top_k: int) -> List[Dict[str, Any]]:
    base = (
        os.environ.get("FHD_API_BASE_URL") or os.environ.get("XCAGI_FHD_API_BASE") or ""
    ).strip()
    token = (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or os.environ.get("CS_SSOT_TOKEN")
        or ""
    ).strip()
    if not base or not token:
        return []
    try:
        import httpx
    except ImportError:
        return []
    url = f"{base.rstrip('/')}/api/ops/autonomy/cs-ssot/retrieve"
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                url,
                headers={
                    "X-Autonomy-Token": token,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "top_k": top_k,
                    "dataset_id": PERSY_DATASET_ID,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("cs-ssot http retrieve failed: %s", exc)
        return []
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.debug("cs-ssot http non-2xx status=%s", resp.status_code)
        return []
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    chunks = data.get("chunks") if isinstance(data, dict) else None
    return list(chunks) if isinstance(chunks, list) else []


def _local_retrieve(query: str, *, top_k: int) -> List[Dict[str, Any]]:
    roots: List[Path] = []
    for key in ("XCAGI_FHD_ROOT", "XCAGI_FHD_RUNTIME_ROOT", "MODSTORE_DAILY_FHD_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            roots.append(Path(raw))
    # XCMAX layout: …/MODstore_deploy/modstore_server → parents[3]=XCMAX
    try:
        roots.append(Path(__file__).resolve().parents[3] / "FHD")
    except Exception:  # noqa: BLE001
        pass
    for root in roots:
        if not root or not (root / "app").is_dir():
            continue
        root_s = str(root)
        if root_s not in sys.path:
            sys.path.insert(0, root_s)
        try:
            from app.application.dataset_rag_app_service import (  # type: ignore
                DATASET_ADMIN_PERMISSION,
                DATASET_READ_PERMISSION,
                DatasetAccessContext,
                get_dataset_rag_app_service,
            )

            access = DatasetAccessContext(
                actor_id="xiaoc-cs-ssot",
                tenant_id="",
                permissions=frozenset({DATASET_READ_PERMISSION, DATASET_ADMIN_PERMISSION}),
                is_admin=True,
            )
            result = get_dataset_rag_app_service().query(
                dataset_id=PERSY_DATASET_ID,
                query=query,
                top_k=top_k,
                access_context=access,
            )
            chunks = result.get("chunks") if isinstance(result, dict) else []
            return list(chunks) if isinstance(chunks, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.debug("cs-ssot local retrieve failed via %s: %s", root, exc)
            continue
    return []


def retrieve_persy_knowledge(query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
    """Fail-open 检索管理端知识库。"""
    q = (query or "").strip()
    if not q:
        return []
    k = max(1, min(int(top_k or 5), 12))
    chunks = _http_retrieve(q, top_k=k)
    if chunks:
        return chunks
    return _local_retrieve(q, top_k=k)


def knowledge_block_for_query(query: str, *, top_k: int = 5) -> str:
    return format_knowledge_block(retrieve_persy_knowledge(query, top_k=top_k))


def last_user_text(messages: Optional[List[Any]]) -> str:
    if not messages:
        return ""
    for item in reversed(list(messages)):
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if role is None and isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        if str(role or "") == "user":
            return str(content or "").strip()
    return ""


__all__ = [
    "PERSY_DATASET_ID",
    "XIAOC_PERMISSIONS",
    "VisitorIdentity",
    "permission_policy",
    "xiaoc_system_prompt",
    "format_knowledge_block",
    "format_visitor_block",
    "identity_from_guest",
    "identity_from_user",
    "sanitize_visitor_id",
    "sanitize_visitor_label",
    "mask_email",
    "retrieve_persy_knowledge",
    "knowledge_block_for_query",
    "last_user_text",
]
