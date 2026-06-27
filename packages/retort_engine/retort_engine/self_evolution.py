from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol

from retort_engine.models import EvolutionRound, ImprovementTask, ProjectAssessment, RetortQuestion, SelfEvolutionResult


class RetortEvaluator(Protocol):
    def evaluate(self, state: dict[str, Any]) -> ProjectAssessment: ...


class RetortImprover(Protocol):
    def improve(self, state: dict[str, Any], assessment: ProjectAssessment, tasks: tuple[ImprovementTask, ...], round_index: int) -> dict[str, Any]: ...


class TaskBacklogImprover:
    def improve(self, state: dict[str, Any], assessment: ProjectAssessment, tasks: tuple[ImprovementTask, ...], round_index: int) -> dict[str, Any]:
        next_state = dict(state)
        backlog = list(next_state.get("retort_task_backlog") or [])
        backlog.extend(task.to_dict() for task in tasks)
        next_state["retort_task_backlog"] = backlog
        next_state["retort_last_round"] = round_index
        next_state["retort_last_scores"] = assessment.score_map()
        return next_state


class RetortSelfEvolutionRunner:
    def __init__(self, evaluator: RetortEvaluator, improver: RetortImprover | None = None, *, threshold: float = 90.0, max_rounds: int | None = 8, stop_on_repeated_scores: bool = True) -> None:
        if max_rounds is not None and max_rounds < 1:
            raise ValueError("max_rounds must be >= 1 or None")
        self.evaluator = evaluator
        self.improver = improver or TaskBacklogImprover()
        self.threshold = threshold
        self.max_rounds = max_rounds
        self.stop_on_repeated_scores = stop_on_repeated_scores

    def run(self, initial_state: dict[str, Any] | None = None) -> SelfEvolutionResult:
        state = dict(initial_state or {})
        rounds: list[EvolutionRound] = []
        seen_signatures: set[tuple[tuple[str, float], ...]] = set()
        round_index = 1
        while True:
            assessment = self.evaluator.evaluate(state)
            passed = assessment.all_scores_over(self.threshold)
            questions = build_retort_questions(assessment, self.threshold)
            tasks = build_improvement_tasks(assessment, questions, self.threshold, round_index)
            rounds.append(EvolutionRound(round_index, assessment, questions, tasks, passed))
            if passed:
                return SelfEvolutionResult("converged", self.threshold, self.max_rounds, tuple(rounds), "all_scores_strictly_above_threshold")
            if self.max_rounds is not None and round_index >= self.max_rounds:
                return SelfEvolutionResult("max_rounds", self.threshold, self.max_rounds, tuple(rounds), "max_rounds_reached_before_all_scores_passed")
            signature = assessment.score_signature()
            if self.stop_on_repeated_scores and signature in seen_signatures:
                return SelfEvolutionResult("blocked", self.threshold, self.max_rounds, tuple(rounds), "scores_repeated_without_convergence")
            seen_signatures.add(signature)
            state = self.improver.improve(state, assessment, tasks, round_index)
            round_index += 1


def build_retort_questions(assessment: ProjectAssessment, threshold: float = 90.0) -> tuple[RetortQuestion, ...]:
    return tuple(RetortQuestion(score.dimension, f"{score.dimension} is {score.value:.1f}. What exact evidence keeps it from being greater than {threshold:.0f}, and what is the smallest verifiable change that would raise it?", score.reason or "This score has not passed the Retort stop gate.") for score in assessment.weak_scores(threshold))


def build_improvement_tasks(assessment: ProjectAssessment, questions: tuple[RetortQuestion, ...], threshold: float, round_index: int) -> tuple[ImprovementTask, ...]:
    score_by_dimension = {score.dimension: score for score in assessment.scores}
    tasks: list[ImprovementTask] = []
    for index, question in enumerate(questions, start=1):
        score = score_by_dimension[question.dimension]
        tasks.append(ImprovementTask(f"retort-r{round_index:02d}-{index:02d}-{_slug(question.dimension)}", f"Raise {question.dimension} above {threshold:.0f}", question.dimension, question.rationale, "Implement the smallest safe improvement and attach validation output.", f"Reassessment shows {question.dimension} > {threshold:.0f}; current score is {score.value:.1f}.", owner_hint_for_dimension(question.dimension), _priority(score.value, threshold)))
    return tuple(tasks)


def state_fingerprint(state: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")).hexdigest()


def owner_hint_for_dimension(dimension: str) -> str:
    lowered = dimension.lower()
    if "license" in lowered or "test" in lowered or "gate" in lowered:
        return "test-qa-runner"
    if "operation" in lowered or "release" in lowered or "branch" in lowered:
        return "deploy-release-officer"
    if "ui" in lowered or "ux" in lowered or "product" in lowered:
        return "market-frontend-dev"
    return "fhd-core-maintainer"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "score"


def _priority(value: float, threshold: float) -> str:
    gap = threshold - value
    if gap >= 20:
        return "P0"
    if gap >= 8:
        return "P1"
    return "P2"
