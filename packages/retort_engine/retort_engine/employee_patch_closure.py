from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


def run_employee_patch_closure_suite(project: str | Path, *, output: str | Path = "", run_id: str = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    suite_id = run_id or _run_id("employee-patch")
    lab = root / ".retort" / "employee_patch_closures" / suite_id
    positive = run_employee_patch_closure_case(
        root,
        target_file=lab / "positive_patch.py",
        replacement="def employee_patch_value():\n    return 'verified-patch'\n",
        expected_text="verified-patch",
        gate_commands=[[sys.executable, "-m", "py_compile", "{target_file}"]],
        run_id=suite_id,
        case_name="positive_gate_pass",
    )
    negative = run_employee_patch_closure_case(
        root,
        target_file=lab / "rollback_patch.py",
        replacement="def employee_patch_value(:\n    return 'broken'\n",
        expected_text="broken",
        gate_commands=[[sys.executable, "-m", "py_compile", "{target_file}"]],
        run_id=suite_id,
        case_name="negative_gate_rollback",
    )
    multi_file = run_multi_file_employee_patch_closure_case(root, lab=lab, run_id=suite_id)
    retry = run_retry_employee_patch_closure_case(root, lab=lab, run_id=suite_id)
    cases = [positive, negative, multi_file, retry]
    summary = {
        "run_id": suite_id,
        "case_count": len(cases),
        "patch_generated_count": sum(1 for case in cases if case["summary"]["patch_generated"]),
        "patch_applied_count": sum(1 for case in cases if case["summary"]["patch_applied"]),
        "gate_passed_count": sum(1 for case in cases if case["summary"]["gates_passed"]),
        "rollback_verified_count": sum(1 for case in cases if case["summary"]["rollback_verified"]),
        "success_case_verified": positive["status"] == "patch_verified",
        "failure_case_rolled_back": negative["status"] == "patch_rolled_back",
        "multi_file_case_verified": multi_file["status"] == "patch_verified",
        "multi_file_changed_file_count": len(multi_file["changed_files"]),
        "secondary_review_status": multi_file["summary"].get("secondary_review_status", ""),
        "secondary_review_comment_count": multi_file["summary"].get("secondary_review_comment_count", 0),
        "successful_repairs_re_reviewed": bool(multi_file["summary"].get("secondary_review_status") == "reviewed"),
        "retry_case_verified": retry["status"] == "patch_verified_after_retry",
        "retry_first_failure_rolled_back": bool(retry["summary"].get("first_failure_rolled_back")),
        "retry_second_patch_passed": bool(retry["summary"].get("retry_gate_passed")),
        "retry_secondary_review_status": retry["summary"].get("secondary_review_status", ""),
        "all_cases_have_patch_files": all(bool(case["evidence"].get("patch_path")) and Path(str(case["evidence"]["patch_path"])).is_file() for case in cases),
    }
    status = (
        "ready"
        if summary["success_case_verified"]
        and summary["failure_case_rolled_back"]
        and summary["multi_file_case_verified"]
        and summary["successful_repairs_re_reviewed"]
        and summary["retry_case_verified"]
        and summary["retry_first_failure_rolled_back"]
        and summary["all_cases_have_patch_files"]
        else "needs_attention"
    )
    result = {
        "status": status,
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "evidence": {
            "lab_dir": str(lab),
            "style": "employee_patch_generation_apply_gate_rollback",
            "positive_patch_path": positive["evidence"].get("patch_path", ""),
            "rollback_patch_path": negative["evidence"].get("patch_path", ""),
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def run_retry_employee_patch_closure_case(project: str | Path, *, lab: str | Path, run_id: str = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    case_id = run_id or _run_id("retry-employee-patch")
    target = Path(lab).expanduser().resolve() / "retry_repair.py"
    first = run_employee_patch_closure_case(
        root,
        target_file=target,
        replacement="def retry_repair(:\n    return 'broken'\n",
        expected_text="broken",
        gate_commands=[[sys.executable, "-m", "py_compile", "{target_file}"]],
        run_id=case_id,
        case_name="retry_first_failure",
    )
    second = run_employee_patch_closure_case(
        root,
        target_file=target,
        replacement="def retry_repair():\n    return 'verified-retry'\n",
        expected_text="verified-retry",
        gate_commands=[[sys.executable, "-m", "py_compile", "{target_file}"]],
        run_id=case_id,
        case_name="retry_second_success",
    )
    patch_text = Path(str(second["evidence"]["patch_path"])).read_text(encoding="utf-8")
    secondary_review = review_diff(patch_text, issue_context="Retry failed employee patch after rollback and prove corrected behavior", max_comments=4)
    status = "patch_verified_after_retry" if first["status"] == "patch_rolled_back" and second["status"] == "patch_verified" else "patch_retry_failed"
    return {
        "status": status,
        "project": str(root),
        "target": str(target),
        "summary": {
            "run_id": case_id,
            "case_name": "retry_failure_then_success",
            "patch_generated": bool(first["summary"]["patch_generated"] and second["summary"]["patch_generated"]),
            "patch_applied": bool(second["summary"]["patch_applied"]),
            "gates_passed": bool(second["summary"]["gates_passed"]),
            "rollback_verified": bool(first["summary"]["rollback_verified"]),
            "retained_change": bool(second["summary"]["retained_change"]),
            "before_exists": bool(first["summary"]["before_exists"] or second["summary"]["before_exists"]),
            "expected_text_present": bool(second["summary"]["expected_text_present"]),
            "retry_count": 2,
            "first_gate_failed": not bool(first["summary"]["gates_passed"]),
            "first_failure_rolled_back": first["status"] == "patch_rolled_back",
            "retry_gate_passed": bool(second["summary"]["gates_passed"]),
            "secondary_review_status": secondary_review.get("status"),
            "secondary_review_comment_count": (secondary_review.get("summary") or {}).get("comment_count", 0),
        },
        "gates": [*(first.get("gates") or []), *(second.get("gates") or [])],
        "changed_files": list(second.get("changed_files") or []),
        "attempted_changed_files": list(first.get("attempted_changed_files") or []) + list(second.get("attempted_changed_files") or []),
        "rollback": {
            "strategy": "rollback_failed_patch_then_apply_corrected_patch",
            "performed": True,
            "verified": first["status"] == "patch_rolled_back",
        },
        "secondary_review": {
            "status": secondary_review.get("status"),
            "summary": secondary_review.get("summary", {}),
            "comment_count": len(secondary_review.get("comments") or []),
        },
        "evidence": {
            "patch_path": str(second["evidence"]["patch_path"]),
            "failed_patch_path": str(first["evidence"]["patch_path"]),
            "target_exists_after": target.exists(),
            "reviewed_after_patch": secondary_review.get("status") == "reviewed",
        },
    }


def run_multi_file_employee_patch_closure_case(project: str | Path, *, lab: str | Path, run_id: str = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    case_id = run_id or _run_id("multi-file-employee-patch")
    lab_root = Path(lab).expanduser().resolve()
    runtime = lab_root / "multi_file_repair" / "runtime.py"
    runtime_test = lab_root / "multi_file_repair" / "test_runtime.py"
    replacements = {
        runtime: "def resolve_runtime_value(env):\n    value = env.get('APP_VALUE', '')\n    if not value:\n        raise ValueError('APP_VALUE is required')\n    return value\n",
        runtime_test: "from runtime import resolve_runtime_value\n\n\ndef test_resolve_runtime_value_requires_configured_value():\n    assert resolve_runtime_value({'APP_VALUE': 'verified'}) == 'verified'\n",
    }
    before_texts: dict[Path, str] = {}
    patch_parts: list[str] = []
    changed_files: list[str] = []
    for target, replacement in replacements.items():
        resolved = _resolve_target(root, target)
        before_exists = resolved.is_file()
        before = resolved.read_text(encoding="utf-8") if before_exists else ""
        before_texts[resolved] = before
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(replacement, encoding="utf-8")
        patch_parts.append(_unified_patch(before, replacement, _project_rel(root, resolved), before_exists=before_exists))
        changed_files.append(str(resolved))
    patch_text = "".join(patch_parts)
    patch_path = root / ".retort" / "employee_patch_closures" / case_id / "multi_file_repair.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(patch_text, encoding="utf-8")
    gates = _run_gates(root, runtime, [[sys.executable, "-m", "py_compile", str(runtime), str(runtime_test)]])
    gates_passed = bool(gates) and all(gate["ok"] for gate in gates)
    secondary_review = review_diff(patch_text, issue_context="Repair employee generated patch and prove behavior with tests", max_comments=6)
    rollback_verified = False
    if not gates_passed:
        for target, before in before_texts.items():
            if before:
                target.write_text(before, encoding="utf-8")
            else:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        rollback_verified = all((target.read_text(encoding="utf-8") == before) if before else not target.exists() for target, before in before_texts.items())
    retained_change = gates_passed and all(Path(item).is_file() for item in changed_files)
    return {
        "status": "patch_verified" if retained_change else "patch_rolled_back" if rollback_verified else "patch_failed",
        "project": str(root),
        "target": ",".join(changed_files),
        "summary": {
            "run_id": case_id,
            "case_name": "multi_file_repair_reviewed",
            "patch_generated": bool(patch_text.strip()),
            "patch_applied": len(changed_files) == len(replacements),
            "gates_passed": gates_passed,
            "rollback_verified": rollback_verified,
            "retained_change": retained_change,
            "before_exists": any(bool(text) for text in before_texts.values()),
            "expected_text_present": all(marker in "".join(Path(item).read_text(encoding="utf-8") for item in changed_files if Path(item).is_file()) for marker in ("APP_VALUE", "verified")),
            "secondary_review_status": secondary_review.get("status"),
            "secondary_review_comment_count": (secondary_review.get("summary") or {}).get("comment_count", 0),
            "secondary_review_publishable_count": (secondary_review.get("summary") or {}).get("publishable_comment_count", 0),
            "secondary_review_context_count": (secondary_review.get("summary") or {}).get("review_context_group_count", 0),
        },
        "gates": gates,
        "changed_files": changed_files if retained_change else [],
        "attempted_changed_files": changed_files,
        "rollback": {
            "strategy": "restore_original_file_bytes_for_all_files",
            "performed": not gates_passed,
            "verified": rollback_verified,
        },
        "secondary_review": {
            "status": secondary_review.get("status"),
            "summary": secondary_review.get("summary", {}),
            "comment_count": len(secondary_review.get("comments") or []),
        },
        "evidence": {
            "patch_path": str(patch_path),
            "target_exists_after": all(Path(item).exists() for item in changed_files),
            "multi_file": True,
            "reviewed_after_patch": secondary_review.get("status") == "reviewed",
        },
    }


def run_employee_patch_closure_case(
    project: str | Path,
    *,
    target_file: str | Path,
    replacement: str,
    expected_text: str = "",
    gate_commands: list[list[str]] | None = None,
    run_id: str = "",
    case_name: str = "employee_patch",
    rollback_on_failure: bool = True,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    case_id = run_id or _run_id(case_name)
    target = _resolve_target(root, target_file)
    before_exists = target.is_file()
    before_text = target.read_text(encoding="utf-8") if before_exists else ""
    before_hash = _sha256(before_text)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(replacement, encoding="utf-8")
    after_text = target.read_text(encoding="utf-8")
    after_hash = _sha256(after_text)
    patch_path = root / ".retort" / "employee_patch_closures" / case_id / f"{case_name}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_text = _unified_patch(before_text, after_text, _project_rel(root, target), before_exists=before_exists)
    patch_path.write_text(patch_text, encoding="utf-8")
    expected_text_present = not expected_text or expected_text in after_text
    gates = _run_gates(root, target, gate_commands or [[sys.executable, "-m", "py_compile", "{target_file}"]])
    gates_passed = bool(gates) and all(gate["ok"] for gate in gates)
    rollback_verified = False
    if not gates_passed and rollback_on_failure:
        if before_exists:
            target.write_text(before_text, encoding="utf-8")
            rollback_verified = target.read_text(encoding="utf-8") == before_text
        else:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            rollback_verified = not target.exists()
    retained_change = gates_passed and expected_text_present and target.exists() and _sha256(target.read_text(encoding="utf-8")) == after_hash
    status = "patch_verified" if retained_change else "patch_rolled_back" if rollback_verified else "patch_failed"
    return {
        "status": status,
        "project": str(root),
        "target": str(target),
        "summary": {
            "run_id": case_id,
            "case_name": case_name,
            "patch_generated": bool(patch_text.strip()),
            "patch_applied": after_hash != before_hash and expected_text_present,
            "gates_passed": gates_passed,
            "rollback_verified": rollback_verified,
            "retained_change": retained_change,
            "before_exists": before_exists,
            "expected_text_present": expected_text_present,
        },
        "gates": gates,
        "changed_files": [str(target)] if retained_change else [],
        "attempted_changed_files": [str(target)],
        "rollback": {
            "strategy": "restore_original_file_bytes",
            "performed": bool(not gates_passed and rollback_on_failure),
            "verified": rollback_verified,
        },
        "evidence": {
            "patch_path": str(patch_path),
            "before_hash": before_hash,
            "after_hash": after_hash,
            "target_exists_after": target.exists(),
        },
    }


def _resolve_target(root: Path, target_file: str | Path) -> Path:
    target = Path(target_file)
    if not target.is_absolute():
        target = root / target
    resolved = target.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"employee patch target must stay inside project: {target_file}") from exc
    return resolved


def _run_gates(root: Path, target: Path, commands: list[list[str]]) -> list[dict[str, Any]]:
    gates = []
    for command in commands:
        expanded = [_expand_arg(str(arg), root, target) for arg in command]
        try:
            completed = subprocess.run(expanded, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False)
            returncode = int(completed.returncode)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "timeout")
        gates.append(
            {
                "command": expanded,
                "ok": returncode == 0,
                "returncode": returncode,
                "stdout_tail": stdout[-1200:],
                "stderr_tail": stderr[-1200:],
            }
        )
    return gates


def _expand_arg(arg: str, root: Path, target: Path) -> str:
    return arg.replace("{project}", str(root)).replace("{target_file}", str(target))


def _unified_patch(before: str, after: str, rel: str, *, before_exists: bool) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    fromfile = f"a/{rel}" if before_exists else "/dev/null"
    tofile = f"b/{rel}"
    header = f"diff --git a/{rel} b/{rel}\n"
    return header + "".join(difflib.unified_diff(before_lines, after_lines, fromfile=fromfile, tofile=tofile))


def _project_rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
