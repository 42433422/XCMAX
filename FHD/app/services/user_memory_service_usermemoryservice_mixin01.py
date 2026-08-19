# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.services.user_memory_service')

class _UserMemoryServicePart01Mixin:

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_type: str='json'):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._store = _facade().UserMemoryStore(storage_type=storage_type)
        self._memory_v2_lock = _facade().threading.RLock()
        self._initialized = True
        _facade().logger.info('用户记忆服务已初始化')

    def add_preference(self, user_id: str, key: str, value: _facade().Any) -> None:
        """
        添加用户偏好

        Args:
            user_id: 用户ID
            key: 偏好键 (如 "favorite_customer", "default_template")
            value: 偏好值
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = _facade().UserMemory(user_id=user_id)
        memory.preferences[key] = {'value': value, 'updated_at': _facade().datetime.now().isoformat(), 'count': memory.preferences.get(key, {}).get('count', 0) + 1}
        self._store.save_memory(user_id, memory)
        _facade().logger.debug('用户 %s 偏好已更新: %s = %s', user_id, key, value)

    def get_preference(self, user_id: str, key: str, default: _facade().Any=None) -> _facade().Any:
        """
        获取用户偏好

        Args:
            user_id: 用户ID
            key: 偏好键
            default: 默认值

        Returns:
            偏好值或默认值
        """
        memory = self._store.get_memory(user_id)
        if memory and key in memory.preferences:
            return memory.preferences[key].get('value', default)
        return default

    def get_all_preferences(self, user_id: str) -> dict[str, _facade().Any]:
        """获取用户所有偏好"""
        memory = self._store.get_memory(user_id)
        if memory:
            return {k: v.get('value') for (k, v) in memory.preferences.items()}
        return {}

    def _normalize_memory_v2_type(self, memory_type: str) -> str:
        normalized = str(memory_type or '').strip().lower()
        aliases = {'pref': 'preference', 'preference_memory': 'preference', 'entity_memory': 'entity', 'episodic_memory': 'episodic', 'task': 'episodic'}
        normalized = aliases.get(normalized, normalized)
        if normalized not in _facade().MEMORY_V2_TYPES:
            raise ValueError(f'unsupported memory_type: {memory_type}')
        return normalized

    def _normalize_memory_v2_status(self, status: str) -> str:
        normalized = str(status or '').strip().lower()
        if normalized not in _facade().MEMORY_V2_STATUSES:
            raise ValueError(f'unsupported memory status: {status}')
        return normalized

    def _memory_v2_fingerprint(self, memory_type: str, key: str, value: _facade().Any) -> str:
        raw = _facade().json.dumps({'memory_type': memory_type, 'key': key, 'value': value}, ensure_ascii=False, sort_keys=True, default=str)
        return _facade().hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

    def _govern_memory_v2_candidate(self, *, source: str, confidence: float, evidence: list[dict[str, _facade().Any]] | None) -> dict[str, _facade().Any]:
        normalized_source = str(source or 'agent_observation').strip().lower()
        normalized_source = normalized_source.replace(' ', '_')[:80] or 'agent_observation'
        flags: list[str] = []
        source_policy = 'requires_confirmation'
        source_trust = 'observed'
        try:
            effective_confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            effective_confidence = 0.5
            flags.append('invalid_confidence_defaulted')
        evidence_items = [dict(item) for item in list(evidence or []) if isinstance(item, dict) and item][:10]
        evidence_required = False
        if normalized_source in _facade().MEMORY_V2_BLOCKED_SOURCES:
            source_policy = 'blocked'
            source_trust = 'blocked'
            flags.append('blocked_source')
            effective_confidence = min(effective_confidence, 0.0)
        elif normalized_source in _facade().MEMORY_V2_TRUSTED_SOURCES:
            source_policy = 'trusted_pending'
            source_trust = 'trusted_user'
        elif normalized_source in _facade().MEMORY_V2_OBSERVED_SOURCES:
            source_policy = 'observed_pending'
            source_trust = 'observed'
            evidence_required = True
        else:
            source_policy = 'needs_evidence'
            source_trust = 'unverified'
            evidence_required = True
            flags.append('unknown_source')
        if evidence_required and (not evidence_items):
            flags.append('missing_evidence')
            effective_confidence = min(effective_confidence, 0.35)
        return {'source': normalized_source, 'source_policy': source_policy, 'source_trust': source_trust, 'source_evidence_required': evidence_required, 'requires_user_confirmation': True, 'auto_confirm_allowed': False, 'eligible_for_planner': False, 'governance_flags': flags, 'confidence': effective_confidence, 'evidence': evidence_items}

    def _find_memory_v2_record(self, memory: _facade().UserMemory, memory_id: str) -> tuple[int, dict[str, _facade().Any] | None]:
        for (idx, record) in enumerate(memory.memory_v2_records):
            if str(record.get('memory_id') or '') == str(memory_id or ''):
                return (idx, record)
        return (-1, None)

    def propose_memory_candidate(self, user_id: str, memory_type: str, key: str, value: _facade().Any, *, source: str='agent_observation', confidence: float=0.5, evidence: list[dict[str, _facade().Any]] | None=None) -> dict[str, _facade().Any]:
        """Atomically deduplicate and persist a governed memory candidate."""
        with self._memory_v2_lock:
            return self._propose_memory_candidate_unlocked(user_id, memory_type, key, value, source=source, confidence=confidence, evidence=evidence)

    def _propose_memory_candidate_unlocked(self, user_id: str, memory_type: str, key: str, value: _facade().Any, *, source: str='agent_observation', confidence: float=0.5, evidence: list[dict[str, _facade().Any]] | None=None) -> dict[str, _facade().Any]:
        """写入待确认记忆候选，不直接污染 planner 可用记忆。"""
        normalized_type = self._normalize_memory_v2_type(memory_type)
        normalized_key = str(key or '').strip()
        if not user_id:
            return {'success': False, 'message': '缺少 user_id'}
        if not normalized_key:
            return {'success': False, 'message': '缺少 memory key'}
        governance = self._govern_memory_v2_candidate(source=source, confidence=confidence, evidence=evidence)
        memory = self._store.get_memory(user_id) or _facade().UserMemory(user_id=user_id)
        fingerprint = self._memory_v2_fingerprint(normalized_type, normalized_key, value)
        for record in memory.memory_v2_records:
            if record.get('fingerprint') == fingerprint and record.get('status') in {'pending', 'active', 'rejected'}:
                return {'success': True, 'created': False, 'candidate': dict(record)}
        now = _facade().datetime.now().isoformat()
        candidate = {'memory_id': f'mem_{_facade().uuid.uuid4().hex[:12]}', 'memory_type': normalized_type, 'key': normalized_key, 'value': value, 'status': 'rejected' if governance['source_policy'] == 'blocked' else 'pending', 'confidence': governance['confidence'], 'source': governance['source'], 'source_policy': governance['source_policy'], 'source_trust': governance['source_trust'], 'source_evidence_required': governance['source_evidence_required'], 'requires_user_confirmation': governance['requires_user_confirmation'], 'auto_confirm_allowed': governance['auto_confirm_allowed'], 'eligible_for_planner': governance['eligible_for_planner'], 'governance_flags': governance['governance_flags'], 'evidence': governance['evidence'], 'fingerprint': fingerprint, 'created_at': now, 'updated_at': now}
        if candidate['status'] == 'rejected':
            candidate['rejected_at'] = now
            candidate['rejected_reason'] = 'source_policy_blocked'
        memory.memory_v2_records.insert(0, candidate)
        memory.memory_v2_records = memory.memory_v2_records[:_facade().MAX_MEMORY_V2_RECORDS]
        self._store.save_memory(user_id, memory)
        return {'success': True, 'created': True, 'candidate': dict(candidate)}

    def confirm_memory_candidate(self, user_id: str, memory_id: str, *, correction: dict[str, _facade().Any] | None=None) -> dict[str, _facade().Any]:
        """确认候选记忆，确认后才进入 active 状态并可被 planner 使用。"""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {'success': False, 'message': '用户记忆不存在'}
        (idx, record) = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {'success': False, 'message': '记忆不存在'}
        if record.get('status') == 'deleted':
            return {'success': False, 'message': '记忆已删除'}
        if record.get('status') == 'rejected':
            return {'success': False, 'message': '记忆已拒绝，不能确认'}
        if record.get('source_policy') == 'blocked':
            return {'success': False, 'message': '记忆来源被策略阻断'}
        updated = dict(record)
        patch = dict(correction or {})
        if patch:
            if 'memory_type' in patch:
                updated['memory_type'] = self._normalize_memory_v2_type(str(patch['memory_type']))
            if 'key' in patch:
                updated['key'] = str(patch['key'] or '').strip()
            if 'value' in patch:
                updated['value'] = patch['value']
            if 'confidence' in patch:
                updated['confidence'] = max(0.0, min(1.0, float(patch['confidence'])))
            updated['correction_count'] = int(updated.get('correction_count') or 0) + 1
        if not str(updated.get('key') or '').strip():
            return {'success': False, 'message': '缺少 memory key'}
        now = _facade().datetime.now().isoformat()
        updated['status'] = 'active'
        updated['confirmed_at'] = now
        updated['updated_at'] = now
        updated['eligible_for_planner'] = True
        updated['fingerprint'] = self._memory_v2_fingerprint(str(updated['memory_type']), str(updated['key']), updated.get('value'))
        memory.memory_v2_records[idx] = updated
        if updated['memory_type'] == 'preference':
            key = str(updated['key'])
            memory.preferences[key] = {'value': updated.get('value'), 'updated_at': now, 'count': memory.preferences.get(key, {}).get('count', 0) + 1, 'source': 'memory_v2', 'memory_id': updated['memory_id']}
        self._store.save_memory(user_id, memory)
        return {'success': True, 'memory': dict(updated)}

    def reject_memory_candidate(self, user_id: str, memory_id: str, *, reason: str='') -> dict[str, _facade().Any]:
        return self._set_memory_v2_status(user_id, memory_id, 'rejected', reason=reason)

    def delete_memory(self, user_id: str, memory_id: str, *, reason: str='') -> dict[str, _facade().Any]:
        return self._set_memory_v2_status(user_id, memory_id, 'deleted', reason=reason)

    def _set_memory_v2_status(self, user_id: str, memory_id: str, status: str, *, reason: str='') -> dict[str, _facade().Any]:
        normalized_status = self._normalize_memory_v2_status(status)
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {'success': False, 'message': '用户记忆不存在'}
        (idx, record) = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {'success': False, 'message': '记忆不存在'}
        updated = dict(record)
        now = _facade().datetime.now().isoformat()
        updated['status'] = normalized_status
        updated['updated_at'] = now
        if reason:
            updated[f'{normalized_status}_reason'] = reason
        if normalized_status == 'deleted':
            updated['deleted_at'] = now
        if normalized_status == 'rejected':
            updated['rejected_at'] = now
        memory.memory_v2_records[idx] = updated
        if normalized_status in {'deleted', 'rejected'} and record.get('memory_type') == 'preference':
            pref_key = str(record.get('key') or '').strip()
            previous_pref = memory.preferences.get(pref_key)
            if isinstance(previous_pref, dict) and previous_pref.get('memory_id') == record.get('memory_id'):
                memory.preferences.pop(pref_key, None)
        self._store.save_memory(user_id, memory)
        return {'success': True, 'memory': dict(updated)}

    def correct_memory(self, user_id: str, memory_id: str, *, value: _facade().Any | None=None, key: str | None=None, reason: str='') -> dict[str, _facade().Any]:
        """纠正 active/pending 记忆，保留同一个 memory_id 便于审计。"""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {'success': False, 'message': '用户记忆不存在'}
        (idx, record) = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {'success': False, 'message': '记忆不存在'}
        if record.get('status') == 'deleted':
            return {'success': False, 'message': '记忆已删除'}
        updated = dict(record)
        previous_key = str(record.get('key') or '').strip()
        if key is not None:
            updated['key'] = str(key or '').strip()
        if value is not None:
            updated['value'] = value
        if not str(updated.get('key') or '').strip():
            return {'success': False, 'message': '缺少 memory key'}
        now = _facade().datetime.now().isoformat()
        updated['updated_at'] = now
        updated['last_correction_reason'] = reason
        updated['correction_count'] = int(updated.get('correction_count') or 0) + 1
        updated['fingerprint'] = self._memory_v2_fingerprint(str(updated['memory_type']), str(updated['key']), updated.get('value'))
        memory.memory_v2_records[idx] = updated
        if updated.get('status') == 'active' and updated.get('memory_type') == 'preference':
            if previous_key and previous_key != str(updated['key']):
                previous_pref = memory.preferences.get(previous_key)
                if isinstance(previous_pref, dict) and previous_pref.get('memory_id') == updated['memory_id']:
                    memory.preferences.pop(previous_key, None)
            pref_key = str(updated['key'])
            memory.preferences[pref_key] = {'value': updated.get('value'), 'updated_at': now, 'count': memory.preferences.get(pref_key, {}).get('count', 0) + 1, 'source': 'memory_v2', 'memory_id': updated['memory_id']}
        self._store.save_memory(user_id, memory)
        return {'success': True, 'memory': dict(updated)}

    def list_memories(self, user_id: str, *, status: str | None=None, memory_type: str | None=None) -> list[dict[str, _facade().Any]]:
        memory = self._store.get_memory(user_id)
        if memory is None:
            return []
        normalized_status = self._normalize_memory_v2_status(status) if status else None
        normalized_type = self._normalize_memory_v2_type(memory_type) if memory_type else None
        records = []
        for record in memory.memory_v2_records:
            if normalized_status and record.get('status') != normalized_status:
                continue
            if normalized_type and record.get('memory_type') != normalized_type:
                continue
            records.append(dict(record))
        return records

    def record_memory_recall(self, user_id: str, memory_id: str) -> dict[str, _facade().Any]:
        """Reinforce a confirmed memory after it contributed to retrieval."""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {'success': False, 'message': '用户记忆不存在'}
        (idx, record) = self._find_memory_v2_record(memory, memory_id)
        if record is None or record.get('status') != 'active':
            return {'success': False, 'message': '可召回记忆不存在'}
        updated = dict(record)
        now = _facade().datetime.now().isoformat()
        updated['recall_count'] = int(updated.get('recall_count') or 0) + 1
        updated['last_recalled_at'] = now
        memory.memory_v2_records[idx] = updated
        self._store.save_memory(user_id, memory)
        return {'success': True, 'memory': dict(updated)}

    def get_memory_v2_summary(self, user_id: str) -> dict[str, _facade().Any]:
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {'total': 0, 'by_status': {}, 'by_type': {}}
        by_status: dict[str, int] = _facade().defaultdict(int)
        by_type: dict[str, int] = _facade().defaultdict(int)
        by_source_policy: dict[str, int] = _facade().defaultdict(int)
        for record in memory.memory_v2_records:
            by_status[str(record.get('status') or 'unknown')] += 1
            by_type[str(record.get('memory_type') or 'unknown')] += 1
            by_source_policy[str(record.get('source_policy') or 'unknown')] += 1
        return {'total': len(memory.memory_v2_records), 'by_status': dict(by_status), 'by_type': dict(by_type), 'by_source_policy': dict(by_source_policy)}

    def format_memory_v2_for_prompt(self, user_id: str, *, max_items: int=6, memory_type: str | None=None) -> str:
        """Format confirmed Memory v2 records as compact planner context."""
        active = [record for record in self.list_memories(user_id, status='active', memory_type=memory_type) if record.get('source_policy') != 'blocked' and record.get('eligible_for_planner', True) is not False]
        if not active:
            return '【MemoryV2】无已确认记忆。'
        type_order = {'preference': 0, 'entity': 1, 'episodic': 2}
        active.sort(key=lambda item: (type_order.get(str(item.get('memory_type') or ''), 99), str(item.get('updated_at') or '')), reverse=False)
        lines = ['【MemoryV2】已确认记忆（仅供 planner 补全偏好/实体/任务上下文，不得编造）:']
        for (idx, record) in enumerate(active[:max(1, int(max_items))], start=1):
            memory_kind = str(record.get('memory_type') or 'unknown')
            key = str(record.get('key') or '-')
            value = _facade().json.dumps(record.get('value'), ensure_ascii=False, default=str)
            confidence = float(record.get('confidence') or 0.0)
            source = str(record.get('source') or '-')
            updated_at = str(record.get('updated_at') or '-')
            lines.append(f'{idx}. type={memory_kind}; key={key}; value={value}; confidence={confidence:.2f}; source={source}; updated_at={updated_at}')
        return '\n'.join(lines)

    def record_action(self, user_id: str, intent: str, slots: dict[str, _facade().Any], message: str='') -> None:
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
        for (idx, action) in enumerate(memory.frequent_actions):
            if action.get('pattern') == pattern_key:
                existing_pattern = action
                pattern_idx = idx
                break
        if existing_pattern:
            existing_pattern['frequency'] += 1
            existing_pattern['last_used'] = _facade().datetime.now().isoformat()
            existing_pattern['confidence'] = min(0.99, existing_pattern['confidence'] + 0.05)
            memory.frequent_actions[pattern_idx] = existing_pattern
        else:
            new_pattern = _facade().ActionPattern(pattern=pattern_key, intent=intent, slots=slots, frequency=1, last_used=_facade().datetime.now().isoformat(), confidence=0.5)
            memory.frequent_actions.insert(0, new_pattern.to_dict())
        memory.frequent_actions.sort(key=lambda x: x.get('frequency', 0), reverse=True)
        memory.frequent_actions = memory.frequent_actions[:_facade().MAX_FREQUENT_ACTIONS]
        self._save_context_summary(memory, intent, slots, message)
        self._store.save_memory(user_id, memory)
        _facade().logger.debug('用户 %s 操作已记录: intent=%s, slots=%s', user_id, intent, slots)

    def _make_pattern_key(self, intent: str, slots: dict[str, _facade().Any]) -> str:
        """生成模式唯一键"""
        key_parts = [intent]
        important_slots = ['unit_name', 'product_name', 'model_number']
        for slot_key in important_slots:
            if slot_key in slots and slots[slot_key]:
                key_parts.append(f'{slot_key}={slots[slot_key]}')
        key_str = '|'.join(key_parts)
        return _facade().hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _save_context_summary(self, memory: _facade().UserMemory, intent: str, slots: dict[str, _facade().Any], message: str) -> None:
        """保存上下文摘要"""
        summary = _facade().ContextSummary(timestamp=_facade().datetime.now().isoformat(), intent=intent, slots=slots, message=message[:100] if message else '', turn_count=1)
        memory.historical_contexts.insert(0, summary.to_dict())
        memory.historical_contexts = memory.historical_contexts[:_facade().MAX_CONTEXT_SUMMARIES]

    def get_recent_actions(self, user_id: str, limit: int=5, intent_filter: str | None=None) -> list[dict[str, _facade().Any]]:
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
            actions = [a for a in actions if a.get('intent') == intent_filter]
        return actions[:limit]

    def get_similar_pattern(self, user_id: str, intent: str, slots: dict[str, _facade().Any], threshold: float=0.2) -> dict[str, _facade().Any] | None:
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
            if action.get('intent') != intent:
                continue
            score = self._calculate_similarity(slots, action.get('slots', {}))
            action_confidence = action.get('confidence', 0.5)
            if score >= 0.5:
                combined_score = score
            else:
                combined_score = score * action_confidence
            if combined_score > best_score and combined_score >= threshold:
                best_score = combined_score
                best_match = action
        if best_match:
            best_match['match_score'] = round(best_score, 3)
        return best_match
