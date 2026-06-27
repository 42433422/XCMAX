from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Score:
    dimension: str
    value: float
    reason: str = ""
    evidence: tuple[str, ...] = ()

    def passes(self, threshold: float) -> bool:
        return self.value > threshold

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "value": self.value, "reason": self.reason, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class ProjectAssessment:
    project: str
    scores: tuple[Score, ...]
    summary: str
    strengths: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def score_map(self) -> dict[str, float]:
        return {score.dimension: score.value for score in self.scores}

    def weak_scores(self, threshold: float) -> tuple[Score, ...]:
        return tuple(score for score in self.scores if not score.passes(threshold))

    def all_scores_over(self, threshold: float) -> bool:
        return bool(self.scores) and all(score.passes(threshold) for score in self.scores)

    def score_signature(self) -> tuple[tuple[str, float], ...]:
        return tuple(sorted((score.dimension, round(score.value, 4)) for score in self.scores))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "summary": self.summary,
            "scores": [score.to_dict() for score in self.scores],
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "recommendations": list(self.recommendations),
            "evidence": list(self.evidence),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RetortQuestion:
    dimension: str
    question: str
    rationale: str

    def to_dict(self) -> dict[str, str]:
        return {"dimension": self.dimension, "question": self.question, "rationale": self.rationale}


@dataclass(frozen=True)
class ImprovementTask:
    task_id: str
    title: str
    dimension: str
    why: str
    action: str
    acceptance: str
    owner_hint: str = "retort"
    priority: str = "P1"

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "dimension": self.dimension,
            "why": self.why,
            "action": self.action,
            "acceptance": self.acceptance,
            "owner_hint": self.owner_hint,
            "priority": self.priority,
        }


@dataclass(frozen=True)
class EvolutionRound:
    round_index: int
    assessment: ProjectAssessment
    questions: tuple[RetortQuestion, ...]
    tasks: tuple[ImprovementTask, ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "passed": self.passed,
            "assessment": self.assessment.to_dict(),
            "questions": [question.to_dict() for question in self.questions],
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True)
class SelfEvolutionResult:
    status: str
    threshold: float
    max_rounds: int | None
    rounds: tuple[EvolutionRound, ...]
    stop_reason: str

    @property
    def final_assessment(self) -> ProjectAssessment | None:
        return None if not self.rounds else self.rounds[-1].assessment

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "threshold": self.threshold,
            "max_rounds": self.max_rounds,
            "stop_reason": self.stop_reason,
            "final_assessment": None if self.final_assessment is None else self.final_assessment.to_dict(),
            "rounds": [round_.to_dict() for round_ in self.rounds],
        }


@dataclass(frozen=True)
class ScoreDelta:
    dimension: str
    own_score: float
    external_score: float
    delta: float

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "own_score": self.own_score, "external_score": self.external_score, "delta": self.delta}


@dataclass(frozen=True)
class ExternalProjectRef:
    source: str
    source_type: str
    local_path: str
    ref: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "source_type": self.source_type, "local_path": self.local_path, "ref": self.ref}


@dataclass(frozen=True)
class AbsorptionResult:
    status: str
    own_assessment: ProjectAssessment
    external_assessment: ProjectAssessment
    external_ref: ExternalProjectRef
    score_deltas: tuple[ScoreDelta, ...]
    tasks: tuple[ImprovementTask, ...]
    summary: str
    safety_findings: tuple[str, ...] = ()
    semantic_findings: tuple[str, ...] = ()
    rejection_findings: tuple[str, ...] = ()
    branch_workflow: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "external_ref": self.external_ref.to_dict(),
            "own_assessment": self.own_assessment.to_dict(),
            "external_assessment": self.external_assessment.to_dict(),
            "score_deltas": [delta.to_dict() for delta in self.score_deltas],
            "tasks": [task.to_dict() for task in self.tasks],
            "safety_findings": list(self.safety_findings),
            "semantic_findings": list(self.semantic_findings),
            "rejection_findings": list(self.rejection_findings),
            "branch_workflow": dict(self.branch_workflow),
        }


@dataclass(frozen=True)
class EmployeeTaskRecord:
    queue_id: str
    task: ImprovementTask
    source: str
    status: str = "queued"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"queue_id": self.queue_id, "task": self.task.to_dict(), "source": self.source, "status": self.status, "created_at": self.created_at}


@dataclass(frozen=True)
class EmployeeTaskResult:
    task_id: str
    status: str
    summary: str
    evidence: tuple[str, ...] = ()
    score_after: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "status": self.status, "summary": self.summary, "evidence": list(self.evidence), "score_after": dict(self.score_after)}
