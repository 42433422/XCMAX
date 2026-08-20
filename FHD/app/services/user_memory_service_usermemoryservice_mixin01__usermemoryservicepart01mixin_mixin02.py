# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.user_memory_service")


class __UserMemoryServicePart01MixinPart02Mixin:
    def correct_memory(
        self,
        user_id: str,
        memory_id: str,
        *,
        value: _facade().Any | None = None,
        key: str | None = None,
        reason: str = "",
    ) -> dict[str, _facade().Any]:
        """纠正 active/pending 记忆，保留同一个 memory_id 便于审计。"""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}
        if record.get("status") == "deleted":
            return {"success": False, "message": "记忆已删除"}
        updated = dict(record)
        previous_key = str(record.get("key") or "").strip()
        if key is not None:
            updated["key"] = str(key or "").strip()
        if value is not None:
            updated["value"] = value
        if not str(updated.get("key") or "").strip():
            return {"success": False, "message": "缺少 memory key"}
        now = _facade().datetime.now().isoformat()
        updated["updated_at"] = now
        updated["last_correction_reason"] = reason
        updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
        updated["fingerprint"] = self._memory_v2_fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
        memory.memory_v2_records[idx] = updated
        if updated.get("status") == "active" and updated.get("memory_type") == "preference":
            if previous_key and previous_key != str(updated["key"]):
                previous_pref = memory.preferences.get(previous_key)
                if (
                    isinstance(previous_pref, dict)
                    and previous_pref.get("memory_id") == updated["memory_id"]
                ):
                    memory.preferences.pop(previous_key, None)
            pref_key = str(updated["key"])
            memory.preferences[pref_key] = {
                "value": updated.get("value"),
                "updated_at": now,
                "count": memory.preferences.get(pref_key, {}).get("count", 0) + 1,
                "source": "memory_v2",
                "memory_id": updated["memory_id"],
            }
        self._store.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    def list_memories(
        self, user_id: str, *, status: str | None = None, memory_type: str | None = None
    ) -> list[dict[str, _facade().Any]]:
        memory = self._store.get_memory(user_id)
        if memory is None:
            return []
        normalized_status = self._normalize_memory_v2_status(status) if status else None
        normalized_type = self._normalize_memory_v2_type(memory_type) if memory_type else None
        records = []
        for record in memory.memory_v2_records:
            if normalized_status and record.get("status") != normalized_status:
                continue
            if normalized_type and record.get("memory_type") != normalized_type:
                continue
            records.append(dict(record))
        return records

    def record_memory_recall(self, user_id: str, memory_id: str) -> dict[str, _facade().Any]:
        """Reinforce a confirmed memory after it contributed to retrieval."""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self._find_memory_v2_record(memory, memory_id)
        if record is None or record.get("status") != "active":
            return {"success": False, "message": "可召回记忆不存在"}
        updated = dict(record)
        now = _facade().datetime.now().isoformat()
        updated["recall_count"] = int(updated.get("recall_count") or 0) + 1
        updated["last_recalled_at"] = now
        memory.memory_v2_records[idx] = updated
        self._store.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    def get_memory_v2_summary(self, user_id: str) -> dict[str, _facade().Any]:
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"total": 0, "by_status": {}, "by_type": {}}
        by_status: dict[str, int] = _facade().defaultdict(int)
        by_type: dict[str, int] = _facade().defaultdict(int)
        by_source_policy: dict[str, int] = _facade().defaultdict(int)
        for record in memory.memory_v2_records:
            by_status[str(record.get("status") or "unknown")] += 1
            by_type[str(record.get("memory_type") or "unknown")] += 1
            by_source_policy[str(record.get("source_policy") or "unknown")] += 1
        return {
            "total": len(memory.memory_v2_records),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "by_source_policy": dict(by_source_policy),
        }

    def format_memory_v2_for_prompt(
        self, user_id: str, *, max_items: int = 6, memory_type: str | None = None
    ) -> str:
        """Format confirmed Memory v2 records as compact planner context."""
        active = [
            record
            for record in self.list_memories(user_id, status="active", memory_type=memory_type)
            if record.get("source_policy") != "blocked"
            and record.get("eligible_for_planner", True) is not False
        ]
        if not active:
            return "【MemoryV2】无已确认记忆。"
        type_order = {"preference": 0, "entity": 1, "episodic": 2}
        active.sort(
            key=lambda item: (
                type_order.get(str(item.get("memory_type") or ""), 99),
                str(item.get("updated_at") or ""),
            ),
            reverse=False,
        )
        lines = ["【MemoryV2】已确认记忆（仅供 planner 补全偏好/实体/任务上下文，不得编造）:"]
        for idx, record in enumerate(active[: max(1, int(max_items))], start=1):
            memory_kind = str(record.get("memory_type") or "unknown")
            key = str(record.get("key") or "-")
            value = _facade().json.dumps(record.get("value"), ensure_ascii=False, default=str)
            confidence = float(record.get("confidence") or 0.0)
            source = str(record.get("source") or "-")
            updated_at = str(record.get("updated_at") or "-")
            lines.append(
                f"{idx}. type={memory_kind}; key={key}; value={value}; confidence={confidence:.2f}; source={source}; updated_at={updated_at}"
            )
        return "\n".join(lines)

    def record_action(
        self, user_id: str, intent: str, slots: dict[str, _facade().Any], message: str = ""
    ) -> None:
        """
        记录用户操作模式

        Args:
            user_id: 用户ID
            intent: 意图类型
            slots: 槽位信息
            message: 原始消息
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = _facade().UserMemory(user_id=user_id)
        pattern_key = self._make_pattern_key(intent, slots)
        existing_pattern = None
        pattern_idx = -1
        for idx, action in enumerate(memory.frequent_actions):
            if action.get("pattern") == pattern_key:
                existing_pattern = action
                pattern_idx = idx
                break
        if existing_pattern:
            existing_pattern["frequency"] += 1
            existing_pattern["last_used"] = _facade().datetime.now().isoformat()
            existing_pattern["confidence"] = min(0.99, existing_pattern["confidence"] + 0.05)
            memory.frequent_actions[pattern_idx] = existing_pattern
        else:
            new_pattern = _facade().ActionPattern(
                pattern=pattern_key,
                intent=intent,
                slots=slots,
                frequency=1,
                last_used=_facade().datetime.now().isoformat(),
                confidence=0.5,
            )
            memory.frequent_actions.insert(0, new_pattern.to_dict())
        memory.frequent_actions.sort(key=lambda x: x.get("frequency", 0), reverse=True)
        memory.frequent_actions = memory.frequent_actions[: _facade().MAX_FREQUENT_ACTIONS]
        self._save_context_summary(memory, intent, slots, message)
        self._store.save_memory(user_id, memory)
        _facade().logger.debug("用户 %s 操作已记录: intent=%s, slots=%s", user_id, intent, slots)

    def _make_pattern_key(self, intent: str, slots: dict[str, _facade().Any]) -> str:
        """生成模式唯一键"""
        key_parts = [intent]
        important_slots = ["unit_name", "product_name", "model_number"]
        for slot_key in important_slots:
            if slot_key in slots and slots[slot_key]:
                key_parts.append(f"{slot_key}={slots[slot_key]}")
        key_str = "|".join(key_parts)
        return _facade().hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _save_context_summary(
        self,
        memory: _facade().UserMemory,
        intent: str,
        slots: dict[str, _facade().Any],
        message: str,
    ) -> None:
        """保存上下文摘要"""
        summary = _facade().ContextSummary(
            timestamp=_facade().datetime.now().isoformat(),
            intent=intent,
            slots=slots,
            message=message[:100] if message else "",
            turn_count=1,
        )
        memory.historical_contexts.insert(0, summary.to_dict())
        memory.historical_contexts = memory.historical_contexts[: _facade().MAX_CONTEXT_SUMMARIES]

    def get_recent_actions(
        self, user_id: str, limit: int = 5, intent_filter: str | None = None
    ) -> list[dict[str, _facade().Any]]:
        """
        获取最近操作模式

        Args:
            user_id: 用户ID
            limit: 返回数量
            intent_filter: 意图过滤器

        Returns:
            最近操作列表
        """
        memory = self._store.get_memory(user_id)
        if not memory:
            return []
        actions = memory.frequent_actions
        if intent_filter:
            actions = [a for a in actions if a.get("intent") == intent_filter]
        return actions[:limit]

    def get_similar_pattern(
        self, user_id: str, intent: str, slots: dict[str, _facade().Any], threshold: float = 0.2
    ) -> dict[str, _facade().Any] | None:
        """
        查找相似的操作模式

        Args:
            user_id: 用户ID
            intent: 目标意图
            slots: 当前槽位
            threshold: 相似度阈值

        Returns:
            相似模式或 None
        """
        memory = self._store.get_memory(user_id)
        if not memory:
            return None
        best_match = None
        best_score = 0.0
        for action in memory.frequent_actions:
            if action.get("intent") != intent:
                continue
            score = self._calculate_similarity(slots, action.get("slots", {}))
            action_confidence = action.get("confidence", 0.5)
            if score >= 0.5:
                combined_score = score
            else:
                combined_score = score * action_confidence
            if combined_score > best_score and combined_score >= threshold:
                best_score = combined_score
                best_match = action
        if best_match:
            best_match["match_score"] = round(best_score, 3)
        return best_match
