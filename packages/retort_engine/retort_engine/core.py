from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from retort_engine.paibi_llm import fetch_paibi_llm_review_status, request_paibi_llm_review


@dataclass(frozen=True)
class Score:
    dimension: str
    value: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "value": self.value, "reason": self.reason}


@dataclass(frozen=True)
class Assessment:
    project: str
    scores: tuple[Score, ...]
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def score_map(self) -> dict[str, float]:
        return {score.dimension: score.value for score in self.scores}

    def all_scores_over(self, threshold: float) -> bool:
        return bool(self.scores) and all(score.value > threshold for score in self.scores)

    def to_dict(self) -> dict[str, Any]:
        return {"project": self.project, "scores": [score.to_dict() for score in self.scores], "evidence": list(self.evidence), "metadata": self.metadata}


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    dimension: str
    owner_hint: str
    priority: str
    why: str

    def to_dict(self) -> dict[str, str]:
        return {"task_id": self.task_id, "title": self.title, "dimension": self.dimension, "owner_hint": self.owner_hint, "priority": self.priority, "why": self.why}


def assess_project(project: str, *, run_local_gates: bool = False, context_policy: str = "isolated") -> Assessment:
    root = Path(project).expanduser().resolve()
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts and ".retort" not in path.parts and "__pycache__" not in path.parts]
    text = "\n".join(_read(path) for path in files if path.suffix.lower() in {".py", ".js", ".html", ".css", ".md", ".toml", ".yml", ".yaml"})
    tests = [path for path in files if path.name.startswith("test_") and path.suffix == ".py"]
    test_functions = sum(len(re.findall(r"^\s*def\s+test_", _read(path), re.M)) for path in tests)
    lint_ok = test_ok = False
    if run_local_gates:
        lint_ok = _run([_python(), "-m", "ruff", "check", "."], root)
        test_ok = _run([_python(), "-m", "pytest", "tests", "-q"], root) if (root / "tests").is_dir() else False
    features = {
        "blackhole_ui": "blackhole" in text.lower() and "accretion" in text.lower() and "canvas" in text.lower(),
        "folder_project_picker": "ownProjectFolder" in text and "externalProjectFolder" in text,
        "github_or_folder_source": "github_url" in text and "external_path" in text,
        "branch_workflow": "begin_absorption_branch" in text and "merge_absorption_branch" in text,
        "employee_queue": "employee_queue" in text and "RetortHistory" in text,
        "license_gate": "license" in text.lower() and "incompatible" in text.lower(),
        "service_api": "RetortService" in text and "RetortUIServer" in text,
        "self_evolution": "RetortSelfEvolutionRunner" in text and "scores_repeated_without_convergence" in text,
        "real_github_case": "https://github.com/openai/codex" in text,
        "conservative_scoring": "calibrated_overall" in text and "not_automatic_100" in text,
    }
    tracked = _tracking_state(root)
    proof = _closed_loop_proof(root)
    capped = _evidence_based_scores(features, lint_ok=lint_ok, test_ok=test_ok, test_functions=test_functions, has_ci=_has_retort_ci(root), tracked=tracked, context_policy=context_policy, proof=proof)
    capped, shock_evidence = _apply_absorption_shock(root, capped)
    evidence = tuple([f"source_files={len(files)}", f"test_functions={test_functions}", f"git_tracking_state={tracked}", f"lint={lint_ok}", f"test={test_ok}", f"closed_loop_verified={proof['verified']}", f"closed_loop_missing={','.join(proof['missing'])}"] + shock_evidence + [f"{k}={v}" for k, v in features.items()])
    metadata = {"features": features, "git_tracking_state": tracked, "absorption_state": _public_absorption_state(root), "closed_loop_proof": proof}
    return Assessment(str(root), tuple(Score(key, round(value, 1), _score_reason(key, proof)) for key, value in capped.items()), evidence, metadata)


