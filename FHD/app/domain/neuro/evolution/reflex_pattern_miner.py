"""反射模式挖掘器（ReflexPatternMiner）——从路由决策日志挖掘新反射规则。

分析 ``routing_decisions.jsonl``（Phase 1 的反馈闭环日志），发现：
- 频繁出现的文本模式
- 总是路由到同一处理器的模式
- 高 SLA 命中率的模式

挖掘出的模式可提议为新反射规则，减少 Conscious 处理器的负载。

设计约束：
- 读取 ``routing_decisions.jsonl``（append-only JSONL）。
- 简单文本特征提取（关键词 + 长度 + 首字符），不依赖重 NLP。
- 输出 ``MinedPattern`` 列表，由人工/自动审核后加入 ``IntentReflexArc``。
- < 100ms（单次挖掘扫描最近 N 条日志）。

Phase 4 用途：让系统从自身运行数据中学习，自动发现可固化为反射的模式。
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path("routing_decisions.jsonl")
_DEFAULT_SCAN_LIMIT = 500  # 最近 N 条日志
_MIN_OCCURRENCES = 3  # 模式最少出现次数
_MIN_CONFIDENCE = 0.8  # 路由一致性最低置信度


@dataclass
class MinedPattern:
    """挖掘出的反射模式。"""

    text_signature: str  # 文本签名（关键词组合）
    suggested_processor: str  # 建议的处理器类型
    occurrence_count: int = 0  # 出现次数
    confidence: float = 0.0  # 路由一致性置信度
    avg_latency_ms: float = 0.0  # 平均延迟
    sla_hit_rate: float = 0.0  # SLA 命中率
    success_rate: float = 0.0  # 成功率
    examples: list[str] = field(default_factory=list)  # 示例文本
    metadata: dict[str, Any] = field(default_factory=dict)


def _extract_signature(text: str) -> str:
    """提取文本签名（简化版：前 3 个关键词 + 长度区间）。"""
    if not text:
        return ""

    # 提取关键词（中文单字 + 英文单词）
    tokens = set()
    tokens.update(re.findall(r"[\u4e00-\u9fff]", text[:50]))
    tokens.update(w.lower() for w in re.findall(r"[a-zA-Z]{2,}", text[:50]))

    # 取前 3 个排序后的关键词
    top_tokens = sorted(tokens)[:3]

    # 长度区间
    length = len(text)
    if length <= 5:
        length_bin = "short"
    elif length <= 20:
        length_bin = "medium"
    else:
        length_bin = "long"

    return f"{'|'.join(top_tokens)}::{length_bin}"


class ReflexPatternMiner:
    """反射模式挖掘器。

    Args:
        log_path: ``routing_decisions.jsonl`` 路径。
        scan_limit: 单次扫描的最大日志条数。
        min_occurrences: 模式最少出现次数才被考虑。
        min_confidence: 路由一致性最低置信度。
    """

    def __init__(
        self,
        log_path: Path | str = _DEFAULT_LOG_PATH,
        scan_limit: int = _DEFAULT_SCAN_LIMIT,
        min_occurrences: int = _MIN_OCCURRENCES,
        min_confidence: float = _MIN_CONFIDENCE,
    ) -> None:
        self._log_path = Path(log_path)
        self._scan_limit = max(scan_limit, 10)
        self._min_occurrences = max(min_occurrences, 2)
        self._min_confidence = max(min_confidence, 0.5)

    def mine(self) -> list[MinedPattern]:
        """挖掘反射模式。

        Returns:
            ``MinedPattern`` 列表，按出现次数降序。
        """
        records = self._read_recent_records()
        if not records:
            return []

        # 按文本签名分组
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            text = str(record.get("text") or record.get("query") or "")
            if not text:
                continue
            sig = _extract_signature(text)
            if not sig:
                continue
            groups[sig].append(record)

        # 分析每个分组
        patterns: list[MinedPattern] = []
        for sig, group_records in groups.items():
            if len(group_records) < self._min_occurrences:
                continue

            pattern = self._analyze_group(sig, group_records)
            if pattern and pattern.confidence >= self._min_confidence:
                patterns.append(pattern)

        # 按出现次数降序
        patterns.sort(key=lambda p: p.occurrence_count, reverse=True)
        return patterns

    def _read_recent_records(self) -> list[dict[str, Any]]:
        """读取最近的日志记录。"""
        if not self._log_path.exists():
            return []

        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().splitlines()
        except RECOVERABLE_ERRORS:
            logger.debug("Failed to read %s", self._log_path, exc_info=True)
            return []

        # 取最后 N 行
        recent_lines = lines[-self._scan_limit :] if len(lines) > self._scan_limit else lines

        records: list[dict[str, Any]] = []
        for line in recent_lines:
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except RECOVERABLE_ERRORS:
                # json.JSONDecodeError 已包含在 RECOVERABLE_ERRORS 中
                continue

        return records

    def _analyze_group(
        self,
        signature: str,
        records: list[dict[str, Any]],
    ) -> MinedPattern | None:
        """分析一个分组，生成 MinedPattern。"""
        # 路由分布
        processor_counts: Counter[str] = Counter()
        latencies: list[float] = []
        sla_hits: list[bool] = []
        successes: list[bool] = []
        examples: list[str] = []

        for record in records:
            action = str(record.get("action") or record.get("processor_type") or "")
            if action:
                processor_counts[action] += 1

            latency = float(record.get("latency_ms") or 0.0)
            latencies.append(latency)

            sla_hits.append(bool(record.get("sla_hit", True)))
            successes.append(bool(record.get("success", True)))

            text = str(record.get("text") or record.get("query") or "")
            if text and len(examples) < 3:
                examples.append(text[:100])

        if not processor_counts:
            return None

        # 最常见的处理器
        suggested_processor, top_count = processor_counts.most_common(1)[0]
        total = sum(processor_counts.values())
        confidence = top_count / total if total > 0 else 0.0

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        sla_rate = sum(sla_hits) / len(sla_hits) if sla_hits else 0.0
        success_rate = sum(successes) / len(successes) if successes else 0.0

        return MinedPattern(
            text_signature=signature,
            suggested_processor=suggested_processor,
            occurrence_count=total,
            confidence=confidence,
            avg_latency_ms=avg_latency,
            sla_hit_rate=sla_rate,
            success_rate=success_rate,
            examples=examples,
            metadata={
                "processor_distribution": dict(processor_counts),
            },
        )

    def get_stats(self) -> dict[str, Any]:
        """获取统计。"""
        records = self._read_recent_records()
        return {
            "log_path": str(self._log_path),
            "log_exists": self._log_path.exists(),
            "records_scanned": len(records),
            "min_occurrences": self._min_occurrences,
            "min_confidence": self._min_confidence,
        }

    def export_to_kb(self, kb_root: Path | None = None, *, min_confidence: float = 0.9) -> int:
        """将挖掘出的高置信度模式导出到 KB patterns 目录。

        安全策略：
        - 只导出 ``confidence >= min_confidence``（默认 0.9）的模式。
        - 文件名带时间戳，避免覆盖。
        - schema_version=1，kind="mined_reflex"。
        - 不修改已有 KB 文件。

        Args:
            kb_root: KB 根目录（默认 ``FHD/XCAGI/kb``）。
            min_confidence: 导出的最低置信度阈值。

        Returns:
            导出的模式数。
        """
        if kb_root is None:
            # 默认 KB 根：FHD/XCAGI/kb
            kb_root = Path(__file__).resolve().parents[4] / "XCAGI" / "kb"

        patterns_dir = kb_root / "patterns"
        try:
            patterns_dir.mkdir(parents=True, exist_ok=True)
        except RECOVERABLE_ERRORS:
            logger.debug("Failed to create patterns dir %s", patterns_dir, exc_info=True)
            return 0

        mined = self.mine()
        exported = 0
        timestamp = _now_utc_iso()

        for pattern in mined:
            if pattern.confidence < min_confidence:
                continue

            # 构造 KB 条目
            entry = {
                "created_at": timestamp,
                "kind": "mined_reflex",
                "metadata": {
                    "source": "reflex_pattern_miner",
                    "occurrence_count": pattern.occurrence_count,
                    "avg_latency_ms": pattern.avg_latency_ms,
                    "sla_hit_rate": pattern.sla_hit_rate,
                    "success_rate": pattern.success_rate,
                    "processor_distribution": pattern.metadata.get("processor_distribution", {}),
                },
                "pattern": f"mined_reflex::{pattern.suggested_processor}",
                "schema_version": 1,
                "summary": (
                    f"挖掘出的反射模式：签名={pattern.text_signature}，"
                    f"建议处理器={pattern.suggested_processor}，"
                    f"出现={pattern.occurrence_count}次，置信度={pattern.confidence:.2f}"
                ),
            }

            # 文件名：时间戳 + 签名哈希
            sig_hash = hash(pattern.text_signature) & 0xFFFFFFFF
            filename = f"{timestamp.replace(':', '').replace('+', 'Z')}-mined-{sig_hash:08x}.json"
            filepath = patterns_dir / filename

            try:
                filepath.write_text(
                    json.dumps(entry, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                exported += 1
            except RECOVERABLE_ERRORS:
                logger.debug("Failed to write %s", filepath, exc_info=True)

        if exported > 0:
            logger.info(
                "ReflexPatternMiner 导出 %d 个模式到 %s（阈值=%.2f）",
                exported,
                patterns_dir,
                min_confidence,
            )

        return exported


def _now_utc_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


_miner: ReflexPatternMiner | None = None


def get_reflex_pattern_miner() -> ReflexPatternMiner:
    """获取全局 ``ReflexPatternMiner`` 单例。"""
    global _miner
    if _miner is None:
        _miner = ReflexPatternMiner()
    return _miner


def reset_reflex_pattern_miner() -> None:
    """重置单例（测试用）。"""
    global _miner
    _miner = None
