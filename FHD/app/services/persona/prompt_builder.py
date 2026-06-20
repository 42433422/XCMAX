"""Persona Prompt 生成器：参数 → prompt 文本。"""

from __future__ import annotations

from app.domain.persona.entities import PersonaProfile
from app.services.persona.identity_resolver import IdentityResolver

# 四轴 → 指令句映射
# 中等档（0.4）刻意去客服腔：不用"保持专业/惜字如金/附带建议/分点"
_WARMTH_INSTRUCTIONS = [
    (0.7, "用口语化表达，可适度寒暄，像朋友聊天"),
    (0.4, "语气自然随和，像跟熟人聊天，别太客气"),
    (0.0, "就事论事，直接给结论，不寒暄"),
]
_DETAIL_INSTRUCTIONS = [
    (0.7, "详细解释，给出具体步骤和原因"),
    (0.4, "说重点，别啰嗦"),
    (0.0, "简洁回答，惜字如金"),
]
_PROACTIVITY_INSTRUCTIONS = [
    (0.7, "主动提建议和下一步，不等用户问"),
    (0.4, "回答完顺嘴说一句就行，别老给建议"),
    (0.0, "问什么答什么，不主动延伸"),
]
_STRUCTURE_INSTRUCTIONS = [
    (0.7, "用编号列表/分点组织回答"),
    (0.4, "自然说话，别分点别列清单"),
    (0.0, "自然段落对话，不强求结构"),
]

_SAFETY_SECTION = "不确定的就说不确定，别瞎编。你就是你这个人，不是 AI、不是模型、不是助手、不是机器人，别暴露身份。"


def _pick_instruction(value: float, table: list[tuple[float, str]]) -> str:
    """根据参数值从指令表中选择对应指令。"""
    for threshold, instruction in table:
        if value >= threshold:
            return instruction
    return table[-1][1]  # 兜底


class PersonaPromptBuilder:
    """Persona Prompt 生成器。

    生成结构：身份段 + 风格段 + 业务上下文段 + 安全段（≤400 字）
    """

    def __init__(self, identity_resolver: IdentityResolver):
        self._identity_resolver = identity_resolver

    def build(self, profile: PersonaProfile, context_prompt: str) -> str:
        """生成 system prompt。

        Args:
            profile: 用户 persona 画像
            context_prompt: 业务上下文段（来自现有 _build_context_prompt）

        Returns:
            str: 完整 system prompt
        """
        # 身份段
        identity = profile.identity
        if identity is None:
            # 理论上 __post_init__ 已保证 identity 非空，此处为类型守卫
            raise ValueError("PersonaProfile.identity 不能为空（生成 prompt 前必须先解析身份）")
        brief = self._identity_resolver.resolve_brief(identity, profile.rapport)
        identity_section = f"你是{identity.name}，{brief}。"

        # 风格段
        axes = profile.axes
        style_instructions = [
            _pick_instruction(axes.warmth, _WARMTH_INSTRUCTIONS),
            _pick_instruction(axes.detail, _DETAIL_INSTRUCTIONS),
            _pick_instruction(axes.proactivity, _PROACTIVITY_INSTRUCTIONS),
            _pick_instruction(axes.structure, _STRUCTURE_INSTRUCTIONS),
        ]
        style_section = "；".join(style_instructions) + "。"

        # 业务上下文段
        context_section = context_prompt.strip() if context_prompt else ""

        # 拼接
        sections = [identity_section, style_section]
        if context_section:
            sections.append(context_section)
        sections.append(_SAFETY_SECTION)

        return "\n\n".join(sections)
