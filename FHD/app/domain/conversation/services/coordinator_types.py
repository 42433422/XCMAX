from __future__ import annotations

"""Types for UnifiedConversationCoordinator (split out of coordinator.py)."""

"""
统一对话编排器

设计目标：
1. 单一入口 - 所有对话消息通过此编排器处理
2. 状态统一 - pending 状态在此组件内统一管理
3. 职责分明 - 意图识别、槽位验证、追问生成、执行编排各司其职
4. 零侵入 - 复用现有组件，不修改原有代码

核心流程：
Message → 意图识别 → 槽位验证 → (缺失? 追问 : 执行编排)

注意：此文件已重构，核心逻辑已移至 context 模块：
- IntentContext: 任务上下文（pending 状态管理）
- ChatContext: 聊天上下文（历史记录和重复检测）
- ContextFacade: 统一门面（组合两者）

此文件保留用于向后兼容，新代码应使用 ContextFacade。
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ProcessingAction(Enum):
    """处理动作枚举（向后兼容）"""

    GREETING = "greeting"
    GOODBYE = "goodbye"
    HELP = "help"
    SLOT_FILL = "slot_fill"
    TOOL_CALL = "tool_call"
    AI_RESPONSE = "ai_response"
    NEGATED = "negated"
    DUPLICATE_RESPONSE = "duplicate_response"
    INTENT_SWITCH_QUERY = "intent_switch_query"


@dataclass
class PendingIntent:
    """
    待确认意图（向后兼容）

    为了保持向后兼容，保留原有的 PendingIntent dataclass。
    新代码应使用 context 模块中的 PendingIntent。
    """

    intent: str
    slots: dict[str, Any]
    missing_slots: list[str]
    created_at: float = field(default_factory=time.time)
    source: str = "unknown"
    last_updated_at: float = field(default_factory=time.time)
    turn_count: int = 1

    def is_expired(self, max_age_seconds: float = 300) -> bool:
        """检查是否过期"""
        return time.time() - self.last_updated_at > max_age_seconds

    def merge_slots(self, new_slots: dict[str, Any]) -> PendingIntent:
        """合并新槽位"""
        merged = self.slots.copy()
        merged.update(new_slots)

        still_missing = [s for s in self.missing_slots if not merged.get(s)]

        return PendingIntent(
            intent=self.intent,
            slots=merged,
            missing_slots=still_missing,
            created_at=self.created_at,
            source=self.source,
            last_updated_at=time.time(),
            turn_count=self.turn_count + 1,
        )


@dataclass
class IntentResult:
    """意图识别结果（向后兼容）"""

    primary_intent: str | None
    tool_key: str | None
    slots: dict[str, Any]
    is_greeting: bool = False
    is_goodbye: bool = False
    is_help: bool = False
    is_confirmation: bool = False
    is_negation_intent: bool = False
    is_negated: bool = False
    confidence: float = 0.0
    source: str = "unknown"
    intent_hints: list[str] = field(default_factory=list)


@dataclass
class ProcessingResult:
    """处理结果（向后兼容）"""

    action: ProcessingAction
    text: str
    data: dict[str, Any]
    pending_intent: PendingIntent | None = None
