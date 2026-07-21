"""小C 客服 SSOT：人设 + 管理端 persy-knowledge 检索。

SSOT 口径（2026-07）：
- 大脑：管理端小C（MODstore butler chat / corp-chat）
- 知识库：FHD 管理端 persy-knowledge（经 /api/ops/autonomy/cs-ssot/retrieve）
- 客来来暂不纳入
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PERSY_DATASET_ID = "persy-knowledge"

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
"""


def xiaoc_system_prompt(*, mode: str = "admin") -> str:
    if mode == "corp":
        return XIAOC_CORE_PERSONA + "\n" + XIAOC_CORP_DUTIES
    return XIAOC_CORE_PERSONA + "\n" + XIAOC_ADMIN_DUTIES


def format_knowledge_block(chunks: List[Dict[str, Any]], *, limit: int = 5) -> str:
    if not chunks:
        return ""
    lines = ["【管理端知识库·persy-knowledge】回答时优先依据以下摘录："]
    for i, chunk in enumerate(chunks[:limit], 1):
        if not isinstance(chunk, dict):
            continue
        text = str(
            chunk.get("text")
            or chunk.get("content")
            or chunk.get("snippet")
            or ""
        ).strip()
        if not text:
            continue
        source = str(
            chunk.get("source")
            or chunk.get("document_id")
            or chunk.get("filename")
            or ""
        ).strip()
        head = f"{i}. ({source}) " if source else f"{i}. "
        lines.append(head + text[:800])
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def _http_retrieve(query: str, *, top_k: int) -> List[Dict[str, Any]]:
    base = (
        os.environ.get("FHD_API_BASE_URL")
        or os.environ.get("XCAGI_FHD_API_BASE")
        or ""
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
                permissions=frozenset(
                    {DATASET_READ_PERMISSION, DATASET_ADMIN_PERMISSION}
                ),
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
    "xiaoc_system_prompt",
    "format_knowledge_block",
    "retrieve_persy_knowledge",
    "knowledge_block_for_query",
    "last_user_text",
]
