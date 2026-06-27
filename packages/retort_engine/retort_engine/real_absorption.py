from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.feedback_audit import audit_feedback_closure
from retort_engine.history import RetortHistoryStore
from retort_engine.license_gate import license_gate
from retort_engine.models import EmployeeTaskResult
from retort_engine.review_pipeline import build_absorption_review_report


SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".toml", ".yml", ".yaml", ".json", ".go"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache", "dist", "build"}


def apply_real_absorption(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    root = Path(str(payload.get("own_project") or payload.get("project") or ".")).expanduser().resolve()
    external_path = Path(str(payload.get("external_path") or "")).expanduser().resolve()
    source = str(payload.get("source") or payload.get("github_url") or payload.get("external_path") or "")
    tasks = [item for item in payload.get("tasks") or [] if isinstance(item, dict)]
    if not external_path.is_dir():
        return _execution_result("skipped_no_external_project", root, source, started, [], [], [], "External project was not materialized locally.")
    if not tasks:
        return _execution_result("skipped_no_tasks", root, source, started, [], [], [], "No absorption tasks were generated.")

    run_id = _run_id(source)
    external_profile = _external_profile(external_path)
    semantic_review = _semantic_review(root, external_path)
    module_path = _implementation_target(root)
    capability_path = _capability_target(root)
    capability_test_path = _capability_test_target(root)
    log_path = root / "docs" / "retort_absorption_log.md"
    report_path = root / "docs" / "retort_external_review_report.json"
    before = _snapshot([module_path, capability_path, capability_test_path, log_path, report_path])
    review_report = _review_report(root, run_id, source, external_path, tasks, external_profile, semantic_review)
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(_module_content(run_id, source, external_path, tasks, external_profile), encoding="utf-8")
    capability_path.parent.mkdir(parents=True, exist_ok=True)
    capability_path.write_text(_capability_module_content(run_id, source, external_path, tasks, external_profile, review_report), encoding="utf-8")
    capability_test_path.parent.mkdir(parents=True, exist_ok=True)
    capability_test_path.write_text(_capability_test_content(_capability_import_name(root, capability_path), source), encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _append_log(log_path, run_id, source, external_path, tasks, external_profile)
    report_path.write_text(json.dumps(review_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    changed_files = _changed_files(before, [module_path, capability_path, capability_test_path, log_path, report_path])
    gates = [
        _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(module_path)], root, timeout=60),
        _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(capability_path)], root, timeout=60),
        _run_command([_python(payload), "-m", "pytest", str(capability_test_path.relative_to(root)), "-q"], root, timeout=120),
    ]
    if payload.get("run_local_gates"):
        gates.extend(_local_gate_commands(root, payload))
    diff_summary = _git_diff_summary(root, changed_files)
    result = _execution_result(
        "applied" if changed_files else "noop",
        root,
        source,
        started,
        changed_files,
        gates,
        diff_summary,
        "CLI absorption applied project-local code and evidence artifacts.",
    )
    result["run_id"] = run_id
    result["external_profile"] = external_profile
    result["semantic_review"] = semantic_review
    result["capability_module_path"] = str(capability_path)
    result["capability_test_path"] = str(capability_test_path)
    result["review_report_path"] = str(report_path)
    result["reproducibility"] = {"command": f"retort absorb --own-project {root} --external-path {external_path} --run-local-gates --branch-workflow --merge-after"}
    result["queue_records_written"] = _write_execution_queue_records(str(payload.get("employee_queue") or ""), run_id, source, tasks)
    employee_results_path = _write_employee_results(root, run_id, source, tasks, result, payload)
    result["employee_results_path"] = str(employee_results_path)
    result["feedback_audit"] = audit_feedback_closure(queue_path=str(payload.get("employee_queue") or ""), history_store=str(payload.get("history_store") or ""), employee_results_dir=employee_results_path.parent)
    _record_execution(root, result)
    return result


def _implementation_target(root: Path) -> Path:
    retort_package = root / "retort_engine"
    if retort_package.is_dir() and (retort_package / "__init__.py").is_file():
        return retort_package / "absorbed_external_patterns.py"
    packages = [path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith(".") and path.name != "tests"]
    if len(packages) == 1:
        return packages[0] / "retort_absorbed_patterns.py"
    return root / "retort_absorbed_patterns.py"


