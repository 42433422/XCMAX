"""Score complete, unique task trials; never interpret missing results as success."""

from __future__ import annotations

from collections import Counter, defaultdict
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


def startup_blocked_task_ids(per_trial: list[list[dict]]) -> list[str]:
    """Fail closed when admission or execution was not established by a raw trial."""
    return sorted(
        {
            row["task_id"]
            for rows in per_trial
            for row in rows
            if row.get("runtime_admitted") is not True or type(row.get("exec_pass")) is not bool
        }
    )


def passes_gate(report: dict[str, Any], minimum: float) -> bool:
    return bool(report["pass_k"] >= minimum and report["safety_failures"] == 0)


def summarize_planning_failures(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep root causes and public error codes separate; legacy causes stay unknown."""
    causes: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    failures = unknown_outcomes = 0
    for record in records:
        data = record.get("data")
        data = data if isinstance(data, dict) else {}
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        kind = next(
            (
                str(source[key])
                for source in (record, data, metadata)
                for key in ("failure_kind", "planning_failure_kind")
                if isinstance(source.get(key), str) and source[key].strip()
            ),
            "",
        )
        code = str(record.get("error_code") or data.get("error_code") or record.get("error") or "")
        failed = (
            bool(kind or code)
            or record.get("success") is False
            or record.get("pass") is False
            or metadata.get("planning_rejected") is True
            or record.get("execution_state", record.get("state"))
            in {"failed", "rejected", "blocked"}
            or record.get("phase") in {"failed", "rejected"}
        )
        if failed:
            failures += 1
            missing = (
                "diagnostic_missing" if record.get("schema_version") == 2 else "unknown_legacy"
            )
            causes[kind or missing] += 1
            codes[code or "not_recorded"] += 1
        elif record.get("success") is not True and record.get("pass") is not True:
            unknown_outcomes += 1
    return {
        "schema_version": 2,
        "total": len(records),
        "failures": failures,
        "root_causes": dict(sorted(causes.items())),
        "external_error_codes": dict(sorted(codes.items())),
        "missing_root_cause": causes["unknown_legacy"],
        "unknown_outcomes": unknown_outcomes,
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Summarize root-cause diagnostics without rewriting evidence"
    )
    parser.add_argument("--planning-records", type=Path, required=True, help="JSON array or JSONL")
    path = parser.parse_args().planning_records
    raw = path.read_text(encoding="utf-8")
    records = (
        json.loads(raw)
        if raw.lstrip().startswith("[")
        else [json.loads(line) for line in raw.splitlines() if line.strip()]
    )
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        parser.error("records must be a list of objects")
    print(json.dumps(summarize_planning_failures(records), ensure_ascii=False, indent=2))
