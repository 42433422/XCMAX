from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.external_advantage_matrix import build_external_advantage_matrix


def build_external_process_adjudication(
    project: str | Path,
    *,
    min_cases: int = 6,
    min_delta: int = 80,
    output: str | Path = "",
    run_id: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    adjudication_id = run_id or _run_id("external-process-adjudication")
    lab = root / ".retort" / "external_process_adjudications" / adjudication_id
    lab.mkdir(parents=True, exist_ok=True)
    matrix = build_external_advantage_matrix(root, min_cases=min_cases)
    rows = [row for row in matrix.get("matrix") or [] if isinstance(row, dict)]
    external_input = {"min_delta": min_delta, "cases": [_redacted_case(row) for row in rows]}
    input_path = lab / "adjudicator_input.json"
    output_path = lab / "adjudicator_output.json"
    script_path = lab / "independent_adjudicator.py"
    input_path.write_text(json.dumps(external_input, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    script_path.write_text(_ADJUDICATOR_SCRIPT, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script_path), str(input_path), str(output_path)],
        cwd=lab,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    adjudication = _read_json(output_path)
    summary = adjudication.get("summary") if isinstance(adjudication.get("summary"), dict) else {}
    script_text = script_path.read_text(encoding="utf-8")
    result_summary = {
        "case_count": len(rows),
        "min_case_count": min_cases,
        "external_process_returncode": completed.returncode,
        "external_process_pid_boundary": completed.returncode == 0,
        "external_process_stdout_tail": completed.stdout[-300:],
        "external_process_stderr_tail": completed.stderr[-300:],
        "external_adjudicated_case_count": summary.get("case_count", 0),
        "external_accepted_case_count": summary.get("accepted_case_count", 0),
        "external_minimum_delta": summary.get("minimum_delta", 0),
        "external_delta_floor": min_delta,
        "external_delta_floor_met": int(summary.get("minimum_delta") or 0) >= min_delta,
        "external_all_cases_accepted": summary.get("all_cases_accepted") is True,
        "script_imports_retort_engine": "retort_engine" in script_text,
        "score_fields_consumed": summary.get("score_fields_consumed", True),
        "input_sha256": _sha256(input_path),
        "output_sha256": _sha256(output_path) if output_path.is_file() else "",
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        matrix.get("status") == "ready"
        and result_summary["case_count"] >= min_cases
        and result_summary["external_process_returncode"] == 0
        and result_summary["external_all_cases_accepted"]
        and result_summary["external_delta_floor_met"]
        and result_summary["script_imports_retort_engine"] is False
        and result_summary["score_fields_consumed"] is False
    )
    result = {
        "status": "ready" if ready else "needs_external_process_adjudication",
        "project": str(root),
        "summary": result_summary,
        "cases": adjudication.get("cases", []),
        "artifacts": {
            "lab_dir": str(lab),
            "script": str(script_path),
            "input": str(input_path),
            "output": str(output_path),
        },
        "evidence": {
            "style": "out_of_package_subprocess_adjudicator",
            "boundary": "generated_script_under_retort_dotdir_imports_no_retort_engine_modules",
            "acceptance": "non_retort_engine_process_recomputes_delta_at_or_above_80",
        },
    }
    if output:
        report_path = Path(output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _redacted_case(row: dict[str, Any]) -> dict[str, Any]:
    retort = row.get("retort") if isinstance(row.get("retort"), dict) else {}
    return {
        "case_id": str(row.get("case_id") or ""),
        "source_project": str(row.get("source_project") or ""),
        "expected_context": str(row.get("expected_context") or ""),
        "expected_severity": str(row.get("expected_severity") or ""),
        "retort_observation": {
            "severity_matched": retort.get("severity_matched") is True,
            "context_matched": retort.get("context_matched") is True,
            "publishable_comment": int(retort.get("publishable_comment_count") or 0) > 0,
            "task_group": int(retort.get("task_group_count") or 0) > 0,
            "extension_policy": int(retort.get("extension_policy_known_count") or 0) > 0,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


_ADJUDICATOR_SCRIPT = r'''
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
'''
