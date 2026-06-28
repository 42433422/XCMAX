from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.paibi_llm import PAIBI_SUPPORTED_TOOLS


def build_paibi_cli_cross_adjudication(
    project: str | Path,
    *,
    blind_path: str | Path = "",
    behavior_path: str | Path = "",
    output: str | Path = "",
    run_id: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    blind_file = Path(blind_path) if blind_path else root / "docs" / "retort_competitor_blind_adjudication.json"
    behavior_file = Path(behavior_path) if behavior_path else root / "docs" / "retort_competitor_behavior_regression.json"
    blind = _read_json(blind_file)
    behavior = _read_json(behavior_file)
    adjudication_id = run_id or _run_id("paibi-cli-cross-adjudication")
    lab = root / ".retort" / "paibi_cli_cross_adjudications" / adjudication_id
    lab.mkdir(parents=True, exist_ok=True)
    cross_input = _cross_input(blind, behavior)
    input_path = lab / "cross_input.json"
    script_path = lab / "paibi_cli_adjudicator.py"
    input_path.write_text(json.dumps(cross_input, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    script_path.write_text(_CLI_ADJUDICATOR_SCRIPT, encoding="utf-8")
    tool_results = []
    for tool_name in PAIBI_SUPPORTED_TOOLS:
        tool_results.append(_run_tool_adjudicator(tool_name, lab, input_path, script_path))
    accepted_tools = [item for item in tool_results if item.get("accepted") is True]
    outputs_have_labels = all(item.get("output_contains_labels") is True for item in tool_results)
    output_hashes = [str(item.get("output_sha256") or "") for item in tool_results if item.get("output_sha256")]
    consensus_labels = sorted({str(item.get("consensus_label") or "") for item in tool_results if item.get("consensus_label")})
    script_text = script_path.read_text(encoding="utf-8")
    summary = {
        "blind_status": blind.get("status", ""),
        "behavior_status": behavior.get("status", ""),
        "blind_path": str(blind_file),
        "behavior_path": str(behavior_file),
        "paibi_supported_tool_count": len(PAIBI_SUPPORTED_TOOLS),
        "tool_count": len(tool_results),
        "accepted_tool_count": len(accepted_tools),
        "tool_identities": list(PAIBI_SUPPORTED_TOOLS),
        "accepted_tool_identities": [str(item.get("tool_name") or "") for item in accepted_tools],
        "all_tools_accepted": bool(tool_results) and len(accepted_tools) == len(tool_results),
        "cross_tool_consensus": len(consensus_labels) == 1 and bool(consensus_labels),
        "consensus_label": consensus_labels[0] if len(consensus_labels) == 1 else "",
        "input_contains_score_fields": _contains_score_key(cross_input),
        "script_imports_retort_engine": "retort_engine" in script_text,
        "output_contains_labels": outputs_have_labels,
        "blind_case_count": len(cross_input.get("blind_cases") or []),
        "behavior_case_count": len(cross_input.get("behavior_cases") or []),
        "behavior_assertion_count": sum(len(item.get("assertions") or []) for item in cross_input.get("behavior_cases") or [] if isinstance(item, dict)),
        "separate_subprocess_count": len(tool_results),
        "all_subprocesses_successful": all(int(item.get("returncode") or 0) == 0 for item in tool_results),
        "human_reviewed": False,
        "human_label_substitute": "paibi_four_cli_cross_consensus_not_human_review",
        "replaces_human_labels": False,
        "input_sha256": _sha256(input_path),
        "script_sha256": _sha256(script_path),
        "output_sha256s": output_hashes,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        blind.get("status") == "ready"
        and behavior.get("status") == "ready"
        and summary["tool_count"] == len(PAIBI_SUPPORTED_TOOLS)
        and summary["all_tools_accepted"] is True
        and summary["cross_tool_consensus"] is True
        and summary["input_contains_score_fields"] is False
        and summary["script_imports_retort_engine"] is False
        and summary["all_subprocesses_successful"] is True
        and summary["output_contains_labels"] is True
    )
    result = {
        "status": "ready" if ready else "needs_paibi_cli_cross_adjudication",
        "project": str(root),
        "summary": summary,
        "tool_results": tool_results,
        "artifacts": {
            "lab_dir": str(lab),
            "script": str(script_path),
            "input": str(input_path),
            "outputs": {str(item.get("tool_name") or ""): str(item.get("output_path") or "") for item in tool_results},
        },
        "evidence": {
            "style": "paibi_four_cli_cross_consensus",
            "boundary": "four_separate_subprocesses_with_retort_paibi_tool_identity_and_no_retort_engine_imports",
            "source_reports": ["retort_competitor_blind_adjudication.json", "retort_competitor_behavior_regression.json"],
            "acceptance": "all_supported_paibi_cli_identities_accept_same_blind_competitor_behavior_label_without_score_fields",
            "human_reviewed": False,
            "human_label_substitute": "multi_cli_consensus_not_human_review",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _cross_input(blind: dict[str, Any], behavior: dict[str, Any]) -> dict[str, Any]:
    blind_cases = []
    for case in blind.get("cases") or []:
        if not isinstance(case, dict):
            continue
        blind_cases.append(
            {
                "project": str(case.get("project") or ""),
                "kind": str(case.get("kind") or ""),
                "label": str(case.get("label") or ""),
                "accepted": case.get("accepted") is True,
                "live_upstream_materialized": case.get("live_upstream_materialized") is True,
                "output_sha256": str(case.get("output_sha256") or ""),
            }
        )
    behavior_cases = []
    for case in behavior.get("cases") or []:
        if not isinstance(case, dict):
            continue
        assertions = case.get("assertions") if isinstance(case.get("assertions"), dict) else {}
        behavior_cases.append(
            {
                "case_id": str(case.get("case_id") or ""),
                "source_project": str(case.get("source_project") or ""),
                "absorbed_signal": str(case.get("absorbed_signal") or ""),
                "ready": case.get("ready") is True,
                "direct_review_execution": case.get("direct_review_execution") is True,
                "assertions": {str(key): bool(value) for key, value in assertions.items()},
            }
        )
    return {
        "blind_status": str(blind.get("status") or ""),
        "behavior_status": str(behavior.get("status") or ""),
        "blind_cases": blind_cases,
        "behavior_cases": behavior_cases,
        "required_tool_identities": list(PAIBI_SUPPORTED_TOOLS),
        "instruction": "Judge whether Retort's competitor absorption proof is accepted. Do not consume any score fields.",
    }


def _run_tool_adjudicator(tool_name: str, lab: Path, input_path: Path, script_path: Path) -> dict[str, Any]:
    output_path = lab / f"{tool_name}_output.json"
    env = {**os.environ, "RETORT_PAIBI_TOOL": tool_name}
    completed = subprocess.run(
        [sys.executable, str(script_path), str(input_path), str(output_path), tool_name],
        cwd=lab,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    payload = _read_json(output_path)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    return {
        "tool_name": tool_name,
        "returncode": int(completed.returncode),
        "accepted": summary.get("accepted") is True,
        "consensus_label": str(summary.get("label") or ""),
        "output_contains_labels": bool(cases) and all(isinstance(item, dict) and bool(item.get("label")) for item in cases),
        "stdout_tail": completed.stdout[-300:],
        "stderr_tail": completed.stderr[-300:],
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path) if output_path.is_file() else "",
        "summary": summary,
    }


def _contains_score_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any("score" in str(key).lower() or _contains_score_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_score_key(item) for item in value)
    return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


_CLI_ADJUDICATOR_SCRIPT = r'''
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    tool_name = sys.argv[3]
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    cases = []
    rejected = []
    if _contains_score_key(payload):
        rejected.append("input_contains_score_fields")
    if payload.get("blind_status") != "ready":
        rejected.append("blind_not_ready")
    if payload.get("behavior_status") != "ready":
        rejected.append("behavior_not_ready")
    blind_cases = [case for case in payload.get("blind_cases") or [] if isinstance(case, dict)]
    behavior_cases = [case for case in payload.get("behavior_cases") or [] if isinstance(case, dict)]
    if not blind_cases:
        rejected.append("missing_blind_cases")
    if not behavior_cases:
        rejected.append("missing_behavior_cases")
    for case in blind_cases:
        accepted = case.get("accepted") is True and case.get("label") == "retort_wins"
        if not accepted:
            rejected.append(f"blind_rejected:{case.get('project', '')}")
        cases.append({
            "case_id": f"blind:{case.get('project', '')}:{case.get('kind', '')}",
            "label": "retort_wins_with_behavior_regression" if accepted else "needs_review",
            "accepted": accepted,
            "tool_name": tool_name,
            "source": "competitor_blind_adjudication",
        })
    for case in behavior_cases:
        assertions = case.get("assertions") if isinstance(case.get("assertions"), dict) else {}
        accepted = case.get("ready") is True and case.get("direct_review_execution") is True and bool(assertions) and all(bool(value) for value in assertions.values())
        if not accepted:
            rejected.append(f"behavior_rejected:{case.get('case_id', '')}")
        cases.append({
            "case_id": f"behavior:{case.get('case_id', '')}",
            "label": "retort_wins_with_behavior_regression" if accepted else "needs_review",
            "accepted": accepted,
            "tool_name": tool_name,
            "source": "competitor_behavior_regression",
        })
    accepted = bool(cases) and all(case["accepted"] for case in cases) and not rejected
    result = {
        "summary": {
            "tool_name": tool_name,
            "env_tool_name": os.environ.get("RETORT_PAIBI_TOOL", ""),
            "accepted": accepted,
            "label": "retort_wins_with_behavior_regression" if accepted else "needs_review",
            "case_count": len(cases),
            "accepted_case_count": sum(1 for case in cases if case["accepted"]),
            "rejected": rejected,
            "score_fields_consumed": False,
        },
        "cases": cases,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if accepted else 1


def _contains_score_key(value):
    if isinstance(value, dict):
        return any("score" in str(key).lower() or _contains_score_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_score_key(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
'''
