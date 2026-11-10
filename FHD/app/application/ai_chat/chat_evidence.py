"""Prepare owner-scoped history and tenant-scoped knowledge for a chat turn."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from fastapi import Request

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_DATASET_QUERY_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-knowledge")
_PREPARED_EVIDENCE = object()
_KNOWLEDGE_QUERY = re.compile(
    r"(?:查(?:一下|下|询|看)?|搜索|找一下|有哪些|是什么|多少|谁是|介绍一下|说明一下|"
    r"怎么(?:办|用|做|使用|操作)|如何(?:使用|操作)|使用指南|操作手册|为什么|是否|有没有|能不能|可以吗|产品|客户|订单|账单|库存|"
    r"报价|合同|业务文档|知识库).{0,40}(?:[？?]|$|产品|客户|订单|账单|库存|报价|合同|文档|知识|"
    r"有哪些|是什么|多少|怎么|如何)|(?:[？?]|有哪些|是什么|多少|谁是|有没有)"
    r"|(?:知识库|知识网络|业务文档|操作手册|使用说明|使用指南|制度|政策|规范|流程).{0,40}(?:怎么|如何|什么|哪些|步骤|流程|使用|说明|查询|$)"
)
_WRITE_REQUEST = re.compile(r"(?:删除|修改|新增|保存|导入|入库|出库|发货|下单|开单|审批|执行|创建)")
_CONVERSATION_FOLLOWUP = re.compile(r"(?:刚才|之前|上次|上面|你记得|记不记得|我叫|我的名字|偏好)")
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
    if context.get("_chat_evidence_prepared_marker") is _PREPARED_EVIDENCE:
        return dict(context)
    from app.application.task_conversation_store import durable_user_id, task_conversation_store
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request

    result = dict(context)
    result.pop("chat_knowledge_evidence", None)
    result.pop("chat_memory_evidence", None)
    result.pop("_chat_memory_evidence_authorized", None)
    result.pop("recent_messages", None)
    result.pop("chat_owned_history", None)
    result.pop("chat_independent_knowledge_query", None)
    result.pop("_chat_evidence_authorized", None)
    result.pop("_chat_evidence_prepared_marker", None)
    owner = durable_user_id(context.get("local_user_id"))
    session = str(context.get("session_id") or context.get("conversation_id") or "").strip()
    tenant = str(context.get("tenant_id") or "").strip()
    if not owner:
        return result
    if not session:
        # Some desktop callers omit the optional conversation id on follow-up
        # calls. Recover only the authenticated owner's active session so we
        # keep history useful without using a client-supplied user id as owner.
        try:
            from app.application.ai_chat.active_conversation import active_conversation_for

            session = active_conversation_for(
                owner,
                tenant_id=tenant,
                mod_id=str(context.get("mod_id") or context.get("active_mod_id") or ""),
            )
            if session:
                result["conversation_id"] = session
        except RECOVERABLE_ERRORS:
            logger.warning("active chat session unavailable", exc_info=True)
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
        authorized_memory = authorized_memory_context(scoped_user, context)
        if authorized_memory is not None:
            memory_user_id, _memory_access = authorized_memory
            result["_chat_memory_evidence_authorized"] = True
            from app.application.user_memory_vector_app_service import (
                get_user_memory_rag_app_service,
            )
            from app.domain.shared_services.user_memory_service import get_user_memory_service

            rag = get_user_memory_rag_app_service()
            hits = rag.query(user_id=memory_user_id, query_text=message, top_k=3).get("hits") or []
            # Read the prior session-scoped index during migration. New turns are
            # written to the stable owner namespace by persist_recallable_chat_turn.
            if scoped_user != memory_user_id:
                old_hits = (
                    rag.query(user_id=scoped_user, query_text=message, top_k=3).get("hits") or []
                )
                merged = {
                    str(hit.get("chunk_id") or f"stable:{index}"): hit
                    for index, hit in enumerate(hits)
                    if isinstance(hit, dict)
                }
                for index, hit in enumerate(old_hits):
                    if isinstance(hit, dict):
                        merged.setdefault(str(hit.get("chunk_id") or f"legacy:{index}"), hit)
                hits = sorted(
                    merged.values(), key=lambda hit: float(hit.get("score") or 0), reverse=True
                )[:3]
            summaries = []
            if hits:
                summaries.append(
                    rag.format_for_prompt(
                        user_id=scoped_user, query_text=message, hits=hits, max_hits=3
                    )
                )
            confirmed = get_user_memory_service().format_memory_v2_for_prompt(
                user_id=str(owner), max_items=6
            )
            if confirmed and "无已确认记忆" not in confirmed:
                summaries.append(confirmed)
            result["chat_memory_evidence"] = "\n".join(summaries)[:3000]
    except RECOVERABLE_ERRORS:
        logger.warning("chat personal memory recall unavailable", exc_info=True)
    if not tenant:
        return result
    try:
        access = dataset_access_context_from_request(request)
        if not access or str(access.actor_id) != str(owner) or str(access.tenant_id) != tenant:
            return result
        result["_chat_evidence_authorized"] = True
        result["_chat_memory_evidence_authorized"] = True
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
        if (
            not _KNOWLEDGE_QUERY.search(message)
            or _WRITE_REQUEST.search(message)
            or _CONVERSATION_FOLLOWUP.search(message)
        ):
            return result
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        service = get_dataset_rag_app_service()
        evidence: list[dict[str, Any]] = []
        catalog = service.status(
            tenant_id=tenant,
            access_context=access,
            include_documents=False,
        )
        datasets = catalog.get("datasets") if catalog.get("success") else {}
        eligible = sorted(
            str(dataset_id)
            for dataset_id, info in (datasets.items() if isinstance(datasets, dict) else [])
            if isinstance(info, dict) and int(info.get("document_count") or 0) > 0
        )[:16]

        def query_dataset(dataset: str) -> tuple[str, dict[str, Any]]:
            response = service.query(
                dataset_id=dataset,
                query=message[:4000],
                top_k=4,
                tenant_id=tenant,
                access_context=access,
                include_sheet_context=True,
            )
            return dataset, response

        futures = [_DATASET_QUERY_POOL.submit(query_dataset, dataset) for dataset in eligible]
        responses: dict[str, dict[str, Any]] = {}
        completed, _pending = wait(futures, timeout=4.0)
        for future in completed:
            try:
                dataset, response = future.result()
            except RECOVERABLE_ERRORS:
                logger.warning("chat dataset query failed", exc_info=True)
                continue
            responses[dataset] = response
        result["chat_knowledge_dataset_ids"] = [
            dataset
            for dataset in eligible
            if isinstance(responses.get(dataset), dict)
            and responses[dataset].get("success") is True
        ]
        for dataset in eligible:
            dataset_response = responses.get(dataset)
            if not isinstance(dataset_response, dict) or not dataset_response.get("success"):
                continue
            for sheet in dataset_response.get("sheet_contexts") or []:
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
    result["_chat_evidence_prepared_marker"] = _PREPARED_EVIDENCE
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
