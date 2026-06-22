"""Persona-A ↔ Butler 视图桥接（方案 B：Persona-A 为单一真相源）。

桥接合并的落地：对话流人格（persona_profile，四轴 [0,1] + rapport）是唯一真相源；
Settings UI 的 ``GET /api/butler/profile`` 改由 persona 派生，**保持 butler
``to_public_dict`` 的字节级契约**（``frontend/src/api/butlerProfile.ts`` 的
``ButlerProfileView`` 零改动 → 目标 6 前端零改动）。

键名映射（必须严格保持，否则前端契约破裂）：
- persona ``warmth``      → butler ``warmth``
- persona ``detail``      → butler ``verbosity``
- persona ``proactivity`` → butler ``proactiveness``
- persona ``structure``   → butler ``structuredness``

axes [0,1] → 0-100 仅用于展示，**永不反向写回**（规避有损逆映射）。Butler 的
``/infer`` 引擎与 ``butler_user_profiles`` 表转为可选/次要，不再驱动对话流人格。
"""

from __future__ import annotations

import asyncio
import logging

from app.domain.persona.entities import PersonaProfile

logger = logging.getLogger(__name__)


def _axis_to_100(value: float) -> int:
    return max(0, min(100, round(float(value) * 100)))


def persona_axes_to_four_axes(profile: PersonaProfile) -> dict[str, int]:
    """persona 四轴 [0,1] → butler four_axes 0-100（保持键名契约）。"""
    axes = profile.axes
    return {
        "warmth": _axis_to_100(axes.warmth),
        "verbosity": _axis_to_100(axes.detail),
        "proactiveness": _axis_to_100(axes.proactivity),
        "structuredness": _axis_to_100(axes.structure),
    }


def _display_mbti_type(profile: PersonaProfile) -> str:
    """从四轴粗略派生一个展示用 16 型标签（仅展示，不参与任何写回）。"""
    axes = profile.axes
    e = "E" if axes.proactivity >= 0.5 else "I"
    n = "N" if axes.detail >= 0.5 else "S"
    f = "F" if axes.warmth >= 0.5 else "T"
    j = "J" if axes.structure >= 0.5 else "P"
    return f"{e}{n}{f}{j}"


def persona_to_butler_view(profile: PersonaProfile, user_id: int) -> dict:
    """把 persona 画像映射成 butler ``to_public_dict`` 形状（前端契约不变）。"""
    identity_name = profile.identity.name if profile.identity else "业务管家"
    return {
        "user_id": user_id,
        "identity_primary": identity_name,
        "identity_composite": identity_name,
        "four_axes": persona_axes_to_four_axes(profile),
        "mbti_type": _display_mbti_type(profile),
        "mbti_confidence": round(profile.rapport.score, 4),
        "interaction_count": profile.rapport.interaction_count,
        "last_inferred_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def persona_view_for_user(user_id: int) -> dict | None:
    """读取 persona 画像（key=str(user_id)）并派生 butler 视图。

    无画像（用户尚未对话过）时返回 ``None``，由调用方回退 butler 自身默认视图。
    仅供同步路由调用（内部用 ``asyncio.run`` 驱动 async 仓储）。
    """
    from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl

    repo = PersonaRepositoryImpl()
    profile = asyncio.run(repo.find_by_user_id(str(user_id)))
    if profile is None:
        return None
    return persona_to_butler_view(profile, user_id)