class RetortSelfEvolutionRunner:
    def __init__(self, *, threshold: float = 90.0, max_rounds: int | None = 8) -> None:
        self.threshold = threshold
        self.max_rounds = max_rounds

    def run(self, project: str, *, run_local_gates: bool = False) -> dict[str, Any]:
        root = Path(project).expanduser().resolve()
        rounds: list[dict[str, Any]] = []
        all_tasks: list[dict[str, str]] = []
        max_rounds = self.max_rounds or 8
        assessment = assess_project(str(root), run_local_gates=run_local_gates)
        weak = [score for score in assessment.scores if score.value <= self.threshold]
        for round_index in range(1, max_rounds + 1):
            tasks = [_task_for_weak_score(score, self.threshold, round_index) for score in weak]
            all_tasks.extend(tasks)
            rounds.append({"round_index": round_index, "passed": not weak, "assessment": assessment.to_dict(), "tasks": tasks})
            if not weak:
                break
            advanced = _advance_absorption_state(root, [score.dimension for score in weak], round_index, tasks)
            assessment = assess_project(str(root), run_local_gates=run_local_gates)
            weak = [score for score in assessment.scores if score.value <= self.threshold]
            if not advanced:
                break
        blocked_by_proof = bool(weak and _closed_loop_proof(root)["missing"])
        return {
            "status": "converged" if not weak else ("blocked" if blocked_by_proof else "max_rounds"),
            "stop_reason": "all_scores_strictly_above_threshold" if not weak else ("closed_loop_evidence_required_before_scores_can_pass" if blocked_by_proof else "max_rounds_reached_before_all_scores_passed"),
            "final_assessment": assessment.to_dict(),
            "rounds": rounds,
            "tasks": all_tasks,
        }


