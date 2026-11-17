"""GEPA adapter for measured trials; optimization never changes audit standards."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from gepa import EvaluationBatch, optimize
from gepa.core.adapter import GEPAAdapter
from gepa.core.result import GEPAResult

from retort_engine.evolution_contract import digest

Trial = Callable[[dict[str, str], dict[str, Any]], dict[str, Any]]


class MeasuredTrialAdapter(GEPAAdapter[dict[str, Any], dict[str, Any], dict[str, Any]]):
    propose_new_texts = None

    def __init__(self, trial: Trial):
        self.trial = trial

    def evaluate(self, batch, candidate, capture_traces=False):
        results = [self.trial(candidate, item) for item in batch]
        for result in results:
            if (
                result.get("execution_mode") != "real"
                or not re.fullmatch(
                    r"[0-9a-f]{64}", str(result.get("evidence_digest", ""))
                )
                or type(result.get("score")) not in (int, float)
                or not math.isfinite(result["score"])
                or not 0 <= result["score"] <= 1
            ):
                raise ValueError(
                    "GEPA requires measured task results and retained evidence"
                )
        return EvaluationBatch(
            outputs=results,
            scores=[r["score"] for r in results],
            trajectories=results if capture_traces else None,
        )

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        return {
            component: [
                {
                    "Inputs": r.get("input", ""),
                    "Outputs": r.get("output", ""),
                    "Feedback": r.get("feedback", ""),
                }
                for r in eval_batch.trajectories or []
            ]
            for component in components_to_update
        }


def optimize_measured(
    *,
    seed: dict[str, str],
    trainset: list[dict],
    valset: list[dict],
    holdout: list[dict],
    trial: Trial,
    max_metric_calls: int,
    reflection_lm=None,
    proposer=None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Keep the final holdout out of GEPA's candidate search and reflection."""
    groups = [
        {str(row.get("id") or "") for row in data}
        for data in (trainset, valset, holdout)
    ]
    if (
        any(not group for group in groups)
        or any(
            len(group) != len(data)
            for group, data in zip(groups, (trainset, valset, holdout))
        )
        or any("" in group for group in groups)
        or groups[0] & groups[1]
        or groups[0] & groups[2]
        or groups[1] & groups[2]
        or any(len(data) > 100 for data in (trainset, valset, holdout))
    ):
        raise ValueError(
            "separate nonempty training, validation and holdout tasks required"
        )
    if not 4 <= max_metric_calls <= 300:
        raise ValueError("bounded GEPA evaluation budget required")
    if reflection_lm is None and proposer is None:
        raise ValueError(
            "a configured reflection model or trusted proposal source is required"
        )
    adapter = MeasuredTrialAdapter(trial)
    result: GEPAResult[dict[str, Any], int] = optimize(
        seed_candidate=seed,
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_lm,
        custom_candidate_proposer=proposer,
        max_metric_calls=max_metric_calls,
        reflection_minibatch_size=1,
        display_progress_bar=False,
        raise_on_exception=True,
        run_dir=str(run_dir) if run_dir else None,
    )
    candidate = result.best_candidate
    baseline = adapter.evaluate(holdout, seed)
    proposed = adapter.evaluate(holdout, candidate)
    no_regression = all(
        new >= old for old, new in zip(baseline.scores, proposed.scores)
    )
    improved = no_regression and sum(proposed.scores) > sum(baseline.scores)
    return {
        "engine": "gepa",
        "status": "proposed" if improved else "no_verified_improvement",
        "candidate": candidate if improved else seed,
        "automatically_applied": False,
        "baseline_scores": baseline.scores,
        "candidate_scores": proposed.scores,
        "holdout_digest": digest(holdout),
        "evidence_digest": digest(
            {"baseline": baseline.outputs, "candidate": proposed.outputs}
        ),
        "search_budget": max_metric_calls,
        "holdout_evaluations": 2 * len(holdout),
    }


class CommandTrial:
    """Trusted evaluation protocol; GEPA only changes candidate text, never the scorer."""

    def __init__(self, protocol, *, local_test=False):
        from jsonschema import Draft202012Validator

        from retort_engine.evolution_contract import CHECK_SCHEMA

        Draft202012Validator(CHECK_SCHEMA).validate(protocol["check"])
        if not local_test and not re.fullmatch(
            r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}",
            protocol.get("container_image", ""),
        ):
            raise ValueError("RSI trials require a digest-pinned evaluation image")
        self.protocol, self.local_test = protocol, local_test

    def __call__(self, candidate, item):
        from retort_engine.evolution_evidence import _check_test_files, execute_check

        project = Path(self.protocol["project"]).resolve()
        check = self.protocol["check"]
        _check_test_files(project, check["files"])
        request = {"candidate": candidate, "task": item}
        root = Path(self.protocol["evidence_dir"]).resolve() / uuid4().hex
        root.mkdir(parents=True, mode=0o700)
        (root / "input.json").write_text(json.dumps(request, ensure_ascii=False))
        log = root / "result.log"
        code, timed_out = execute_check(
            check,
            project,
            log,
            None if self.local_test else self.protocol["container_image"],
            json.dumps(request, ensure_ascii=False).encode(),
        )
        _check_test_files(project, check["files"])
        if code or timed_out:
            raise ValueError("RSI evaluation failed; no promotion allowed")
        result = json.loads(log.read_text())
        return {
            **result,
            "execution_mode": "real",
            "input": item,
            "evidence_digest": digest(
                {
                    "input": request,
                    "protocol": self.protocol,
                    "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                }
            ),
            "evidence_path": str(root),
        }


def optimize_protocol(path: Path, *, seed, reflection_lm=None, proposer=None):
    protocol = json.loads(path.read_text())
    run_dir = (
        Path(protocol["evidence_dir"])
        / "search"
        / digest({"protocol": protocol, "seed": seed})
    )
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return optimize_measured(
        seed=seed,
        trainset=protocol["trainset"],
        valset=protocol["valset"],
        holdout=protocol["holdout"],
        trial=CommandTrial(protocol),
        max_metric_calls=protocol["max_metric_calls"],
        reflection_lm=reflection_lm,
        proposer=proposer,
        run_dir=run_dir,
    )
