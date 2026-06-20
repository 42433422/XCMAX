# FHD/app/services/persona/persona_service.py
"""PersonaService 主服务：编排三层推断 + 融合 + 持久化。"""

from __future__ import annotations

import logging

from app.application.ports.persona_repository import PersonaProfileRepository
from app.domain.persona.entities import PersonaProfile
from app.services.persona.axes_fuser import AxesFuser
from app.services.persona.embedding_inferencer import EmbeddingInferencer
from app.services.persona.identity_resolver import IdentityResolver
from app.services.persona.llm_inferencer import LlmInferencer
from app.services.persona.param_mapper import PersonaParamMapper
from app.services.persona.prompt_builder import PersonaPromptBuilder
from app.services.persona.rapport_calculator import RapportCalculator
from app.services.persona.rule_inferencer import RuleInferencer

logger = logging.getLogger(__name__)


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

        # 3. 融合（L1 + 缓存的 L2/L3）
        # 注意：L2/L3 的缓存值在 profile 中，这里简化为仅用 L1
        # 生产环境应从 Redis 读取 L2/L3 缓存值
        fused_axes = self._axes_fuser.fuse(
            l1=l1_result.axes,
            l2=None,  # 从缓存读取
            l3=None,  # 从缓存读取
            rapport=profile.rapport,
            signal_strength=l1_result.confidence,
        )

        # 4. 更新 rapport
        new_interaction_count = profile.rapport.interaction_count + 1
        new_domain_counts = dict(profile.business_domain_counts)
        # 简化：每轮都计入当前身份域
        current_domain = profile.identity.business_domain
        new_domain_counts[current_domain] = new_domain_counts.get(current_domain, 0) + 1

        new_rapport = self._rapport_calculator.calculate(
            interaction_count=new_interaction_count,
            business_domain_counts=new_domain_counts,
            emotion_signal_count=profile.rapport.emotion_signal_count,
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

        # 7. 异步触发 L2/L3（按轮数阈值）
        # 注意：实际生产应使用 asyncio.create_task 异步执行
        # 这里简化为同步调用，由调用方决定是否异步
        if new_interaction_count % self.L2_TRIGGER_INTERVAL == 0:
            logger.debug("触发 L2 embedding 推断: user=%s", user_id)
        if new_interaction_count % self.L3_TRIGGER_INTERVAL == 0:
            logger.debug("触发 L3 LLM 推断: user=%s", user_id)

        return updated_profile

    def build_prompt(self, profile: PersonaProfile, context_prompt: str) -> str:
        """生成 system prompt。"""
        return self._prompt_builder.build(profile, context_prompt)

    def map_params(self, profile: PersonaProfile) -> dict[str, float | int]:
        """映射模型推理参数。"""
        return self._param_mapper.map(profile.axes, profile.rapport)
