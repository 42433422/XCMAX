
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    min_delta = int(payload["min_delta"])
    cases = []
    deltas = []
    for item in payload["cases"]:
        observation = item["retort_observation"]
        baseline = 20
        retort = 0
        retort += 25 if observation["severity_matched"] else 0
        retort += 25 if observation["context_matched"] else 0
        retort += 20 if observation["publishable_comment"] else 0
        retort += 15 if observation["task_group"] else 0
        retort += 15 if observation["extension_policy"] else 0
        delta = retort - baseline
        deltas.append(delta)
        cases.append({
            "case_id": item["case_id"],
            "source_project": item["source_project"],
            "external_delta": delta,
            "accepted": delta >= min_delta,
        })
    accepted = [case for case in cases if case["accepted"]]
    result = {
        "summary": {
            "case_count": len(cases),
            "accepted_case_count": len(accepted),
            "minimum_delta": min(deltas) if deltas else 0,
            "all_cases_accepted": bool(cases) and len(accepted) == len(cases),
            "score_fields_consumed": False,
        },
        "cases": cases,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if result["summary"]["all_cases_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
