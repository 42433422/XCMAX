from __future__ import annotations

from typing import Any

from retort_engine.models import ProjectAssessment, Score
from retort_engine.self_evolution import RetortSelfEvolutionRunner


class ScriptedEvaluator:
    def __init__(self, score_sets: list[dict[str, float]]) -> None:
        self.score_sets = score_sets
        self.calls = 0

    def evaluate(self, state: dict[str, Any]) -> ProjectAssessment:
        index = min(self.calls, len(self.score_sets) - 1)
        self.calls += 1
        scores = tuple(Score(dim, value, f"{dim} reason") for dim, value in self.score_sets[index].items())
        return ProjectAssessment("demo", scores, "scripted")


def test_score_90_does_not_converge_but_91_does() -> None:
    result = RetortSelfEvolutionRunner(ScriptedEvaluator([{"project_level": 90.0}, {"project_level": 91.0}]), threshold=90, max_rounds=3).run({})
    assert result.status == "converged"
    assert not result.rounds[0].passed
    assert result.rounds[1].passed


def test_blocks_when_scores_repeat_without_convergence() -> None:
    result = RetortSelfEvolutionRunner(ScriptedEvaluator([{"project_level": 60.0}, {"project_level": 60.0}]), threshold=90, max_rounds=None).run({})
    assert result.status == "blocked"


def test_generates_tasks_for_weak_scores() -> None:
    result = RetortSelfEvolutionRunner(ScriptedEvaluator([{"architecture": 72.0, "docs": 96.0}]), threshold=90, max_rounds=1).run({})
    assert [task.dimension for task in result.rounds[0].tasks] == ["architecture"]
