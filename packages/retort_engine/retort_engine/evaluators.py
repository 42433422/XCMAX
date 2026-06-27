from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retort_engine.models import ProjectAssessment, Score

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


class StaticProjectEvaluator:
    def evaluate(self, state: dict[str, Any]) -> ProjectAssessment:
        project_path = Path(state.get("project_path") or ".").resolve()
        signals = collect_project_signals(project_path, state)
        scores = _score_project(signals)
        weak = tuple(f"{s.dimension}: {s.value:.1f} - {s.reason}" for s in scores if s.value <= 90)
        recs = tuple(f"Raise {s.dimension} from {s.value:.1f} to >90 with a verified task." for s in scores if s.value <= 90)
        return ProjectAssessment(str(project_path), scores, "Retort static assessment. Default mode is isolated: no chat context is used.", tuple(_strengths(signals)), weak, recs, tuple(_evidence(signals)), {"evaluator": "static", "strict_stop_rule": "every score must be > 90", "signals": {"source_files": signals.source_files, "python_package_files": signals.python_package_files, "test_files": signals.test_files, "test_functions": signals.test_functions, "git_dirty": signals.git_dirty, "git_tracking_state": signals.git_tracking_state, "allow_dirty": signals.allow_dirty, "has_project_github_actions": signals.has_project_github_actions, "has_retort_ci_reference": signals.has_retort_ci_reference, "context_policy": signals.context_policy, "gate_results": signals.gate_results, "gate_sources": signals.gate_sources, "ignored_context_keys": list(signals.ignored_context_keys), "retort_engine_detected": _is_retort_engine_project(signals), "retort_features": dict(signals.retort_features)}})


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
    return ProjectSignals(project_path, source_files, python_package_files, test_files, test_functions, (project_path / "README.md").is_file(), (project_path / "Makefile").is_file(), (project_path / "pyproject.toml").is_file(), (project_path / "package.json").is_file(), _has_workflow_dir(project_path, repo_root), (project_path / ".github" / "workflows").is_dir(), _has_retort_ci_reference(repo_root), "[project.scripts]" in pyproject_text, _has_file_named(project_path, "cli.py"), _has_file_named(project_path, "models.py"), _has_file_named(project_path, "self_evolution.py"), _has_file_named(project_path, "prompts.py"), (project_path / "docs" / "evolution_protocol.md").is_file(), _contains(project_path, "def to_dict"), _contains(project_path, "scores_repeated_without_convergence"), _contains(project_path, "TaskBacklogImprover"), _retort_feature_flags(project_path) if has_absorption or has_sources else {}, _git_dirty(project_path), _git_tracking_state(project_path), context_policy == "provided" and _bool_state(state, "allow_dirty"), context_policy, gate_results, gate_sources, _ignored_context_keys(state, context_policy))


def _score_project(signals: ProjectSignals) -> tuple[Score, ...]:
    product = 45 + min(12, signals.source_files * 1.5) + 10 * signals.has_readme + 10 * (signals.has_pyproject or signals.has_package_json) + 12 * signals.has_console_script + 8 * signals.has_cli_module + 6 * signals.has_protocol_doc
    architecture = 50 + min(12, signals.python_package_files * 2) + 9 * signals.has_models_module + 9 * signals.has_self_evolution_module + 8 * (signals.python_package_files >= 5) + 8 * signals.has_to_dict_contracts + 6 * signals.has_prompts_module
    tests = 30 + min(28, signals.test_functions * 4) + 6 * bool(signals.test_files) + 25 * (signals.gate_results.get("test") is True) - 18 * (signals.gate_results.get("test") is False) + 10 * (signals.gate_results.get("lint") is True)
    contract = 55 + 6 * (signals.has_pyproject or signals.has_package_json) + 10 * signals.has_console_script + 8 * signals.has_cli_module + 10 * signals.has_to_dict_contracts + 8 * signals.has_protocol_doc + 5 * (signals.test_functions >= 4)
    operations = 55 + 12 * signals.has_makefile + 12 * signals.has_repo_github_actions + 8 * (signals.gate_results.get("lint") is True) + 8 * (signals.gate_results.get("test") is True) + 5 * signals.has_console_script - 8 * bool(signals.git_dirty and not signals.allow_dirty)
    evolution = 50 + 15 * signals.has_self_evolution_module + 10 * signals.has_prompts_module + 10 * signals.has_task_backlog_improver + 8 * signals.has_repeated_score_blocker + min(10, signals.test_functions * 1.5) + 5 * signals.has_protocol_doc + 8 * signals.has_makefile - 6 * bool(signals.git_dirty and not signals.allow_dirty)
    base = (_score("product_level", product, signals), _score("architecture_depth", architecture, signals), _score("test_gate_evidence", tests, signals), _score("api_contract_quality", contract, signals), _score("operational_readiness", operations, signals), _score("evolution_readiness", evolution, signals))
    if not _is_retort_engine_project(signals):
        return base
    retort = _score_retort_engine(signals)
    readiness = _retort_readiness(retort)
    maturity = _retort_product_maturity(signals)
    retort_values = {s.dimension: s.value for s in retort}
    capped = []
    for score in base:
        value = score.value
        reason = score.reason
        if score.dimension == "product_level":
            value = min(value, readiness, maturity)
            reason = "Retort product-level score is capped by external-evolution and product-maturity evidence." if value <= 90 else reason
        elif score.dimension == "evolution_readiness":
            value = min(value, retort_values["feedback_loop_closure"])
        elif score.dimension == "operational_readiness":
            value = min(value, retort_values["product_operability"])
        capped.append(Score(score.dimension, round(value, 1), reason, score.evidence))
    return tuple(capped) + retort + (_score("retort_product_maturity", maturity, signals),)


