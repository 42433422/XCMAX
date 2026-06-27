from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retort_engine.models import ProjectAssessment

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".ruff_cache", ".pytest_cache", "playwright-report"}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".kt", ".swift", ".java", ".html", ".css"}


@dataclass(frozen=True)
class ProjectSignals:
    project_path: Path
    source_files: int
    python_package_files: int
    test_files: int
    test_functions: int
    has_readme: bool
    has_makefile: bool
    has_pyproject: bool
    has_package_json: bool
    has_repo_github_actions: bool
    has_project_github_actions: bool
    has_retort_ci_reference: bool
    has_console_script: bool
    has_cli_module: bool
    has_models_module: bool
    has_self_evolution_module: bool
    has_prompts_module: bool
    has_protocol_doc: bool
    has_to_dict_contracts: bool
    has_repeated_score_blocker: bool
    has_task_backlog_improver: bool
    retort_features: dict[str, bool]
    git_dirty: bool | None
    git_tracking_state: str
    allow_dirty: bool
    context_policy: str
    gate_results: dict[str, bool]
    gate_sources: dict[str, str]
    ignored_context_keys: tuple[str, ...]


class EvidenceProjectEvaluator:
    def evaluate(self, state: dict[str, Any]) -> ProjectAssessment:
        project_path = Path(state.get("project_path") or ".").resolve()
        signals = collect_project_signals(project_path, state)
        return ProjectAssessment(
            str(project_path),
            (),
            "Evidence snapshot only. Retort scores must come from the PaiBi LLM prompt.",
            tuple(_strengths(signals)),
            ("llm_deep_review_required",),
            ("Run a completed PaiBi LLM deep review to obtain scores.",),
            tuple(_evidence(signals)),
            {
                "evaluator": "evidence_only",
                "score_authority": "paibi_llm_prompt_only",
                "local_scores_removed": True,
                "signals": {
                    "source_files": signals.source_files,
                    "python_package_files": signals.python_package_files,
                    "test_files": signals.test_files,
                    "test_functions": signals.test_functions,
                    "git_dirty": signals.git_dirty,
                    "git_tracking_state": signals.git_tracking_state,
                    "allow_dirty": signals.allow_dirty,
                    "has_project_github_actions": signals.has_project_github_actions,
                    "has_retort_ci_reference": signals.has_retort_ci_reference,
                    "context_policy": signals.context_policy,
                    "gate_results": signals.gate_results,
                    "gate_sources": signals.gate_sources,
                    "ignored_context_keys": list(signals.ignored_context_keys),
                    "retort_engine_detected": bool(signals.retort_features),
                    "retort_features": dict(signals.retort_features),
                },
            },
        )


def collect_project_signals(project_path: Path, state: dict[str, Any]) -> ProjectSignals:
    source_files = python_package_files = test_files = test_functions = 0
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            path = Path(root) / filename
            suffix = path.suffix.lower()
            if suffix in SOURCE_SUFFIXES:
                source_files += 1
            if suffix == ".py" and not filename.startswith("test_"):
                python_package_files += 1
            if filename.startswith("test_") and suffix == ".py":
                test_files += 1
                test_functions += len(re.findall(r"^\s*(?:async\s+def|def)\s+test_", _read_text(path), re.M))
    context_policy = _context_policy(state)
    gate_results: dict[str, bool] = {}
    gate_sources: dict[str, str] = {}
    if context_policy == "provided":
        gate_results = _gate_results_from_state(state)
        gate_sources = {name: "provided_context" for name in gate_results}
    if _bool_state(state, "run_local_gates"):
        local_results, local_sources = _run_local_gates(project_path)
        gate_results.update(local_results)
        gate_sources.update(local_sources)
    pyproject_text = _read_text(project_path / "pyproject.toml")
    repo_root = _git_root(project_path)
    has_absorption = _has_file_named(project_path, "absorption.py")
    has_sources = _has_file_named(project_path, "sources.py")
    return ProjectSignals(
        project_path,
        source_files,
        python_package_files,
        test_files,
        test_functions,
        (project_path / "README.md").is_file(),
        (project_path / "Makefile").is_file(),
        (project_path / "pyproject.toml").is_file(),
        (project_path / "package.json").is_file(),
        _has_workflow_dir(project_path, repo_root),
        (project_path / ".github" / "workflows").is_dir(),
        _has_retort_ci_reference(repo_root),
        "[project.scripts]" in pyproject_text,
        _has_file_named(project_path, "cli.py"),
        _has_file_named(project_path, "models.py"),
        _has_file_named(project_path, "self_evolution.py"),
        _has_file_named(project_path, "prompts.py"),
        (project_path / "docs" / "evolution_protocol.md").is_file(),
        _contains(project_path, "def to_dict"),
        _contains(project_path, "scores_repeated_without_convergence"),
        _contains(project_path, "TaskBacklogImprover"),
        _retort_feature_flags(project_path) if has_absorption or has_sources else {},
        _git_dirty(project_path),
        _git_tracking_state(project_path),
        context_policy == "provided" and _bool_state(state, "allow_dirty"),
        context_policy,
        gate_results,
        gate_sources,
        _ignored_context_keys(state, context_policy),
    )