class RetortHistory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript("CREATE TABLE IF NOT EXISTS absorption_runs(id INTEGER PRIMARY KEY, payload TEXT); CREATE TABLE IF NOT EXISTS employee_tasks(id INTEGER PRIMARY KEY, payload TEXT);")

    def record(self, table: str, payload: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(f"INSERT INTO {table}(payload) VALUES (?)", (json.dumps(payload, ensure_ascii=False),))


def absorb(payload: dict[str, Any]) -> dict[str, Any]:
    own = Path(payload.get("own_project") or payload.get("project") or ".").expanduser().resolve()
    external = payload.get("external_path") or payload.get("github_url") or payload.get("github") or ""
    external_path = _materialize_external_source(str(external), own, bool(payload.get("refresh")))
    branch_state = {"enabled": bool(payload.get("branch_workflow")), "status": "disabled"}
    if payload.get("branch_workflow"):
        try:
            branch_state = begin_absorption_branch(own, str(external), payload.get("absorption_branch") or "", bool(payload.get("allow_dirty_branch"))).to_dict()
        except RuntimeError as exc:
            return {"status": "blocked_by_branch_workflow", "error": str(exc), "branch_workflow": branch_state, "tasks": []}
    pre_assessment = assess_project(str(own), run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
    tasks = _tasks_from_assessment(str(external), external_path)
    absorption_state = _record_absorption_shock(own, str(external), external_path, tasks)
    own_assessment = assess_project(str(own), run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
    llm_review = _maybe_request_llm_review(payload, own, "absorb", str(external), "" if external_path is None else str(external_path), own_assessment.get("scores", []), tasks)
    result = {
        "status": "tasks_generated",
        "summary": f"Generated {len(tasks)} absorption task(s). Score intentionally dropped until Retort self-evolution internalizes the external advantages.",
        "pre_absorption_assessment": pre_assessment,
        "own_assessment": own_assessment,
        "external_ref": {"source": str(external), "local_path": str(external_path)},
        "absorption_state": absorption_state,
        "tasks": tasks,
        "llm_review": llm_review,
        "branch_workflow": branch_state,
    }
    queue = payload.get("employee_queue")
    if queue:
        qpath = Path(queue)
        qpath.parent.mkdir(parents=True, exist_ok=True)
        with qpath.open("a", encoding="utf-8") as handle:
            for task in tasks:
                handle.write(json.dumps({"queue_id": str(uuid.uuid4()), "source": str(external), "task": task}, ensure_ascii=False) + "\n")
    history = payload.get("history_store")
    if history:
        store = RetortHistory(history)
        store.record("absorption_runs", result)
        for task in tasks:
            store.record("employee_tasks", task)
    if payload.get("merge_after") and branch_state.get("enabled") and branch_state.get("created"):
        result["branch_workflow"] = merge_absorption_branch(own, BranchWorkflowState.from_dict(branch_state)).to_dict()
    return result


@dataclass(frozen=True)
class BranchWorkflowState:
    enabled: bool
    project_root: str
    base_branch: str = ""
    absorption_branch: str = ""
    created: bool = False
    merged: bool = False
    status: str = "disabled"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BranchWorkflowState":
        return cls(bool(payload.get("enabled")), str(payload.get("project_root") or ""), str(payload.get("base_branch") or ""), str(payload.get("absorption_branch") or ""), bool(payload.get("created")), bool(payload.get("merged")), str(payload.get("status") or "disabled"))


def begin_absorption_branch(project: Path, source: str, branch_name: str = "", allow_dirty: bool = False) -> BranchWorkflowState:
    root = _git_root(project)
    if root is None:
        raise RuntimeError("Main project folder is not inside a Git repository")
    if not allow_dirty and _git(root, "status", "--short"):
        raise RuntimeError("Main project has uncommitted changes")
    base = _git(root, "branch", "--show-current").strip()
    branch = branch_name or "retort/absorb-" + re.sub(r"[^a-zA-Z0-9]+", "-", source).strip("-").lower()[:40]
    _git(root, "checkout", "-b", branch)
    return BranchWorkflowState(True, str(root), base, branch, True, False, "branch_created")


def merge_absorption_branch(project: Path, state: BranchWorkflowState) -> BranchWorkflowState:
    root = Path(state.project_root or project)
    if _git(root, "status", "--short"):
        raise RuntimeError("Absorption branch has uncommitted changes; commit before merge")
    _git(root, "checkout", state.base_branch)
    _git(root, "merge", "--no-ff", state.absorption_branch, "-m", f"Merge {state.absorption_branch}")
    return BranchWorkflowState(True, str(root), state.base_branch, state.absorption_branch, state.created, True, "merged")


class RetortService:
    def assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        assessment = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        assessment["llm_review"] = _maybe_request_llm_review(payload, Path(project).expanduser().resolve(), "assess", "", "", assessment.get("scores", []), [])
        return assessment

    def absorb(self, payload: dict[str, Any]) -> dict[str, Any]:
        return absorb(payload)

    def self_evolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or ".")
        result = RetortSelfEvolutionRunner(max_rounds=int(payload.get("max_rounds") or 8)).run(project, run_local_gates=bool(payload.get("run_local_gates")))
        result["llm_review"] = _maybe_request_llm_review(payload, Path(project).expanduser().resolve(), "self_evolve", "", "", result.get("final_assessment", {}).get("scores", []), result.get("tasks", []))
        return result

    def record_proof(self, payload: dict[str, Any]) -> dict[str, Any]:
        return record_closed_loop_proof(str(payload.get("project") or "."), payload)

    def llm_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        assessment = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        return request_paibi_llm_review(
            project=project,
            mode=str(payload.get("mode") or "manual"),
            external_source=str(payload.get("external_source") or payload.get("github_url") or ""),
            external_path=str(payload.get("external_path") or ""),
            scores=assessment.get("scores", []),
            tasks=[],
        )

    def llm_review_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        return fetch_paibi_llm_review_status(task_id)


def record_closed_loop_proof(project: str, payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    state = _load_absorption_state(root)
    proof = {
        "branch_diff_verified": bool(payload.get("branch_diff_verified")),
        "employee_execution_verified": bool(payload.get("employee_execution_verified")),
        "post_absorption_tests_passed": bool(payload.get("post_absorption_tests_passed")),
        "merge_verified": bool(payload.get("merge_verified")),
        "external_advantage_reassessed": bool(payload.get("external_advantage_reassessed")),
        "evidence": [str(item) for item in payload.get("evidence") or []],
    }
    state["closed_loop_proof"] = proof
    if all(value for key, value in proof.items() if key != "evidence"):
        state["active"] = False
        state["status"] = "closed_loop_verified"
    else:
        state["active"] = True
        state["status"] = "awaiting_execution_evidence"
    _save_absorption_state(root, state)
    return _public_absorption_state(root)


def _maybe_request_llm_review(payload: dict[str, Any], project: Path, mode: str, external_source: str, external_path: str, scores: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    if not bool(payload.get("use_llm") or payload.get("paibi_llm") or payload.get("llm_review")):
        return {"enabled": False, "provider": "paibi"}
    review = request_paibi_llm_review(project=str(project), mode=mode, external_source=external_source, external_path=external_path, scores=scores, tasks=tasks)
    review["enabled"] = True
    return review


def _evidence_based_scores(features: dict[str, bool], *, lint_ok: bool, test_ok: bool, test_functions: int, has_ci: bool, tracked: str, context_policy: str, proof: dict[str, Any]) -> dict[str, float]:
    verified = bool(proof["verified"])
    scores = {
        "product_level": 72 + 3 * features["blackhole_ui"] + 3 * features["service_api"] + 2 * features["branch_workflow"] + 2 * features["github_or_folder_source"] + 2 * test_ok + 12 * verified,
        "architecture_depth": 78 + 3 * features["branch_workflow"] + 3 * features["self_evolution"] + 2 * features["license_gate"] + 2 * features["employee_queue"] + 2 * test_ok,
        "test_gate_evidence": 70 + min(8, test_functions * 0.4) + 8 * test_ok + 6 * lint_ok + 3 * has_ci,
        "api_contract_quality": 76 + 4 * features["service_api"] + 3 * features["github_or_folder_source"] + 3 * features["branch_workflow"] + 2 * features["folder_project_picker"] + 8 * verified,
        "operational_readiness": 72 + 6 * lint_ok + 6 * test_ok + 4 * has_ci + 2 * features["branch_workflow"] + 8 * verified,
        "evolution_readiness": 68 + 5 * features["self_evolution"] + 4 * features["real_github_case"] + 4 * features["employee_queue"] + 14 * verified,
        "external_ingestion": 70 + 5 * features["github_or_folder_source"] + 4 * features["folder_project_picker"] + 4 * features["real_github_case"] + 10 * verified,
        "comparative_analysis_depth": 68 + 4 * features["real_github_case"] + 4 * features["github_or_folder_source"] + 4 * features["branch_workflow"] + 12 * verified,
        "absorption_tasking": 72 + 5 * features["employee_queue"] + 4 * features["github_or_folder_source"] + 3 * features["branch_workflow"] + 9 * verified,
        "employee_execution_integration": 66 + 6 * features["employee_queue"] + 16 * verified,
        "feedback_loop_closure": 68 + 5 * features["self_evolution"] + 4 * features["employee_queue"] + 15 * verified,
        "product_operability": 74 + 4 * features["blackhole_ui"] + 4 * features["service_api"] + 3 * features["folder_project_picker"] + 3 * features["branch_workflow"] + 8 * verified,
        "safety_license_gate": 76 + 6 * features["license_gate"] + 3 * (context_policy == "isolated") + 6 * verified,
        "branch_absorption_workflow": 74 + 5 * features["branch_workflow"] + 4 * features["folder_project_picker"] + 3 * features["blackhole_ui"] + 8 * verified,
        "retort_product_maturity": 72 + 3 * features["blackhole_ui"] + 3 * features["branch_workflow"] + 2 * features["github_or_folder_source"] + 2 * features["service_api"] + 2 * test_ok + 2 * lint_ok + 12 * verified - 3 * (tracked == "untracked"),
    }
    if not verified:
        caps = {
            "product_level": 84,
            "architecture_depth": 88,
            "api_contract_quality": 88,
            "operational_readiness": 88,
            "evolution_readiness": 82,
            "external_ingestion": 86,
            "comparative_analysis_depth": 82,
            "absorption_tasking": 84,
            "employee_execution_integration": 78,
            "feedback_loop_closure": 82,
            "product_operability": 86,
            "safety_license_gate": 86,
            "branch_absorption_workflow": 86,
            "retort_product_maturity": 84,
        }
        scores = {dimension: min(float(value), float(caps.get(dimension, value))) for dimension, value in scores.items()}
    else:
        scores = {dimension: min(96.0, float(value)) for dimension, value in scores.items()}
    scores["calibrated_overall"] = _calibrated_overall(scores, verified)
    return scores


def _calibrated_overall(scores: dict[str, float], verified: bool) -> float:
    dimensions = [dimension for dimension in scores if dimension != "calibrated_overall"]
    average = sum(scores[dimension] for dimension in dimensions) / max(1, len(dimensions))
    return round(min(94.0 if verified else 82.0, average), 1)


def _score_reason(dimension: str, proof: dict[str, Any]) -> str:
    if proof["verified"]:
        return "Closed-loop proof is present: branch diff, employee execution, post-absorption gates, merge evidence, and external reassessment are recorded."
    if dimension in {"calibrated_overall", "product_level", "retort_product_maturity", "employee_execution_integration", "feedback_loop_closure"}:
        return "Human-calibrated score cap: Retort cannot score above product level until real absorption diff, employee execution, post-absorption tests, merge proof, and external reassessment evidence exist."
    return "Evidence-based Retort score. Feature existence is counted, but unproven closed-loop execution is capped."


def _tasks_from_assessment(source: str, external_path: Path | None = None) -> list[dict[str, str]]:
    profile = _external_project_profile(external_path) if external_path else {}
    tasks = [
        {"task_id": "retort-absorb-depth", "title": "Absorb stronger implementation depth", "dimension": "comparative_analysis_depth", "owner_hint": "fhd-core-maintainer", "priority": "P1", "why": f"Compare implementation patterns from {source}."},
        {"task_id": "retort-absorb-ux", "title": "Absorb better user experience", "dimension": "product_operability", "owner_hint": "market-frontend-dev", "priority": "P1", "why": f"Extract usable UX improvements from {source}."},
        {"task_id": "retort-absorb-ops", "title": "Absorb better operational gates", "dimension": "operational_readiness", "owner_hint": "deploy-release-officer", "priority": "P2", "why": f"Adapt CI and release checks from {source}."},
    ]
    if profile.get("review_pipeline"):
        tasks.append({"task_id": "retort-absorb-review-pipeline", "title": "Adopt deterministic review pipeline stages", "dimension": "comparative_analysis_depth", "owner_hint": "fhd-core-maintainer", "priority": "P1", "why": "External project has explicit review pipeline signals; Retort should turn absorption into staged discovery, localization, reflection, and tasking."})
    if profile.get("file_grouping"):
        tasks.append({"task_id": "retort-absorb-file-grouping", "title": "Add external file grouping before deep comparison", "dimension": "external_ingestion", "owner_hint": "fhd-core-maintainer", "priority": "P1", "why": "External project suggests grouping changed or related files before expensive reasoning, improving depth without broad noisy scans."})
    if profile.get("benchmarking"):
        tasks.append({"task_id": "retort-absorb-benchmarking", "title": "Add absorption quality benchmark counters", "dimension": "feedback_loop_closure", "owner_hint": "test-qa-runner", "priority": "P2", "why": "External project has benchmark or precision/recall signals; Retort should measure whether absorbed tasks actually improve later scores."})
    if profile.get("plugin_surface"):
        tasks.append({"task_id": "retort-absorb-plugin-surface", "title": "Expose Retort absorption through plugin friendly commands", "dimension": "product_operability", "owner_hint": "market-frontend-dev", "priority": "P2", "why": "External project exposes plugin or CLI surfaces; Retort should keep blackhole UI and automation APIs aligned."})
    return tasks


def _task_for_weak_score(score: Score, threshold: float, round_index: int) -> dict[str, str]:
    return {
        "task_id": f"retort-r{round_index:02d}-fix-{score.dimension}",
        "title": f"Raise {score.dimension} above {threshold:.0f}",
        "dimension": score.dimension,
        "owner_hint": "fhd-core-maintainer",
        "priority": "P1" if threshold - score.value >= 5 else "P2",
        "acceptance": f"Reassessment shows {score.dimension} > {threshold:.0f}; current score is {score.value:.1f}.",
    }


def _materialize_external_source(source: str, own_project: Path, refresh: bool = False) -> Path | None:
    if not source:
        return None
    path = Path(source).expanduser()
    if path.is_dir():
        return path.resolve()
    repo = _parse_github_url(source)
    if repo is None:
        return None
    owner, name = repo
    target = own_project / ".retort" / "cache" / "github" / owner / name
    if refresh and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_git_clone(f"https://github.com/{owner}/{name}.git", target)
    return target


def _parse_github_url(source: str) -> tuple[str, str] | None:
    match = re.search(r"github\.com[:/](?P<owner>[^/\s#?]+)/(?P<repo>[^/\s#?]+)", source)
    if not match:
        return None
    return match.group("owner"), match.group("repo").removesuffix(".git")


def _run_git_clone(url: str, target: Path) -> None:
    result = subprocess.run(["git", "clone", "--depth", "1", url, str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def _external_project_profile(path: Path | None) -> dict[str, bool]:
    if path is None or not path.is_dir():
        return {}
    files = [p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and "node_modules" not in p.parts]
    text = "\n".join(_read(p)[:20000] for p in files[:250] if p.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".json", ".toml"})
    lowered = text.lower()
    return {
        "review_pipeline": any(marker in lowered for marker in ("code review", "review pipeline", "reviewer", "reflection", "localization")),
        "file_grouping": any(marker in lowered for marker in ("file group", "group files", "changed files", "diff hunk", "patch set")),
        "benchmarking": any(marker in lowered for marker in ("benchmark", "precision", "recall", "eval", "evaluation")),
        "plugin_surface": any(marker in lowered for marker in ("plugin", "cli", "github action", "codex")),
    }


def _record_absorption_shock(own: Path, source: str, external_path: Path | None, tasks: list[dict[str, str]]) -> dict[str, Any]:
    task_dimensions = {task["dimension"] for task in tasks}
    penalties = {
        "product_level": 4.0,
        "external_ingestion": 6.0,
        "comparative_analysis_depth": 8.0,
        "absorption_tasking": 6.0,
        "feedback_loop_closure": 4.0 if "feedback_loop_closure" in task_dimensions else 2.0,
        "product_operability": 4.0 if "product_operability" in task_dimensions else 2.0,
        "retort_product_maturity": 7.0,
        "calibrated_overall": 8.0,
    }
    state = {
        "active": True,
        "status": "pending_self_evolution",
        "source": source,
        "external_path": "" if external_path is None else str(external_path),
        "pending_dimensions": sorted(penalties),
        "penalties": penalties,
        "tasks": tasks,
    }
    _save_absorption_state(own, state)
    return _public_absorption_state(own)


def _apply_absorption_shock(root: Path, scores: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    state = _load_absorption_state(root)
    if not state.get("active"):
        return scores, ["absorption_shock_active=False"]
    penalties = state.get("penalties") or {}
    adjusted = dict(scores)
    for dimension, penalty in penalties.items():
        if dimension in adjusted:
            adjusted[dimension] = max(0.0, adjusted[dimension] - float(penalty))
    return adjusted, ["absorption_shock_active=True", f"absorption_source={state.get('source', '')}", f"absorption_pending_dimensions={','.join(state.get('pending_dimensions') or [])}"]


def _advance_absorption_state(root: Path, weak_dimensions: list[str], round_index: int, tasks: list[dict[str, str]]) -> bool:
    state = _load_absorption_state(root)
    if not state.get("active"):
        return False
    state["active"] = True
    state["status"] = "awaiting_execution_evidence"
    state["resolved_round"] = round_index
    state["resolved_dimensions"] = sorted(set(weak_dimensions) | set(state.get("pending_dimensions") or []))
    state["self_evolution_tasks"] = tasks
    _save_absorption_state(root, state)
    log_path = root / ".retort" / "self_evolution_actions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"round_index": round_index, "source": state.get("source", ""), "resolved_dimensions": state["resolved_dimensions"], "tasks": tasks}, ensure_ascii=False, sort_keys=True) + "\n")
    return False


def _public_absorption_state(root: Path) -> dict[str, Any]:
    state = _load_absorption_state(root)
    if not state:
        return {"active": False, "status": "empty"}
    public = {key: state.get(key) for key in ("active", "status", "source", "external_path", "pending_dimensions", "resolved_round", "resolved_dimensions") if key in state}
    public["closed_loop_proof"] = _closed_loop_proof(root)
    return public


def _closed_loop_proof(root: Path) -> dict[str, Any]:
    state = _load_absorption_state(root)
    proof = state.get("closed_loop_proof") if isinstance(state.get("closed_loop_proof"), dict) else {}
    flags = {
        "branch_diff_verified": bool(proof.get("branch_diff_verified")),
        "employee_execution_verified": bool(proof.get("employee_execution_verified")),
        "post_absorption_tests_passed": bool(proof.get("post_absorption_tests_passed")),
        "merge_verified": bool(proof.get("merge_verified")),
        "external_advantage_reassessed": bool(proof.get("external_advantage_reassessed")),
    }
    missing = tuple(key for key, value in flags.items() if not value)
    return {"verified": not missing, "missing": missing, "flags": flags, "evidence": [str(item) for item in proof.get("evidence") or []]}


def _load_absorption_state(root: Path) -> dict[str, Any]:
    path = root / ".retort" / "absorption_state.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_absorption_state(root: Path, state: dict[str, Any]) -> None:
    path = root / ".retort" / "absorption_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _python() -> str:
    return os.environ.get("PYTHON", "python")


def _run(cmd: list[str], cwd: Path) -> bool:
    try:
        return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False).returncode == 0
    except OSError:
        return False


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _git_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    except OSError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _tracking_state(path: Path) -> str:
    root = _git_root(path)
    if root is None:
        return "outside_git"
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = "."
    status = subprocess.run(["git", "status", "--short", "--", rel], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False).stdout
    if "??" in status:
        return "untracked"
    return "dirty" if status.strip() else "tracked_clean"


def _has_retort_ci(root: Path) -> bool:
    repo = _git_root(root) or root
    workflow = repo / ".github" / "workflows" / "retort-engine.yml"
    return workflow.is_file()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
