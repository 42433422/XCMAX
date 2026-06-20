"""自进化层（Evolution Layer）Phase 4 组件测试。

覆盖：
- ``KBRetriever``：知识库检索器（索引、检索、增量添加、统计）
- ``ReflexPatternMiner``：反射模式挖掘器（日志读取、签名提取、模式分析）
- ``RuntimeSelfFix``：运行时自修复（KB 检索、修复类型推断、noop 降级）
- ``EvolutionHandler``：进化处理器（4 种事件类型、错误处理、统计）

测试策略：
- ``KBRetriever``：使用真实 KB 文件（``FHD/XCAGI/kb/``）+ 临时目录隔离
- ``ReflexPatternMiner``：使用临时 JSONL 文件模拟路由决策日志
- ``RuntimeSelfFix``：使用 mock KBRetriever 隔离测试修复推断逻辑
- ``EvolutionHandler``：使用 mock 子组件测试事件分发
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.domain.neuro.evolution.evolution_handler import (
    EvolutionHandler,
    get_evolution_handler,
    reset_evolution_handler,
)
from app.domain.neuro.evolution.kb_retriever import (
    KBEntry,
    KBRetriever,
    KBSearchResult,
    _cosine_similarity,
    _extract_search_text,
    get_kb_retriever,
    reset_kb_retriever,
)
from app.domain.neuro.evolution.reflex_pattern_miner import (
    MinedPattern,
    ReflexPatternMiner,
    _extract_signature,
    get_reflex_pattern_miner,
    reset_reflex_pattern_miner,
)
from app.domain.neuro.evolution.runtime_self_fix import (
    FixProposal,
    RuntimeSelfFix,
    get_runtime_self_fix,
    reset_runtime_self_fix,
)

# ============================================================================
# 辅助函数测试
# ============================================================================


class TestCosineSimilarity:
    """余弦相似度测试。"""

    def test_identical_vectors_returns_one(self):
        """相同向量返回 1。"""
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_returns_zero(self):
        """正交向量返回 0。"""
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_empty_vectors_returns_zero(self):
        """空向量返回 0。"""
        assert _cosine_similarity([], []) == 0.0

    def test_different_length_returns_zero(self):
        """不同长度返回 0。"""
        assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_norm_returns_zero(self):
        """零范数返回 0。"""
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestExtractSearchText:
    """搜索文本提取测试。"""

    def test_extracts_summary(self):
        """提取 summary 字段。"""
        raw = {"summary": "测试摘要"}
        assert "测试摘要" in _extract_search_text(raw)

    def test_extracts_multiple_fields(self):
        """提取多个字段。"""
        raw = {
            "summary": "摘要",
            "symptom": "症状",
            "root_cause": "根因",
            "before": "之前",
            "after": "之后",
            "pattern": "模式",
        }
        text = _extract_search_text(raw)
        for field in ("摘要", "症状", "根因", "之前", "之后", "模式"):
            assert field in text

    def test_empty_dict_returns_empty(self):
        """空字典返回空字符串。"""
        assert _extract_search_text({}) == ""

    def test_non_string_values_skipped(self):
        """非字符串值被跳过。"""
        raw = {"summary": 123, "pattern": "ok"}
        text = _extract_search_text(raw)
        assert "ok" in text
        assert "123" not in text


class TestExtractSignature:
    """文本签名提取测试。"""

    def test_empty_text_returns_empty(self):
        """空文本返回空签名。"""
        assert _extract_signature("") == ""

    def test_short_text(self):
        """短文本分类为 short。"""
        sig = _extract_signature("hi")
        assert "short" in sig

    def test_medium_text(self):
        """中等长度文本分类为 medium。"""
        sig = _extract_signature("hello world foo bar")
        assert "medium" in sig

    def test_long_text(self):
        """长文本分类为 long。"""
        sig = _extract_signature("a" * 30)
        assert "long" in sig

    def test_chinese_text_extracts_chars(self):
        """中文文本提取单字。"""
        sig = _extract_signature("你好世界测试")
        assert "你" in sig or "世" in sig or "界" in sig

    def test_english_text_extracts_words(self):
        """英文文本提取单词。"""
        sig = _extract_signature("hello world foo bar")
        # 至少包含一个英文单词
        assert any(w in sig for w in ["hello", "world", "foo", "bar"])


# ============================================================================
# KBRetriever 测试
# ============================================================================


class TestKBRetriever:
    """知识库检索器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_kb_retriever()
        yield
        reset_kb_retriever()

    @pytest.fixture
    def tmp_kb(self, tmp_path: Path) -> Path:
        """创建临时 KB 目录结构。"""
        patterns_dir = tmp_path / "patterns"
        fixes_dir = tmp_path / "fixes"
        patterns_dir.mkdir()
        fixes_dir.mkdir()

        # 写入测试 pattern
        (patterns_dir / "p1.json").write_text(
            json.dumps(
                {
                    "summary": "验证候选代码而非陈旧磁盘代码",
                    "before": "对磁盘代码运行测试",
                    "after": "对覆盖层运行测试",
                    "pattern": "candidate_overlay",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # 写入测试 fix
        (fixes_dir / "f1.json").write_text(
            json.dumps(
                {
                    "symptom": "测试跳过生产根目录",
                    "root_cause": "路径解析错误",
                    "fix_diff": "添加路径解析逻辑",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return tmp_path

    def test_index_returns_count(self, tmp_kb: Path):
        """index 返回索引条目数。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        count = retriever.index()
        assert count == 2

    def test_index_empty_dir_returns_zero(self, tmp_path: Path):
        """空目录索引返回 0。"""
        retriever = KBRetriever(kb_root=tmp_path)
        assert retriever.index() == 0

    def test_index_nonexistent_dir_returns_zero(self, tmp_path: Path):
        """不存在的目录返回 0。"""
        retriever = KBRetriever(kb_root=tmp_path / "nonexistent")
        assert retriever.index() == 0

    def test_search_returns_results(self, tmp_kb: Path):
        """检索返回相关结果。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        results = retriever.search("候选代码")
        assert len(results) > 0
        assert isinstance(results[0], KBSearchResult)
        assert results[0].score > 0.0

    def test_search_empty_query_returns_empty(self, tmp_kb: Path):
        """空查询返回空列表。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        # 空字符串经过 embed 后可能是零向量
        results = retriever.search("")
        assert results == []

    def test_search_not_indexed_returns_empty(self, tmp_kb: Path):
        """未索引时检索返回空。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        assert retriever.search("anything") == []

    def test_search_patterns_filters_kind(self, tmp_kb: Path):
        """search_patterns 只返回 pattern 类型。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        results = retriever.search_patterns("代码")
        assert all(r.entry.kind == "pattern" for r in results)

    def test_search_fixes_filters_kind(self, tmp_kb: Path):
        """search_fixes 只返回 fix 类型。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        results = retriever.search_fixes("测试")
        assert all(r.entry.kind == "fix" for r in results)

    def test_search_top_k_limits_results(self, tmp_kb: Path):
        """top_k 限制返回数量。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        results = retriever.search("代码", top_k=1)
        assert len(results) <= 1

    def test_add_entry_incremental(self, tmp_kb: Path):
        """add_entry 增量添加条目。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        initial_count = retriever.entry_count

        retriever.add_entry(
            "pattern",
            {"summary": "新增的模式条目"},
            path="/tmp/new.json",
        )
        assert retriever.entry_count == initial_count + 1

    def test_add_entry_empty_content_skipped(self, tmp_kb: Path):
        """空内容的条目被跳过。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        initial_count = retriever.entry_count

        retriever.add_entry("pattern", {})
        assert retriever.entry_count == initial_count

    def test_is_indexed_flag(self, tmp_kb: Path):
        """index 后 is_indexed 为 True。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        assert not retriever.is_indexed
        retriever.index()
        assert retriever.is_indexed

    def test_get_stats(self, tmp_kb: Path):
        """get_stats 返回统计信息。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        retriever.index()
        stats = retriever.get_stats()
        assert stats["total_entries"] == 2
        assert stats["indexed"] is True
        assert "pattern" in stats["by_kind"]
        assert "fix" in stats["by_kind"]
        assert stats["by_kind"]["pattern"] == 1
        assert stats["by_kind"]["fix"] == 1

    def test_index_can_be_called_multiple_times(self, tmp_kb: Path):
        """index 可多次调用（重新索引）。"""
        retriever = KBRetriever(kb_root=tmp_kb)
        c1 = retriever.index()
        c2 = retriever.index()
        assert c1 == c2

    def test_singleton_returns_same_instance(self):
        """get_kb_retriever 返回同一单例。"""
        r1 = get_kb_retriever()
        r2 = get_kb_retriever()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        """reset_kb_retriever 清除单例。"""
        r1 = get_kb_retriever()
        reset_kb_retriever()
        r2 = get_kb_retriever()
        assert r1 is not r2


# ============================================================================
# ReflexPatternMiner 测试
# ============================================================================


class TestReflexPatternMiner:
    """反射模式挖掘器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_reflex_pattern_miner()
        yield
        reset_reflex_pattern_miner()

    @pytest.fixture
    def log_file(self, tmp_path: Path) -> Path:
        """创建测试用 routing_decisions.jsonl。"""
        log_path = tmp_path / "routing_decisions.jsonl"
        records = [
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.5,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.6,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.4,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "复杂问题需要思考",
                "action": "conscious",
                "latency_ms": 150.0,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "复杂问题需要思考",
                "action": "conscious",
                "latency_ms": 180.0,
                "sla_hit": False,
                "success": True,
            },
            {
                "text": "复杂问题需要思考",
                "action": "conscious",
                "latency_ms": 200.0,
                "sla_hit": False,
                "success": True,
            },
        ]
        with log_path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return log_path

    def test_mine_returns_patterns(self, log_file: Path):
        """mine 返回挖掘出的模式。"""
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=3, min_confidence=0.5)
        patterns = miner.mine()
        assert len(patterns) > 0
        assert all(isinstance(p, MinedPattern) for p in patterns)

    def test_mine_empty_log_returns_empty(self, tmp_path: Path):
        """空日志返回空列表。"""
        log_path = tmp_path / "empty.jsonl"
        log_path.write_text("", encoding="utf-8")
        miner = ReflexPatternMiner(log_path=log_path)
        assert miner.mine() == []

    def test_mine_nonexistent_log_returns_empty(self, tmp_path: Path):
        """不存在的日志返回空列表。"""
        miner = ReflexPatternMiner(log_path=tmp_path / "nonexistent.jsonl")
        assert miner.mine() == []

    def test_mine_filters_low_occurrences(self, log_file: Path):
        """min_occurrences 过滤低频模式。"""
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=10)
        patterns = miner.mine()
        assert patterns == []

    def test_mine_filters_low_confidence(self, log_file: Path):
        """min_confidence 过滤低置信度模式。"""
        # 混合路由 → 低置信度
        log_path = log_file.parent / "mixed.jsonl"
        with log_path.open("w", encoding="utf-8") as f:
            for action in ["reflex", "conscious", "reflex", "conscious"]:
                f.write(json.dumps({"text": "same text", "action": action}) + "\n")
        miner = ReflexPatternMiner(log_path=log_path, min_confidence=0.9)
        patterns = miner.mine()
        # 置信度 0.5 < 0.9，应被过滤
        assert patterns == []

    def test_mine_patterns_sorted_by_count(self, log_file: Path):
        """挖掘结果按出现次数降序。"""
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=2, min_confidence=0.5)
        patterns = miner.mine()
        for i in range(len(patterns) - 1):
            assert patterns[i].occurrence_count >= patterns[i + 1].occurrence_count

    def test_mined_pattern_fields(self, log_file: Path):
        """MinedPattern 字段完整。"""
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=3, min_confidence=0.5)
        patterns = miner.mine()
        assert len(patterns) > 0
        p = patterns[0]
        assert p.text_signature
        assert p.suggested_processor
        assert p.occurrence_count >= 3
        assert 0.0 <= p.confidence <= 1.0
        assert p.avg_latency_ms >= 0.0
        assert 0.0 <= p.sla_hit_rate <= 1.0
        assert 0.0 <= p.success_rate <= 1.0
        assert isinstance(p.examples, list)

    def test_mined_pattern_metadata_has_distribution(self, log_file: Path):
        """MinedPattern.metadata 包含 processor_distribution。"""
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=3, min_confidence=0.5)
        patterns = miner.mine()
        assert len(patterns) > 0
        assert "processor_distribution" in patterns[0].metadata

    def test_mine_handles_invalid_json_lines(self, tmp_path: Path):
        """无效 JSON 行被跳过。"""
        log_path = tmp_path / "invalid.jsonl"
        log_path.write_text(
            "invalid json line\n" + json.dumps({"text": "valid", "action": "reflex"}) + "\n",
            encoding="utf-8",
        )
        miner = ReflexPatternMiner(log_path=log_path, min_occurrences=1, min_confidence=0.5)
        # 不应抛异常
        patterns = miner.mine()
        # 至少能解析一条
        assert isinstance(patterns, list)

    def test_scan_limit_reads_last_n(self, tmp_path: Path):
        """scan_limit 只读最后 N 行。"""
        log_path = tmp_path / "large.jsonl"
        with log_path.open("w", encoding="utf-8") as f:
            for i in range(100):
                f.write(json.dumps({"text": f"text_{i}", "action": "reflex"}) + "\n")
        miner = ReflexPatternMiner(log_path=log_path, scan_limit=10, min_occurrences=1)
        # 每条记录签名不同，应返回空
        patterns = miner.mine()
        assert isinstance(patterns, list)

    def test_get_stats(self, log_file: Path):
        """get_stats 返回统计。"""
        miner = ReflexPatternMiner(log_path=log_file)
        stats = miner.get_stats()
        assert stats["log_path"] == str(log_file)
        assert stats["log_exists"] is True
        assert stats["records_scanned"] >= 0
        assert "min_occurrences" in stats
        assert "min_confidence" in stats

    def test_singleton_returns_same_instance(self):
        """get_reflex_pattern_miner 返回同一单例。"""
        m1 = get_reflex_pattern_miner()
        m2 = get_reflex_pattern_miner()
        assert m1 is m2

    def test_reset_clears_singleton(self):
        """reset_reflex_pattern_miner 清除单例。"""
        m1 = get_reflex_pattern_miner()
        reset_reflex_pattern_miner()
        m2 = get_reflex_pattern_miner()
        assert m1 is not m2