def _strengths(signals: ProjectSignals) -> list[str]:
    strengths = []
    if signals.source_files:
        strengths.append(f"{signals.source_files} source files detected")
    if signals.test_files:
        strengths.append(f"{signals.test_files} Python test files detected")
    if signals.has_console_script:
        strengths.append("console script entrypoint exists")
    for label in ("blackhole_ui", "branch_workflow", "employee_runtime_adapter", "license_gate"):
        if signals.retort_features.get(label):
            strengths.append(label)
    return strengths


def _evidence(signals: ProjectSignals) -> list[str]:
    evidence = [
        f"project_path={signals.project_path}",
        f"source_files={signals.source_files}",
        f"python_package_files={signals.python_package_files}",
        f"test_files={signals.test_files}",
        f"test_functions={signals.test_functions}",
        f"has_readme={signals.has_readme}",
        f"has_makefile={signals.has_makefile}",
        f"has_pyproject={signals.has_pyproject}",
        f"has_console_script={signals.has_console_script}",
        f"has_cli_module={signals.has_cli_module}",
        f"has_models_module={signals.has_models_module}",
        f"has_self_evolution_module={signals.has_self_evolution_module}",
        f"has_protocol_doc={signals.has_protocol_doc}",
        f"git_dirty={signals.git_dirty}",
        f"git_tracking_state={signals.git_tracking_state}",
        f"allow_dirty={signals.allow_dirty}",
        f"has_project_github_actions={signals.has_project_github_actions}",
        f"has_retort_ci_reference={signals.has_retort_ci_reference}",
        f"context_policy={signals.context_policy}",
    ]
    for name, passed in sorted(signals.gate_results.items()):
        evidence.append(f"gate:{name}={passed} source={signals.gate_sources.get(name, 'unknown')}")
    for key in signals.ignored_context_keys:
        evidence.append(f"ignored_context={key}")
    for key, value in sorted(signals.retort_features.items()):
        evidence.append(f"retort_feature:{key}={value}")
    return evidence


def _retort_feature_flags(project_path: Path) -> dict[str, bool]:
    text = _all_project_text(project_path, include_tests=False, exclude_filenames={"evaluators.py"}, include_docs=False)
    all_code_text = _all_project_text(project_path, include_tests=True, exclude_filenames={"evaluators.py"}, include_docs=False)
    frontend_text = _all_project_text(project_path / "retort_engine" / "frontend", include_tests=True, include_docs=True)
    return {
        "absorption_module": _has_file_named(project_path, "absorption.py"),
        "sources_module": _has_file_named(project_path, "sources.py"),
        "absorb_cli": 'add_parser("absorb"' in text,
        "record_result_cli": "record-result" in text,
        "github_ingestion": "parse_github_url" in text and "clone_or_update" in text,
        "local_external_ingestion": "external_path" in text and "local_path" in text,
        "absorption_result_model": "class AbsorptionResult" in text,
        "absorption_tests": _has_file_named(project_path, "test_absorption.py"),
        "license_tests": _has_file_named(project_path, "test_runtime_integrations.py"),
        "branch_tests": _has_file_named(project_path, "test_branching.py"),
        "employee_owner_hints": "owner_hint" in text,
        "employee_queue_integration": "enqueue_employee_task" in text or "RetortEmployeeRuntimeAdapter" in text,
        "execution_feedback_ingest": "feedback_ingest" in text or "task_result" in text or "employee_result" in text,
        "history_store": "RetortHistoryStore" in text or "retort_history" in text,
        "license_warning": "license-incompatible" in text or "license_gate" in text,
        "license_gate": "def license_gate" in text and "DEFAULT_ALLOWED_LICENSES" in text,
        "semantic_reviewer": "semantic_compare" in text and "ast.parse" in text,
        "json_output": "--json" in text,
        "report_output": "--output" in text or "write_text" in text,
        "real_github_absorption_case": bool(re.search(r"run_absorption\([\s\S]{0,800}?github_url\s*=\s*['\"]https://github\.com/(?!owner/repo)", all_code_text)),
        "employee_runtime_adapter": any(marker in text for marker in ("employee_runtime", "agent_loop", "workflow_scheduler", "RetortEmployeeRuntimeAdapter")),
        "product_surface": any(marker in text for marker in ("FastAPI", "APIRouter", "uvicorn", "RetortService", "RetortUIServer")),
        "blackhole_ui": "blackhole" in frontend_text.lower() and "accretion" in frontend_text.lower() and "canvas" in frontend_text.lower(),
        "folder_project_picker": "ownProjectFolder" in frontend_text and "externalProjectFolder" in frontend_text,
        "branch_workflow": "begin_absorption_branch" in text and "branch_workflow" in text,
        "merge_after_absorption": "merge_absorption_branch" in text and "merge_after" in text,
    }


