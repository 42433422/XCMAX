"""Validate structured review and QA protocols and focused test evidence."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server import self_maintenance_quality_gate

from . import config


def _python_supports_focused_tests(candidate: Path) -> bool:
    """Return whether a Python executable has the loop's test dependencies."""
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return False
    try:
        probe = subprocess.run(
            [str(candidate), "-c", "import apscheduler, pytest"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _focused_test_command() -> str:
    """Resolve one executable QA command from the running MODstore environment.

    The scheduler may itself run from the lighter FHD venv, which intentionally
    does not install pytest.  Prefer the MODstore venv used for repository tests
    and expose explicit overrides for production or isolated runners.
    """
    command_override = os.environ.get("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", "").strip()
    if command_override:
        return command_override
    test_python_override = os.environ.get("MODSTORE_SELF_MAINTENANCE_TEST_PYTHON", "").strip()
    deploy_root = Path(
        os.environ.get("MODSTORE_DEPLOY_ROOT") or Path(__file__).resolve().parents[2]
    )
    runtime_root = os.environ.get("MODSTORE_RUNTIME_ROOT", "").strip()
    candidates = [
        Path(test_python_override).expanduser() if test_python_override else None,
        deploy_root / ".venv" / "bin" / "python",
        (
            Path(runtime_root).expanduser() / "MODstore_deploy" / ".venv" / "bin" / "python"
            if runtime_root
            else None
        ),
        Path(sys.executable),
    ]
    test_python = next(
        (
            candidate
            for candidate in candidates
            if candidate and _python_supports_focused_tests(candidate)
        ),
        Path(sys.executable),
    )
    test_path = (
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py"
    )
    return f"{shlex.quote(str(test_python))} -m pytest {shlex.quote(test_path)} -q"


def _json_after_marker(text: str, marker: str) -> Optional[Dict[str, Any]]:
    report = text or ""
    positions: List[int] = []
    start = 0
    while True:
        idx = report.find(marker, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + len(marker)
    for idx in reversed(positions):
        tail = report[idx + len(marker) :]
        tail = tail.lstrip(" \t\r\n:=`")
        if tail.startswith("json"):
            tail = tail[4:].lstrip(" \t\r\n")
        try:
            obj, _ = json.JSONDecoder().raw_decode(tail)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _validate_structured_review_protocol(
    obj: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Strict protocol for review employee output. Incomplete → reject/rerun."""
    if not isinstance(obj, dict):
        return (False, "missing_structured_review_object")
    severity = str(obj.get("max_severity") or "").strip().lower()
    if severity not in config._REVIEW_SEVERITIES:
        return (False, "invalid_max_severity")
    if str(obj.get("risk_class") or "").strip().lower() not in config._REVIEW_RISK_CLASSES:
        return (False, "invalid_risk_class")
    if not isinstance(obj.get("blocking_findings"), list):
        return (False, "blocking_findings_not_list")
    if not isinstance(obj.get("tested_commands"), list):
        return (False, "tested_commands_not_list")
    if "target_branch_available" not in obj or not isinstance(
        obj.get("target_branch_available"), bool
    ):
        return (False, "target_branch_available_not_bool")
    dimensions = obj.get("dimensions")
    if not isinstance(dimensions, dict):
        return (False, "missing_dimensions")
    for key in config._REVIEW_DIMENSION_KEYS:
        dim = dimensions.get(key)
        if not isinstance(dim, dict):
            return (False, f"missing_dimension_{key}")
        status = str(dim.get("status") or "").strip().lower()
        if status not in config._REVIEW_DIMENSION_STATUSES:
            return (False, f"invalid_dimension_status_{key}")
        if not isinstance(dim.get("findings"), list):
            return (False, f"dimension_findings_not_list_{key}")
        if status == "fail" and (not dim.get("findings")):
            return (False, f"dimension_fail_without_findings_{key}")
    fail_dims = [
        key
        for key in config._REVIEW_DIMENSION_KEYS
        if str((dimensions.get(key) or {}).get("status") or "").lower() == "fail"
    ]
    if fail_dims and severity in {"none", "low"}:
        return (False, "dimension_fail_severity_too_low")
    if fail_dims and (not obj.get("blocking_findings")):
        return (False, "dimension_fail_without_blocking_findings")
    return (True, "")


def _validate_structured_qa_protocol(
    obj: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    if not isinstance(obj, dict):
        return (False, "missing_structured_qa_result")
    if str(obj.get("verdict") or "").strip().upper() not in {"PASS", "FAIL"}:
        return (False, "invalid_qa_verdict")
    if not isinstance(obj.get("blocking_findings"), list):
        return (False, "qa_blocking_findings_not_list")
    if not isinstance(obj.get("tested_commands"), list):
        return (False, "qa_tested_commands_not_list")
    if "target_branch_available" not in obj or not isinstance(
        obj.get("target_branch_available"), bool
    ):
        return (False, "qa_target_branch_available_not_bool")
    return (True, "")


def _structured_report_from_step(step: Dict[str, Any], marker: str) -> Optional[Dict[str, Any]]:
    report = str(step.get("report_excerpt") or "")
    parsed = _json_after_marker(report, marker)
    candidates: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        candidates.append(parsed)
    for line in report.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            if marker == config.STRUCTURED_QA_MARKER and "verdict" in obj:
                candidates.append(obj)
            if marker == config.STRUCTURED_REVIEW_MARKER and "max_severity" in obj:
                candidates.append(obj)
    for obj in candidates:
        if marker == config.STRUCTURED_REVIEW_MARKER:
            ok, _reason = _validate_structured_review_protocol(obj)
            if ok:
                return obj
        elif marker == config.STRUCTURED_QA_MARKER:
            ok, _reason = _validate_structured_qa_protocol(obj)
            if ok:
                return obj
        else:
            return obj
    return candidates[0] if candidates else None


def _structured_protocol_ok(step_name: str, report_excerpt: str) -> Tuple[bool, str]:
    if step_name == "review":
        obj = _json_after_marker(report_excerpt, config.STRUCTURED_REVIEW_MARKER)
        if obj is None:
            loose = None
            for line in str(report_excerpt or "").splitlines():
                line = line.strip()
                if line.startswith("{") and '"max_severity"' in line:
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        loose = candidate
                        break
            obj = loose
        return _validate_structured_review_protocol(obj)
    if step_name == "qa":
        obj = _json_after_marker(report_excerpt, config.STRUCTURED_QA_MARKER)
        if obj is None:
            for line in str(report_excerpt or "").splitlines():
                line = line.strip()
                if line.startswith("{") and '"verdict"' in line:
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        obj = candidate
                        break
        return _validate_structured_qa_protocol(obj)
    return (True, "")


def _structured_report_gate(steps: List[Dict[str, Any]], branch=None) -> Dict[str, Any]:
    review_steps = [step for step in steps if step.get("step") == "review"]
    qa_steps = [step for step in steps if step.get("step") == "qa"]
    if review_steps:
        review_json = _structured_report_from_step(
            review_steps[-1], config.STRUCTURED_REVIEW_MARKER
        )
        protocol_ok, protocol_reason = _validate_structured_review_protocol(review_json)
        if not protocol_ok:
            return {
                "ok": False,
                "reason": protocol_reason or "missing_structured_review_result",
                "review": review_json,
            }
        severity = str(review_json.get("max_severity") or "high").lower()
        blocking = review_json.get("blocking_findings")
        dimensions = (
            review_json.get("dimensions") if isinstance(review_json.get("dimensions"), dict) else {}
        )
        failed_dims = [
            key
            for key in config._REVIEW_DIMENSION_KEYS
            if str((dimensions.get(key) or {}).get("status") or "").lower() == "fail"
        ]
        if severity not in {"none", "low", "medium"}:
            return {
                "ok": False,
                "reason": "structured_review_high_severity",
                "review": review_json,
            }
        if isinstance(blocking, list) and blocking:
            return {
                "ok": False,
                "reason": "structured_review_blocking_findings",
                "review": review_json,
                "failed_dimensions": failed_dims,
            }
        if failed_dims:
            return {
                "ok": False,
                "reason": "structured_review_dimension_fail",
                "review": review_json,
                "failed_dimensions": failed_dims,
            }
    else:
        review_json = None
    if qa_steps:
        qa_json = _structured_report_from_step(qa_steps[-1], config.STRUCTURED_QA_MARKER)
        qa_ok, qa_reason = _validate_structured_qa_protocol(qa_json)
        if not qa_ok:
            return {
                "ok": False,
                "reason": qa_reason or "missing_structured_qa_result",
                "review": review_json,
                "qa": qa_json,
            }
        if qa_json.get("target_branch_available") is not True:
            return {
                "ok": False,
                "reason": "structured_qa_target_branch_unavailable",
                "qa": qa_json,
            }
        verdict = str(qa_json.get("verdict") or "").upper()
        if verdict != "PASS":
            return {
                "ok": False,
                "reason": self_maintenance_quality_gate.qa_verdict_failure_reason(qa_json),
                "qa": qa_json,
            }
        blocking = qa_json.get("blocking_findings")
        if isinstance(blocking, list) and blocking:
            return {
                "ok": False,
                "reason": "structured_qa_blocking_findings",
                "qa": qa_json,
            }
        tested_commands = qa_json.get("tested_commands")
        focused_command = _focused_test_command()
        if not isinstance(tested_commands, list) or not any(
            (
                isinstance(item, dict)
                and self_maintenance_quality_gate.matches_focused_test_command(
                    item.get("command"), focused_command
                )
                and (int(item.get("exit_code") if item.get("exit_code") is not None else -1) == 0)
                and str(item.get("status") or "").lower().startswith("passed")
                for item in tested_commands
            )
        ):
            return {
                "ok": False,
                "reason": "structured_qa_focused_command_not_passed",
                "focused_command": focused_command,
                "qa": qa_json,
            }
        quality_failure = self_maintenance_quality_gate.quality_check_failure(
            qa_json, target_branch=branch
        )
        if quality_failure:
            return {"ok": False, "reason": quality_failure, "qa": qa_json}
        test_delta = (
            qa_json.get("test_delta") if isinstance(qa_json.get("test_delta"), dict) else {}
        )
        for key in ("new_failures", "new_errors"):
            values = test_delta.get(key)
            if isinstance(values, list) and values:
                return {"ok": False, "reason": f"structured_qa_{key}", "qa": qa_json}
    else:
        qa_json = None
    return {
        "ok": True,
        "qa": qa_json,
        "reason": "structured_reports_passed",
        "review": review_json,
    }


def _step_reports(steps: List[Dict[str, Any]]) -> str:
    return "\n".join((str(step.get("report_excerpt") or "") for step in steps))


def _has_high_risk_report(
    steps: List[Dict[str, Any]],
) -> bool:
    text = _step_reports(steps).lower()
    if any((term.lower() in text for term in config.HIGH_RISK_TERMS)):
        return True
    return bool(config.HIGH_RISK_REPORT_RE.search(_step_reports(steps)))


def _missing_report_only_evidence(
    steps: List[Dict[str, Any]],
) -> bool:
    markers = (
        "report-only task completed",
        "result:",
        "verdict",
        "审查结论",
        "具体发现",
        "evidence:",
    )
    for step in steps:
        if step.get("step") not in {"review", "qa"}:
            continue
        text = str(step.get("report_excerpt") or "").lower()
        if not any((marker in text for marker in markers)):
            return True
    return False
