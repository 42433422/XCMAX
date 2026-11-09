"""Prepare owner-scoped history and tenant-scoped knowledge for a chat turn."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import Request

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_DATASETS = ("persy-knowledge", "office-docking")
_CUSTOMER_LOOKUP = re.compile(
    r"(?:查一下|查下|查询|查看|查)\s*([\u4e00-\u9fffA-Za-z0-9]{2,8}?)(?:那个|这个|的)(?:账单|订单|单据|产品)"
)


def customer_name_question(message: str, context: dict[str, Any]) -> str:
    """Ask before substituting a similar customer named earlier in this conversation."""
    target = _CUSTOMER_LOOKUP.search(message)
    if not target:
        return ""
    name = target.group(1)
    candidates: set[str] = set()
    for row in context.get("recent_messages") or []:
        if not isinstance(row, dict) or row.get("role") != "user":
            continue
        text = str(row.get("content") or "")
        for match in re.finditer(
            r"(?:^|[，。！？\s])([\u4e00-\u9fffA-Za-z0-9]{2,8}?)(?:的)?(?:产品|订单|账单|客户)",
            text,
        ):
            candidates.add(match.group(1))
    if name in candidates:
        return ""
    similar = sorted(
        value
        for value in candidates
        if len(name) == len(value)
        and len(name) >= 2
        and name[-1] == value[-1]
        and sum(a != b for a, b in zip(name, value, strict=True)) == 1
    )
    if len(similar) != 1:
        return ""
    return f"你说的「{name}」是之前提到的「{similar[0]}」吗？请回复正确的客户名称和查询需求。"


def prepare_chat_evidence(
    request: Request, context: dict[str, Any], message: str
) -> dict[str, Any]:
    """Resolve evidence from authenticated server state, never from client claims."""
    from app.application.task_conversation_store import durable_user_id, task_conversation_store
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request

    result = dict(context)
    result.pop("chat_knowledge_evidence", None)
    result.pop("chat_memory_evidence", None)
    result.pop("recent_messages", None)
    result.pop("chat_owned_history", None)
    result.pop("chat_independent_knowledge_query", None)
    owner = durable_user_id(context.get("local_user_id"))
    session = str(context.get("session_id") or context.get("conversation_id") or "").strip()
    tenant = str(context.get("tenant_id") or "").strip()
    if not owner or not tenant:
        return result
    if session:
        try:
            history = task_conversation_store.get_conversation(session_id=session, user_id=owner)
            owned_history = [
                {
                    "role": "assistant" if item.get("role") == "ai" else item.get("role"),
                    "content": str(item.get("content") or "")[:2000],
                }
                for item in (history.get("messages") or [])[-24:]
                if isinstance(item, dict) and item.get("role") in {"user", "assistant", "ai"}
            ]
            result["chat_owned_history"] = owned_history
            result["recent_messages"] = owned_history[-12:]
        except RECOVERABLE_ERRORS:
            logger.warning("chat history unavailable", exc_info=True)
        try:
            from app.application.agent_task_context import scoped_conversation_user_id
            from app.application.ai_chat.conversation_history import authorized_memory_context

            scoped_user = scoped_conversation_user_id(str(owner), context)
            if authorized_memory_context(scoped_user, context) is not None:
                from app.application.user_memory_vector_app_service import (
                    get_user_memory_rag_app_service,
                )
                from app.domain.shared_services.user_memory_service import get_user_memory_service

                rag = get_user_memory_rag_app_service()
                hits = rag.query(user_id=scoped_user, query_text=message, top_k=3).get("hits") or []
                summaries = []
                if hits:
                    summaries.append(
                        rag.format_for_prompt(
                            user_id=scoped_user, query_text=message, hits=hits, max_hits=3
                        )
                    )
                confirmed = get_user_memory_service().format_memory_v2_for_prompt(
                    user_id=scoped_user, max_items=6
                )
                if confirmed and "无已确认记忆" not in confirmed:
                    summaries.append(confirmed)
                result["chat_memory_evidence"] = "\n".join(summaries)[:3000]
        except RECOVERABLE_ERRORS:
            logger.warning("chat personal memory recall unavailable", exc_info=True)
    try:
        access = dataset_access_context_from_request(request)
        if not access or str(access.actor_id) != str(owner) or str(access.tenant_id) != tenant:
            return result
        try:
            from app.application.persy_memory_app_service import get_persy_memory_app_service

            recalled = get_persy_memory_app_service().query(
                access_context=access, query=message[:4000], top_k=5, reinforce=False
            )
            memories = recalled.get("memories") if recalled.get("success") else []
            if memories:
                prior = str(result.get("chat_memory_evidence") or "")
                statements = [
                    str(item.get("statement") or "")[:500]
                    for item in memories
                    if isinstance(item, dict)
                ]
                result["chat_memory_evidence"] = (prior + "\n" + "\n".join(statements))[:3000]
        except RECOVERABLE_ERRORS:
            logger.warning("chat confirmed memory recall unavailable", exc_info=True)
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        service = get_dataset_rag_app_service()
        evidence: list[dict[str, Any]] = []
        for dataset in _DATASETS:
            response = service.query(
                dataset_id=dataset,
                query=message[:4000],
                top_k=4,
                tenant_id=tenant,
                access_context=access,
                include_sheet_context=True,
            )
            if not response.get("success"):
                continue
            for sheet in response.get("sheet_contexts") or []:
                if isinstance(sheet, dict) and sheet.get("text"):
                    evidence.append(
                        {
                            "dataset": dataset,
                            "source": str(sheet.get("source") or "")[:200],
                            "sheet": str(sheet.get("sheet") or "")[:200],
                            "text": str(sheet["text"])[:8000],
                            "truncated": bool(sheet.get("truncated"))
                            or len(str(sheet["text"])) > 8000,
                        }
                    )
            for item in response.get("chunks") or []:
                if isinstance(item, dict) and str(item.get("text") or "").strip():
                    raw_metadata = item.get("metadata")
                    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                    evidence.append(
                        {
                            "dataset": dataset,
                            "source": str(metadata.get("source") or item.get("source") or "")[:200],
                            "sheet": str(metadata.get("sheet_context") or "")[:200],
                            "text": str(item["text"])[:1800],
                        }
                    )
        # An explicitly named worksheet is a stronger scope than a shared
        # workbook filename. Do not mix sibling worksheets into that answer.
        named_sheets = {
            sheet.removeprefix("片段含工作表边界：").strip()
            for item in evidence
            if (sheet := item.get("sheet", ""))
            and "、" not in sheet
            and sheet.removeprefix("片段含工作表边界：").strip() in message
        }
        if named_sheets and not re.search(r"所有工作表|全部工作表|整本工作簿", message):
            evidence = [
                item
                for item in evidence
                if not item.get("sheet")
                or item["sheet"].removeprefix("片段含工作表边界：").strip() in named_sheets
            ]
            for item in evidence:
                sheet = item.get("sheet", "")
                if sheet.startswith("片段含工作表边界："):
                    marker = "# sheet:" + sheet.removeprefix("片段含工作表边界：").strip()
                    start = item["text"].find(marker)
                    if start >= 0:
                        item["text"] = item["text"][start:]
            result["chat_independent_knowledge_query"] = not bool(
                re.search(r"刚才|之前|上次|上面|那个|这个|它的|上述", message)
            )
        result["chat_knowledge_evidence"] = evidence[:8]
    except RECOVERABLE_ERRORS:
        logger.warning("chat knowledge recall unavailable", exc_info=True)
    return result


def use_contextual_reply(slot: dict[str, Any], context: dict[str, Any], message: str = "") -> bool:
    """Allow the model to use evidence instead of a generic early response."""
    raw_data = slot.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    intent = data.get("intent")
    return bool(
        (
            context.get("recent_messages")
            and re.search(
                r"(?:刚才|之前|上次|上面).{0,12}(?:问|说|提)|(?:问|说|提).{0,12}(?:刚才|之前|上次|上面)|(?:那个|这个|它的|他的|她的|上述|刚才那)",
                message,
            )
            and not re.search(r"删除|修改|新增|保存|导入|发货|下单|开单|打印", message)
        )
        or intent == "knowledge_query"
        or (
            intent == "product_query"
            and data.get("query_status") == "succeeded"
            and data.get("result_count") == 0
            and context.get("chat_knowledge_evidence")
        )
        or (
            intent == "clarify"
            and (
                context.get("recent_messages")
                or context.get("chat_knowledge_evidence")
                or context.get("chat_memory_evidence")
            )
        )
    )
