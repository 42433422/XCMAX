# FHD/app/services/persona/persona_service.py
"""PersonaService 主服务：编排三层推断 + 融合 + 持久化。"""

from __future__ import annotations

import asyncio
import logging

from app.application.ports.persona_repository import PersonaProfileRepository
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes
from app.services.persona.axes_fuser import AxesFuser
from app.services.persona.embedding_inferencer import EmbeddingInferencer
from app.services.persona.identity_resolver import IdentityResolver
from app.services.persona.llm_inferencer import LlmInferencer
from app.services.persona.param_mapper import PersonaParamMapper
from app.services.persona.prompt_builder import PersonaPromptBuilder
from app.services.persona.rapport_calculator import RapportCalculator
from app.services.persona.rule_inferencer import RuleInferencer

logger = logging.getLogger(__name__)

# L1 命中这些信号视为一次"情感信号"，驱动 rapport 的情感权重（0.2 项）
_EMOTION_SIGNALS = frozenset({"emoji", "modal_particle"})


class PersonaService:
    """Persona 主服务。

    职责：
    1. 加载用户画像（Redis 优先，DB 回源）
    2. L1 规则层实时推断（同步）
    3. 融合最终 persona（L1 + L2缓存 + L3缓存）
    4. 异步更新画像（不阻塞响应）
    5. 触发 L2/L3 异步推断（按轮数阈值）
    """

    L2_TRIGGER_INTERVAL = 10  # 每 10 轮触发 L2
    L3_TRIGGER_INTERVAL = 20  # 每 20 轮触发 L3

    def __init__(
        self,
        repo: PersonaProfileRepository,
        rule_inferencer: RuleInferencer,
        embedding_inferencer: EmbeddingInferencer,
        llm_inferencer: LlmInferencer,
        axes_fuser: AxesFuser,
        rapport_calculator: RapportCalculator,
        identity_resolver: IdentityResolver,
        prompt_builder: PersonaPromptBuilder,
        param_mapper: PersonaParamMapper,
    ):
        self._repo = repo
        self._rule_inferencer = rule_inferencer
        self._embedding_inferencer = embedding_inferencer
        self._llm_inferencer = llm_inferencer
        self._axes_fuser = axes_fuser
        self._rapport_calculator = rapport_calculator
        self._identity_resolver = identity_resolver
        self._prompt_builder = prompt_builder
        self._param_mapper = param_mapper
        # L2/L3 周期性后台推断结果缓存（按 user_id），供后续每轮融合复用
        self._axes_cache: dict[str, dict[str, PersonaAxes | None]] = {}
        # 后台任务引用，防止被 GC 提前回收
        self._bg_tasks: set[asyncio.Task] = set()

    async def get_persona(self, user_id: str, industry: str) -> PersonaProfile:
        """加载用户画像。

        冷启动：无历史画像时根据行业创建默认画像。
        """
        profile = await self._repo.find_by_user_id(user_id)
        if profile is None:
            profile = PersonaProfile.create(user_id=user_id, industry=industry)
            await self._repo.save(profile)
        return profile

    async def update_on_message(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        industry: str,
    ) -> PersonaProfile:
        """消息到达时更新 persona（同步路径）。

        1. 加载画像
        2. L1 规则推断（同步）
        3. 融合（L1 + L2/L3 缓存值）
        4. 更新 rapport
        5. 保存 + 发布事件
        6. 异步触发 L2/L3（按轮数阈值）

        延迟预算：<10ms（同步路径）
        """
        # 1. 加载画像
        profile = await self.get_persona(user_id, industry)

        # 2. L1 规则推断（同步）
        l1_result = self._rule_inferencer.infer(message, history)

        # 3. 融合（L1 + 周期性后台推断出的 L2/L3 缓存值）
        cached_axes = self._axes_cache.get(user_id, {})
        fused_axes = self._axes_fuser.fuse(
            l1=l1_result.axes,
            l2=cached_axes.get("l2"),
            l3=cached_axes.get("l3"),
            rapport=profile.rapport,
            signal_strength=l1_result.confidence,
        )

        # 4. 更新 rapport
        new_interaction_count = profile.rapport.interaction_count + 1
        new_domain_counts = dict(profile.business_domain_counts)
        # 简化：每轮都计入当前身份域
        if profile.identity is None:
            raise ValueError("PersonaProfile.identity 不能为空（更新 rapport 前必须先解析身份）")
        current_domain = profile.identity.business_domain
        new_domain_counts[current_domain] = new_domain_counts.get(current_domain, 0) + 1

        # 情感信号累计：L1 命中 emoji / 语气词 即记一次情感信号（激活 rapport 的 0.2 权重）
        new_emotion_count = profile.rapport.emotion_signal_count
        if _EMOTION_SIGNALS.intersection(l1_result.signals):
            new_emotion_count += 1

        new_rapport = self._rapport_calculator.calculate(
            interaction_count=new_interaction_count,
            business_domain_counts=new_domain_counts,
            emotion_signal_count=new_emotion_count,
        )

        # 5. 更新画像
        updated_profile = profile.update_axes(fused_axes).update_rapport(new_rapport)
        updated_profile = PersonaProfile(
            user_id=updated_profile.user_id,
            identity=updated_profile.identity,
            axes=updated_profile.axes,
            rapport=updated_profile.rapport,
            business_domain_counts=new_domain_counts,
            created_at=updated_profile.created_at,
            updated_at=updated_profile.updated_at,
        )

        # 5b. 身份漂移：长期主要操作某非初始业务域时平滑改名
        #     （IdentityResolver.DRIFT_THRESHOLD=50 轮、占比 >=60% 才触发）。
        #     注：触发前提是 business_domain_counts 出现多个业务域；当前每轮仅计入当前身份域，
        #     真正漂移需上游按消息意图填充不同业务域计数——机制已接通，待意图归因喂入即生效。
        if self._identity_resolver.should_drift(updated_profile):
            drifted = self._identity_resolver.drift_target(updated_profile)
            if drifted is not None:
                logger.info(
                    "persona 身份漂移: user=%s %s → %s",
                    user_id,
                    updated_profile.identity.name if updated_profile.identity else "?",
                    drifted.name,
                )
                updated_profile = updated_profile.drift_identity(drifted)

        # 6. 保存 + 发布事件
        await self._repo.save(updated_profile)
        await self._repo.append_event(
            user_id=user_id,
            event_type="l1_infer",
            event_data={
                "axes": l1_result.axes.to_dict(),
                "fused_axes": fused_axes.to_dict(),
                "signals": l1_result.signals,
                "confidence": l1_result.confidence,
            },
        )

        # 7. 异步触发 L2/L3（按轮数阈值）：后台执行不阻塞响应；
        #    结果回填 self._axes_cache，供后续每轮 fuse 复用。
        if new_interaction_count % self.L2_TRIGGER_INTERVAL == 0:
            self._schedule_background(self._run_l2(user_id, history))
        if new_interaction_count % self.L3_TRIGGER_INTERVAL == 0:
            self._schedule_background(self._run_l3(user_id, history, fused_axes))

        return updated_profile

    def _schedule_background(self, coro) -> None:
        """把后台推断协程挂到当前事件循环；无运行中事件循环时安全跳过。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _run_l2(self, user_id: str, history: list[dict]) -> None:
        """L2 embedding 后台推断。

        未配置 embedding 端点（XCAGI_EMBEDDING_API_KEY）时，inferencer 返回中性值、
        confidence=0，缓存不更新——L2 自动待命，不影响 L1/L3。
        """
        if self._embedding_inferencer is None:
            return
        try:
            messages = [
                str(m.get("content", ""))
                for m in (history or [])
                if isinstance(m, dict) and m.get("role") == "user"
            ]
            result = await self._embedding_inferencer.infer(user_id, messages)
            if result.confidence > 0:
                self._axes_cache.setdefault(user_id, {})["l2"] = result.axes
        except Exception as exc:  # noqa: BLE001  后台推断失败不影响对话
            logger.warning("L2 后台推断失败: %s", exc)

    async def _run_l3(self, user_id: str, history: list[dict], current_axes: PersonaAxes) -> None:
        """L3 LLM 后台推断：复用主对话 LLM 客户端对最近对话做风格校准。"""
        if self._llm_inferencer is None:
            return
        try:
            result = await self._llm_inferencer.infer(user_id, history or [], current_axes)
            if result.confidence > 0:
                self._axes_cache.setdefault(user_id, {})["l3"] = result.axes
        except Exception as exc:  # noqa: BLE001
            logger.warning("L3 后台推断失败: %s", exc)

    def build_prompt(self, profile: PersonaProfile, context_prompt: str) -> str:
        """生成 system prompt。"""
        return self._prompt_builder.build(profile, context_prompt)

    def map_params(self, profile: PersonaProfile) -> dict[str, float | int]:
        """映射模型推理参数。"""
        return self._param_mapper.map(profile.axes, profile.rapport)

    async def build_prompt_from_message(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        industry: str,
        context_prompt: str,
    ) -> tuple[str, dict[str, float | int]]:
        """便捷方法：更新 persona + 生成 prompt + 映射参数。"""
        profile = await self.update_on_message(user_id, message, history, industry)
        prompt = self.build_prompt(profile, context_prompt)
        params = self.map_params(profile)
        return prompt, params
