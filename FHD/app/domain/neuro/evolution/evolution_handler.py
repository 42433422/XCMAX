"""进化处理器（EvolutionHandler）——Neuro-DDD 自进化层的集成处理器。

整合 ``KBRetriever`` + ``ReflexPatternMiner`` + ``RuntimeSelfFix``，
为 ``ConsciousProcessor`` 提供运行时自进化能力。

处理的事件类型：
- ``error.occurred``：错误发生时，调用 ``RuntimeSelfFix.propose_fix()`` 提议修复。
- ``evolution.mine``：触发反射模式挖掘（``ReflexPatternMiner.mine()``）。
- ``evolution.search``：检索 KB（``KBRetriever.search()``）。
- ``evolution.index``：重新索引 KB（``KBRetriever.index()``）。

设计原则：
1. **best-effort**——任何子组件失败都不阻断主流程，返回降级结果。
2. **可审计**——所有进化动作记录到日志，供人工审核。
3. **安全优先**——``RuntimeSelfFix`` 只提议低风险修复，不修改代码。
4. **SLA 感知**——挖掘/索引是慢操作（>100ms），仅在 Conscious 处理器中运行。

注册方式：
    processor = get_conscious_processor()
    processor.register_handler("error.occurred", EvolutionHandler())
    processor.register_handler("evolution.mine", EvolutionHandler())
    processor.register_handler("evolution.search", EvolutionHandler())
    processor.register_handler("evolution.index", EvolutionHandler())
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.domain.neuro.evolution.kb_retriever import KBRetriever, get_kb_retriever
from app.domain.neuro.evolution.reflex_pattern_miner import (
    ReflexPatternMiner,
    get_reflex_pattern_miner,
)
from app.domain.neuro.evolution.runtime_self_fix import (
    FixProposal,
    RuntimeSelfFix,
    get_runtime_self_fix,
)
from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 支持的事件类型
_EVENT_ERROR_OCCURRED = "error.occurred"
_EVENT_MINE = "evolution.mine"
_EVENT_SEARCH = "evolution.search"
_EVENT_INDEX = "evolution.index"
_EVENT_EXPORT = "evolution.export"

_SUPPORTED_EVENTS = frozenset(
    {_EVENT_ERROR_OCCURRED, _EVENT_MINE, _EVENT_SEARCH, _EVENT_INDEX, _EVENT_EXPORT}
)


class EvolutionHandler:
    """自进化处理器。

    可注册到 ``ConsciousProcessor.register_handler(event_type, handler)``。

    Args:
        kb_retriever: KB 检索器（默认全局单例）。
        pattern_miner: 反射模式挖掘器（默认全局单例）。
        runtime_fixer: 运行时自修复器（默认全局单例）。
    """

    def __init__(
        self,
        kb_retriever: KBRetriever | None = None,
        pattern_miner: ReflexPatternMiner | None = None,
        runtime_fixer: RuntimeSelfFix | None = None,
    ) -> None:
        self._kb = kb_retriever or get_kb_retriever()
        self._miner = pattern_miner or get_reflex_pattern_miner()
        self._fixer = runtime_fixer or get_runtime_self_fix()
        self._total_handled = 0
        self._total_success = 0

    async def handle(self, event: NeuroEvent) -> dict[str, Any]:
        """处理进化相关事件。

        根据 ``event.event_type`` 分发到对应的子处理方法。

        Args:
            event: 神经事件，``payload`` 内容因事件类型而异。

        Returns:
            处理结果字典，至少包含 ``handled`` / ``event_type`` / ``latency_ms``。
        """
        start = time.perf_counter()
        self._total_handled += 1
        event_type = event.event_type
        payload = event.payload or {}

        result: dict[str, Any] = {
            "handled": False,
            "event_type": event_type,
            "latency_ms": 0.0,
        }

        try:
            if event_type == _EVENT_ERROR_OCCURRED:
                result.update(self._handle_error(payload))
            elif event_type == _EVENT_MINE:
                result.update(self._handle_mine(payload))
            elif event_type == _EVENT_SEARCH:
                result.update(self._handle_search(payload))
            elif event_type == _EVENT_INDEX:
                result.update(self._handle_index(payload))
            elif event_type == _EVENT_EXPORT:
                result.update(self._handle_export(payload))
            else:
                result["error"] = f"unsupported_event_type:{event_type}"
                logger.debug("EvolutionHandler: unsupported event %s", event_type)
                return result

            result["handled"] = True
            self._total_success += 1
        except RECOVERABLE_ERRORS:
            logger.debug("EvolutionHandler: failed to handle %s", event_type, exc_info=True)
            result["error"] = "handler_exception"

        result["latency_ms"] = (time.perf_counter() - start) * 1000
        return result

    def _handle_error(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理 ``error.occurred`` 事件——提议修复。"""
        error_message = str(payload.get("error") or payload.get("message") or "")
        context = payload.get("context") or {}

        proposal: FixProposal = self._fixer.propose_fix(error_message, context=context)

        return {
            "fix_proposal": {
                "fix_type": proposal.fix_type,
                "description": proposal.description,
                "confidence": proposal.confidence,
                "source": proposal.source,
                "is_actionable": proposal.is_actionable,
                "patch_strategy": proposal.patch_strategy,
                "rollback_plan": proposal.rollback_plan,
            },
        }

    def _handle_mine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理 ``evolution.mine`` 事件——挖掘反射模式。"""
        patterns = self._miner.mine()

        return {
            "mined_patterns": [
                {
                    "text_signature": p.text_signature,
                    "suggested_processor": p.suggested_processor,
                    "occurrence_count": p.occurrence_count,
                    "confidence": p.confidence,
                    "avg_latency_ms": p.avg_latency_ms,
                    "sla_hit_rate": p.sla_hit_rate,
                    "success_rate": p.success_rate,
                    "examples": p.examples,
                }
                for p in patterns
            ],
            "pattern_count": len(patterns),
        }

    def _handle_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理 ``evolution.search`` 事件——检索 KB。"""
        query = str(payload.get("query") or "")
        kind = payload.get("kind")  # "pattern" | "fix" | None
        top_k = int(payload.get("top_k") or 5)

        if not query:
            return {"results": [], "result_count": 0, "error": "empty_query"}

        if kind == "pattern":
            results = self._kb.search_patterns(query, top_k=top_k)
        elif kind == "fix":
            results = self._kb.search_fixes(query, top_k=top_k)
        else:
            results = self._kb.search(query, top_k=top_k)

        return {
            "results": [
                {
                    "kind": r.entry.kind,
                    "path": r.entry.path,
                    "score": r.score,
                    "content_preview": r.entry.content[:200],
                }
                for r in results
            ],
            "result_count": len(results),
        }

    def _handle_index(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理 ``evolution.index`` 事件——重新索引 KB。"""
        count = self._kb.index()
        return {
            "indexed_entries": count,
            "kb_stats": self._kb.get_stats(),
        }

    def _handle_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理 ``evolution.export`` 事件——将挖掘的模式导出到 KB。

        触发 ``ReflexPatternMiner.export_to_kb()``，将高置信度模式写入
        ``kb/patterns/``，然后重新索引 KB。

        payload 期望字段：
        - ``min_confidence``: 导出的最低置信度阈值（默认 0.9）
        """
        min_confidence = float(payload.get("min_confidence") or 0.9)
        exported = self._miner.export_to_kb(min_confidence=min_confidence)

        # 如果有导出，重新索引 KB
        if exported > 0:
            try:
                self._kb.index()
            except RECOVERABLE_ERRORS:
                logger.debug("KB re-index after export skipped", exc_info=True)

        return {
            "exported_patterns": exported,
            "min_confidence": min_confidence,
            "kb_stats": self._kb.get_stats(),
        }

    def get_stats(self) -> dict[str, Any]:
        """获取处理器统计。"""
        return {
            "total_handled": self._total_handled,
            "total_success": self._total_success,
            "success_rate": self._total_success / max(self._total_handled, 1),
            "supported_events": list(_SUPPORTED_EVENTS),
            "kb_stats": self._kb.get_stats(),
            "miner_stats": self._miner.get_stats(),
            "fixer_stats": self._fixer.get_stats(),
        }


_handler: EvolutionHandler | None = None


def get_evolution_handler() -> EvolutionHandler:
    """获取全局 ``EvolutionHandler`` 单例。"""
    global _handler
    if _handler is None:
        _handler = EvolutionHandler()
    return _handler


def reset_evolution_handler() -> None:
    """重置单例（测试用）。"""
    global _handler
    _handler = None
