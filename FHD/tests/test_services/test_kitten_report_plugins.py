"""app/services/kitten_report/plugins 单测。"""

from __future__ import annotations

from app.services.kitten_report.plugins import (
    ForecastHeuristicPlugin,
    IndustryStrategyPlugin,
    RuleStatsPlugin,
    TimeSeriesModelPlugin,
    _extract_numeric_values,
    _safe_float,
)


class TestKittenHelpers:
    def test_safe_float(self) -> None:
        assert _safe_float("3.5") == 3.5
        assert _safe_float(None) is None
        assert _safe_float("x") is None

    def test_extract_numeric_values_from_list_rows(self) -> None:
        dataset = {"preview": [[1, "2", "x"], [3.0]]}
        assert _extract_numeric_values(dataset) == [1.0, 2.0, 3.0]

    def test_extract_numeric_values_from_dict_rows(self) -> None:
        dataset = {"preview": [{"a": 1, "b": "2.5"}]}
        assert _extract_numeric_values(dataset) == [1.0, 2.5]


class TestKittenPlugins:
    def test_rule_stats_plugin(self) -> None:
        out = RuleStatsPlugin().run(
            {
                "dataset": {"rows": 10, "columns": 3},
                "messages": [{"role": "user"}, {"role": "ai"}],
            }
        )
        assert out.key == "rule_stats"
        assert "10" in out.summary

    def test_forecast_heuristic_no_values(self) -> None:
        out = ForecastHeuristicPlugin().run({"dataset": {"preview": []}})
        assert out.level == "warn"

    def test_forecast_heuristic_with_values(self) -> None:
        out = ForecastHeuristicPlugin().run({"dataset": {"preview": [[1, 2, 3]]}})
        assert out.details.get("forecast_available") is True

    def test_timeseries_insufficient_points(self) -> None:
        out = TimeSeriesModelPlugin().run({"dataset": {"preview": [[1]]}})
        assert out.level == "warn"

    def test_industry_strategy_coating(self) -> None:
        out = IndustryStrategyPlugin().run({"industry": "涂料行业"})
        assert "涂料" in out.summary or "涂料" in out.details.get("hint", "")

    def test_industry_strategy_generic(self) -> None:
        out = IndustryStrategyPlugin().run({"industry": "未知"})
        assert "通用" in out.summary
