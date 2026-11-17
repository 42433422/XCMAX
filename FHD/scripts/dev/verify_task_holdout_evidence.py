"""Verify holdout reports using actual provider-response evidence."""

import json
import os
from pathlib import Path
from typing import Any


def write_holdout_evidence() -> dict[str, Any]:
    report_path = "test_reports/task_holdout_report.json"
    assert os.path.isfile(report_path), "留出评测失败：task_holdout_report.json 不存在"
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    cases = json.loads(Path("tests/benchmarks/task_holdout_set.json").read_text(encoding="utf-8"))
    assert int(report.get("total_tasks", 0)) == len(cases["tasks"]) > 0, (
        f"留出样本数不符 report={report.get('total_tasks')} set={len(cases['tasks'])}"
    )
    marker = {
        "mode": "task_holdout",
        "llm_verified": int(report.get("model_responses", 0)) > 0,
        "status": "VERIFIED" if int(report.get("model_responses", 0)) > 0 else "UNVERIFIED",
        "evidence": {
            "report": report_path,
            "model_responses": int(report.get("model_responses", 0)),
            "total_tasks": report["total_tasks"],
            "trials": report.get("trials"),
            "pass_1": report.get("pass_1"),
            "pass_k": report.get("pass_k"),
        },
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
        "actor": os.environ.get("GITHUB_ACTOR", ""),
    }
    os.makedirs("test_reports", exist_ok=True)
    with open("test_reports/task_holdout_run_mode.json", "w", encoding="utf-8") as f:
        json.dump(marker, f, ensure_ascii=False, indent=2)
    return marker


if __name__ == "__main__":
    print(json.dumps(write_holdout_evidence(), ensure_ascii=False, indent=2))