def _score_retort_engine(signals: ProjectSignals) -> tuple[Score, ...]:
    f = signals.retort_features
    scores = {
        "external_ingestion": 45 + 12 * f.get("sources_module", False) + 12 * f.get("github_ingestion", False) + 10 * f.get("local_external_ingestion", False) + 8 * f.get("absorption_tests", False) + 4 * f.get("report_output", False),
        "comparative_analysis_depth": 35 + 12 * f.get("score_delta_model", False) + 10 * f.get("absorption_result_model", False) + 8 * f.get("absorption_module", False) + 8 * f.get("report_output", False) + 20 * f.get("semantic_reviewer", False),
        "absorption_tasking": 45 + 12 * f.get("employee_owner_hints", False) + 10 * f.get("absorption_module", False) + 8 * f.get("absorption_tests", False) + 8 * f.get("json_output", False) + 8 * f.get("employee_queue_integration", False) + 5 * f.get("report_output", False),
        "employee_execution_integration": 20 + 16 * f.get("employee_owner_hints", False) + 28 * f.get("employee_queue_integration", False) + 16 * f.get("history_store", False) + 10 * f.get("record_result_cli", False) + 7 * f.get("employee_runtime_adapter", False),
        "feedback_loop_closure": 30 + 12 * signals.has_self_evolution_module + 8 * signals.has_repeated_score_blocker + 21 * f.get("execution_feedback_ingest", False) + 12 * f.get("history_store", False) + 8 * f.get("record_result_cli", False),
        "product_operability": 30 + 8 * f.get("absorb_cli", False) + 6 * f.get("json_output", False) + 6 * f.get("report_output", False) + 6 * signals.has_makefile + 6 * signals.has_protocol_doc + 7 * f.get("history_store", False) + 6 * f.get("record_result_cli", False) + 10 * f.get("blackhole_ui", False) + 7 * f.get("product_surface", False) + 5 * f.get("branch_workflow", False),
        "safety_license_gate": 28 + 10 * (signals.context_policy == "isolated") + 8 * f.get("license_warning", False) + 30 * f.get("license_gate", False) + 6 * signals.has_protocol_doc + 10 * f.get("license_tests", False),
        "branch_absorption_workflow": 40 + 18 * f.get("branch_workflow", False) + 12 * f.get("merge_after_absorption", False) + 10 * f.get("folder_project_picker", False) + 8 * f.get("branch_tests", False) + 6 * f.get("blackhole_ui", False),
    }
    return tuple(_score(dim, val, signals) for dim, val in scores.items())


def _retort_product_maturity(signals: ProjectSignals) -> float:
    f = signals.retort_features
    value = 42.0 + 6 * (signals.gate_results.get("lint") is True) + 6 * (signals.gate_results.get("test") is True) + 5 * (f.get("absorb_cli", False) and f.get("record_result_cli", False)) + 5 * (f.get("employee_queue_integration", False) and f.get("history_store", False)) + 5 * (f.get("license_gate", False) and f.get("semantic_reviewer", False)) + 4 * (f.get("absorption_tests", False) and f.get("license_tests", False)) + 4 * f.get("real_github_absorption_case", False) + 5 * f.get("employee_runtime_adapter", False) + 5 * f.get("product_surface", False) + 6 * f.get("blackhole_ui", False) + 5 * f.get("branch_workflow", False) + 3 * (signals.has_project_github_actions or signals.has_retort_ci_reference) + 1 * (signals.git_tracking_state != "untracked") - 2 * (signals.git_tracking_state == "untracked") - 1 * bool(signals.git_dirty and not signals.allow_dirty and signals.git_tracking_state != "untracked")
    return round(min(value, 94.0), 1)