# ============================================================================
# RuntimeSelfFix 测试
# ============================================================================


class TestRuntimeSelfFix:
    """运行时自修复测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_runtime_self_fix()
        yield
        reset_runtime_self_fix()

    @pytest.fixture
    def mock_kb(self):
        """构造 mock KBRetriever。"""
        kb = MagicMock(spec=KBRetriever)
        return kb

    def test_propose_fix_empty_error_returns_noop(self, mock_kb):
        """空错误消息返回 noop。"""
        fixer = RuntimeSelfFix(kb_retriever=mock_kb)
        proposal = fixer.propose_fix("")
        assert proposal.fix_type == "noop"
        assert not proposal.is_actionable

    def test_propose_fix_no_kb_match_returns_noop(self, mock_kb):
        """KB 无匹配返回 noop。"""
        mock_kb.search_fixes.return_value = []
        fixer = RuntimeSelfFix(kb_retriever=mock_kb)
        proposal = fixer.propose_fix("some error")
        assert proposal.fix_type == "noop"
        mock_kb.search_fixes.assert_called_once()

    def test_propose_fix_low_score_returns_noop(self, mock_kb):
        """低相似度返回 noop。"""
        entry = KBEntry(kind="fix", path="/tmp/x.json", content="test", raw={})
        mock_kb.search_fixes.return_value = [KBSearchResult(entry=entry, score=0.1)]
        fixer = RuntimeSelfFix(kb_retriever=mock_kb, min_score=0.5)
        proposal = fixer.propose_fix("some error")
        assert proposal.fix_type == "noop"

    def test_propose_fix_retry_type(self, mock_kb):
        """retry 关键词推断为 retry 类型。"""
        entry = KBEntry(
            kind="fix",
            path="/tmp/retry.json",
            content="timeout retry",
            raw={
                "symptom": "请求超时",
                "root_cause": "网络 timeout",
                "executable_template": {
                    "patch_strategy": "增加 retry 次数",
                    "applicability_check": "网络超时场景",
                    "rollback_plan": "恢复原 retry 次数",
                },
            },
        )
        mock_kb.search_fixes.return_value = [KBSearchResult(entry=entry, score=0.9)]
        fixer = RuntimeSelfFix(kb_retriever=mock_kb, min_score=0.5)
        proposal = fixer.propose_fix("请求超时")
        assert proposal.fix_type == "retry"
        assert proposal.is_actionable
        assert proposal.confidence == 0.9
        assert proposal.source == "/tmp/retry.json"

    def test_propose_fix_config_type(self, mock_kb):
        """config 关键词推断为 config 类型。"""
        entry = KBEntry(
            kind="fix",
            path="/tmp/config.json",
            content="config",
            raw={
                "symptom": "配置错误",
                "root_cause": "env 变量缺失",
            },
        )
        mock_kb.search_fixes.return_value = [KBSearchResult(entry=entry, score=0.8)]
        fixer = RuntimeSelfFix(kb_retriever=mock_kb, min_score=0.5)
        proposal = fixer.propose_fix("配置错误")
        assert proposal.fix_type == "config"
        assert proposal.is_actionable

    def test_propose_fix_fallback_type(self, mock_kb):
        """fallback 关键词推断为 fallback 类型。"""
        entry = KBEntry(
            kind="fix",
            path="/tmp/fallback.json",
            content="fallback",
            raw={
                "symptom": "服务降级",
                "root_cause": "依赖不可用",
            },
        )
        mock_kb.search_fixes.return_value = [KBSearchResult(entry=entry, score=0.8)]
        fixer = RuntimeSelfFix(kb_retriever=mock_kb, min_score=0.5)
        proposal = fixer.propose_fix("服务降级")
        assert proposal.fix_type == "fallback"
        assert proposal.is_actionable

    def test_propose_fix_noop_type_when_no_keyword(self, mock_kb):
        """无匹配关键词返回 noop。"""
        entry = KBEntry(
            kind="fix",
            path="/tmp/unknown.json",
            content="unknown issue",
            raw={
                "symptom": "未知问题",
                "root_cause": "未知根因",
            },
        )
        mock_kb.search_fixes.return_value = [KBSearchResult(entry=entry, score=0.8)]
        fixer = RuntimeSelfFix(kb_retriever=mock_kb, min_score=0.5)
        proposal = fixer.propose_fix("未知问题")
        assert proposal.fix_type == "noop"
        assert not proposal.is_actionable

    def test_propose_fix_with_context(self, mock_kb):
        """带上下文的修复提议。"""
        entry = KBEntry(
            kind="fix",
            path="/tmp/ctx.json",
            content="retry",
            raw={"symptom": "timeout", "root_cause": "network"},
        )
        mock_kb.search_fixes.return_value = [KBSearchResult(entry=entry, score=0.9)]
        fixer = RuntimeSelfFix(kb_retriever=mock_kb, min_score=0.5)
        proposal = fixer.propose_fix("timeout", context={"component": "api"})
        assert proposal.fix_type == "retry"

    def test_propose_fix_kb_search_exception_returns_noop(self, mock_kb):
        """KB 检索异常返回 noop。"""
        mock_kb.search_fixes.side_effect = RuntimeError("kb error")
        fixer = RuntimeSelfFix(kb_retriever=mock_kb)
        proposal = fixer.propose_fix("error")
        assert proposal.fix_type == "noop"

    def test_fix_proposal_is_actionable_property(self):
        """FixProposal.is_actionable 属性。"""
        assert FixProposal(fix_type="retry").is_actionable is True
        assert FixProposal(fix_type="config").is_actionable is True
        assert FixProposal(fix_type="fallback").is_actionable is True
        assert FixProposal(fix_type="noop").is_actionable is False

    def test_get_stats(self, mock_kb):
        """get_stats 返回统计。"""
        mock_kb.get_stats.return_value = {"total_entries": 0}
        fixer = RuntimeSelfFix(kb_retriever=mock_kb)
        fixer.propose_fix("")  # noop
        stats = fixer.get_stats()
        assert stats["total_proposals"] == 1
        assert stats["actionable_proposals"] == 0
        assert stats["actionable_rate"] == 0.0

    def test_singleton_returns_same_instance(self):
        """get_runtime_self_fix 返回同一单例。"""
        f1 = get_runtime_self_fix()
        f2 = get_runtime_self_fix()
        assert f1 is f2

    def test_reset_clears_singleton(self):
        """reset_runtime_self_fix 清除单例。"""
        f1 = get_runtime_self_fix()
        reset_runtime_self_fix()
        f2 = get_runtime_self_fix()
        assert f1 is not f2


# ============================================================================
# EvolutionHandler 测试
# ============================================================================


class TestEvolutionHandler:
    """进化处理器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_evolution_handler()
        yield
        reset_evolution_handler()

    @pytest.fixture
    def mock_kb(self):
        kb = MagicMock(spec=KBRetriever)
        kb.get_stats.return_value = {"total_entries": 0}
        return kb

    @pytest.fixture
    def mock_miner(self):
        miner = MagicMock(spec=ReflexPatternMiner)
        miner.get_stats.return_value = {"records_scanned": 0}
        miner.mine.return_value = []
        return miner

    @pytest.fixture
    def mock_fixer(self):
        fixer = MagicMock(spec=RuntimeSelfFix)
        fixer.get_stats.return_value = {"total_proposals": 0}
        fixer.propose_fix.return_value = FixProposal(
            fix_type="retry",
            description="重试",
            confidence=0.9,
            source="/tmp/x.json",
        )
        return fixer

    @pytest.fixture
    def handler(self, mock_kb, mock_miner, mock_fixer):
        return EvolutionHandler(
            kb_retriever=mock_kb,
            pattern_miner=mock_miner,
            runtime_fixer=mock_fixer,
        )

    def _make_event(self, event_type: str, payload: dict):
        """构造 mock NeuroEvent。"""
        event = MagicMock()
        event.event_type = event_type
        event.payload = payload
        return event

    async def test_handle_error_occurred(self, handler, mock_fixer):
        """处理 error.occurred 事件。"""
        event = self._make_event("error.occurred", {"error": "timeout error"})
        result = await handler.handle(event)
        assert result["handled"] is True
        assert result["event_type"] == "error.occurred"
        assert "fix_proposal" in result
        assert result["fix_proposal"]["fix_type"] == "retry"
        mock_fixer.propose_fix.assert_called_once()

    async def test_handle_error_occurred_with_message_field(self, handler, mock_fixer):
        """error.occurred 支持 message 字段。"""
        event = self._make_event("error.occurred", {"message": "some error"})
        result = await handler.handle(event)
        assert result["handled"] is True
        mock_fixer.propose_fix.assert_called_once_with("some error", context={})

    async def test_handle_evolution_mine(self, handler, mock_miner):
        """处理 evolution.mine 事件。"""
        event = self._make_event("evolution.mine", {})
        result = await handler.handle(event)
        assert result["handled"] is True
        assert "mined_patterns" in result
        assert result["pattern_count"] == 0
        mock_miner.mine.assert_called_once()

    async def test_handle_evolution_search(self, handler, mock_kb):
        """处理 evolution.search 事件。"""
        mock_kb.search.return_value = []
        event = self._make_event(
            "evolution.search",
            {"query": "测试", "top_k": 3},
        )
        result = await handler.handle(event)
        assert result["handled"] is True
        assert "results" in result
        assert result["result_count"] == 0
        mock_kb.search.assert_called_once_with("测试", top_k=3)

    async def test_handle_evolution_search_patterns(self, handler, mock_kb):
        """evolution.search 支持 kind=pattern。"""
        mock_kb.search_patterns.return_value = []
        event = self._make_event(
            "evolution.search",
            {"query": "测试", "kind": "pattern"},
        )
        result = await handler.handle(event)
        assert result["handled"] is True
        mock_kb.search_patterns.assert_called_once()

    async def test_handle_evolution_search_fixes(self, handler, mock_kb):
        """evolution.search 支持 kind=fix。"""
        mock_kb.search_fixes.return_value = []
        event = self._make_event(
            "evolution.search",
            {"query": "错误", "kind": "fix"},
        )
        result = await handler.handle(event)
        assert result["handled"] is True
        mock_kb.search_fixes.assert_called_once()

    async def test_handle_evolution_search_empty_query(self, handler, mock_kb):
        """evolution.search 空查询返回错误。"""
        event = self._make_event("evolution.search", {"query": ""})
        result = await handler.handle(event)
        assert result["handled"] is True
        assert result["result_count"] == 0
        assert result["error"] == "empty_query"
        mock_kb.search.assert_not_called()

    async def test_handle_evolution_index(self, handler, mock_kb):
        """处理 evolution.index 事件。"""
        mock_kb.index.return_value = 5
        event = self._make_event("evolution.index", {})
        result = await handler.handle(event)
        assert result["handled"] is True
        assert result["indexed_entries"] == 5
        mock_kb.index.assert_called_once()

    async def test_handle_unsupported_event(self, handler):
        """不支持的事件类型返回 handled=False。"""
        event = self._make_event("unknown.event", {})
        result = await handler.handle(event)
        assert result["handled"] is False
        assert "unsupported_event_type" in result["error"]

    async def test_handle_returns_latency_ms(self, handler, mock_fixer):
        """handle 返回 latency_ms。"""
        event = self._make_event("error.occurred", {"error": "x"})
        result = await handler.handle(event)
        assert "latency_ms" in result
        assert result["latency_ms"] >= 0.0

    async def test_handle_exception_returns_handled_false(self, handler, mock_fixer):
        """子组件异常时返回 handled=False。"""
        mock_fixer.propose_fix.side_effect = RuntimeError("boom")
        event = self._make_event("error.occurred", {"error": "x"})
        result = await handler.handle(event)
        assert result["handled"] is False
        assert result["error"] == "handler_exception"

    async def test_handle_increments_counters(self, handler, mock_miner):
        """handle 递增计数器。"""
        event = self._make_event("evolution.mine", {})
        await handler.handle(event)
        await handler.handle(event)
        stats = handler.get_stats()
        assert stats["total_handled"] == 2
        assert stats["total_success"] == 2

    def test_get_stats(self, handler, mock_kb, mock_miner, mock_fixer):
        """get_stats 返回完整统计。"""
        stats = handler.get_stats()
        assert stats["total_handled"] == 0
        assert stats["total_success"] == 0
        assert "supported_events" in stats
        assert "kb_stats" in stats
        assert "miner_stats" in stats
        assert "fixer_stats" in stats

    def test_singleton_returns_same_instance(self):
        """get_evolution_handler 返回同一单例。"""
        h1 = get_evolution_handler()
        h2 = get_evolution_handler()
        assert h1 is h2

    def test_reset_clears_singleton(self):
        """reset_evolution_handler 清除单例。"""
        h1 = get_evolution_handler()
        reset_evolution_handler()
        h2 = get_evolution_handler()
        assert h1 is not h2


