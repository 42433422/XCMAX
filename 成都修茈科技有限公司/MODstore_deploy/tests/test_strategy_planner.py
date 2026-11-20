from modstore_server import strategy_planner


def _candidate(**overrides):
    row = {
        "title": "意图准确率提升",
        "hypothesis": "补意图样本能把准确率拉到 85%",
        "metric_id": "intent_accuracy",
        "threshold": 0.85,
        "direction": "max",
        "window_days": 14,
        "kill_criteria": ["两周无提升"],
        "expected_value": 4,
        "effort": 2,
    }
    row.update(overrides)
    return row


def test_parse_plan_accepts_fenced_json():
    text = '```json\n[{"title": "a"}]\n```'
    assert strategy_planner.parse_plan(text) == [{"title": "a"}]


def test_parse_plan_returns_empty_on_garbage():
    assert strategy_planner.parse_plan("不是 JSON") == []
    assert strategy_planner.parse_plan("") == []


def test_validate_candidate_rejects():
    assert strategy_planner.validate_candidate(_candidate()) is None
    assert strategy_planner.validate_candidate(_candidate(metric_id="nope")) == "unsupported_metric"
    assert strategy_planner.validate_candidate(_candidate(window_days=0)) == "invalid_window"
    assert (
        strategy_planner.validate_candidate(_candidate(kill_criteria=[]))
        == "invalid_kill_criteria"
    )
    assert strategy_planner.validate_candidate(_candidate(effort=9)) == "invalid_effort"


def test_rank_prefers_value_per_effort_and_drops_invalid():
    high = _candidate(title="high", expected_value=5, effort=1)
    low = _candidate(title="low", expected_value=2, effort=5)
    broken = _candidate(title="broken", metric_id="nope")
    ranked = strategy_planner.rank_candidates([low, broken, high])
    assert [row["title"] for row in ranked] == ["high", "low"]


def test_fit_envelope_stops_at_capacity():
    rows = [_candidate(title=f"c{i}") for i in range(3)]
    envelope = {"proposals": 2, "tokens": 100, "ci_minutes": 10, "human_hours": 2}
    kept = strategy_planner.fit_envelope(rows, envelope, [])
    assert len(kept) == 2
    assert all(row["budget"]["proposals"] >= 1 for row in kept)


def test_new_bet_id_is_deterministic_and_valid():
    first = strategy_planner._new_bet_id("意图准确率提升")
    second = strategy_planner._new_bet_id("意图准确率提升")
    assert first == second
    assert first.startswith("bet-")
    assert len(first) <= 64