def _retort_readiness(scores: tuple[Score, ...]) -> float:
    weights = {"external_ingestion": 0.12, "comparative_analysis_depth": 0.13, "absorption_tasking": 0.13, "employee_execution_integration": 0.16, "feedback_loop_closure": 0.14, "product_operability": 0.12, "safety_license_gate": 0.08, "branch_absorption_workflow": 0.12}
    return round(sum(score.value * weights.get(score.dimension, 0) for score in scores), 1)


def _score(dimension: str, value: float, signals: ProjectSignals) -> Score:
    clamped = max(0.0, min(100.0, round(float(value), 1)))
    return Score(dimension, clamped, _reason_for(dimension, clamped, signals), tuple(_evidence(signals)))


def _reason_for(dimension: str, value: float, signals: ProjectSignals) -> str:
    if value > 90:
        return "Current static evidence is above the Retort stop gate."
    if _is_retort_engine_project(signals) and dimension in {"product_level", "retort_product_maturity"}:
        return "Retort core mechanisms exist, but product maturity is capped by missing field evidence: " + ", ".join(_retort_maturity_gaps(signals)[:6])
    if dimension == "operational_readiness" and signals.git_dirty and not signals.allow_dirty:
        return "The target project has uncommitted changes, so release readiness is limited."
    return "Static evidence is not strong enough to pass the strict >90 Retort gate."


def _retort_feature_flags(project_path: Path) -> dict[str, bool]:
    text = _all_project_text(project_path, include_tests=False, exclude_filenames={"evaluators.py"}, include_docs=False)
    all_code_text = _all_project_text(project_path, include_tests=True, exclude_filenames={"evaluators.py"}, include_docs=False)
    frontend_text = _all_project_text(project_path / "retort_engine" / "frontend", include_tests=True, include_docs=True)
    return {"absorption_module": _has_file_named(project_path, "absorption.py"), "sources_module": _has_file_named(project_path, "sources.py"), "absorb_cli": 'add_parser("absorb"' in text, "record_result_cli": "record-result" in text, "github_ingestion": "parse_github_url" in text and "clone_or_update" in text, "local_external_ingestion": "external_path" in text and "local_path" in text, "score_delta_model": "class ScoreDelta" in text, "absorption_result_model": "class AbsorptionResult" in text, "absorption_tests": _has_file_named(project_path, "test_absorption.py"), "license_tests": _has_file_named(project_path, "test_runtime_integrations.py"), "branch_tests": _has_file_named(project_path, "test_branching.py"), "employee_owner_hints": "owner_hint" in text, "employee_queue_integration": "enqueue_employee_task" in text or "RetortEmployeeRuntimeAdapter" in text, "execution_feedback_ingest": "feedback_ingest" in text or "task_result" in text or "employee_result" in text, "history_store": "RetortHistoryStore" in text or "retort_history" in text, "license_warning": "license-incompatible" in text or "license_gate" in text, "license_gate": "def license_gate" in text and "DEFAULT_ALLOWED_LICENSES" in text, "semantic_reviewer": "semantic_compare" in text and "ast.parse" in text, "json_output": "--json" in text, "report_output": "--output" in text or "write_text" in text, "real_github_absorption_case": bool(re.search(r"run_absorption\([\s\S]{0,800}?github_url\s*=\s*['\"]https://github\.com/(?!owner/repo)", all_code_text)), "employee_runtime_adapter": any(marker in text for marker in ("employee_runtime", "agent_loop", "workflow_scheduler", "RetortEmployeeRuntimeAdapter")), "product_surface": any(marker in text for marker in ("FastAPI", "APIRouter", "uvicorn", "RetortService", "RetortUIServer")), "blackhole_ui": "blackhole" in frontend_text.lower() and "accretion" in frontend_text.lower() and "canvas" in frontend_text.lower(), "folder_project_picker": "ownProjectFolder" in frontend_text and "externalProjectFolder" in frontend_text, "branch_workflow": "begin_absorption_branch" in text and "branch_workflow" in text, "merge_after_absorption": "merge_absorption_branch" in text and "merge_after" in text}


