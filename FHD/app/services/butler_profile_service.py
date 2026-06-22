"""Butler Profile Service — 拟人 Persy 系统的读写服务。

读路径：get_active_profile(user_id) → 返回身份+四轴+记忆片段，供 prompt 注入
写路径：record_interaction(user_id, conversation) → 落行为事件 + 检测偏好纠正
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.application.butler_identity_catalog import (
    DEFAULT_MBTI_EI,
    DEFAULT_MBTI_JP,
    DEFAULT_MBTI_SN,
    DEFAULT_MBTI_TF,
    derive_four_axes,
    derive_mbti_type,
    get_identity_affinities,
    pick_primary_identity,
)
from app.db.models.butler_profile import ButlerUserProfile

logger = logging.getLogger(__name__)


class ButlerProfileService:
    """Butler 个性化人设读写服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ===== 读路径 =====

    def get_active_profile(self, user_id: int) -> Optional[ButlerUserProfile]:
        """读取用户当前 butler profile。不存在则返回 None。

        DB 异常向上抛出，由调用方（路由层）统一捕获返回 JSON。
        """
        return (
            self.db.query(ButlerUserProfile)
            .filter(ButlerUserProfile.user_id == user_id)
            .one_or_none()
        )

    def get_or_create_profile(
        self, user_id: int, mod_hints: List[str] | None = None
    ) -> ButlerUserProfile:
        """读取或初始化 profile。新用户用默认 MBTI + MOD 提示选身份。"""
        profile = self.get_active_profile(user_id)
        if profile is not None:
            return profile

        mbti_type = derive_mbti_type(
            DEFAULT_MBTI_EI, DEFAULT_MBTI_SN, DEFAULT_MBTI_TF, DEFAULT_MBTI_JP
        )
        primary = pick_primary_identity(mbti_type, mod_hints)
        affinities = get_identity_affinities(mbti_type)

        profile = ButlerUserProfile(
            user_id=user_id,
            identity_primary=primary,
            identity_composite=primary,
            identity_vector_json=json.dumps(affinities, ensure_ascii=False),
            mbti_ei=DEFAULT_MBTI_EI,
            mbti_sn=DEFAULT_MBTI_SN,
            mbti_tf=DEFAULT_MBTI_TF,
            mbti_jp=DEFAULT_MBTI_JP,
            mbti_type=mbti_type,
            mbti_confidence=0.3,
            last_inferred_at=datetime.utcnow(),
            interaction_count=0,
        )
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        logger.info(
            "初始化 butler profile user_id=%s identity=%s mbti=%s", user_id, primary, mbti_type
        )
        return profile

    def get_profile_view(self, user_id: int) -> Dict[str, Any]:
        """返回 UI 可见的 profile 视图（不含 MBTI 原始分数）。"""
        profile = self.get_or_create_profile(user_id)
        return profile.to_public_dict()

    def get_prompt_overlay(self, user_id: int) -> str:
        """生成 prompt 叠加层文本，注入到 butler system prompt 之后。"""
        profile = self.get_or_create_profile(user_id)
        axes = derive_four_axes(profile.mbti_ei, profile.mbti_sn, profile.mbti_tf, profile.mbti_jp)

        lines = [
            "【个性化人设叠加】",
            f"身份：{profile.identity_composite or profile.identity_primary}",
            f"人格类型：{profile.mbti_type}",
            "说话风格：",
            f"- 亲切度 {axes['warmth']}/100",
            f"- 详细度 {axes['verbosity']}/100",
            f"- 主动度 {axes['proactiveness']}/100",
            f"- 结构度 {axes['structuredness']}/100",
        ]
        return "\n".join(lines)

    # ===== 写路径 =====

    def record_interaction(
        self,
        user_id: int,
        user_message: str,
        assistant_message: str,
        *,
        interrupted: bool = False,
        corrected: bool = False,
    ) -> None:
        """记录一次对话互动，更新互动轮数。

        行为特征（interrupted/corrected）供推断引擎 cron 消费。
        DB 异常向上抛出，由路由层捕获。
        """
        profile = self.get_or_create_profile(user_id)
        profile.interaction_count = (profile.interaction_count or 0) + 1
        self.db.commit()

    def update_profile(
        self,
        user_id: int,
        *,
        mbti_ei: int | None = None,
        mbti_sn: int | None = None,
        mbti_tf: int | None = None,
        mbti_jp: int | None = None,
        identity_primary: str | None = None,
        identity_composite: str | None = None,
        mbti_confidence: float | None = None,
    ) -> Optional[ButlerUserProfile]:
        """更新 profile 字段（供推断引擎调用）。"""
        profile = self.get_active_profile(user_id)
        if profile is None:
            return None

        if mbti_ei is not None:
            profile.mbti_ei = _clamp(mbti_ei)
        if mbti_sn is not None:
            profile.mbti_sn = _clamp(mbti_sn)
        if mbti_tf is not None:
            profile.mbti_tf = _clamp(mbti_tf)
        if mbti_jp is not None:
            profile.mbti_jp = _clamp(mbti_jp)

        # 重新派生 16 型
        profile.mbti_type = derive_mbti_type(
            profile.mbti_ei, profile.mbti_sn, profile.mbti_tf, profile.mbti_jp
        )

        if identity_primary is not None:
            profile.identity_primary = identity_primary
        if identity_composite is not None:
            profile.identity_composite = identity_composite
        if mbti_confidence is not None:
            profile.mbti_confidence = max(0.0, min(1.0, mbti_confidence))

        profile.last_inferred_at = datetime.utcnow()

        # 更新身份亲和度向量
        affinities = get_identity_affinities(profile.mbti_type)
        profile.identity_vector_json = json.dumps(affinities, ensure_ascii=False)

        self.db.commit()
        self.db.refresh(profile)
        return profile


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))