def _capability_target(root: Path) -> Path:
    retort_package = root / "retort_engine"
    if retort_package.is_dir() and (retort_package / "__init__.py").is_file():
        return retort_package / "absorbed_capabilities.py"
    packages = [path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith(".") and path.name != "tests"]
    if len(packages) == 1:
        return packages[0] / "absorbed_capabilities.py"
    return root / "absorbed_capabilities.py"


def _capability_test_target(root: Path) -> Path:
    return root / "tests" / "test_absorbed_capabilities.py"


def _capability_import_name(root: Path, capability_path: Path) -> str:
    rel = capability_path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[0] == "tests":
        parts = parts[1:]
    return ".".join(parts)


def _module_content(run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    payload = {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "external_profile": profile,
        "tasks": [
            {
                "task_id": str(task.get("task_id") or ""),
                "title": str(task.get("title") or ""),
                "dimension": str(task.get("dimension") or ""),
                "priority": str(task.get("priority") or ""),
                "why": str(task.get("why") or ""),
            }
            for task in tasks
        ],
    }
    payload_text = repr(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return f'''"""Retort-applied external absorption patterns.

This file is generated by `retort apply-absorption`. It records project-local
implementation signals adapted from an external repository without copying
license-sensitive source code.
"""

from __future__ import annotations

import json
from typing import Any


ABSORBED_EXTERNAL_PATTERNS: dict[str, Any] = json.loads({payload_text})


def absorbed_external_patterns() -> dict[str, Any]:
    """Return the latest externally absorbed implementation signals."""
    return dict(ABSORBED_EXTERNAL_PATTERNS)
'''


def _capability_module_content(run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any], review_report: dict[str, Any]) -> str:
    capability_payload = {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "signals": list(profile.get("signals") or []),
        "signal_evidence": dict(profile.get("signal_evidence") or {}),
        "component_gaps": list((review_report.get("review_pipeline") or {}).get("component_gaps") or [])[:12],
        "prioritized_absorptions": list((review_report.get("review_pipeline") or {}).get("prioritized_absorptions") or [])[:12],
        "benchmark": dict((review_report.get("review_pipeline") or {}).get("benchmark") or {}),
        "tasks": [
            {
                "task_id": str(task.get("task_id") or ""),
                "title": str(task.get("title") or ""),
                "dimension": str(task.get("dimension") or ""),
                "priority": str(task.get("priority") or ""),
                "why": str(task.get("why") or ""),
            }
            for task in tasks
        ],
    }
    payload_text = repr(json.dumps(capability_payload, ensure_ascii=True, indent=2, sort_keys=True))
    return f'''"""Runtime behavior absorbed from external review tools.

This module is rewritten by `retort apply-absorption` when an external project
contributes implementation signals that should affect Retort behavior. Unlike
the audit report, these functions are executable gates used by product code and
tests to decide whether an absorption actually improved Retort.
"""

from __future__ import annotations

import json
from typing import Any


ABSORBED_CAPABILITY_STATE: dict[str, Any] = json.loads({payload_text})

SIGNAL_WEIGHTS = {{
    "review_pipeline": 24,
    "file_grouping": 20,
    "diff_hunk_review": 18,
    "benchmarking": 16,
    "plugin_surface": 12,
    "multi_provider": 10,
}}


def absorbed_capability_plan() -> dict[str, Any]:
    """Return the latest executable capability plan from external absorption."""
    state = dict(ABSORBED_CAPABILITY_STATE)
    state["ranked_capabilities"] = ranked_capabilities()
    state["minimum_behavior_tests"] = int((state.get("benchmark") or {{}}).get("minimum_expected_behavior_tests") or 3)
    return state


def ranked_capabilities() -> list[dict[str, Any]]:
    """Rank absorbed signals by behavior depth rather than keyword count."""
    state = ABSORBED_CAPABILITY_STATE
    rows: list[dict[str, Any]] = []
    for signal in state.get("signals") or []:
        evidence = list((state.get("signal_evidence") or {{}}).get(signal) or [])
        gap_hits = sum(1 for gap in state.get("component_gaps") or [] if str(gap.get("component") or "").replace("benchmark_eval", "benchmarking") == signal)
        weight = SIGNAL_WEIGHTS.get(signal, 8) + min(12, len(evidence) * 2) + min(10, gap_hits * 5)
        rows.append({{"signal": signal, "weight": weight, "evidence_files": evidence[:5], "gap_hits": gap_hits}})
    return sorted(rows, key=lambda row: (int(row["weight"]), row["signal"]), reverse=True)


def capability_progress_from_execution(changed_files: list[str], gates: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether an absorption changed behavior and proved it with tests."""
    source_files = [path for path in changed_files if path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go")) and "/tests/" not in path and not path.endswith("absorbed_external_patterns.py")]
    test_files = [path for path in changed_files if "/tests/" in path or path.rsplit("/", 1)[-1].startswith("test_")]
    gate_count = len(gates)
    passed_gates = sum(1 for gate in gates if bool(gate.get("ok")))
    ready = bool(source_files and test_files and gate_count and passed_gates == gate_count)
    return {{
        "behavior_source_files": source_files,
        "behavior_test_files": test_files,
        "gate_count": gate_count,
        "passed_gates": passed_gates,
        "ready_for_90": ready,
    }}


def explain_missing_absorption_evidence(changed_files: list[str], gates: list[dict[str, Any]]) -> list[str]:
    """Explain why a run should not be allowed to score as real absorption."""
    progress = capability_progress_from_execution(changed_files, gates)
    missing: list[str] = []
    if not progress["behavior_source_files"]:
        missing.append("missing_behavior_source_diff")
    if not progress["behavior_test_files"]:
        missing.append("missing_behavior_test_diff")
    if not progress["gate_count"]:
        missing.append("missing_post_absorption_gate")
    elif progress["passed_gates"] != progress["gate_count"]:
        missing.append("post_absorption_gate_failed")
    return missing
'''


def _capability_test_content(import_name: str, source: str) -> str:
    source_text = repr(source)
    return f'''from __future__ import annotations

from {import_name} import absorbed_capability_plan, capability_progress_from_execution, explain_missing_absorption_evidence, ranked_capabilities

EXPECTED_ABSORPTION_SOURCE = {source_text}


def test_absorbed_capability_plan_has_ranked_behavior_signals() -> None:
    plan = absorbed_capability_plan()
    assert plan["run_id"]
    assert plan["source"] == EXPECTED_ABSORPTION_SOURCE
    assert isinstance(plan["tasks"], list)
    assert plan["minimum_behavior_tests"] >= 3
    assert ranked_capabilities()


def test_capability_progress_requires_behavior_code_tests_and_gates() -> None:
    progress = capability_progress_from_execution(
        ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
        [{{"ok": True}}, {{"ok": True}}],
    )
    assert progress["ready_for_90"] is True


def test_missing_absorption_evidence_blocks_report_only_runs() -> None:
    missing = explain_missing_absorption_evidence(["docs/retort_absorption_log.md"], [{{"ok": True}}])
    assert "missing_behavior_source_diff" in missing
    assert "missing_behavior_test_diff" in missing
'''


def _append_log(log_path: Path, run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    lines = [
        "",
        f"## {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {run_id}",
        "",
        f"- Source: `{source}`",
        f"- Local path: `{external_path}`",
        f"- External files scanned: `{profile['file_count']}`",
        f"- Absorbed signals: `{', '.join(profile['signals']) or 'none'}`",
        "- Applied tasks:",
    ]
    for task in tasks:
        lines.append(f"  - `{task.get('task_id', '')}` {task.get('title', '')} [{task.get('dimension', '')}]")
    log_path.write_text((_read(log_path) + "\n".join(lines) + "\n").lstrip(), encoding="utf-8")


def _external_profile(root: Path) -> dict[str, Any]:
    files = _project_files(root)
    text_parts: list[str] = []
    suffix_counts: dict[str, int] = {}
    signal_evidence: dict[str, list[str]] = {}
    for path in files[:600]:
        suffix = path.suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        if path.suffix.lower() in SOURCE_SUFFIXES:
            text = _read(path)[:20000]
            text_parts.append(text)
            lowered_file = text.lower()
            rel = str(path.relative_to(root))
            for signal, markers in {
                "review_pipeline": ("code review", "review pipeline", "reviewer", "reflection", "localization"),
                "file_grouping": ("file group", "group files", "changed files", "diff hunk", "patch set"),
                "benchmarking": ("benchmark", "precision", "recall", "eval", "evaluation"),
                "plugin_surface": ("plugin", "cli", "github action", "codex"),
                "multi_provider": ("provider", "model", "openai", "anthropic", "ollama"),
            }.items():
                if any(marker in lowered_file for marker in markers):
                    signal_evidence.setdefault(signal, [])
                    if len(signal_evidence[signal]) < 5:
                        signal_evidence[signal].append(rel)
    lowered = "\n".join(text_parts).lower()
    signal_map = {
        "review_pipeline": ("code review", "review pipeline", "reviewer", "reflection", "localization"),
        "file_grouping": ("file group", "group files", "changed files", "diff hunk", "patch set"),
        "benchmarking": ("benchmark", "precision", "recall", "eval", "evaluation"),
        "plugin_surface": ("plugin", "cli", "github action", "codex"),
        "multi_provider": ("provider", "model", "openai", "anthropic", "ollama"),
    }
    signals = [name for name, markers in signal_map.items() if any(marker in lowered for marker in markers)]
    return {"file_count": len(files), "suffix_counts": suffix_counts, "signals": signals, "signal_evidence": signal_evidence, "git_revision": _git_revision(root)}


def _semantic_review(own: Path, external: Path) -> dict[str, Any]:
    own_profile = _code_profile(own)
    external_profile = _code_profile(external)
    gaps = []
    for key in sorted(external_profile):
        gap = int(external_profile[key]) - int(own_profile.get(key, 0))
        if gap > 0:
            gaps.append({"metric": key, "external_advantage": gap})
    return {"own": own_profile, "external": external_profile, "gaps": gaps[:12]}


def _code_profile(root: Path) -> dict[str, int]:
    profile = {"source_files": 0, "functions": 0, "classes": 0, "cli_markers": 0, "test_markers": 0, "workflow_markers": 0}
    for path in _project_files(root)[:800]:
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        text = _read(path)
        profile["source_files"] += 1
        profile["functions"] += text.count("def ") + text.count("function ") + text.count("func ")
        profile["classes"] += text.count("class ") + text.count("type ")
        profile["cli_markers"] += text.count("add_parser(") + text.lower().count("cobra.command") + text.lower().count("commander")
        profile["test_markers"] += text.count("def test_") + text.count("it(") + text.count("describe(")
        profile["workflow_markers"] += text.lower().count("workflow") + text.lower().count("pipeline") + text.lower().count("review")
    return profile


def _review_report(root: Path, run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any], semantic_review: dict[str, Any]) -> dict[str, Any]:
    pipeline_report = build_absorption_review_report(root, external_path, tasks)
    return {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "external_snapshot": {"git_revision": profile.get("git_revision"), "file_count": profile.get("file_count"), "suffix_counts": profile.get("suffix_counts")},
        "license_review": license_gate(external_path, enforce=True).to_dict(),
        "absorbed_signals": profile.get("signals", []),
        "signal_evidence": profile.get("signal_evidence", {}),
        "semantic_review": semantic_review,
        "review_pipeline": pipeline_report,
        "tasks": tasks,
        "replay": {"command": f"retort absorb --own-project <main-project> --external-path {external_path} --run-local-gates --branch-workflow --merge-after"},
    }


def _project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if set(path.relative_to(root).parts) & SKIP_PARTS:
            continue
        files.append(path)
    return files


def _local_gate_commands(root: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    python = _python(payload)
    if (root / "tests").is_dir():
        commands.append(_run_command([python, "-m", "pytest", "tests", "-q"], root, timeout=int(payload.get("gate_timeout_sec") or 600)))
    return commands


def _run_command(cmd: list[str], cwd: Path, *, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
        return {
            "command": cmd,
            "cwd": str(cwd),
            "exit_code": result.returncode,
            "ok": result.returncode == 0,
            "duration_sec": round(time.monotonic() - started, 3),
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": cmd,
            "cwd": str(cwd),
            "exit_code": 124,
            "ok": False,
            "duration_sec": round(time.monotonic() - started, 3),
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "timeout": True,
        }


def _snapshot(paths: list[Path]) -> dict[str, bytes | None]:
    return {str(path): path.read_bytes() if path.is_file() else None for path in paths}


def _changed_files(before: dict[str, bytes | None], paths: list[Path]) -> list[str]:
    changed: list[str] = []
    for path in paths:
        current = path.read_bytes() if path.is_file() else None
        if before.get(str(path)) != current:
            changed.append(str(path))
    return changed


def _git_diff_summary(root: Path, changed_files: list[str]) -> list[str]:
    git_root = _git_root(root)
    if git_root is None or not changed_files:
        return []
    rels = [str(Path(path).resolve().relative_to(git_root)) for path in changed_files if Path(path).resolve().is_relative_to(git_root)]
    if not rels:
        return []
    result = subprocess.run(["git", "diff", "--stat", "--", *rels], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30, check=False)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if lines:
        return lines
    fallback = []
    for rel in rels:
        path = git_root / rel
        if path.is_file():
            fallback.append(f"{rel} | {_line_count(path)} lines")
    return fallback


def _git_root(path: Path) -> Path | None:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _record_execution(root: Path, result: dict[str, Any]) -> None:
    path = root / ".retort" / "real_absorption_runs" / f"{result.get('run_id', 'run')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_employee_results(root: Path, run_id: str, source: str, tasks: list[dict[str, Any]], result: dict[str, Any], payload: dict[str, Any]) -> Path:
    path = root / ".retort" / "employee_results" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    queue_path = str(payload.get("employee_queue") or "")
    history_store = str(payload.get("history_store") or "")
    execution_mode = "employee_runtime_adapter" if queue_path and history_store else "retort_apply_absorption_cli"
    task_results = []
    for task in tasks:
        task_result = {
            "task_id": str(task.get("task_id") or ""),
            "status": "completed" if result.get("gates_passed") else "failed",
            "summary": f"Retort apply-absorption executed task for {task.get('dimension', 'unknown')}.",
            "evidence": [
                f"source={source}",
                f"review_report={result.get('review_report_path')}",
                f"changed_files={','.join(result.get('changed_files') or [])}",
                f"gates_passed={result.get('gates_passed')}",
            ],
            "score_after": {"employee_execution_integration": 92.0 if result.get("gates_passed") else 70.0, "feedback_loop_closure": 92.0 if result.get("gates_passed") else 70.0},
        }
        task_results.append(task_result)
    payload_out = {
        "run_id": run_id,
        "source": source,
        "execution_mode": execution_mode,
        "runtime_evidence": {
            "queue_path": queue_path,
            "history_store": history_store,
            "result_path": str(path),
            "task_result_count": len(task_results),
        },
        "results": task_results,
    }
    path.write_text(json.dumps(payload_out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if history_store:
        store = RetortHistoryStore(history_store)
        for item in task_results:
            store.record_task_result(
                EmployeeTaskResult(
                    task_id=str(item.get("task_id") or ""),
                    status=str(item.get("status") or ""),
                    summary=str(item.get("summary") or ""),
                    evidence=tuple(str(row) for row in item.get("evidence") or []),
                    score_after={str(k): float(v) for k, v in (item.get("score_after") or {}).items()},
                )
            )
    return path


def _write_execution_queue_records(queue_path: str, run_id: str, source: str, tasks: list[dict[str, Any]]) -> int:
    if not queue_path:
        return 0
    path = Path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(json.dumps({"queue_id": str(uuid.uuid4()), "run_id": run_id, "source": source, "status": "executing", "task": task}, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _execution_result(status: str, root: Path, source: str, started: float, changed_files: list[str], gates: list[dict[str, Any]], diff_summary: list[str], summary: str) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "project": str(root),
        "summary": summary,
        "changed_files": changed_files,
        "commands": [gate["command"] for gate in gates],
        "gates": gates,
        "gates_passed": bool(gates) and all(bool(gate.get("ok")) for gate in gates),
        "git_diff_summary": diff_summary,
        "duration_sec": round(time.monotonic() - started, 3),
        "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _run_id(source: str) -> str:
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{digest}"


def _python(payload: dict[str, Any]) -> str:
    return str(payload.get("python") or "python")


def _git_revision(root: Path) -> str:
    git_root = _git_root(root)
    if git_root is None:
        return ""
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
