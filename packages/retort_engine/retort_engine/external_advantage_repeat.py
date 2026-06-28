from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.external_advantage_matrix import build_external_advantage_matrix


def build_external_advantage_repeat(
    project: str | Path,
    *,
    repeat_count: int = 2,
    min_cases: int = 6,
    output: str | Path = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    runs = [build_external_advantage_matrix(root, min_cases=min_cases) for _ in range(max(2, repeat_count))]
    deltas = [float((run.get("summary") or {}).get("score_delta") or 0) for run in runs]
    case_ids_by_run = [[str(row.get("case_id") or "") for row in run.get("matrix") or [] if isinstance(row, dict)] for run in runs]
    first_case_ids = case_ids_by_run[0] if case_ids_by_run else []
    stable_case_set = all(case_ids == first_case_ids for case_ids in case_ids_by_run)
    ready_runs = [run for run in runs if run.get("status") == "ready"]
    summary = {
        "repeat_count": len(runs),
        "ready_repeat_count": len(ready_runs),
        "min_case_count": min_cases,
        "case_count_per_run": [len(case_ids) for case_ids in case_ids_by_run],
        "total_case_evaluation_count": sum(len(case_ids) for case_ids in case_ids_by_run),
        "score_deltas": deltas,
        "stable_case_set": stable_case_set,
        "stable_score_delta": len(set(deltas)) == 1,
        "minimum_score_delta": min(deltas) if deltas else 0,
        "all_runs_ready": len(ready_runs) == len(runs),
    }
    ready = (
        summary["repeat_count"] >= 2
        and summary["all_runs_ready"]
        and summary["stable_case_set"]
        and summary["stable_score_delta"]
        and summary["total_case_evaluation_count"] >= min_cases * 2
        and summary["minimum_score_delta"] >= 35
    )
    result = {
        "status": "ready" if ready else "needs_more_replay",
        "project": str(root),
        "summary": summary,
        "runs": [
            {
                "index": index,
                "status": run.get("status"),
                "summary": run.get("summary", {}),
                "case_ids": case_ids_by_run[index - 1],
            }
            for index, run in enumerate(runs, start=1)
        ],
        "evidence": {
            "style": "repeatable_external_advantage_regression_manifest",
            "source": "retort_engine.external_advantage_matrix",
            "comparison": "same_cases_same_delta_across_repeated_runs",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result
