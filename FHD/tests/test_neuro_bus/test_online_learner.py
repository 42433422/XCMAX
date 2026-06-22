"""OnlineLearner 单元测试 — Contextual Bandit 在线微调器。"""

from __future__ import annotations

from app.neuro_bus.routing.online_learner import OnlineLearner


def test_should_explore_returns_bool():
    """should_explore 返回 bool 类型。"""
    learner = OnlineLearner(epsilon=0.5)
    result = learner.should_explore()
    assert isinstance(result, bool)


def test_record_decision_adds_to_window():
    """record_decision 将样本加入滑动窗口。"""
    learner = OnlineLearner()
    initial_count = learner.get_stats()["window_size"]
    learner.record_decision(
        features=[0.1] * 16,
        action=0,
        sla_hit=True,
        success=True,
    )
    stats = learner.get_stats()
    assert stats["window_size"] == initial_count + 1


def test_should_update_threshold():
    """should_update 在样本数达到阈值时返回 True。"""
    learner = OnlineLearner(update_threshold=3)
    assert learner.should_update() is False

    learner.record_decision([0.1] * 16, action=0, sla_hit=True, success=True)
    assert learner.should_update() is False

    learner.record_decision([0.2] * 16, action=1, sla_hit=False, success=True)
    assert learner.should_update() is False

    learner.record_decision([0.3] * 16, action=2, sla_hit=True, success=False)
    assert learner.should_update() is True


def test_reward_calculation():
    """reward = sla_hit*0.6 + success*0.4。"""
    learner = OnlineLearner()
    # sla_hit=True, success=True → reward=1.0
    learner.record_decision(
        features=[0.1] * 16,
        action=0,
        sla_hit=True,
        success=True,
    )
    sample = list(learner._window)[-1]
    assert sample[2] == 1.0  # reward

    # sla_hit=True, success=False → reward=0.6
    learner.record_decision(
        features=[0.2] * 16,
        action=1,
        sla_hit=True,
        success=False,
    )
    sample = list(learner._window)[-1]
    assert sample[2] == 0.6

    # sla_hit=False, success=True → reward=0.4
    learner.record_decision(
        features=[0.3] * 16,
        action=2,
        sla_hit=False,
        success=True,
    )
    sample = list(learner._window)[-1]
    assert sample[2] == 0.4

    # sla_hit=False, success=False → reward=0.0
    learner.record_decision(
        features=[0.4] * 16,
        action=0,
        sla_hit=False,
        success=False,
    )
    sample = list(learner._window)[-1]
    assert sample[2] == 0.0


def test_window_sliding():
    """超过 window_size 时丢弃旧样本。"""
    learner = OnlineLearner(window_size=3)
    for i in range(5):
        learner.record_decision(
            features=[float(i)] * 16,
            action=i % 3,
            sla_hit=True,
            success=True,
        )
    stats = learner.get_stats()
    assert stats["window_size"] == 3
    # 窗口应保留最后 3 条样本（i=2,3,4）
    samples = list(learner._window)
    assert samples[0][0][0] == 2.0  # features[0] of first sample = 2.0
    assert samples[1][0][0] == 3.0
    assert samples[2][0][0] == 4.0


def test_get_stats():
    """get_stats 返回完整统计字典。"""
    learner = OnlineLearner(
        window_size=100,
        epsilon=0.2,
        lr=0.01,
        update_threshold=50,
    )
    # 添加 3 条样本
    learner.record_decision([0.1] * 16, action=0, sla_hit=True, success=True)  # reward=1.0
    learner.record_decision([0.2] * 16, action=1, sla_hit=False, success=True)  # reward=0.4
    learner.record_decision([0.3] * 16, action=2, sla_hit=True, success=False)  # reward=0.6

    stats = learner.get_stats()
    assert stats["window_size"] == 3
    assert stats["max_window_size"] == 100
    assert stats["avg_reward"] == (1.0 + 0.4 + 0.6) / 3
    assert stats["sla_hit_count"] == 2
    assert stats["success_count"] == 2
    assert stats["epsilon"] == 0.2
    assert stats["lr"] == 0.01
    assert stats["update_threshold"] == 50
    assert stats["explore_count"] == 0
    assert stats["total_count"] == 0
    assert stats["explore_rate"] == 0.0
    assert stats["should_update"] is False
