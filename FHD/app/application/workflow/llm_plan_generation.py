"""LLM plan generation through typed conversation/transport ports."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any, Protocol, cast

import httpx

from app.application.workflow.planner_prompt_profile import (
    select_rules_for_prompt,
    select_tools_for_prompt,
)
from app.application.workflow.workflow_types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    normalize_workflow_risk,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_MODEL_SECRET_TEXT = re.compile(
    r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|密码|口令)\b\s*[:=]\s*)([^\s,;]+)|"
    r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+"
)
# 模型偶尔在 JSON 字符串值里输出裸控制字符（\x00-\x1f），json.loads 会直接拒绝。
_BARE_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_model_json(raw: str) -> str:
    """清洗模型输出中的裸控制字符，保留换行与制表符，避免合法计划被误拒。"""
    return _BARE_CONTROL_CHARS.sub("", raw)


_MODEL_CONTEXT_PRIVATE_KEYS = (
    "authorization",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "credential",
    "cookie",
    "session",
    "conversation_id",
    "turn_id",
    "idempotency",
    "user_id",
    "actor_id",
    "tenant_id",
    "workspace_id",
    "permission",
    "secret",
    "token",
)
_MODEL_CONTEXT_MAX_CHARS = 24_000
_MODEL_CONTEXT_PRIORITY_KEYS = (
    "chat_knowledge_evidence",
    "chat_knowledge_dataset_ids",
    "chat_customer_evidence",
    "chat_memory_evidence",
    "memory_v2",
    "user_memory_rag",
    "recent_messages",
    "available_employees",
    "chat_owned_history",
    "file_context",
    "file_analysis",
    "excel_analysis",
)


def _model_context_value(value: Any, _remaining: list[int] | None = None) -> Any:
    """Bound, redact, and strip identity/authority fields before model IO."""
    if _remaining is None:
        _remaining = [_MODEL_CONTEXT_MAX_CHARS]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        priority = {key: index for index, key in enumerate(_MODEL_CONTEXT_PRIORITY_KEYS)}
        entries = sorted(
            value.items(),
            key=lambda pair: (priority.get(str(pair[0]), len(priority)), str(pair[0])),
        )
        for raw_key, item in entries:
            key = str(raw_key)
            lowered = key.lower()
            if key.startswith("_") or any(part in lowered for part in _MODEL_CONTEXT_PRIVATE_KEYS):
                continue
            safe[key] = _model_context_value(item, _remaining)
        return safe
    if isinstance(value, list):
        return [_model_context_value(item, _remaining) for item in value[:200] if _remaining[0] > 0]
    if isinstance(value, str):
        if _remaining[0] <= 0:
            return ""
        bounded = value[: min(12_000, _remaining[0])]
        _remaining[0] -= len(bounded)
        return _MODEL_SECRET_TEXT.sub(
            lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", bounded
        )
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]


class ConversationHistory(Protocol):
    conversation_history: list[dict[str, Any]]


class PlannerConversation(Protocol):
    def get_context(self, user_id: str) -> ConversationHistory | None: ...


class PlannerCompletion(Protocol):
    def __call__(
        self,
        *,
        ai_service: PlannerConversation,
        context: dict[str, Any] | None,
        messages: list[dict[str, str]],
        http_client_factory: Callable[[], httpx.Client] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1200,
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...


# 纯闲聊/资料问答不需要业务工具：命中快路径时不再把完整工具目录塞进提示。
_CONVERSATIONAL_MAX_CHARS = 80
_BUSINESS_INTENT = re.compile(
    "查|统计|汇总|报表|导出|打印|生成|创建|新建|新增|修改|更新|删除|下单|开单|订单|客户|产品|型号|"
    "库存|仓库|发货|物流|收款|付款|退款|发票|合同|审批|员工|数据库|明细|金额|单价|数量|销售|采购|"
    "物料|供应商|表格|excel|Excel|文件|文档|数据集|sql|SQL|附件|上传|下载|导入|审核|识别|录入|同步|"
    "提交|扫描|图片|照片|ocr|OCR"
)
_LIGHT_SYSTEM = "你是平台对话助手。只输出约定 JSON。"


class _LightReplyUnavailable(Exception):
    """轻量轮次的模型调用已失败，不再重复调用完整规划。"""


_LIGHT_RULES = (
    "只输出 JSON，不要 markdown。",
    '闲聊、解释、总结、写作和通用问答返回 {"mode":"reply","reply":"..."}。',
    "reply 只能依据 user_message 与 context；不要假装查询过企业数据库。",
    '只要用户需要查询或操作企业数据、生成文件、调用工具，返回 {"mode":"workflow"}，不要输出 nodes，也不要编造结果。',
)

_PLAN_OUTPUT_SCHEMA_DOC: dict[str, Any] = {
    "mode": "reply|workflow",
    "reply": "string; mode=reply required, otherwise omit",
    "intent": "string",
    "todo_steps": ["string"],
    "risk_level": "low|medium|high",
    "nodes": [
        {
            "node_id": "string",
            "tool_id": "string",
            "action": "string",
            "params": {},
            "risk": "low|medium|high",
            "idempotent": "bool",
            "description": "string",
            "depends_on": ["node_id"],
            "next": "node_id or null",
            "branches": [
                {
                    "target": "node_id",
                    "condition": {"key": "result_field", "equals": "value"},
                }
            ],
        }
    ],
}

# 结构化输出校验（复用现有 jsonschema，不新增依赖）：workflow 必须有至少一个
# 可执行节点；reply 必须带非空正文且不能混入节点。
_PLAN_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["mode"],
    "properties": {
        "mode": {"type": "string", "enum": ["reply", "workflow"]},
        "reply": {"type": "string"},
        "intent": {"type": "string"},
        "todo_steps": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool_id", "action"],
                "properties": {
                    "node_id": {"type": "string"},
                    "tool_id": {"type": "string", "minLength": 1},
                    "action": {"type": "string", "minLength": 1},
                    "params": {"type": "object"},
                    "depends_on": {"type": "array"},
                    "branches": {"type": "array"},
                },
            },
        },
    },
    "allOf": [
        {
            "if": {"properties": {"mode": {"const": "workflow"}}, "required": ["mode"]},
            "then": {"required": ["nodes"], "properties": {"nodes": {"minItems": 1}}},
        },
        {
            "if": {"properties": {"mode": {"const": "reply"}}, "required": ["mode"]},
            "then": {
                "required": ["reply"],
                "properties": {"reply": {"minLength": 1}, "nodes": {"maxItems": 0}},
            },
        },
    ],
}

_SHAPE_REPAIR_RULES = (
    "只输出 JSON，不要 markdown。",
    "保留用户原始意图，只补全或修正结构，不要更换业务对象。",
    "mode=workflow 时必须给出至少一个 nodes；每个 node 必须有非空 tool_id 与 action，params 必须是对象。",
    "mode=reply 时必须给出非空 reply，且不能包含 nodes。",
    "无法在不臆造业务事实的前提下补全时，改为 mode=workflow 的 clarify.ask 节点提出具体澄清问题。",
)


def _conversational_turn(message: str, context: dict[str, Any]) -> bool:
    text = str(message or "").strip()
    if not text or len(text) > _CONVERSATIONAL_MAX_CHARS:
        return False
    if _BUSINESS_INTENT.search(text):
        return False
    # 企业资料/客户证据已召回，或带着附件，说明这一轮在问业务事实，交给完整规划。
    if context.get("chat_knowledge_evidence") or context.get("chat_customer_evidence"):
        return False
    if context.get("multimodal_attachments") or context.get("attachments"):
        return False
    return True


_JSON_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
}


def _reply_prefix(raw: str) -> str | None:
    """从尚不完整的 JSON 里取出 reply 字符串已到达的部分。"""
    mode = re.search(r'"mode"\s*:\s*"([^"]*)"', raw)
    if mode and mode.group(1).strip() != "reply":
        return None
    # 出现 nodes 说明模型走的是工作流分支，正文不是最终回答。
    if '"nodes"' in raw or '"tool_id"' in raw:
        return None
    key = re.search(r'"reply"\s*:\s*"', raw)
    if not key:
        return None
    out: list[str] = []
    index = key.end()
    while index < len(raw):
        char = raw[index]
        if char == "\\":
            if index + 1 >= len(raw):
                break
            nxt = raw[index + 1]
            if nxt == "u":
                if index + 6 > len(raw):
                    break
                try:
                    out.append(chr(int(raw[index + 2 : index + 6], 16)))
                except ValueError:
                    pass
                index += 6
                continue
            out.append(_JSON_ESCAPES.get(nxt, nxt))
            index += 2
            continue
        if char == '"':
            break
        out.append(char)
        index += 1
    return "".join(out)


async def _consume_reply_stream(stream, on_prefix: Callable[[str], None]) -> tuple[str, str]:
    """消费模型增量，确认是普通回复后把正文前缀实时推给前端。"""
    chunks: list[str] = []
    emitted_text = ""
    try:
        async for delta in stream:
            if not delta:
                continue
            chunks.append(delta)
            prefix = _reply_prefix("".join(chunks))
            if prefix is None or len(prefix) <= len(emitted_text):
                continue
            on_prefix(prefix[len(emitted_text) :])
            emitted_text = prefix
    except RECOVERABLE_ERRORS:  # 流中断：保留下发内容，交给已发送前缀收尾
        logger.warning("planner reply stream interrupted", exc_info=True)
    return "".join(chunks), emitted_text


def _memory_digest(context: dict[str, Any]) -> dict[str, str]:
    digest: dict[str, str] = {}
    for key in ("user_memory_rag", "memory_v2"):
        item = context.get(key)
        if isinstance(item, dict):
            summary = str(item.get("summary") or "").strip()
            if summary:
                digest[key] = summary[:1200]
    return digest


def _tool_specs(tool_registry: dict[str, Any]) -> list[dict[str, Any]]:
    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

    contracts = build_tool_specs_v2()
    result = []
    for tool_id, spec in tool_registry.items():
        actions = spec.get("actions", {})
        action_specs = []
        for name, metadata in actions.items():
            contract = contracts.get((str(tool_id), str(name)))
            raw_schema = getattr(contract, "input_schema", {})
            action_specs.append(
                {
                    "action": name,
                    "description": str(
                        getattr(contract, "description", "") or spec.get("description") or ""
                    )[:240],
                    "risk": metadata.get("risk", "low"),
                    "idempotent": bool(metadata.get("idempotent", False)),
                    "output_schema": getattr(contract, "output_schema", {}),
                    "required_params": metadata.get("required_params", []),
                    "input_schema": raw_schema,
                }
            )
        result.append(
            {
                "tool_id": tool_id,
                "description": spec.get("description", ""),
                "actions": action_specs,
            }
        )
    return result


def _load_model_json(raw: str) -> Any:
    """严格 JSON 优先；失败时用 json-repair 容忍模型常见截断/尾逗号。"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        try:
            from json_repair import loads as repair_loads
        except ImportError:
            return None
        try:
            return repair_loads(raw)
        except (ValueError, TypeError):
            return None


