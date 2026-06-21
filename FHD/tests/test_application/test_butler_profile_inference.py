"""测试 butler_profile_inference — MBTI 推断引擎。"""

from __future__ import annotations

import pytest

from app.application.butler_profile_inference import (
    MIN_INTERACTIONS_FOR_INFER,
    BehaviorFeatures,
    ButlerProfileInference,
    InferenceResult,
)


class TestBehaviorFeatures:
    """测试行为特征提取。"""

    def test_empty_conversations_returns_zero_features(self):
        features = BehaviorFeatures.from_conversations([])
        assert features.turn_count == 0
        assert features.total_messages == 0
        assert features.avg_message_length == 0.0

    def test_interrupted_count(self):
        convs = [
            {"user_message": "hi", "interrupted": True},
            {"user_message": "hello", "interrupted": False},
            {"user_message": "hey", "interrupted": True},
        ]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.interrupt_count == 2

    def test_corrected_count(self):
        convs = [
            {"user_message": "hi", "corrected": True},
            {"user_message": "hello", "corrected": False},
        ]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.correction_count == 1

    def test_why_question_detection(self):
        convs = [{"user_message": "为什么要这样做？"}]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.why_question_count == 1

    def test_emotion_expression_detection(self):
        convs = [{"user_message": "谢谢，太棒了"}]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.emotion_expression_count == 1

    def test_structure_request_detection(self):
        convs = [{"user_message": "请列步骤给我看"}]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.structure_request_count == 1

    def test_interrupt_keyword_detection(self):
        """催促关键词也算打断。"""
        convs = [{"user_message": "快点回复我"}]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.interrupt_count == 1

    def test_avg_message_length(self):
        convs = [
            {"user_message": "ab"},
            {"user_message": "abcdef"},
        ]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.avg_message_length == 4.0

    def test_missing_fields_handled_gracefully(self):
        """缺失字段不报错。"""
        convs = [{}]
        features = BehaviorFeatures.from_conversations(convs)
        assert features.turn_count == 1
        assert features.total_messages == 1


class TestButlerProfileInference:
    """测试推断引擎。"""

    @pytest.fixture
    def engine(self):
        return ButlerProfileInference()

    @pytest.fixture
    def default_profile(self):
        return {
            "mbti_ei": 65,
            "mbti_sn": 60,
            "mbti_tf": 70,
            "mbti_jp": 60,
            "mbti_type": "ENFJ",
        }

    def test_insufficient_interactions_returns_empty_result(self, engine, default_profile):
        """互动不足时不推断。"""
        convs = [{"user_message": "hi"}]  # 少于 MIN_INTERACTIONS_FOR_INFER
        result = engine.infer(default_profile, convs)
        assert result.new_mbti_type == ""
        assert "互动轮数不足" in result.reasons[0]

    def test_sufficient_interactions_produces_result(self, engine, default_profile):
        convs = [{"user_message": "hi"} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        result = engine.infer(default_profile, convs)
        assert result.new_mbti_type != ""
        assert result.confidence > 0

    def test_interrupt_behavior_increases_ei(self, engine, default_profile):
        """打断/催促 → +E/I。"""
        convs = [
            {"user_message": "快点", "interrupted": True} for _ in range(MIN_INTERACTIONS_FOR_INFER)
        ]
        result = engine.infer(default_profile, convs)
        assert result.mbti_ei_delta > 0
        assert any("E/I" in r for r in result.reasons)

    def test_why_question_increases_sn(self, engine, default_profile):
        """问为什么 → +S/N。"""
        convs = [{"user_message": "为什么要这样做？"} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        result = engine.infer(default_profile, convs)
        assert result.mbti_sn_delta > 0

    def test_emotion_increases_tf(self, engine, default_profile):
        """情绪表达 → +T/F。"""
        convs = [{"user_message": "谢谢，太棒了"} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        result = engine.infer(default_profile, convs)
        assert result.mbti_tf_delta > 0

    def test_structure_request_increases_jp(self, engine, default_profile):
        """要求结构化 → +J/P。"""
        convs = [{"user_message": "请列步骤"} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        result = engine.infer(default_profile, convs)
        assert result.mbti_jp_delta > 0

    def test_correction_decreases_tf(self, engine, default_profile):
        """纠正 → -T/F（更理性）。"""
        convs = [
            {"user_message": "不对", "corrected": True} for _ in range(MIN_INTERACTIONS_FOR_INFER)
        ]
        result = engine.infer(default_profile, convs)
        assert result.mbti_tf_delta < 0

    def test_long_messages_decrease_ei(self, engine, default_profile):
        """长消息 → -E/I（内向信号）。"""
        long_msg = "x" * 150
        convs = [{"user_message": long_msg} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        result = engine.infer(default_profile, convs)
        assert result.mbti_ei_delta < 0

    def test_confidence_increases_with_turns(self, engine, default_profile):
        """置信度随互动轮数提升。"""
        convs_small = [{"user_message": "hi"} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        convs_large = [{"user_message": "hi"} for _ in range(MIN_INTERACTIONS_FOR_INFER * 5)]

        result_small = engine.infer(default_profile, convs_small)
        result_large = engine.infer(default_profile, convs_large)
        assert result_large.confidence > result_small.confidence

    def test_confidence_capped_at_095(self, engine, default_profile):
        """置信度上限 0.95。"""
        convs = [{"user_message": "hi"} for _ in range(100)]
        result = engine.infer(default_profile, convs)
        assert result.confidence <= 0.95

    def test_identity_changes_when_mbti_type_changes(self, engine):
        """MBTI 跨型时身份重选。"""
        # 当前 ISTP，行为推动向 E/F 方向
        profile = {
            "mbti_ei": 45,  # 接近边界
            "mbti_sn": 30,
            "mbti_tf": 45,  # 接近边界
            "mbti_jp": 20,
            "mbti_type": "ISTP",
        }
        convs = [
            {"user_message": "快点", "interrupted": True},  # +EI
            {"user_message": "谢谢"},  # +TF
        ] * 10
        result = engine.infer(profile, convs)
        # 若型变了，identity_changed 应为 True
        if result.new_mbti_type != "ISTP":
            assert result.identity_changed is True
            assert result.new_identity_primary != ""

    def test_delta_capped_at_max(self, engine, default_profile):
        """单次增量不超过 MAX_DELTA。"""
        from app.application.butler_profile_inference import MAX_DELTA

        convs = [
            {"user_message": "快点", "interrupted": True}
            for _ in range(50)  # 大量打断
        ]
        result = engine.infer(default_profile, convs)
        assert result.mbti_ei_delta <= MAX_DELTA

    def test_mod_hints_affect_identity_selection(self, engine):
        """MOD 提示影响身份选择。"""
        profile = {
            "mbti_ei": 30,
            "mbti_sn": 30,
            "mbti_tf": 30,
            "mbti_jp": 30,
            "mbti_type": "ISTP",
        }
        convs = [{"user_message": "hi"} for _ in range(MIN_INTERACTIONS_FOR_INFER)]
        # 推动向 E 方向，触发跨型
        convs_e = [
            {"user_message": "快点", "interrupted": True} for _ in range(MIN_INTERACTIONS_FOR_INFER)
        ]
        result = engine.infer(profile, convs_e, mod_hints=["发货"])
        if result.identity_changed:
            assert result.new_identity_primary == "发货管家"