def _gate_results_from_state(state: dict[str, Any]) -> dict[str, bool]:
    raw = state.get("gate_results") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) if isinstance(v, bool) else str(v).lower() in {"pass", "passed", "ok", "true", "1"} for k, v in raw.items()}


def _run_local_gates(project_path: Path) -> tuple[dict[str, bool], dict[str, str]]:
    results: dict[str, bool] = {}
    sources: dict[str, str] = {}
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_path) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    for name, cmd in (("lint", [sys.executable, "-m", "ruff", "check", "."]), ("test", [sys.executable, "-m", "pytest", "tests", "-q"])):
        if name == "test" and not (project_path / "tests").is_dir():
            continue
        if name == "lint" and not _has_python_files(project_path):
            continue
        passed, source = _run_gate(project_path, cmd, env)
        if source != "local:unavailable":
            results[name] = passed
            sources[name] = source
    return results, sources


def _run_gate(project_path: Path, cmd: list[str], env: dict[str, str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, cwd=project_path, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return False, "local:timeout"
    except OSError:
        return False, "local:unavailable"
    output = result.stdout + "\n" + result.stderr
    if "No module named" in output and ("ruff" in output or "pytest" in output):
        return False, "local:unavailable"
    return result.returncode == 0, f"local:exit={result.returncode}"


def _context_policy(state: dict[str, Any]) -> str:
    raw = str(state.get("context_policy") or "isolated").strip().lower()
    return "provided" if raw in {"provided", "use_context", "context"} else "isolated"


def _ignored_context_keys(state: dict[str, Any], context_policy: str) -> tuple[str, ...]:
    if context_policy == "provided":
        return ()
    return tuple(key for key in ("prompt", "gate_results", "allow_dirty") if state.get(key) not in (None, "", {}, [], False))


def _bool_state(state: dict[str, Any], key: str) -> bool:
    value = state.get(key)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "passed", "pass", "ok"}
    return bool(value)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _contains(project_path: Path, needle: str) -> bool:
    return needle in _all_project_text(project_path, include_tests=True, include_docs=True)


def _all_project_text(project_path: Path, *, include_tests: bool, exclude_filenames: set[str] | None = None, include_docs: bool = True) -> str:
    exclude_filenames = exclude_filenames or set()
    chunks: list[str] = []
    suffixes = SOURCE_SUFFIXES | {".md", ".toml", ".yml", ".yaml", ".json"}
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        parts = set(Path(root).parts)
        if not include_tests and "tests" in parts:
            continue
        if not include_docs and ("docs" in parts or "frontend" in parts):
            continue
        for filename in files:
            if filename in exclude_filenames:
                continue
            path = Path(root) / filename
            if path.suffix.lower() in suffixes:
                chunks.append(_read_text(path)[:20000])
    return "\n".join(chunks)


def _has_file_named(project_path: Path, name: str) -> bool:
    return any(path.name == name for path in project_path.rglob("*") if path.is_file() and not any(part in SKIP_DIRS for part in path.parts))


def _has_python_files(project_path: Path) -> bool:
    return any(path.suffix == ".py" for path in project_path.rglob("*.py") if not any(part in SKIP_DIRS for part in path.parts))


def _has_workflow_dir(project_path: Path, repo_root: Path | None) -> bool:
    return (project_path / ".github" / "workflows").is_dir() or bool(repo_root and (repo_root / ".github" / "workflows").is_dir())


def _has_retort_ci_reference(repo_root: Path | None) -> bool:
    if repo_root is None:
        return False
    workflow_dir = repo_root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return False
    return any("packages/retort_engine" in _read_text(path) or "retort_engine" in _read_text(path) for path in workflow_dir.glob("*.yml"))


def _git_root(project_path: Path) -> Path | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=project_path, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _git_dirty(project_path: Path) -> bool | None:
    root = _git_root(project_path)
    if root is None:
        return None
    try:
        result = subprocess.run(["git", "status", "--short", "--", str(project_path)], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bool(result.stdout.strip())


def _git_tracking_state(project_path: Path) -> str:
    root = _git_root(project_path)
    if root is None:
        return "no_git"
    rel = "."
    try:
        rel = str(project_path.resolve().relative_to(root.resolve()))
    except ValueError:
        pass
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=root, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False).returncode == 0
        status = subprocess.run(["git", "status", "--short", "--", rel], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if not tracked and status:
        return "untracked"
    if status:
        return "tracked_dirty"
    return "tracked_clean"
