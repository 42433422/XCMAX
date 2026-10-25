"""小C 客服 SSOT：人设 + 知识库三档隔离检索。

SSOT 口径（2026-07）：
- 大脑：管理端小C（MODstore butler）/ 官网 corp-chat
- 公开库：persy-knowledge（官网/市场客服只读）
- 内部库：xiaoc-internal（仅管理端小C 可读可写策略）
- 客户私有库：仅企业桌面端；Web 小C 禁止触及
- 客来来暂不纳入
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.operational_errors import BOUNDARY_ERRORS
from modstore_server.xiaoc_identity import (
    VisitorIdentity,
    active_plan_id_for_user,
    format_visitor_block,
    identity_from_guest,
    identity_from_user,
    mask_email,
    resolve_user_identity,
    sanitize_visitor_id,
    sanitize_visitor_label,
)
from modstore_server.xiaoc_policy_data import (
    _PRIVATE_DATASET_PREFIXES,
    INTERNAL_DATASET_ID,
    PERSY_DATASET_ID,
    PUBLIC_DATASET_ID,
    XIAOC_PERMISSIONS,
)

logger = logging.getLogger(__name__)


# ─── 权限矩阵（SSOT，代码即契约）────────────────────────────────────
# external = 官网 / 未登录公开入口（corp-chat、官网浮窗）→ 仅公开库
# market_cs = 市场 AI 客服页 / 工作台客服 Bot → 仅公开库
# admin = 管理端内部主客服 → 公开库 + 内部库；禁止客户私有/桌面库


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
    return f"【权限契约·{p.get('label')}】\n允许：{allowed}\n禁止：{denied}"


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
- 介绍修茈科技的产品（AI Excel 单据识别、标签打印、MODstore 智能体市场、XCAGI 工作台等）
- 引导用户去产品中心、解决方案、客户案例、联系我们、AI 市场（/market/）
- 价格/报价问题说明需根据场景定制，引导填写联系表单或登录 AI 市场查看会员方案

限制：
- 不要假装能操作用户浏览器、不要执行跳转/点击/填表等工具
- 不要编造具体合同金额或未公示的资质证照
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
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        logger.debug("cs-ssot http retrieve failed: %s", exc)
        return []
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.debug("cs-ssot http non-2xx status=%s", resp.status_code)
        return []
    try:
        data = resp.json()
    except BOUNDARY_ERRORS:  # noqa: BLE001
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
    except BOUNDARY_ERRORS:  # noqa: BLE001
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
                dataset_id=dataset_id or PUBLIC_DATASET_ID,
                query=query,
                top_k=top_k,
                access_context=access,
            )
            chunks = result.get("chunks") if isinstance(result, dict) else []
            return list(chunks) if isinstance(chunks, list) else []
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001
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
