# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.user_memory_service")


class _UserMemoryServicePart02Mixin:
    def _calculate_similarity(
        self, slots1: dict[str, _facade().Any], slots2: dict[str, _facade().Any]
    ) -> float:
        """计算槽位相似度"""
        if not slots1 and (not slots2):
            return 1.0
        important_keys = ["unit_name", "spec", "model_number", "quantity", "product_name"]
        match_count = 0
        total_count = 0
        for key in important_keys:
            v1 = slots1.get(key, "") or slots1.get(key)
            v2 = slots2.get(key, "") or slots2.get(key)
            if v1 and v2:
                total_count += 1
                if str(v1) == str(v2):
                    match_count += 1
        if total_count == 0:
            return 0.5
        return match_count / total_count

    def add_feedback(
        self,
        user_id: str,
        message: str,
        recognized_intent: str,
        feedback: str,
        corrected_intent: str | None = None,
        slots: dict[str, _facade().Any] | None = None,
    ) -> None:
        """
        添加用户反馈

        Args:
            user_id: 用户ID
            message: 用户消息
            recognized_intent: 系统识别的意图
            feedback: 反馈类型 (confirmed/negated/corrected)
            corrected_intent: 正确意图（当 feedback=corrected 时）
            slots: 槽位信息
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = _facade().UserMemory(user_id=user_id)
        record = _facade().FeedbackRecord(
            timestamp=_facade().datetime.now().isoformat(),
            message=message[:200] if message else "",
            recognized_intent=recognized_intent,
            user_feedback=feedback,
            corrected_intent=corrected_intent,
            slots=slots or {},
        )
        memory.feedback_history.insert(0, record.to_dict())
        memory.feedback_history = memory.feedback_history[: _facade().MAX_FEEDBACK_HISTORY]
        self._adjust_pattern_weights(memory, recognized_intent, corrected_intent, feedback)
        self._store.save_memory(user_id, memory)
        _facade().logger.debug(
            "用户 %s 反馈已记录: feedback=%s, recognized=%s", user_id, feedback, recognized_intent
        )

    def _adjust_pattern_weights(
        self,
        memory: _facade().UserMemory,
        recognized_intent: str,
        corrected_intent: str | None,
        feedback: str,
    ) -> None:
        """调整模式权重"""
        weight_delta = 0.0
        target_intent = recognized_intent
        if feedback == "confirmed":
            weight_delta = 0.1
        elif feedback == "negated":
            weight_delta = -0.15
        elif feedback == "corrected" and corrected_intent:
            for action in memory.frequent_actions:
                if action.get("intent") == recognized_intent:
                    new_confidence = action.get("confidence", 0.5) - 0.1
                    action["confidence"] = max(0.1, min(0.99, new_confidence))
            target_intent = corrected_intent
            weight_delta = 0.1
        for action in memory.frequent_actions:
            if action.get("intent") == target_intent:
                new_confidence = action.get("confidence", 0.5) + weight_delta
                action["confidence"] = max(0.1, min(0.99, new_confidence))

    def get_feedback_stats(self, user_id: str) -> dict[str, _facade().Any]:
        """获取反馈统计"""
        memory = self._store.get_memory(user_id)
        if not memory:
            return {"total": 0, "confirmed": 0, "negated": 0, "corrected": 0}
        feedback_counts: dict[str, int] = _facade().defaultdict(int)
        intent_error_rates: dict[str, dict[str, int]] = _facade().defaultdict(
            lambda: {"total": 0, "errors": 0}
        )
        for record in memory.feedback_history:
            fb_type = record.get("user_feedback", "unknown")
            feedback_counts[fb_type] += 1
            recognized = record.get("recognized_intent", "")
            intent_error_rates[recognized]["total"] += 1
            if fb_type in ("negated", "corrected"):
                intent_error_rates[recognized]["errors"] += 1
        error_rates = {}
        for intent, stats in intent_error_rates.items():
            if stats["total"] >= 3:
                error_rates[intent] = round(stats["errors"] / stats["total"], 3)
        return {
            "total": len(memory.feedback_history),
            "confirmed": feedback_counts.get("confirmed", 0),
            "negated": feedback_counts.get("negated", 0),
            "corrected": feedback_counts.get("corrected", 0),
            "error_rates": error_rates,
        }

    def get_habit_suggestions(self, user_id: str) -> list[dict[str, _facade().Any]]:
        """
        获取操作习惯建议

        Returns:
            习惯建议列表 (如：生成发货单后经常打印标签)
        """
        memory = self._store.get_memory(user_id)
        if not memory:
            return []
        suggestions = []
        action_sequence = self._analyze_action_sequence(memory)
        for seq in action_sequence:
            if seq["confidence"] >= 0.8 and len(seq["actions"]) >= 2:
                suggestions.append(
                    {
                        "type": "action_sequence",
                        "actions": seq["actions"],
                        "confidence": seq["confidence"],
                        "suggestion": f"执行 {seq['actions'][0]} 后主动提示 {seq['actions'][1]}",
                    }
                )
        return suggestions

    def _analyze_action_sequence(
        self, memory: _facade().UserMemory
    ) -> list[dict[str, _facade().Any]]:
        """分析操作序列"""
        sequences: dict[str, dict[str, _facade().Any]] = _facade().defaultdict(
            lambda: {"count": 0, "first_action": ""}
        )
        for i in range(len(memory.historical_contexts) - 1):
            current = memory.historical_contexts[i]
            next_ctx = memory.historical_contexts[i + 1]
            seq_key = f"{current.get('intent')}->{next_ctx.get('intent')}"
            sequences[seq_key]["count"] += 1
            sequences[seq_key]["first_action"] = current.get("intent")
        result = []
        for seq_key, stats in sequences.items():
            if stats["count"] >= 2:
                actions = seq_key.split("->")
                result.append(
                    {
                        "actions": actions,
                        "confidence": min(0.95, stats["count"] * 0.15),
                        "count": stats["count"],
                    }
                )
        return result

    def apply_preference_to_slots(
        self, user_id: str, intent: str, slots: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any]:
        """
        将用户偏好应用到槽位

        Args:
            user_id: 用户ID
            intent: 当前意图
            slots: 当前槽位

        Returns:
            填充后的槽位
        """
        filled_slots = slots.copy()
        if "unit_name" not in filled_slots or not filled_slots["unit_name"]:
            favorite_customer = self.get_preference(user_id, "favorite_customer")
            if favorite_customer:
                filled_slots["unit_name"] = favorite_customer
        if "template" not in filled_slots:
            default_template = self.get_preference(user_id, "default_template")
            if default_template:
                filled_slots["template"] = default_template
        return filled_slots

    def get_memory_summary(self, user_id: str) -> dict[str, _facade().Any]:
        """获取用户记忆摘要"""
        memory = self._store.get_memory(user_id)
        if not memory:
            return {"has_memory": False}
        return {
            "has_memory": True,
            "preference_count": len(memory.preferences),
            "action_count": len(memory.frequent_actions),
            "feedback_count": len(memory.feedback_history),
            "memory_v2_count": len(memory.memory_v2_records),
            "memory_v2_pending_count": len(
                [m for m in memory.memory_v2_records if m.get("status") == "pending"]
            ),
            "memory_v2_active_count": len(
                [m for m in memory.memory_v2_records if m.get("status") == "active"]
            ),
            "last_updated": memory.updated_at,
            "top_intents": [a.get("intent") for a in memory.frequent_actions[:3]],
        }