def _model_payload(response_data: dict[str, Any]) -> tuple[Any, str]:
    """返回（解析后的 JSON, 原始正文）；不校验业务结构。"""
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None, ""
    raw = str(message.get("content") or "").strip()
    if not raw:
        return None, ""
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return _load_model_json(_sanitize_model_json(raw)), raw


def model_plan_schema_error(payload: Any) -> str | None:
    """校验模型计划 JSON 的必需形状；合规返回 None，否则返回可回灌的错误描述。"""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # 运行环境缺依赖时保持原有行为（由调用方结构检查兜底）
        return None
    validator = Draft202012Validator(_PLAN_OUTPUT_JSON_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if not errors:
        return None
    first = errors[0]
    path = ".".join(str(part) for part in first.absolute_path) or "root"
    return f"{path}: {first.message}"


def _decode_completion(payload: dict[str, Any]) -> tuple[dict[str, Any], list[WorkflowNode]] | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    raw = str(message.get("content") or "").strip()
    if not raw:
        return None
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = _load_model_json(_sanitize_model_json(raw))
    if not isinstance(parsed, dict):
        return None
    mode = str(parsed.get("mode") or "workflow").strip().lower()
    if mode == "reply":
        response = str(parsed.get("reply") or "").strip()
        if (
            not response
            or len(response) > 12_000
            or parsed.get("nodes") not in (None, [])
            or message.get("tool_calls")
            or message.get("function_call")
        ):
            return None
        parsed["reply"] = response
        return parsed, [
            WorkflowNode(
                node_id="model_reply",
                tool_id="conversation",
                action="reply",
                params={"response": response},
                risk="low",
                idempotent=True,
                description="通过平台模型生成普通对话回复",
            )
        ]
    if mode != "workflow" or not isinstance(parsed.get("nodes"), list):
        return None
    nodes: list[WorkflowNode] = []
    for idx, node in enumerate(parsed["nodes"], start=1):
        if not isinstance(node, dict):
            return None
        params = node.get("params") or {}
        dependencies = node.get("depends_on") or []
        branches = node.get("branches") or []
        if (
            not isinstance(params, dict)
            or not isinstance(dependencies, list)
            or not isinstance(branches, list)
        ):
            return None
        parsed_branches: list[Branch] = []
        for branch in branches:
            if not isinstance(branch, dict):
                return None
            condition = branch.get("condition") or {}
            if not isinstance(condition, dict):
                return None
            parsed_branches.append(
                Branch(target=str(branch.get("target") or "").strip(), condition=condition)
            )
        nodes.append(
            WorkflowNode(
                node_id=str(node.get("node_id") or f"node_{idx}"),
                tool_id=str(node.get("tool_id") or ""),
                action=str(node.get("action") or ""),
                params=params,
                risk=normalize_workflow_risk(str(node.get("risk") or "low")),
                idempotent=bool(node.get("idempotent", False)),
                description=str(node.get("description") or ""),
                depends_on=[str(value) for value in dependencies],
                next=str(node.get("next") or "").strip() or None,
                branches=parsed_branches,
            )
        )
    return parsed, nodes


def build_plan_from_payload(
    *,
    plan_id: str,
    message: str,
    parsed: dict[str, Any],
    nodes: list[WorkflowNode],
    context: dict[str, Any] | None,
) -> PlanGraph:
    """把已解析的模型 JSON 收敛为 ``PlanGraph``；生成与修复共用同一收敛规则。"""
    user_memory_rag_summary = ""
    memory_v2_summary = ""
    if isinstance(context, dict):
        user_memory_rag = context.get("user_memory_rag")
        if isinstance(user_memory_rag, dict):
            user_memory_rag_summary = str(user_memory_rag.get("summary") or "").strip()
        memory_v2 = context.get("memory_v2")
        if isinstance(memory_v2, dict):
            memory_v2_summary = str(memory_v2.get("summary") or "").strip()
    return PlanGraph(
        plan_id=plan_id,
        intent=str(
            parsed.get("intent")
            or ("conversation_reply" if parsed.get("mode") == "reply" else "dynamic_workflow")
        ),
        todo_steps=[str(x) for x in parsed.get("todo_steps") or []],
        nodes=nodes,
        risk_level=normalize_workflow_risk(str(parsed.get("risk_level") or "low")),
        metadata={
            "planner": "llm",
            "response_mode": "reply" if parsed.get("mode") == "reply" else "workflow",
            **(
                {"reply": parsed["reply"]}
                if parsed.get("mode") == "reply"
                else {"message": message}
            ),
            "user_memory_rag_summary": user_memory_rag_summary,
            "memory_v2_summary": memory_v2_summary,
        },
    )


class LlmPlanGeneration:
    def __init__(
        self,
        conversation: PlannerConversation,
        completion: PlannerCompletion,
        http_client: Callable[[], httpx.Client],
    ) -> None:
        self.conversation = conversation
        self.completion = completion
        self.http_client = http_client

    def _stream_reply(
        self, messages: list[dict[str, str]], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """流式生成闲聊回复；无法流式或判定为工作流时返回 None 走原路径。"""
        from app.application.workflow.planner_llm_gateway import stream_planner_completion
        from app.infrastructure.chat_stream_lifetime import current_lifetime

        lifetime = current_lifetime.get()
        if lifetime is None:
            return None
        try:
            stream = stream_planner_completion(
                ai_service=self.conversation, context=context, messages=messages
            )
        except RECOVERABLE_ERRORS:
            logger.debug("planner streaming unavailable", exc_info=True)
            return None
        if stream is None:
            return None

        def emit(delta: str) -> None:
            lifetime.publish_delta(delta)

        try:
            from app.application.employee_runtime.agent_runner import _run_async

            text, streamed = _run_async(_consume_reply_stream(stream, emit))
        except RECOVERABLE_ERRORS:
            logger.warning("planner streaming failed, falling back", exc_info=True)
            return None
        if not text.strip():
            return None
        if streamed and not text.rstrip().endswith("}"):
            # 流被截断：以已下发内容为准，避免前端出现重复正文。
            text = json.dumps({"mode": "reply", "reply": streamed}, ensure_ascii=False)
        return {"choices": [{"message": {"content": text}}]}

    def _light_reply(self, plan_id: str, message: str, context: dict[str, Any]) -> PlanGraph | None:
        """闲聊轮次只带对话必需上下文，避免每轮重发整份工具目录。"""

        from app.application.ai_chat.dialogue_memory import recent_conversation_messages

        prompt: dict[str, Any] = {
            "task": "普通对话：直接回复；需要业务工具时返回 workflow。",
            "rules": list(_LIGHT_RULES),
            "user_message": message,
            "recent_messages": _model_context_value(recent_conversation_messages(context, limit=6)),
        }
        digest = _memory_digest(context)
        if digest:
            prompt["context"] = digest
        messages = [
            {"role": "system", "content": _LIGHT_SYSTEM},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        response = self._stream_reply(messages, context)
        if response is None:
            from app.application.workflow.retry_policy import (
                call_with_retry,
                is_transport_error,
                planner_retry_policy,
            )

            try:
                response = call_with_retry(
                    lambda: self.completion(
                        ai_service=self.conversation,
                        context=context,
                        messages=messages,
                        http_client_factory=self.http_client,
                    ),
                    policy=planner_retry_policy(),
                )
            except RECOVERABLE_ERRORS as exc:
                # 传输类错误重试耗尽：轻量轮次已失败，不再重复打完整规划，交由上层 fail-closed。
                if not is_transport_error(exc):
                    raise
                raise _LightReplyUnavailable from exc
        if response is None:
            # 模型调用本身失败：轻量轮次已经花掉一次调用，不再重复打一次完整规划。
            raise _LightReplyUnavailable
        decoded = _decode_completion(response)
        if decoded is None:
            return None
        parsed, nodes = decoded
        if str(parsed.get("mode") or "").strip().lower() != "reply":
            return None
        return PlanGraph(
            plan_id=plan_id,
            intent="conversation_reply",
            todo_steps=[],
            nodes=nodes,
            risk_level="low",
            metadata={
                "planner": "llm",
                "planning_tier": "light",
                "response_mode": "reply",
                "reply": parsed["reply"],
            },
        )

    def _repair_output_shape(
        self,
        *,
        plan_id: str,
        message: str,
        context: dict[str, Any],
        raw_content: str,
        error: str,
    ) -> PlanGraph | None:
        """一次有界的结构修复：把 schema 错误回灌给模型，要求补全计划 JSON。"""
        payload = {
            "task": "修复模型输出，使其满足计划 JSON schema；不得臆造业务事实。",
            "rules": list(_SHAPE_REPAIR_RULES),
            "error": _model_context_value(str(error or "")[:400]),
            "user_message": _model_context_value(str(message or "")[:2000]),
            "invalid_output": _model_context_value(str(raw_content or "")[:8000]),
            "output_schema": _PLAN_OUTPUT_SCHEMA_DOC,
        }
        messages = [
            {"role": "system", "content": "你是计划结构修复器，只输出约定 JSON。"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            response = self.completion(
                ai_service=self.conversation,
                context=context,
                messages=messages,
                http_client_factory=self.http_client,
                temperature=0.0,
            )
        except RECOVERABLE_ERRORS:
            logger.warning("计划结构修复请求失败", exc_info=True)
            return None
        if not isinstance(response, dict):
            return None
        decoded = _decode_completion(response)
        if decoded is None:
            return None
        parsed, nodes = decoded
        if model_plan_schema_error(parsed) is not None:
            return None
        return build_plan_from_payload(
            plan_id=plan_id,
            message=message,
            parsed=parsed,
            nodes=nodes,
            context=context,
        )

    def generate(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph | None:
        try:
            if _conversational_turn(message, context):
                try:
                    light = self._light_reply(plan_id, message, context)
                except _LightReplyUnavailable:
                    return None
                if light is not None:
                    return light
            tool_specs = _tool_specs(select_tools_for_prompt(tool_registry, message, context))
            recent_messages: list[dict[str, Any]] = []
            from app.application.ai_chat.dialogue_memory import recent_conversation_messages

            recent_messages.extend(recent_conversation_messages(context, limit=6))
            conv_ctx = self.conversation.get_context(user_id)
            if (
                not (context.get("session_id") or context.get("conversation_id"))
                and conv_ctx
                and conv_ctx.conversation_history
            ):
                recent_messages.extend(_model_context_value(conv_ctx.conversation_history[-6:]))
            deduplicated_messages: list[dict[str, Any]] = []
            seen_messages: set[str] = set()
            for item in recent_messages:
                if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                    continue
                signature = json.dumps(
                    [item.get("role"), item.get("content")],
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                if signature in seen_messages:
                    continue
                seen_messages.add(signature)
                deduplicated_messages.append(item)
            recent_messages = _model_context_value(deduplicated_messages[-6:])
            prompt = {
                "task": "根据用户输入和授权上下文，选择普通回复或生成完整业务工作流（JSON）。",
                "rules": select_rules_for_prompt(message, context),
                "user_message": message,
                "recent_messages": recent_messages,
                "context": _model_context_value(context),
                "tool_registry": tool_specs,
                "output_schema": _PLAN_OUTPUT_SCHEMA_DOC,
            }
            messages = [
                {
                    "role": "system",
                    "content": "你是平台对话与业务规划模型。根据用户输入选择普通回复或完整业务计划，只输出约定 JSON。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ]
            from app.application.workflow.tool_calling import (
                build_function_tools,
                plan_from_tool_calls,
                tool_calls_enabled,
                unsupported_tool_parameter,
            )

            native_tools: list[dict[str, Any]] = []
            native_lookup: dict[str, tuple[str, str]] = {}
            if tool_calls_enabled():
                native_tools, native_lookup = build_function_tools(tool_registry)
            extra: dict[str, Any] = (
                {"tools": native_tools, "tool_choice": "auto"} if native_tools else {}
            )
            from app.application.workflow.retry_policy import call_with_retry, planner_retry_policy

            policy = planner_retry_policy()
            response_data = self._stream_reply(messages, context)
            if response_data is None:
                try:
                    response_data = call_with_retry(
                        lambda: self.completion(
                            ai_service=self.conversation,
                            context=context,
                            messages=messages,
                            http_client_factory=self.http_client,
                            **extra,
                        ),
                        policy=policy,
                    )
                except TypeError as exc:
                    if not extra or not unsupported_tool_parameter(exc):
                        raise
                    # 兼容不接受额外参数的旧 completion 实现（含测试替身）。
                    response_data = call_with_retry(
                        lambda: self.completion(
                            ai_service=self.conversation,
                            context=context,
                            messages=messages,
                            http_client_factory=self.http_client,
                        ),
                        policy=policy,
                    )
            if response_data is None:
                return None
            native_plan = plan_from_tool_calls(
                response_data,
                plan_id=plan_id,
                message=message,
                context=context,
                lookup=native_lookup,
            )
            if native_plan is not None:
                return native_plan
            decoded = _decode_completion(response_data)
            if decoded is None:
                parsed_payload, raw_content = _model_payload(response_data)
                schema_error = (
                    "输出不是可解析的 JSON"
                    if parsed_payload is None
                    else (model_plan_schema_error(parsed_payload) or "计划结构不完整")
                )
                repaired = self._repair_output_shape(
                    plan_id=plan_id,
                    message=message,
                    context=context,
                    raw_content=raw_content,
                    error=schema_error,
                )
                if repaired is not None:
                    return repaired
                context["planning_failure_reason"] = (
                    f"计划结构修复未完成：{schema_error}"
                )[:300]
                return None
            parsed, nodes = decoded
            return build_plan_from_payload(
                plan_id=plan_id,
                message=message,
                parsed=parsed,
                nodes=nodes,
                context=context,
            )
        except (OSError, httpx.TransportError) as err:
            # Exhausted retries must retain the existing fail-closed plan result,
            # not escape into chat or invoke the retired fallback dispatcher.
            logger.warning("模型传输重试已耗尽，拒绝计划：%s", type(err).__name__)
            return None
        except (ValueError, TypeError) as err:
            from app.infrastructure.modstore_transport import MarketModelError

            if isinstance(err, MarketModelError):
                raise
            logger.warning("LLM 规划参数错误，拒绝计划并暂停执行: %s", err)
            return None
        except RuntimeError as err:
            from app.infrastructure.llm.model_admission import (
                ModelCircuitOpenError,
                ModelConcurrencyLimitError,
                ModelRateLimitError,
            )
            from app.utils.resilience.rate_limiter import RateLimitBackendError

            if isinstance(
                err,
                (
                    ModelCircuitOpenError,
                    ModelConcurrencyLimitError,
                    ModelRateLimitError,
                    RateLimitBackendError,
                ),
            ):
                raise
            logger.warning("LLM 规划运行时错误，拒绝计划并暂停执行: %s", err)
            return None

    def extract_clarification_parameters(
        self,
        *,
        user_id: str,
        original_message: str,
        answer: str,
        tool_id: str,
        action: str,
        current_params: dict[str, Any],
        allowed_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract only the values the deterministic clarification gate requested."""
        if not allowed_fields:
            return None
        try:
            from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

            spec = get_tool_action_spec(tool_id, action)
            if spec is None:
                return None
            schema = spec.input_schema if isinstance(spec.input_schema, dict) else {}
            properties = schema.get("properties") or {}
            if not isinstance(properties, dict):
                properties = {}
            allowed = sorted(str(key) for key in allowed_fields)
            field_schema: dict[str, Any] = {}
            for key in allowed:
                if key in properties:
                    field_schema[key] = properties[key]
                    continue
                parts = key.split(".")
                if len(parts) == 3 and parts[0] == "items" and parts[1].isdigit():
                    items_schema = properties.get("items")
                    item_schema = (
                        items_schema.get("items") if isinstance(items_schema, dict) else None
                    )
                    item_properties = (
                        item_schema.get("properties") if isinstance(item_schema, dict) else None
                    )
                    if isinstance(item_properties, dict) and parts[2] in item_properties:
                        field_schema[key] = item_properties[parts[2]]
            request = {
                "task": "只从用户本轮回答中提取指定参数；不规划、不调用工具、不补造事实。",
                "rules": [
                    '仅返回 JSON：{"resolved": true|false, "parameters": {...}}。',
                    "parameters 的键必须来自 allowed_fields。信息不足、含糊或互相矛盾时 resolved=false 且 parameters={}。",
                    "原始任务仅用于理解当前问题；不得把未被本轮回答确认的原始猜测补成事实。",
                    "不得输出工具名、动作、权限、身份、SQL、解释文本或 markdown。",
                ],
                "original_message": str(original_message or "")[:4000],
                "user_answer": str(answer or "")[:4000],
                "target": {
                    "tool_id": tool_id,
                    "action": action,
                    "current_params": _model_context_value(current_params),
                    "allowed_fields": allowed,
                    "field_schema": _model_context_value(field_schema),
                },
            }
            response = self.completion(
                ai_service=self.conversation,
                context=context,
                messages=[
                    {"role": "system", "content": "你是参数提取器，只输出 JSON。"},
                    {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
                ],
                http_client_factory=self.http_client,
                temperature=0,
                max_tokens=700,
            )
            if not isinstance(response, dict):
                return None
            choices = response.get("choices")
            first = choices[0] if isinstance(choices, list) and choices else {}
            message = first.get("message") if isinstance(first, dict) else {}
            raw = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(_sanitize_model_json(raw))
            if not isinstance(parsed, dict) or parsed.get("resolved") is not True:
                return None
            parameters = parsed.get("parameters")
            if not isinstance(parameters, dict) or not parameters:
                return None
            if set(map(str, parameters)) - set(allowed):
                return None
            return cast("dict[str, Any]", _model_context_value(parameters))
        except (ValueError, TypeError, KeyError, IndexError):
            logger.info("模型未能从澄清回答中提取有效参数")
            return None
