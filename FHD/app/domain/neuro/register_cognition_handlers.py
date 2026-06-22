"""注册认知层 / 潜意识层 / 进化层 handler 到对应处理器。

在 NeuroBus 启动后调用，将 Phase 2-4 的 handler 接线到生产处理器：
- ``ConsciousLLMHandler`` → ``ConsciousProcessor``（处理 ``intent.process``）
- ``EvolutionHandler`` → ``ConsciousProcessor``（处理 ``error.occurred`` / ``evolution.*``）
- ``SubconsciousMLHandler`` → ``SubconsciousProcessor``（处理 ``routing.decision``）

设计原则：
1. **best-effort**——任何 handler 注册失败都不阻断启动，只记录警告。
2. **幂等**——重复调用安全（覆盖注册）。
3. **可禁用**——通过环境变量 ``XCAGI_NEURO_COGNITION=0`` 关闭认知层接线。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _cognition_enabled() -> bool:
    """检查认知层是否启用（默认启用）。"""
    raw = os.environ.get("XCAGI_NEURO_COGNITION", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def register_cognition_handlers() -> dict[str, Any]:
    """注册认知层 / 潜意识层 / 进化层 handler。

    Returns:
        注册结果统计。
    """
    if not _cognition_enabled():
        logger.info("认知层 handler 注册跳过（XCAGI_NEURO_COGNITION=0）")
        return {"enabled": False, "registered": []}

    registered: list[str] = []

    # 1. ConsciousLLMHandler → ConsciousProcessor
    try:
        from app.domain.neuro.cognition.conscious_llm_handler import ConsciousLLMHandler
        from app.domain.neuro.processors.conscious import get_conscious_processor

        processor = get_conscious_processor()
        handler = ConsciousLLMHandler()
        # ConsciousLLMHandler.handle 是 async，但 register_handler 期望 Callable[[NeuroEvent], Any]
        # async 函数满足这个签名（返回 coroutine）
        processor.register_handler("intent.process", handler.handle)
        registered.append("conscious:intent.process")
        logger.info("✅ ConsciousLLMHandler 已注册到 ConsciousProcessor（intent.process）")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ ConsciousLLMHandler 注册失败: %s", e)

    # 2. EvolutionHandler → ConsciousProcessor（4 种事件）
    try:
        from app.domain.neuro.evolution.evolution_handler import EvolutionHandler
        from app.domain.neuro.processors.conscious import get_conscious_processor

        processor = get_conscious_processor()
        handler = EvolutionHandler()
        for event_type in (
            "error.occurred",
            "evolution.mine",
            "evolution.search",
            "evolution.index",
            "evolution.export",
        ):
            processor.register_handler(event_type, handler.handle)
            registered.append(f"evolution:{event_type}")
        logger.info("✅ EvolutionHandler 已注册到 ConsciousProcessor（5 种事件）")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ EvolutionHandler 注册失败: %s", e)

    # 3. SubconsciousMLHandler → SubconsciousProcessor
    try:
        from app.domain.neuro.processors.subconscious import get_subconscious_processor
        from app.domain.neuro.subconscious.subconscious_ml_handler import SubconsciousMLHandler

        processor = get_subconscious_processor()
        handler = SubconsciousMLHandler()
        processor.register_handler("routing.decision", handler.handle)
        registered.append("subconscious:routing.decision")
        logger.info("✅ SubconsciousMLHandler 已注册到 SubconsciousProcessor（routing.decision）")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ SubconsciousMLHandler 注册失败: %s", e)

    logger.info(
        "认知层 handler 注册完成：共 %d 个 handler（%s）",
        len(registered),
        ", ".join(registered) or "无",
    )

    return {
        "enabled": True,
        "registered": registered,
        "handler_count": len(registered),
    }


def get_cognition_stats() -> dict[str, Any]:
    """获取认知层各组件统计（供监控端点使用）。"""
    stats: dict[str, Any] = {"enabled": _cognition_enabled()}

    if not _cognition_enabled():
        return stats

    # Conscious
    try:
        from app.domain.neuro.processors.conscious import get_conscious_processor

        stats["conscious_processor"] = get_conscious_processor().get_stats()
    except RECOVERABLE_ERRORS:
        stats["conscious_processor"] = {"error": "unavailable"}

    # Subconscious
    try:
        from app.domain.neuro.processors.subconscious import get_subconscious_processor

        stats["subconscious_processor"] = get_subconscious_processor().get_stats()
    except RECOVERABLE_ERRORS:
        stats["subconscious_processor"] = {"error": "unavailable"}

    # Cognition 组件
    try:
        from app.domain.neuro.cognition import get_llm_port

        stats["cognition"] = {
            "llm_port_available": get_llm_port().is_available,
        }
    except RECOVERABLE_ERRORS:
        stats["cognition"] = {"error": "unavailable"}

    # Subconscious ML 组件
    try:
        from app.domain.neuro.subconscious import (
            get_anomaly_detector,
            get_local_embedder,
            get_pattern_predictor,
        )

        stats["subconscious_ml"] = {
            "anomaly_detector": get_anomaly_detector().get_stats(),
            "pattern_predictor": get_pattern_predictor().get_stats(),
            "local_embedder": {"cache_size": get_local_embedder().cache_size},
        }
    except RECOVERABLE_ERRORS:
        stats["subconscious_ml"] = {"error": "unavailable"}

    # Evolution 组件
    try:
        from app.domain.neuro.evolution import (
            get_evolution_handler,
            get_kb_retriever,
            get_reflex_pattern_miner,
            get_runtime_self_fix,
        )

        stats["evolution"] = {
            "handler": get_evolution_handler().get_stats(),
            "kb_retriever": get_kb_retriever().get_stats(),
            "reflex_pattern_miner": get_reflex_pattern_miner().get_stats(),
            "runtime_self_fix": get_runtime_self_fix().get_stats(),
        }
    except RECOVERABLE_ERRORS:
        stats["evolution"] = {"error": "unavailable"}

    return stats


__all__ = [
    "get_cognition_stats",
    "register_cognition_handlers",
]
