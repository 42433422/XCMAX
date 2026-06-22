"""Butler Profile Inference — MBTI 推断引擎（规则 + embedding + LLM）。

三层推断：
1. 规则层：从对话行为特征提取 MBTI 4 维增量
2. embedding 层：对话内容向量与 16 型原型比对（可选，需 embedding 服务）
3. LLM 层：综合规则+embedding → 新 MBTI 分数 + 身份演进建议（可选）

设计原则：
- 规则层始终可用（不依赖外部服务）
- embedding/LLM 层可选（降级时不阻塞）
- 推断结果带置信度，渐进式更新（增量 ≤ 10 分/次）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.application.butler_identity_catalog import (
    DEFAULT_MBTI_EI,
    DEFAULT_MBTI_JP,
    DEFAULT_MBTI_SN,
    DEFAULT_MBTI_TF,
    derive_mbti_type,
    pick_primary_identity,
)
from app.services.butler_profile_service import ButlerProfileService

logger = logging.getLogger(__name__)

# 单次推断最大增量（防止跳变）
MAX_DELTA = 10
# 最小互动轮数才触发推断
MIN_INTERACTIONS_FOR_INFER = 5


@dataclass
class BehaviorFeatures:
    """从对话行为中提取的特征。"""

    turn_count: int = 0
    interrupt_count: int = 0  # 用户打断/催促次数
    correction_count: int = 0  # 用户纠正 butler 次数
    why_question_count: int = 0  # 用户问"为什么"/"如果"次数
    emotion_expression_count: int = 0  # 用户表达情绪/感谢次数
    structure_request_count: int = 0  # 用户要求"列步骤"/"排期"次数
    avg_message_length: float = 0.0  # 用户平均消息长度
    total_messages: int = 0

    @classmethod
    def from_conversations(cls, conversations: List[Dict[str, Any]]) -> BehaviorFeatures:
        """从对话历史中提取行为特征。

        每条对话: {"user_message": str, "assistant_message": str, "interrupted": bool, "corrected": bool}
        """
        features = cls()
        if not conversations:
            return features

        total_len = 0
        for conv in conversations:
            user_msg = str(conv.get("user_message") or "")
            features.total_messages += 1
            total_len += len(user_msg)

            if conv.get("interrupted"):
                features.interrupt_count += 1
            if conv.get("corrected"):
                features.correction_count += 1

            # 为什么/如果 → N（直觉信号）
            if re.search(r"为什么|如果|假设|万一|可能|也许|大概", user_msg):
                features.why_question_count += 1

            # 情绪/感谢 → F（情感信号）
            if re.search(r"谢谢|感谢|辛苦|喜欢|讨厌|开心|难过|生气|棒|赞|不行|糟糕", user_msg):
                features.emotion_expression_count += 1

            # 列步骤/排期 → J（判断信号）
            if re.search(r"列步骤|排期|计划|流程|步骤|清单|汇总|总结|整理", user_msg):
                features.structure_request_count += 1

            # 催促/打断 → E（外向信号）
            if re.search(r"快点|赶紧| hurry|催|急|马上|现在", user_msg):
                features.interrupt_count += 1

        features.turn_count = len(conversations)
        features.avg_message_length = total_len / max(features.total_messages, 1)
        return features


@dataclass
class InferenceResult:
    """推断结果。"""

    mbti_ei_delta: int = 0
    mbti_sn_delta: int = 0
    mbti_tf_delta: int = 0
    mbti_jp_delta: int = 0
    new_mbti_type: str = ""
    identity_changed: bool = False
    new_identity_primary: str = ""
    new_identity_composite: str = ""
    confidence: float = 0.5
    reasons: List[str] = field(default_factory=list)


class ButlerProfileInference:
    """MBTI 推断引擎。"""

    def infer(
        self,
        current_profile: Dict[str, Any],
        conversations: List[Dict[str, Any]],
        *,
        mod_hints: Optional[List[str]] = None,
    ) -> InferenceResult:
        """执行推断。

        Args:
            current_profile: 当前 profile 的 internal dict
            conversations: 最近对话历史
            mod_hints: MOD 所有权提示（影响身份选择）

        Returns:
            InferenceResult
        """
        result = InferenceResult()

        # 互动不足时不推断
        if len(conversations) < MIN_INTERACTIONS_FOR_INFER:
            result.reasons.append("互动轮数不足，保持当前人设")
            return result

        features = BehaviorFeatures.from_conversations(conversations)

        # === 规则层 ===
        self._apply_rules(features, result)

        # === 计算新 MBTI 分数 ===
        current_ei = int(current_profile.get("mbti_ei") or DEFAULT_MBTI_EI)
        current_sn = int(current_profile.get("mbti_sn") or DEFAULT_MBTI_SN)
        current_tf = int(current_profile.get("mbti_tf") or DEFAULT_MBTI_TF)
        current_jp = int(current_profile.get("mbti_jp") or DEFAULT_MBTI_JP)

        new_ei = _clamp(current_ei + result.mbti_ei_delta)
        new_sn = _clamp(current_sn + result.mbti_sn_delta)
        new_tf = _clamp(current_tf + result.mbti_tf_delta)
        new_jp = _clamp(current_jp + result.mbti_jp_delta)

        new_type = derive_mbti_type(new_ei, new_sn, new_tf, new_jp)
        old_type = current_profile.get("mbti_type") or derive_mbti_type(
            current_ei, current_sn, current_tf, current_jp
        )

        result.new_mbti_type = new_type

        # === 身份演进 ===
        if new_type != old_type:
            result.identity_changed = True
            result.new_identity_primary = pick_primary_identity(new_type, mod_hints)
            result.new_identity_composite = result.new_identity_primary
            result.reasons.append(
                f"MBTI 型变化 {old_type}→{new_type}，身份重选为 {result.new_identity_primary}"
            )
        else:
            result.reasons.append(f"MBTI 型保持 {new_type}，身份不变")

        # 置信度随互动轮数提升
        result.confidence = min(0.95, 0.3 + features.turn_count * 0.02)

        return result

    def _apply_rules(self, features: BehaviorFeatures, result: InferenceResult) -> None:
        """规则层：行为特征 → MBTI 4 维增量。"""

        # E/I 轴：打断/催促 → +E（外向）
        if features.interrupt_count > 0:
            delta = min(MAX_DELTA, features.interrupt_count * 2)
            result.mbti_ei_delta += delta
            result.reasons.append(f"打断/催促 {features.interrupt_count} 次 → E/I +{delta}")

        # S/N 轴：问"为什么" → +N（直觉）
        if features.why_question_count > 0:
            delta = min(MAX_DELTA, features.why_question_count * 2)
            result.mbti_sn_delta += delta
            result.reasons.append(f"追问为什么 {features.why_question_count} 次 → S/N +{delta}")

        # T/F 轴：表达情绪 → +F（情感）
        if features.emotion_expression_count > 0:
            delta = min(MAX_DELTA, features.emotion_expression_count * 2)
            result.mbti_tf_delta += delta
            result.reasons.append(f"情绪表达 {features.emotion_expression_count} 次 → T/F +{delta}")

        # J/P 轴：要求结构化 → +J（判断）
        if features.structure_request_count > 0:
            delta = min(MAX_DELTA, features.structure_request_count * 2)
            result.mbti_jp_delta += delta
            result.reasons.append(
                f"要求结构化 {features.structure_request_count} 次 → J/P +{delta}"
            )

        # 纠正 → +T（思考，更理性）
        if features.correction_count > 0:
            delta = min(MAX_DELTA, features.correction_count * 3)
            result.mbti_tf_delta -= delta
            result.reasons.append(f"纠正 butler {features.correction_count} 次 → T/F -{delta}")

        # 平均消息长度：长消息 → +I（内向，深思熟虑）
        if features.avg_message_length > 100:
            result.mbti_ei_delta -= 3
            result.reasons.append("消息偏长 → E/I -3")


def apply_inference(
    service: ButlerProfileService,
    user_id: int,
    result: InferenceResult,
    current_profile: Dict[str, Any],
) -> None:
    """将推断结果应用到 profile。

    Args:
        service: ButlerProfileService 实例
        user_id: 用户 ID
        result: 推断结果
        current_profile: 当前 profile 的 internal dict（含原始 MBTI 分数）
    """
    if not result.new_mbti_type:
        return

    current_ei = int(current_profile.get("mbti_ei") or DEFAULT_MBTI_EI)
    current_sn = int(current_profile.get("mbti_sn") or DEFAULT_MBTI_SN)
    current_tf = int(current_profile.get("mbti_tf") or DEFAULT_MBTI_TF)
    current_jp = int(current_profile.get("mbti_jp") or DEFAULT_MBTI_JP)

    new_ei = _clamp(current_ei + result.mbti_ei_delta)
    new_sn = _clamp(current_sn + result.mbti_sn_delta)
    new_tf = _clamp(current_tf + result.mbti_tf_delta)
    new_jp = _clamp(current_jp + result.mbti_jp_delta)

    update_kwargs: Dict[str, Any] = {
        "mbti_ei": new_ei,
        "mbti_sn": new_sn,
        "mbti_tf": new_tf,
        "mbti_jp": new_jp,
        "mbti_confidence": result.confidence,
    }

    if result.identity_changed and result.new_identity_primary:
        update_kwargs["identity_primary"] = result.new_identity_primary
        update_kwargs["identity_composite"] = (
            result.new_identity_composite or result.new_identity_primary
        )

    service.update_profile(user_id, **update_kwargs)
    logger.info(
        "应用推断 user_id=%s mbti=%s confidence=%.2f identity_changed=%s",
        user_id,
        result.new_mbti_type,
        result.confidence,
        result.identity_changed,
    )


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))