def _is_retort_engine_project(signals: ProjectSignals) -> bool:
    return bool(signals.retort_features)


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
    evidence = [f"project_path={signals.project_path}", f"source_files={signals.source_files}", f"python_package_files={signals.python_package_files}", f"test_files={signals.test_files}", f"test_functions={signals.test_functions}", f"has_readme={signals.has_readme}", f"has_makefile={signals.has_makefile}", f"has_pyproject={signals.has_pyproject}", f"has_console_script={signals.has_console_script}", f"has_cli_module={signals.has_cli_module}", f"has_models_module={signals.has_models_module}", f"has_self_evolution_module={signals.has_self_evolution_module}", f"has_protocol_doc={signals.has_protocol_doc}", f"git_dirty={signals.git_dirty}", f"git_tracking_state={signals.git_tracking_state}", f"allow_dirty={signals.allow_dirty}", f"has_project_github_actions={signals.has_project_github_actions}", f"has_retort_ci_reference={signals.has_retort_ci_reference}", f"context_policy={signals.context_policy}"]
    for name, passed in sorted(signals.gate_results.items()):
        evidence.append(f"gate:{name}={passed} source={signals.gate_sources.get(name, 'unknown')}")
    for key in signals.ignored_context_keys:
        evidence.append(f"ignored_context={key}")
    for gap in _retort_maturity_gaps(signals):
        evidence.append(f"retort_maturity_gap={gap}")
    return evidence


def _retort_maturity_gaps(signals: ProjectSignals) -> list[str]:
    if not _is_retort_engine_project(signals):
        return []
    f = signals.retort_features
    gaps = []
    for key, label in (("real_github_absorption_case", "no real GitHub absorption case"), ("employee_runtime_adapter", "no existing employee runtime adapter"), ("product_surface", "no UI or service API surface"), ("blackhole_ui", "no blackhole UI"), ("branch_workflow", "no branch absorption workflow")):
        if not f.get(key):
            gaps.append(label)
    if not (signals.has_project_github_actions or signals.has_retort_ci_reference):
        gaps.append("no Retort-specific CI evidence")
    if signals.git_tracking_state == "untracked":
        gaps.append("project directory is untracked")
    return gaps


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
    return value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes", "y", "on", "ok"}


def _git_dirty(project_path: Path) -> bool | None:
    root = _git_root(project_path)
    cwd = root or project_path
    rel = "."
    if root:
        try:
            rel = str(project_path.relative_to(root))
        except ValueError:
            rel = "."
    try:
        result = subprocess.run(["git", "status", "--short", "--", rel], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if result.returncode else bool(result.stdout.strip())


def _git_tracking_state(project_path: Path) -> str:
    root = _git_root(project_path)
    if root is None:
        return "outside_git"
    try:
        rel = str(project_path.relative_to(root))
    except ValueError:
        rel = "."
    try:
        result = subprocess.run(["git", "status", "--short", "--", rel], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if any(line.startswith("??") for line in lines):
        return "untracked"
    return "dirty" if lines else "tracked_clean"


def _git_root(project_path: Path) -> Path | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=project_path, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _has_workflow_dir(project_path: Path, repo_root: Path | None) -> bool:
    candidates = [project_path]
    if repo_root is not None and repo_root != project_path:
        candidates.append(repo_root)
    return any((candidate / ".github" / "workflows").is_dir() for candidate in candidates)


def _has_retort_ci_reference(repo_root: Path | None) -> bool:
    workflow_dir = repo_root / ".github" / "workflows" if repo_root else Path("__missing__")
    return workflow_dir.is_dir() and any("retort_engine" in _read_text(path) for path in workflow_dir.glob("*") if path.suffix.lower() in {".yml", ".yaml"})


def _has_file_named(project_path: Path, filename: str) -> bool:
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if filename in files:
            return True
    return False


def _contains(project_path: Path, pattern: str) -> bool:
    return pattern in _all_project_text(project_path)


def _all_project_text(project_path: Path, *, include_tests: bool = True, exclude_filenames: set[str] | None = None, include_docs: bool = True) -> str:
    chunks: list[str] = []
    excluded = exclude_filenames or set()
    if not project_path.exists():
        return ""
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        root_path = Path(root)
        try:
            rel_parts = root_path.relative_to(project_path).parts
        except ValueError:
            rel_parts = ()
        if not include_tests and "tests" in rel_parts:
            continue
        for filename in files:
            if filename in excluded:
                continue
            path = Path(root) / filename
            text_suffixes = {".py", ".toml", ".json", ".yaml", ".yml", ".html", ".css", ".js"}
            if include_docs:
                text_suffixes.add(".md")
            if path.suffix.lower() in text_suffixes:
                chunks.append(_read_text(path))
    return "\n".join(chunks)


def _has_python_files(project_path: Path) -> bool:
    return any(path.suffix == ".py" for path in project_path.rglob("*.py"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
