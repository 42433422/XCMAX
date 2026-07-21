import logging
import os
import time
from typing import Any, cast

from app.services.conversation.api import ApiMixin
from app.services.conversation.context import ContextMixin, ConversationContext
from app.services.conversation.handlers import HandlersMixin
from app.services.conversation.intent import IntentMixin
from app.services.conversation.prompts import PromptsMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 内存对话历史滚动上限（原硬编码 20，现为可配置）
_DEFAULT_HISTORY_MAX = 50


def _resolve_history_max() -> int:
    """从环境变量 ``FHD_CONVERSATION_HISTORY_MAX`` 读取内存历史上限。

    Returns:
        历史上限（``int``，≥ 10）。无效值或未设置时返回默认 50。
    """
    raw = os.environ.get("FHD_CONVERSATION_HISTORY_MAX", "")
    try:
        value = int(raw) if raw else _DEFAULT_HISTORY_MAX
    except (TypeError, ValueError):
        return _DEFAULT_HISTORY_MAX
    return max(10, value)


class AIConversationService(
    ContextMixin,
    IntentMixin,
    HandlersMixin,
    PromptsMixin,
    ApiMixin,
):
    def __init__(self):
        self.contexts: dict[str, ConversationContext] = {}

        # ========== LLM调用架构初始化（三级优先级）==========
        self.llm_adapter = None
        self.modstore_adapter = None
        llm_init_mode = "none"

        try:
            # 优先级1: 平台代理模式（修茈市场统一接口）
            from app.services.conversation.modstore_adapter import (
                create_modstore_adapter_from_env,
            )

            modstore = create_modstore_adapter_from_env()
            if modstore and modstore.is_configured:
                self.modstore_adapter = modstore
                llm_init_mode = "platform"
                logger.info(
                    "🌐 [优先级1] 启用修茈市场平台代理模式\n"
                    "   平台地址: %s\n"
                    "   默认模型: %s/%s\n"
                    "   用户ID: %s\n"
                    "   ✅ 所有LLM请求将通过平台统一路由",
                    modstore.platform_url,
                    modstore.default_provider,
                    modstore.default_model,
                    modstore.user_id,
                )
            else:
                logger.debug("未检测到修茈市场平台配置，尝试直连模式...")

            # 优先级2: 直连模式（OpenAI兼容适配器）
            if not self.modstore_adapter:
                from app.infrastructure.llm.providers.credentials import (
                    resolve_default_chat_model,
                    resolve_default_openai_provider,
                    resolve_openai_env_credentials,
                )
                from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

                llm_provider = resolve_default_openai_provider()
                llm_model = resolve_default_chat_model()
                llm_api_key, llm_base_url = resolve_openai_env_credentials()

                self.llm_adapter = OpenAICompatibleAdapter(
                    provider=llm_provider,
                    model=llm_model,
                    api_key=llm_api_key,
                    base_url=llm_base_url,
                )

                if self.llm_adapter.is_configured:
                    llm_init_mode = "direct"
                    logger.info(
                        "⚡ [优先级2] 启用直连模式: %s/%s (Key已配置)",
                        self.llm_adapter.provider_name,
                        self.llm_adapter.model_name,
                    )
                else:
                    logger.warning("⚠️ 直连适配器已创建但 [%s] API Key未配置", llm_provider)

        except RECOVERABLE_ERRORS as adapter_err:
            logger.error("❌ LLM适配器初始化失败: %s", adapter_err)
            self.llm_adapter = None
            self.modstore_adapter = None

        # ========== 保留原有DeepSeek配置（向后兼容降级 - 优先级3）==========
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            try:
                from app.utils.path_utils import get_resource_path

                config_path = get_resource_path("config", "deepseek_config.py")
                if os.path.exists(config_path):
                    import importlib.util

                    spec = importlib.util.spec_from_file_location(
                        "xcagi_deepseek_config", config_path
                    )
                    if spec and spec.loader:
                        config_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(config_module)
                        self.api_key = getattr(config_module, "DEEPSEEK_API_KEY", "") or ""
            except RECOVERABLE_ERRORS as e:
                logger.warning("无法读取 resources/config/deepseek_config.py: %s", e)

        if self.api_key and llm_init_mode == "none":
            llm_init_mode = "legacy"
            logger.info(
                "📦 [优先级3/降级] 使用旧版DeepSeek直连模式 (Key长度: %s)", len(self.api_key)
            )
        elif self.api_key:
            logger.info("DeepSeek API Key 已配置（长度: %s）(作为降级备选)", len(self.api_key))
        else:
            logger.warning("DeepSeek API Key 未配置（降级路径不可用）")

        from app.infrastructure.llm.providers.credentials import (
            default_chat_completions_url,
            resolve_default_chat_model,
        )

        self.api_url = default_chat_completions_url()
        self.model = resolve_default_chat_model()

        # 记录最终使用的模式
        self._llm_mode = llm_init_mode
        logger.info("🎯 LLM初始化完成，运行模式: %s", llm_init_mode)

        from app.services.deepseek_intent_service import HybridIntentWithDeepSeek
        from app.services.intent_confirmation_service import get_confirmation_service
        from app.services.intent_service import recognize_intents
        from app.services.task_agent import get_task_agent
        from app.services.unified_intent_recognizer import get_unified_intent_recognizer
        from app.services.user_memory_service import get_user_memory_service
        from app.services.user_preference_service import get_user_preference_service

        use_distilled = os.environ.get("USE_DISTILLED_MODEL", "0") == "1"
        if use_distilled:
            logger.info("已启用蒸馏意图识别开关：USE_DISTILLED_MODEL=1")

        self.intent_service = recognize_intents
        self.online_intent_service = HybridIntentWithDeepSeek(
            use_deepseek=True,
            rule_priority=True,
            confidence_threshold=0.6,
            use_distilled=use_distilled,
        )
        self.offline_intent_service = HybridIntentWithDeepSeek(
            use_deepseek=False,
            rule_priority=True,
            confidence_threshold=0.6,
            use_distilled=True,
        )
        self.deepseek_intent_service = self.online_intent_service
        self.unified_recognizer = get_unified_intent_recognizer()
        self.confirmation_service = get_confirmation_service()
        self.task_agent = get_task_agent()
        self.user_memory = get_user_memory_service()
        self.user_preference_service = get_user_preference_service()
        self._deepseek_async_client: Any = None
        self._deepseek_async_loop: Any = None
        self.persona_service = None  # 默认 None，由外部注入

    def add_to_history(self, user_id: str, role: str, content: str) -> bool:
        context = self.contexts.get(user_id)
        if not context:
            context = self.create_context(user_id)

        context.conversation_history.append({"role": role, "content": content})

        # 内存历史滚动上限可配置（默认 50，原硬编码 20）
        # 全量历史仍可保留在 DB（AIConversation 表），内存只保留近期窗口
        # 实际 token 预算裁剪由 ContextWindowManager 在 call_llm_api 内统一处理
        history_max = _resolve_history_max()
        if len(context.conversation_history) > history_max:
            context.conversation_history = context.conversation_history[-history_max:]
            # 更新摘要覆盖索引：被裁剪的老消息不再可用，summary_covered_until 重置
            context.summary_covered_until = -1
            context.summary = None

        # 刷新 token 估算缓存
        context.estimate_history_tokens()
        context.updated_at = time.time()
        return True

    def add_intent_feedback(
        self,
        user_id: str,
        message: str,
        recognized_intent: str,
        feedback: str,
        corrected_intent: str | None = None,
        slots: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.user_memory.add_feedback(
                user_id=user_id,
                message=message,
                recognized_intent=recognized_intent,
                feedback=feedback,
                corrected_intent=corrected_intent,
                slots=slots or {},
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("添加意图反馈失败: %s", e)

    def record_user_action(
        self,
        user_id: str,
        intent: str,
        slots: dict[str, Any],
        message: str,
    ) -> None:
        try:
            self.user_memory.record_action(
                user_id=user_id,
                intent=intent,
                slots=slots,
                message=message,
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("记录用户操作失败: %s", e)

    def apply_memory_preferences(
        self, user_id: str, intent: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return cast(
                "dict[str, Any]", self.user_memory.apply_preference_to_slots(user_id, intent, slots)
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("应用用户偏好失败: %s", e)
            return slots

    def get_memory_similar_action(
        self, user_id: str, intent: str, slots: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            return cast(
                "dict[str, Any] | None",
                self.user_memory.get_similar_pattern(user_id, intent, slots),
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("获取相似操作失败: %s", e)
            return None

    def get_habit_suggestions(self, user_id: str) -> list[dict[str, Any]]:
        try:
            return cast("list[dict[str, Any]]", self.user_memory.get_habit_suggestions(user_id))
        except RECOVERABLE_ERRORS as e:
            logger.error("获取习惯建议失败: %s", e)
            return []

    def get_context_for_recognition(
        self, user_id: str, conv_context: ConversationContext
    ) -> dict[str, Any]:
        context = {
            "user_id": user_id,
            "current_intent": conv_context.current_intent,
            "current_tool_key": conv_context.current_tool_key,
            "last_intent": conv_context.current_intent,
            "last_tool_key": conv_context.current_tool_key,
            "last_slots": (
                conv_context.last_intent_result.get("slots", {})
                if conv_context.last_intent_result
                else {}
            ),
            "pending_confirmation": conv_context.pending_confirmation,
        }

        recent_actions = self.user_memory.get_recent_actions(user_id, limit=3)
        if recent_actions:
            context["recent_intents"] = [a.get("intent") for a in recent_actions]

        preferences = self.user_memory.get_all_preferences(user_id)
        if preferences:
            context["user_preferences"] = preferences

        return context

    def _check_habit_suggestion(
        self, user_id: str, current_intent: str, slots: dict[str, Any]
    ) -> str | None:
        try:
            habits = self.get_habit_suggestions(user_id)

            for habit in habits:
                actions = habit.get("actions", [])
                confidence = habit.get("confidence", 0)

                if confidence < 0.8:
                    continue

                for action in actions:
                    if action.get("intent") == current_intent:
                        return f"💡 根据您的习惯，您可能还需要：{action.get('description', '')}"
        except RECOVERABLE_ERRORS as e:
            logger.error("检查习惯建议失败: %s", e)

        return None

    async def chat(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        try:
            conv_context = await self._get_or_create_context_async(user_id, context, message)

            intent_result = await self._recognize_intent(message, source, user_id, context)
            intent_result = self._enhance_intent_slots(message, intent_result, user_id)

            logger.info(
                "[INTENT_RESULT] final_intent=%s, primary_intent=%s, tool_key=%s, slots=%s, intent_source=%s",
                intent_result.get("final_intent"),
                intent_result.get("primary_intent"),
                intent_result.get("tool_key"),
                intent_result.get("slots"),
                intent_result.get("intent_source"),
            )
            self._update_context_from_intent(conv_context, intent_result)

            if result := await self._handle_special_intents(
                message, intent_result, conv_context, user_id
            ):
                return self._maybe_attach_kitten_web(conv_context, result)

            if result := await self._handle_pending_intent(
                message, intent_result, conv_context, user_id
            ):
                return self._maybe_attach_kitten_web(conv_context, result)

            out = await self._execute_or_generate_response(
                message, intent_result, conv_context, user_id
            )
            return self._maybe_attach_kitten_web(conv_context, out)

        except RECOVERABLE_ERRORS as e:
            logger.error("处理聊天消息失败：%s", e)
            return {
                "text": f"抱歉，处理消息时出现问题：{str(e)}",
                "action": "error",
                "data": {"message": str(e)},
            }


_ai_conversation_service: AIConversationService | None = None


class _InMemoryPersonaRepository:
    """内存版 persona 仓储：无 DB/Redis 环境下的 fallback。

    画像不持久化，进程内缓存；冷启动时 PersonaService 会创建默认画像。
    L1 规则推断 + prompt 生成仍正常工作，仅 L2/L3 缓存和跨会话画像不保留。
    """

    def __init__(self):
        self._store: dict[str, Any] = {}
        self._events: dict[str, list[dict]] = {}

    async def find_by_user_id(self, user_id: str):
        return self._store.get(user_id)

    async def save(self, profile):
        self._store[profile.user_id] = profile
        return profile

    async def delete(self, user_id: str) -> bool:
        return self._store.pop(user_id, None) is not None

    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        self._events.setdefault(user_id, []).append({"type": event_type, "data": event_data})

    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        return self._events.get(user_id, [])[-limit:]


def _build_persona_repository():
    """构造持久化 persona 仓储（Redis 热缓存 + DB 冷存储）。

    PersonaRepositoryImpl 内部已对 Redis/DB 不可用做优雅降级；仅当构造本身失败时
    才回退纯内存仓储，确保对话流人格永不因持久化层缺失而中断。
    """
    try:
        from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl

        return PersonaRepositoryImpl()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Persona 持久化仓储不可用，降级内存仓储: %s", exc)
        return _InMemoryPersonaRepository()


def _create_persona_service():
    """创建 PersonaService 实例（持久化仓储 + L1/L2/L3 三层推断）。

    - 持久化：PersonaRepositoryImpl（Redis-first + DB），画像跨重启存活。
    - L1：RuleInferencer（同步实时）。
    - L2：EmbeddingInferencer；未配置 XCAGI_EMBEDDING_API_KEY 时返回中性值自动待命。
    - L3：LlmInferencer，复用主对话 LLM 客户端（PersonaLlmClient 适配器）。
    """
    from app.infrastructure.persona.embedding_client import EmbeddingClient
    from app.infrastructure.persona.llm_client_adapter import PersonaLlmClient
    from app.services.persona.axes_fuser import AxesFuser
    from app.services.persona.embedding_inferencer import EmbeddingInferencer
    from app.services.persona.identity_resolver import IdentityResolver
    from app.services.persona.llm_inferencer import LlmInferencer
    from app.services.persona.param_mapper import PersonaParamMapper
    from app.services.persona.persona_service import PersonaService
    from app.services.persona.prompt_builder import PersonaPromptBuilder
    from app.services.persona.rapport_calculator import RapportCalculator
    from app.services.persona.rule_inferencer import RuleInferencer

    identity_resolver = IdentityResolver()
    return PersonaService(
        repo=_build_persona_repository(),
        rule_inferencer=RuleInferencer(),
        embedding_inferencer=EmbeddingInferencer(EmbeddingClient()),
        llm_inferencer=LlmInferencer(PersonaLlmClient()),
        axes_fuser=AxesFuser(),
        rapport_calculator=RapportCalculator(),
        identity_resolver=identity_resolver,
        prompt_builder=PersonaPromptBuilder(identity_resolver),
        param_mapper=PersonaParamMapper(),
    )


def get_ai_conversation_service() -> AIConversationService:
    global _ai_conversation_service
    if _ai_conversation_service is None:
        _ai_conversation_service = AIConversationService()
        _ai_conversation_service.persona_service = _create_persona_service()
    return _ai_conversation_service


def init_ai_conversation_service() -> AIConversationService:
    global _ai_conversation_service
    _ai_conversation_service = AIConversationService()
    _ai_conversation_service.persona_service = _create_persona_service()
    logger.info("AI 对话服务已初始化（已注入 PersonaService）")
    return _ai_conversation_service


from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(AIConversationService, "app.services.ai_conversation_service")