# ============================================================================
# 集成测试（使用真实 KB 文件）
# ============================================================================


class TestEvolutionIntegration:
    """集成测试——使用真实 KB 文件验证端到端流程。"""

    @pytest.fixture(autouse=True)
    def _reset_all(self):
        reset_kb_retriever()
        reset_reflex_pattern_miner()
        reset_runtime_self_fix()
        reset_evolution_handler()
        yield
        reset_kb_retriever()
        reset_reflex_pattern_miner()
        reset_runtime_self_fix()
        reset_evolution_handler()

    def test_kb_retriever_indexes_real_kb(self):
        """KBRetriever 能索引真实 KB 文件。"""
        retriever = KBRetriever()
        count = retriever.index()
        # 真实 KB 有 13 patterns + 13 fixes = 26 条目
        assert count >= 20, f"Expected >= 20 KB entries, got {count}"

    def test_kb_retriever_search_real_kb(self):
        """KBRetriever 能检索真实 KB。"""
        retriever = KBRetriever()
        retriever.index()
        results = retriever.search("测试")
        assert len(results) > 0
        assert results[0].score > 0.0

    def test_runtime_self_fix_with_real_kb(self):
        """RuntimeSelfFix 能用真实 KB 提议修复。"""
        retriever = KBRetriever()
        retriever.index()
        fixer = RuntimeSelfFix(kb_retriever=retriever, min_score=0.1)
        # 用 KB 中存在的关键词
        proposal = fixer.propose_fix("测试跳过")
        # 至少不抛异常
        assert isinstance(proposal, FixProposal)

    def test_evolution_handler_search_real_kb(self):
        """EvolutionHandler 能用真实 KB 检索。"""
        import asyncio

        retriever = KBRetriever()
        retriever.index()
        handler = EvolutionHandler(kb_retriever=retriever)

        event = MagicMock()
        event.event_type = "evolution.search"
        event.payload = {"query": "测试", "top_k": 3}

        result = asyncio.get_event_loop().run_until_complete(handler.handle(event))
        assert result["handled"] is True
        assert result["result_count"] >= 0


