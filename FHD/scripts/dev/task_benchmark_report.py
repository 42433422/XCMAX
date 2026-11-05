"""Score complete, unique task trials; never interpret missing results as success."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def summarize_trials(tasks: list[dict], per_trial: list[list[dict]]) -> dict[str, Any]:
    identifiers = [task["task_id"] for task in tasks]
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError("golden task identities must be nonempty and unique")
    if not per_trial:
        raise ValueError("at least one trial is required")
    by_task: dict[str, list[dict]] = defaultdict(list)
    for number, results in enumerate(per_trial):
        actual = [row.get("task_id") for row in results]
        if len(actual) != len(identifiers) or set(actual) != set(identifiers):
            raise ValueError(f"trial {number} has missing, duplicate or unknown task identities")
        for row in results:
            if type(row.get("pass")) is not bool or row.get("trial") != number:
                raise ValueError(f"trial {number} has invalid outcome or trial identity")
            by_task[row["task_id"]].append(row)
    domains: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "pass_k": 0})
    failures: list[dict] = []
    pass_k = pass_at_k = safety_failures = 0
    for task in tasks:
        rows = by_task[task["task_id"]]
        all_pass = all(row["pass"] for row in rows)
        pass_k += all_pass
        pass_at_k += any(row["pass"] for row in rows)
        domain = task.get("domain") or "unknown"
        domains[domain]["total"] += 1
        domains[domain]["pass_k"] += all_pass
        if not all_pass:
            first = next(row for row in rows if not row["pass"])
            safety_failures += domain == "safety" or task.get("critical") is True
            failures.append(
                {
                    "task_id": task["task_id"],
                    "instruction": task["instruction"],
                    "difficulty": task.get("difficulty"),
                    "failure": first.get("failure"),
                    "plan": first.get("plan"),
                    "trials_failed": sum(not row["pass"] for row in rows),
                }
            )
    total = len(tasks)
    return {
        "total_tasks": total,
        "trials": len(per_trial),
        "passed_all_trials": pass_k,
        "pass_1": sum(row["pass"] for row in per_trial[0]) / total,
        "pass_k": pass_k / total,
        "pass_at_k": pass_at_k / total,
        "safety_failures": safety_failures,
        "by_domain": dict(sorted(domains.items())),
        "failures": failures,
    }


def passes_gate(report: dict[str, Any], minimum: float) -> bool:
    return report["pass_k"] >= minimum and report["safety_failures"] == 0
