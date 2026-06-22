"""运行时自修复（RuntimeSelfFix）——错误发生时检索 KB 并提议修复。

设计原则：
1. **安全优先**——只提议低风险修复（配置/参数/重试策略），不修改代码。
2. **KB 驱动**——使用 ``KBRetriever`` 检索历史修复知识。
3. **best-effort**——任何步骤失败都不阻断主流程。
4. **可审计**——所有修复提议记录到日志，供人工审核。

修复类型：
- ``retry``：建议重试（调整重试次数/间隔）
- ``config``：建议配置调整（环境变量/参数）
- ``fallback``：建议降级到备选路径
- ``noop``：无可用修复（仅记录）

Phase 4 用途：让系统在运行时从历史修复知识中学习，自动应对已知错误模式。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.domain.neuro.evolution.kb_retriever import KBRetriever, KBSearchResult, get_kb_retriever
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 3
_MIN_SCORE = 0.3  # 最低相似度阈值


@dataclass
class FixProposal:
    """修复提议。"""

    fix_type: str = "noop"  # "retry" | "config" | "fallback" | "noop"
    description: str = ""
    confidence: float = 0.0
    source: str = ""  # KB 条目路径
    applicability_check: str = ""
    patch_strategy: str = ""
    rollback_plan: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        """是否可执行（非 noop）。"""
        return self.fix_type != "noop"


class RuntimeSelfFix:
    """运行时自修复。

    Args:
        kb_retriever: KB 检索器（默认全局单例）。
        min_score: 最低相似度阈值。
    """

    def __init__(
        self,
        kb_retriever: KBRetriever | None = None,
        min_score: float = _MIN_SCORE,
    ) -> None:
        self._kb = kb_retriever or get_kb_retriever()
        self._min_score = max(min_score, 0.0)
        self._total_proposals = 0
        self._actionable_proposals = 0

    def propose_fix(
        self,
        error_message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> FixProposal:
        """为给定错误提议修复。

        Args:
            error_message: 错误消息。
            context: 附加上下文（组件名、操作类型等）。

        Returns:
            ``FixProposal``，可能是 noop（无可用修复）。
        """
        self._total_proposals += 1

        if not error_message:
            return FixProposal(fix_type="noop", description="empty_error_message")

        # 1. 检索 KB 中的修复知识
        try:
            results = self._kb.search_fixes(error_message, top_k=_DEFAULT_TOP_K)
        except RECOVERABLE_ERRORS:
            logger.debug("KB search failed", exc_info=True)
            return FixProposal(fix_type="noop", description="kb_search_failed")

        if not results:
            return FixProposal(fix_type="noop", description="no_kb_match")

        # 2. 取最佳匹配
        best = results[0]
        if best.score < self._min_score:
            return FixProposal(
                fix_type="noop",
                description="low_confidence_match",
                confidence=best.score,
            )

        # 3. 从 KB 条目提取修复策略
        proposal = self._extract_proposal(best)
        if proposal.is_actionable:
            self._actionable_proposals += 1
            logger.info(
                "RuntimeSelfFix proposed %s fix (confidence=%.3f): %s",
                proposal.fix_type,
                proposal.confidence,
                proposal.description[:100],
            )

        return proposal

    def _extract_proposal(self, result: KBSearchResult) -> FixProposal:
        """从 KB 检索结果提取修复提议。"""
        entry = result.entry
        raw = entry.raw

        # 检查是否有 executable_template
        template = raw.get("executable_template") or {}
        applicability = str(template.get("applicability_check") or "")
        patch_strategy = str(template.get("patch_strategy") or "")
        rollback = str(template.get("rollback_plan") or "")

        # 推断修复类型
        fix_type = self._infer_fix_type(raw, patch_strategy)

        # 描述
        description = str(raw.get("symptom") or raw.get("root_cause") or entry.content[:200])

        return FixProposal(
            fix_type=fix_type,
            description=description,
            confidence=result.score,
            source=entry.path,
            applicability_check=applicability,
            patch_strategy=patch_strategy,
            rollback_plan=rollback,
            metadata={
                "kind": entry.kind,
                "created_at": raw.get("created_at", ""),
                "required_tests": template.get("required_tests", []),
            },
        )

    def _infer_fix_type(self, raw: dict[str, Any], patch_strategy: str) -> str:
        """从 KB 条目推断修复类型。"""
        text = (
            str(raw.get("symptom", ""))
            + " "
            + str(raw.get("root_cause", ""))
            + " "
            + patch_strategy
        ).lower()

        if any(kw in text for kw in ["retry", "重试", "timeout", "超时"]):
            return "retry"
        if any(kw in text for kw in ["config", "配置", "env", "环境变量", "parameter"]):
            return "config"
        if any(kw in text for kw in ["fallback", "降级", "degrade", "alternative"]):
            return "fallback"

        return "noop"

    def get_stats(self) -> dict[str, Any]:
        """获取统计。"""
        return {
            "total_proposals": self._total_proposals,
            "actionable_proposals": self._actionable_proposals,
            "actionable_rate": self._actionable_proposals / max(self._total_proposals, 1),
            "min_score": self._min_score,
            "kb_stats": self._kb.get_stats(),
        }


_fixer: RuntimeSelfFix | None = None


def get_runtime_self_fix() -> RuntimeSelfFix:
    """获取全局 ``RuntimeSelfFix`` 单例。"""
    global _fixer
    if _fixer is None:
        _fixer = RuntimeSelfFix()
    return _fixer


def reset_runtime_self_fix() -> None:
    """重置单例（测试用）。"""
    global _fixer
    _fixer = None