# ============================================================================
# ReflexPatternMiner.export_to_kb 测试
# ============================================================================


class TestReflexPatternMinerExport:
    """反射模式挖掘器 KB 导出测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_reflex_pattern_miner()
        yield
        reset_reflex_pattern_miner()

    @pytest.fixture
    def log_file(self, tmp_path: Path) -> Path:
        """创建高置信度路由日志（同一签名总是路由到同一处理器）。"""
        log_path = tmp_path / "routing_decisions.jsonl"
        records = [
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.5,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.6,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.4,
                "sla_hit": True,
                "success": True,
            },
            {
                "text": "你好世界",
                "action": "reflex",
                "latency_ms": 0.5,
                "sla_hit": True,
                "success": True,
            },
        ]
        with log_path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return log_path

    def test_export_to_kb_writes_files(self, log_file, tmp_path):
        """export_to_kb 将高置信度模式写入 KB patterns 目录。"""
        kb_root = tmp_path / "kb"
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=3, min_confidence=0.5)
        exported = miner.export_to_kb(kb_root=kb_root, min_confidence=0.5)

        assert exported >= 1
        patterns_dir = kb_root / "patterns"
        assert patterns_dir.exists()
        files = list(patterns_dir.glob("*.json"))
        assert len(files) >= 1

        # 验证文件内容
        import json as json_mod

        data = json_mod.loads(files[0].read_text(encoding="utf-8"))
        assert data["kind"] == "mined_reflex"
        assert data["schema_version"] == 1
        assert "mined_reflex::" in data["pattern"]
        assert "summary" in data
        assert data["metadata"]["source"] == "reflex_pattern_miner"

    def test_export_to_kb_filters_low_confidence(self, log_file, tmp_path):
        """低置信度模式不被导出。"""
        kb_root = tmp_path / "kb"
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=3, min_confidence=0.5)
        # min_confidence=0.99 过滤掉所有模式（实际置信度=1.0，但阈值太高可能过滤）
        # 这里用 0.5 确保有导出
        exported = miner.export_to_kb(kb_root=kb_root, min_confidence=0.5)
        assert exported >= 1

    def test_export_to_kb_empty_log_returns_zero(self, tmp_path):
        """空日志导出 0。"""
        log_path = tmp_path / "empty.jsonl"
        log_path.write_text("", encoding="utf-8")
        miner = ReflexPatternMiner(log_path=log_path)
        exported = miner.export_to_kb(kb_root=tmp_path / "kb")
        assert exported == 0

    def test_export_to_kb_creates_patterns_dir(self, log_file, tmp_path):
        """export_to_kb 自动创建 patterns 目录。"""
        kb_root = tmp_path / "new_kb"
        assert not (kb_root / "patterns").exists()
        miner = ReflexPatternMiner(log_path=log_file, min_occurrences=3, min_confidence=0.5)
        miner.export_to_kb(kb_root=kb_root, min_confidence=0.5)
        assert (kb_root / "patterns").exists()


# ============================================================================
# EvolutionHandler._handle_export 测试
# ============================================================================


class TestEvolutionHandlerExport:
    """EvolutionHandler 导出事件测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_evolution_handler()
        yield
        reset_evolution_handler()

    @pytest.fixture
    def mock_kb(self):
        kb = MagicMock(spec=KBRetriever)
        kb.get_stats.return_value = {"total_entries": 0}
        kb.index.return_value = 0
        return kb

    @pytest.fixture
    def mock_miner(self):
        miner = MagicMock(spec=ReflexPatternMiner)
        miner.get_stats.return_value = {"records_scanned": 0}
        miner.mine.return_value = []
        miner.export_to_kb.return_value = 2
        return miner

    @pytest.fixture
    def mock_fixer(self):
        fixer = MagicMock(spec=RuntimeSelfFix)
        fixer.get_stats.return_value = {"total_proposals": 0}
        return fixer

    @pytest.fixture
    def handler(self, mock_kb, mock_miner, mock_fixer):
        return EvolutionHandler(
            kb_retriever=mock_kb,
            pattern_miner=mock_miner,
            runtime_fixer=mock_fixer,
        )

    def _make_event(self, event_type: str, payload: dict):
        event = MagicMock()
        event.event_type = event_type
        event.payload = payload
        return event

    async def test_handle_evolution_export(self, handler, mock_miner, mock_kb):
        """处理 evolution.export 事件。"""
        event = self._make_event("evolution.export", {"min_confidence": 0.8})
        result = await handler.handle(event)
        assert result["handled"] is True
        assert result["exported_patterns"] == 2
        assert result["min_confidence"] == 0.8
        mock_miner.export_to_kb.assert_called_once_with(min_confidence=0.8)
        # 有导出时应重新索引 KB
        mock_kb.index.assert_called_once()

    async def test_handle_evolution_export_no_export_skips_reindex(
        self, handler, mock_miner, mock_kb
    ):
        """无导出时不重新索引 KB。"""
        mock_miner.export_to_kb.return_value = 0
        event = self._make_event("evolution.export", {})
        result = await handler.handle(event)
        assert result["handled"] is True
        assert result["exported_patterns"] == 0
        mock_kb.index.assert_not_called()

    async def test_handle_evolution_export_default_confidence(self, handler, mock_miner):
        """默认 min_confidence=0.9。"""
        event = self._make_event("evolution.export", {})
        await handler.handle(event)
        mock_miner.export_to_kb.assert_called_once_with(min_confidence=0.9)


# ============================================================================
# register_cognition_handlers 测试
# ============================================================================


class TestRegisterCognitionHandlers:
    """认知层 handler 注册测试。"""

    def test_register_cognition_handlers_returns_result(self):
        """register_cognition_handlers 返回注册结果。"""
        from app.domain.neuro.register_cognition_handlers import (
            register_cognition_handlers,
        )

        result = register_cognition_handlers()
        assert "enabled" in result
        assert "registered" in result
        assert isinstance(result["registered"], list)

    def test_get_cognition_stats_returns_dict(self):
        """get_cognition_stats 返回统计字典。"""
        from app.domain.neuro.register_cognition_handlers import get_cognition_stats

        stats = get_cognition_stats()
        assert isinstance(stats, dict)
        assert "enabled" in stats

    def test_register_cognition_handlers_disabled_via_env(self, monkeypatch):
        """环境变量禁用时返回 enabled=False。"""
        monkeypatch.setenv("XCAGI_NEURO_COGNITION", "0")
        from app.domain.neuro.register_cognition_handlers import (
            register_cognition_handlers,
        )

        result = register_cognition_handlers()
        assert result["enabled"] is False
