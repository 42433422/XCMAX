"""小C 客服 SSOT：人设 + 知识库三档隔离检索。"""

from __future__ import annotations

import copy
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .xiaoc_public_scope import is_published_public_chunk, public_query_kwargs

logger = logging.getLogger(__name__)

PUBLIC_DATASET_ID = "persy-knowledge"
INTERNAL_DATASET_ID = "xiaoc-internal"
# 兼容旧符号
PERSY_DATASET_ID = PUBLIC_DATASET_ID

_PRIVATE_DATASET_PREFIXES = ("user_", "desktop_", "tenant_")
_DENY_PRIVATE_LABELS = (INTERNAL_DATASET_ID, "user_*", "desktop_private", "tenant_private")

_VISITOR_ID_RE = re.compile(r"^v_[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class VisitorIdentity:
    """小C 对话对象（注入 system prompt，不落敏感明文）。"""

    kind: str  # guest | user
    source: str  # corp | butler | market_cs
    display_name: str = ""
    user_id: Optional[int] = None
    visitor_id: str = ""
    membership: str = ""  # 展示档：普通用户 / VIP / VIP+ / svip / SVIP2…
    account_role: str = ""  # user | enterprise | admin
    plan_id: str = ""
    email_hint: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "display_name": self.display_name,
            "user_id": self.user_id,
            "visitor_id": self.visitor_id,
            "membership": self.membership,
            "account_role": self.account_role,
            "plan_id": self.plan_id,
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


def _account_role_of(user: Any) -> str:
    if bool(getattr(user, "is_admin", False)):
        return "admin"
    if bool(getattr(user, "is_enterprise", False)):
        return "enterprise"
    return "user"


def _membership_label_for_plan(plan_id: str) -> str:
    """套餐展示名（与 payment_common 会员档对齐；无套餐=普通用户）。"""
    pid = (plan_id or "").strip()
    if not pid:
        return "普通用户"
    try:
        from modstore_server.payment_common import _membership_meta

        meta = _membership_meta(pid)
        label = str(meta.get("label") or "").strip()
        if label:
            return label
    except Exception:  # noqa: BLE001
        pass
    # llm_api 旧映射兜底
    try:
        from modstore_server.llm_api import _membership_meta as _llm_meta

        label = str((_llm_meta(pid) or {}).get("label") or "").strip()
        if label:
            return label
    except Exception:  # noqa: BLE001
        pass
    return pid


def active_plan_id_for_user(db: Any, user_id: int) -> str:
    """读取 user_plans 当前生效套餐（账号 SSOT）。"""
    if db is None or not user_id:
        return ""
    try:
        from modstore_server.models import UserPlan

        # SAVEPOINT：查询失败时只回滚嵌套事务，避免吞掉异常后污染外层事务
        # （否则后续客服建会话 INSERT 会变成 InFailedSqlTransaction → 500）
        nested = db.begin_nested() if hasattr(db, "begin_nested") else None
        try:
            row = (
                db.query(UserPlan)
                .filter(UserPlan.user_id == int(user_id), UserPlan.is_active == True)  # noqa: E712
                .order_by(UserPlan.id.desc())
                .first()
            )
            plan_id = str(row.plan_id) if row else ""
            if nested is not None:
                nested.commit()
            return plan_id
        except Exception:
            if nested is not None:
                nested.rollback()
            raise
    except Exception:  # noqa: BLE001
        logger.debug("active_plan_id_for_user failed", exc_info=True)
        return ""


def identity_from_user(
    user: Any,
    *,
    source: str = "butler",
    membership_tier: Optional[str] = None,
    visitor_id: str = "",
    plan_id: str = "",
    account_role: Optional[str] = None,
    db: Any = None,
) -> VisitorIdentity:
    """从 User（+ 可选 DB 套餐）构建对话对象。

    会员档优先读 ``user_plans``；口语「体验版」≈ 无付费套餐（普通用户）。
    """
    uid = getattr(user, "id", None)
    try:
        user_id = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        user_id = None
    username = str(getattr(user, "username", None) or "").strip()
    email = str(getattr(user, "email", None) or "").strip()
    display = (
        username
        or (email.split("@")[0] if email else "")
        or (f"用户{user_id}" if user_id else "用户")
    )
    role = (account_role or _account_role_of(user)).strip() or "user"
    pid = (plan_id or "").strip()
    if not pid and db is not None and user_id:
        pid = active_plan_id_for_user(db, user_id)
    membership = (membership_tier or "").strip()
    if not membership:
        membership = _membership_label_for_plan(pid)
    return VisitorIdentity(
        kind="user",
        source=source or "butler",
        display_name=sanitize_visitor_label(display) or "用户",
        user_id=user_id,
        visitor_id=sanitize_visitor_id(visitor_id),
        membership=membership,
        account_role=role,
        plan_id=pid,
        email_hint=mask_email(email),
    )


def resolve_user_identity(
    user: Any,
    *,
    db: Any = None,
    source: str = "butler",
    visitor_id: str = "",
) -> VisitorIdentity:
    """已登录用户身份 SSOT：档案 + 管理员/企业旗标 + 当前会员套餐。"""
    return identity_from_user(user, source=source, visitor_id=visitor_id, db=db)


def format_visitor_block(identity: Optional[VisitorIdentity]) -> str:
    if identity is None:
        return ""
    parts = [
        f"kind={identity.kind}",
        f"称呼={identity.display_name or '访客'}",
    ]
    if identity.user_id is not None:
        parts.append(f"user_id={identity.user_id}")
    role = (identity.account_role or "").strip()
    if role and role != "user":
        role_label = {"admin": "管理员", "enterprise": "企业账号"}.get(role, role)
        parts.append(f"角色={role_label}")
    if identity.membership:
        parts.append(f"会员={identity.membership}")
    if identity.plan_id:
        parts.append(f"套餐={identity.plan_id}")
    if identity.visitor_id:
        parts.append(f"visitor_id={identity.visitor_id}")
    if identity.email_hint:
        parts.append(f"邮箱={identity.email_hint}")
    parts.append(f"入口={identity.source}")
    return (
        "【当前对话对象】" + "；".join(parts) + "。可自然称呼并按会员/角色调整话术（如权益说明），"
        "勿复读整段 ID/内部字段，勿向访客复述敏感信息。"
    )


# ─── 权限矩阵（SSOT，代码即契约）────────────────────────────────────
# external = 官网 / 未登录公开入口（corp-chat、官网浮窗）→ 仅公开库
# market_cs = 市场 AI 客服页 / 工作台客服 Bot → 仅公开库
# admin = 管理端内部主客服 → 公开库 + 内部库；禁止客户私有/桌面库

_PUBLIC_ONLY_KNOWLEDGE: Dict[str, Any] = {
    "read_persy": True,
    "write_persy": False,
    "dataset_id": PUBLIC_DATASET_ID,
    "public_dataset_id": PUBLIC_DATASET_ID,
    "internal_dataset_id": INTERNAL_DATASET_ID,
    "datasets": {
        "read": [PUBLIC_DATASET_ID],
        "write": [],
        "deny": list(_DENY_PRIVATE_LABELS),
    },
}

XIAOC_PERMISSIONS: Dict[str, Dict[str, Any]] = {
    "external": {
        "label": "外部小C（官网公开）",
        "auth": "none",
        "knowledge": copy.deepcopy(_PUBLIC_ONLY_KNOWLEDGE),
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
            "仅基于公开库（persy-knowledge）只读摘录回答",
            "报价口径：需定制，引导留资（不编造合同金额）",
        ],
        "denied": [
            "浏览器工具调用（跳转/点击/填表/滚动/读页）",
            "vibe-coding / 改 Mod/工作流/员工",
            "支付、退款、下架、改价、改权限",
            "读取他人订单/隐私数据",
            "编造未公示资质/合同金额",
            "读取内部库 xiaoc-internal",
            "读取客户私有库 / 企业桌面私有库",
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
        "knowledge": copy.deepcopy(_PUBLIC_ONLY_KNOWLEDGE),
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
            "仅基于公开库只读摘录回答产品问题",
        ],
        "denied": [
            "直接执行退款/下架",
            "页面自动化工具",
            "管理端运维操作",
            "读取内部库 xiaoc-internal",
            "读取客户私有库 / 企业桌面私有库",
        ],
        "limits": {
            "max_reply_chars": 600,
            "llm_tools": False,
        },
    },
    "admin": {
        "label": "管理端小C（内部主客服）",
        "auth": "login",
        "knowledge": {
            "read_persy": True,
            "write_persy": True,  # 写走知识库 UI/API；对话侧保证检索边界
            "dataset_id": PUBLIC_DATASET_ID,
            "public_dataset_id": PUBLIC_DATASET_ID,
            "internal_dataset_id": INTERNAL_DATASET_ID,
            "datasets": {
                "read": [PUBLIC_DATASET_ID, INTERNAL_DATASET_ID],
                "write": [PUBLIC_DATASET_ID, INTERNAL_DATASET_ID],
                "deny": ["user_*", "desktop_private", "tenant_private"],
            },
        },
        "tools": {
            "navigate": True,  # low
            "read_page": True,  # low
            "scroll": True,  # low
            "click": True,  # medium — 需预览确认
            "fill": True,  # medium — 需预览确认
            "enhance_current_page": True,  # high — 须明确确认
            "get_my_account_snapshot": True,  # admin only, self
            "get_my_wallet": True,
            "get_my_orders": True,
            "get_my_tickets": True,
            "get_ops_update_brief": True,
            "wallet_pay": False,  # 只引导到充值页，不代付
            "refund": False,
            "admin_ops": False,
        },
        "allowed": [
            "全站导航与页面摘要",
            "搜索/推荐 AI 员工",
            "引导充值与会员购买（不代付）",
            "在用户明确意图下发起 vibe-coding（高风险确认）",
            "检索公开库 + 内部库并回答",
            "管理员会话：本人账户/钱包/订单/工单只读摘要",
            "管理员会话：日更与 release_train 更新推送（只读）",
        ],
        "denied": [
            "未确认的高风险改文件/支付",
            "直接退款或后台运维危险操作",
            "查询他人账户/订单/工单",
            "触发 all-hands 重算或其它写操作运维",
            "读取客户私有库 / 企业桌面私有库",
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
                "get_my_account_snapshot",
                "get_my_wallet",
                "get_my_orders",
                "get_my_tickets",
                "get_ops_update_brief",
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
    raw = XIAOC_PERMISSIONS[key]
    policy = dict(raw)
    # 深拷贝 knowledge，避免调用方改坏 SSOT
    kn = dict(raw.get("knowledge") or {})
    ds = dict(kn.get("datasets") or {})
    kn["datasets"] = {
        "read": list(ds.get("read") or []),
        "write": list(ds.get("write") or []),
        "deny": list(ds.get("deny") or []),
    }
    policy["knowledge"] = kn
    policy["mode"] = key
    policy["ssot"] = {
        "brain": "admin_xiaoc_butler",
        "knowledge": {
            "public": PUBLIC_DATASET_ID,
            "internal": INTERNAL_DATASET_ID,
            "private": "enterprise_desktop_only",
        },
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
7. 管理员会话：可用只读工具核对本人账户/会员/钱包/订单/工单，并用 get_ops_update_brief 播报最近日更与版本更新（运维客服风格）

操作原则：低风险直接执行；中风险展示预览；高风险必须用户明确确认。
只读工具仅限当前登录用户本人数据，禁止查他人；勿代付/退款/改权限。
知识库：可引用【公开库】与【内部库】摘录；禁止客户私有库/企业桌面私有库。
若下方提供了知识库摘录，优先依据摘录回答，不要编造未出现的价格/合同/资质。
若下方提供了「当前对话对象」，可自然称呼，勿复读 ID/内部字段。
"""

XIAOC_CORP_DUTIES = """你同时是成都修茈科技有限公司官网对外客服（小C）。

你能做的事：
- 介绍修茈科技、XCAGI、行业 Mod、AI 员工、修茈 AI 市场、客来来及公开解决方案
- 引导用户去产品中心、解决方案、客户案例、联系我们、AI 市场（/market/）
- 价格/报价问题说明需根据场景定制，引导填写联系表单或登录 AI 市场查看会员方案

限制：
- 不要假装能操作用户浏览器、不要执行跳转/点击/填表等工具
- 不要编造具体合同金额或未公示的资质证照
- 客来来是联合发布的独立产品品牌，不得称为“修茈科技旗下产品”或单方自有产品
- 未经项目确认，不得把“可配置、可评估”的方案能力描述成已经自动打通或已经上线
- 回复控制在 200 字以内
- 可提供相对路径链接，如 /contact.html、/services.html、/market/
- 知识库仅公开库只读；禁止内部库与客户私有/桌面库
- 若下方提供了「公开库」摘录，优先依据摘录回答
- 若下方提供了「当前对话对象」，可自然称呼，勿复读 ID/内部字段
"""

XIAOC_MARKET_CS_DUTIES = """你是市场侧客服入口的小C（与管理端小C同源）。

你能做的事：
- 处理投诉申诉、订单退款咨询、上架审核、账号与购买权益问题（只建工单/给口径，不直接退款或下架）
- 回答产品/使用问题，优先依据公开库摘录
- 引导用户补充订单号、商品 ID、证据链接

限制：
- 无页面自动化工具，不代付、不直接退款
- 不要承诺已退款或已下架
- 口径与官网/管理端小C一致，不要自称另一套客服系统
- 知识库仅公开库只读；禁止内部库与客户私有/桌面库
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


def _dataset_label(dataset_id: str) -> str:
    did = (dataset_id or "").strip()
    if did == PUBLIC_DATASET_ID:
        return "公开库"
    if did == INTERNAL_DATASET_ID:
        return "内部库"
    return did or "知识库"


def is_private_dataset_id(dataset_id: str) -> bool:
    did = (dataset_id or "").strip().lower()
    if not did:
        return False
    if did in {"desktop_private", "tenant_private"}:
        return True
    return did.startswith(_PRIVATE_DATASET_PREFIXES)


def dataset_allowed_for_mode(dataset_id: str, *, mode: str = "admin") -> bool:
    """Web 小C 硬边界：非 admin 禁内部库；所有 Web 模式禁客户私有/桌面库。"""
    did = (dataset_id or "").strip()
    if not did or is_private_dataset_id(did):
        return False
    key = permission_policy(mode=mode).get("mode") or "admin"
    if did == INTERNAL_DATASET_ID and key != "admin":
        return False
    allowed = list(
        (permission_policy(mode=key).get("knowledge") or {}).get("datasets", {}).get("read") or []
    )
    return did in allowed


def format_knowledge_block(
    chunks: List[Dict[str, Any]],
    *,
    limit: int = 5,
    title: Optional[str] = None,
) -> str:
    if not chunks:
        return ""
    head_title = title or "【公开库·persy-knowledge】回答时优先依据以下摘录："
    lines = [head_title]
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


def _http_retrieve(
    query: str, *, top_k: int, dataset_id: str = PUBLIC_DATASET_ID
) -> List[Dict[str, Any]]:
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
                    "dataset_id": dataset_id or PUBLIC_DATASET_ID,
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


def _local_retrieve(
    query: str, *, top_k: int, dataset_id: str = PUBLIC_DATASET_ID
) -> List[Dict[str, Any]]:
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
            candidate_k = min(50, max(12, top_k * 3))
            target_dataset_id = dataset_id or PUBLIC_DATASET_ID
            query_kwargs: Dict[str, Any] = {
                "dataset_id": target_dataset_id,
                "query": query,
                "top_k": candidate_k,
                "rerank": True,
                "access_context": access,
            }
            if target_dataset_id == PUBLIC_DATASET_ID:
                query_kwargs.update(public_query_kwargs())
            result = get_dataset_rag_app_service().query(**query_kwargs)
            chunks = result.get("chunks") if isinstance(result, dict) else []
            return list(chunks[:top_k]) if isinstance(chunks, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.debug("cs-ssot local retrieve failed via %s: %s", root, exc)
            continue
    return []


def retrieve_dataset_knowledge(
    query: str, *, dataset_id: str, top_k: int = 5
) -> List[Dict[str, Any]]:
    """Fail-open 检索指定 dataset（不做 mode 校验；调用方须先 allowed）。"""
    q = (query or "").strip()
    did = (dataset_id or "").strip()
    if not q or not did or is_private_dataset_id(did):
        return []
    k = max(1, min(int(top_k or 5), 12))
    chunks = _http_retrieve(q, top_k=k, dataset_id=did)
    if chunks:
        return chunks
    return _local_retrieve(q, top_k=k, dataset_id=did)


def retrieve_persy_knowledge(query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
    """兼容旧调用：等同公开库检索。"""
    return retrieve_dataset_knowledge(query, dataset_id=PUBLIC_DATASET_ID, top_k=top_k)


def retrieve_knowledge_for_mode(
    query: str, *, mode: str = "admin", top_k: int = 5
) -> List[Dict[str, Any]]:
    """按身份 mode 检索允许的知识库，并标注 dataset_id。"""
    q = (query or "").strip()
    if not q:
        return []
    policy = permission_policy(mode=mode)
    read_ids = list((policy.get("knowledge") or {}).get("datasets", {}).get("read") or [])
    k = max(1, min(int(top_k or 5), 12))
    out: List[Dict[str, Any]] = []
    per_ds = max(1, (k + max(len(read_ids), 1) - 1) // max(len(read_ids), 1))
    for did in read_ids:
        if not dataset_allowed_for_mode(did, mode=policy.get("mode") or mode):
            continue
        chunks = retrieve_dataset_knowledge(q, dataset_id=did, top_k=per_ds)
        if did == PUBLIC_DATASET_ID:
            chunks = [chunk for chunk in chunks if is_published_public_chunk(chunk)]
        for c in chunks:
            if not isinstance(c, dict):
                continue
            item = dict(c)
            item["dataset_id"] = did
            item["_kb_label"] = _dataset_label(did)
            out.append(item)
            if len(out) >= k:
                return out
    return out


_is_published_public_chunk = is_published_public_chunk


def knowledge_block_for_query(query: str, *, top_k: int = 5, mode: str = "external") -> str:
    """按 mode 组装知识库摘录块（默认偏保守：仅公开库）。"""
    chunks = retrieve_knowledge_for_mode(query, mode=mode, top_k=top_k)
    if not chunks:
        return ""
    # 按库分组打标
    by_ds: Dict[str, List[Dict[str, Any]]] = {}
    for c in chunks:
        did = str(c.get("dataset_id") or PUBLIC_DATASET_ID)
        by_ds.setdefault(did, []).append(c)
    parts: List[str] = []
    for did, items in by_ds.items():
        label = _dataset_label(did)
        title = f"【{label}·{did}】回答时优先依据以下摘录："
        block = format_knowledge_block(items, limit=top_k, title=title)
        if block:
            parts.append(block)
    return "\n\n".join(parts)


def last_user_text(messages: Optional[List[Any]]) -> str:
    if not messages:
        return ""
    for item in reversed(list(messages)):
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if role is None and isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        if str(role or "") != "user":
            continue
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, dict) and str(part.get("type") or "") == "text":
                    parts.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    parts.append(part)
            return " ".join(p for p in parts if p).strip()
        return str(content or "").strip()
    return ""


__all__ = [
    "PUBLIC_DATASET_ID",
    "INTERNAL_DATASET_ID",
    "PERSY_DATASET_ID",
    "XIAOC_PERMISSIONS",
    "VisitorIdentity",
    "permission_policy",
    "xiaoc_system_prompt",
    "format_knowledge_block",
    "format_visitor_block",
    "identity_from_guest",
    "identity_from_user",
    "resolve_user_identity",
    "active_plan_id_for_user",
    "sanitize_visitor_id",
    "sanitize_visitor_label",
    "mask_email",
    "is_private_dataset_id",
    "dataset_allowed_for_mode",
    "retrieve_dataset_knowledge",
    "retrieve_knowledge_for_mode",
    "retrieve_persy_knowledge",
    "knowledge_block_for_query",
    "last_user_text",
]
