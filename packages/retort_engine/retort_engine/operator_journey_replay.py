from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.architecture_contracts import evaluate_architecture_contracts
from retort_engine.codebase_graph import build_codebase_graph
from retort_engine.ui_features import blackhole_ui_structure


def build_operator_journey_replay(project: str | Path, *, output: str | Path = "") -> dict[str, Any]:
    """Replay the operator-facing absorption journey from existing durable evidence."""
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("operator-journey-%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    latest_run = _latest_real_absorption_run(root)
    artifacts = _artifact_manifest(root, latest_run)
    artifact_by_name = {str(item["name"]): item for item in artifacts}
    live_probes = _live_cross_domain_probes(root)
    stages = _journey_stages(root, latest_run, artifact_by_name, live_probes)
    ready_stages = [stage for stage in stages if stage["ready"]]
    failed_stages = [stage for stage in stages if not stage["ready"]]
    manifest_path = root / ".retort" / "operator_journey_replays" / f"{run_id}.manifest.json"
    summary = {
        "run_id": run_id,
        "stage_count": len(stages),
        "ready_stage_count": len(ready_stages),
        "failed_stage_count": len(failed_stages),
        "artifact_count": len(artifacts),
        "hashed_artifact_count": sum(1 for item in artifacts if item["exists"] and item["sha256"]),
        "source_report_count": sum(1 for item in artifacts if item["kind"] == "source_report" and item["exists"]),
        "real_absorption_run_present": bool(latest_run),
        "real_absorption_gates_passed": latest_run.get("gates_passed") is True if latest_run else False,
        "per_run_code_graph_proved": _code_graph_ready(latest_run),
        "cross_domain_live_probe_ready": _cross_domain_ready(live_probes),
        "frontend_structure_ready": bool((live_probes.get("blackhole_ui") or {}).get("ready")),
        "architecture_contract_ready": bool((live_probes.get("architecture_contracts") or {}).get("ready")),
        "codebase_graph_ready": bool((live_probes.get("codebase_graph") or {}).get("ready")),
        "manifest_path": str(manifest_path),
        "single_command_surface": True,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    status = "ready" if not failed_stages and summary["hashed_artifact_count"] >= 8 else "blocked"
    result = {
        "status": status,
        "project": str(root),
        "summary": summary,
        "stages": stages,
        "artifacts": artifacts,
        "live_probes": live_probes,
        "replay": {
            "command": ["retort", "operator-journey-replay", "--project", str(root), "--output", "docs/retort_operator_journey_replay.json"],
            "manifest_path": str(manifest_path),
            "minimal_evidence_pack": True,
            "replay_model": "hash_bound_reports_plus_live_cross_domain_probes",
        },
        "evidence": {
            "style": "operator_end_to_end_absorption_journey_replay",
            "flow": "github_or_folder_source_to_deep_review_to_absorption_to_employee_tasks_to_publish_degrade_to_release_decision",
            "hash_algorithm": "sha256",
            "source_reports": [str(item["relative_path"]) for item in artifacts if item["kind"] == "source_report" and item["exists"]],
        },
    }
    _write_manifest(manifest_path, result)
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _journey_stages(
    root: Path,
    latest_run: dict[str, Any],
    artifact_by_name: dict[str, dict[str, Any]],
    live_probes: dict[str, Any],
) -> list[dict[str, Any]]:
    external_report = artifact_by_name.get("external_review_report", {})
    location = _location_evidence(latest_run)
    quality = artifact_by_name.get("quality_gate_bundle", {})
    holdout = artifact_by_name.get("pr_holdout_blind_eval", {})
    rollback = artifact_by_name.get("pr_failure_rollback_replay", {})
    employee_patch = artifact_by_name.get("employee_patch_closure", {})
    scheduler = artifact_by_name.get("employee_scheduler_stress", {})
    publish_dry_run = artifact_by_name.get("pr_publish_dry_run", {})
    readonly_probe = artifact_by_name.get("pr_readonly_degradation_probe", {})
    low_permission_probe = artifact_by_name.get("pr_low_permission_probe", {})
    return [
        _stage(
            "select_external_source",
            "外部项目进入",
            bool(latest_run.get("source")) and external_report.get("exists") is True,
            [
                f"source={latest_run.get('source', '')}",
                f"external_report_sha={external_report.get('sha256', '')}",
            ],
        ),
        _stage(
            "pre_absorption_locate",
            "吸收前定位",
            external_report.get("exists") is True and location["ready"] and _code_graph_ready(latest_run),
            [
                f"pre_absorption_focus={bool(latest_run.get('pre_absorption_focus'))}",
                f"post_absorption_graph_focus={location['post_absorption_graph_focus']}",
                f"location_evidence={location['kind']}",
                f"per_run_code_graph={_code_graph_ready(latest_run)}",
                f"external_report_fields={external_report.get('required_field_count', 0)}",
            ],
        ),
        _stage(
            "absorb_and_gate",
            "真实吸收和门禁",
            latest_run.get("gates_passed") is True and quality.get("exists") is True and bool(latest_run.get("changed_files")),
            [
                f"changed_files={len(latest_run.get('changed_files') or [])}",
                f"gates_passed={latest_run.get('gates_passed')}",
                f"quality_gate_sha={quality.get('sha256', '')}",
            ],
        ),
        _stage(
            "employee_long_chain",
            "员工长链路产物",
            employee_patch.get("exists") is True and scheduler.get("exists") is True,
            [
                f"employee_patch_sha={employee_patch.get('sha256', '')}",
                f"scheduler_sha={scheduler.get('sha256', '')}",
                f"employee_results_path={latest_run.get('employee_results_path', '')}",
            ],
        ),
        _stage(
            "quality_holdout_and_rollback",
            "质量盲测和失败回滚",
            holdout.get("exists") is True and rollback.get("exists") is True,
            [
                f"holdout_sha={holdout.get('sha256', '')}",
                f"rollback_sha={rollback.get('sha256', '')}",
            ],
        ),
        _stage(
            "publish_or_degrade",
            "发布或权限降级",
            publish_dry_run.get("exists") is True and (readonly_probe.get("exists") is True or low_permission_probe.get("exists") is True),
            [
                f"publish_dry_run_sha={publish_dry_run.get('sha256', '')}",
                f"readonly_probe_sha={readonly_probe.get('sha256', '')}",
                f"low_permission_probe_sha={low_permission_probe.get('sha256', '')}",
            ],
        ),
        _stage(
            "cross_domain_live_probe",
            "跨领域现场探针",
            _cross_domain_ready(live_probes),
            [
                f"codebase_graph_ready={(live_probes.get('codebase_graph') or {}).get('ready')}",
                f"architecture_contract_ready={(live_probes.get('architecture_contracts') or {}).get('ready')}",
                f"blackhole_ui_ready={(live_probes.get('blackhole_ui') or {}).get('ready')}",
            ],
        ),
        _stage(
            "release_decision",
            "最终发布输入",
            _release_inputs_ready(root),
            [
                f"release_inputs_ready={_release_inputs_ready(root)}",
                "release_decision_self_reference=False",
            ],
        ),
    ]


def _artifact_manifest(root: Path, latest_run: dict[str, Any]) -> list[dict[str, Any]]:
    docs = root / "docs"
    specs = [
        ("external_review_report", docs / "retort_external_review_report.json", "source_report", ("source", "external_snapshot", "review_pipeline")),
        ("quality_gate_bundle", docs / "retort_quality_gate_bundle.json", "source_report", ("status", "summary", "gates")),
        ("absorption_continuity_probe", docs / "retort_absorption_continuity_probe.json", "source_report", ("status", "summary", "runs")),
        ("multi_project_absorption_replay", docs / "retort_multi_project_absorption_replay.json", "source_report", ("status", "summary", "projects")),
        ("pr_holdout_blind_eval", docs / "retort_pr_holdout_blind_eval.json", "source_report", ("status", "summary", "cases")),
        ("pr_failure_rollback_replay", docs / "retort_pr_failure_rollback_replay.json", "source_report", ("status", "summary", "cases")),
        ("employee_patch_closure", docs / "retort_employee_patch_closure.json", "source_report", ("status", "summary", "cases")),
        ("employee_scheduler_stress", docs / "retort_employee_scheduler_stress.json", "source_report", ("status", "summary", "rounds")),
        ("pr_publish_dry_run", docs / "retort_pr_publish_dry_run.json", "source_report", ("status", "summary", "comments")),
        ("pr_readonly_degradation_probe", docs / "retort_pr_readonly_degradation_probe.json", "source_report", ("status", "summary", "evidence")),
        ("pr_low_permission_probe", docs / "retort_pr_low_permission_probe.json", "source_report", ("status", "summary", "evidence")),
        ("production_recovery_drill", docs / "retort_production_recovery_drill.json", "source_report", ("status", "summary", "scenarios")),
        ("review_quality_benchmark", docs / "retort_review_quality_benchmark.json", "source_report", ("status", "summary", "samples")),
        ("external_advantage_matrix", docs / "retort_external_advantage_matrix.json", "source_report", ("status", "summary", "matrix")),
        ("external_advantage_repeat", docs / "retort_external_advantage_repeat.json", "source_report", ("status", "summary", "runs")),
        ("heterogeneous_absorption_replay", docs / "retort_heterogeneous_absorption_replay.json", "source_report", ("status", "summary", "cases")),
        ("external_merge_landing", docs / "retort_external_merge_landing.json", "source_report", ("status", "summary", "cases")),
        ("review_adjudication_calibration", docs / "retort_review_adjudication_calibration.json", "source_report", ("status", "summary", "cases")),
    ]
    run_path = Path(str(latest_run.get("run_record_path") or ""))
    if not run_path.is_file() and latest_run:
        run_path = root / ".retort" / "real_absorption_runs" / f"{latest_run.get('run_id')}.json"
    if latest_run:
        specs.append(("latest_real_absorption_run", run_path, "real_absorption_run", ("status", "summary", "changed_files", "code_graph_proof")))
    return [_artifact(root, name, path, kind, required) for name, path, kind, required in specs]


def _artifact(root: Path, name: str, path: Path, kind: str, required: tuple[str, ...]) -> dict[str, Any]:
    exists = path.is_file()
    payload = _read_json(path) if exists else {}
    present = [field for field in required if field in payload]
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        relative = path
    return {
        "name": name,
        "kind": kind,
        "path": str(path),
        "relative_path": relative.as_posix(),
        "exists": exists,
        "bytes": path.stat().st_size if exists else 0,
        "sha256": _sha256(path) if exists else "",
        "required_fields": list(required),
        "required_fields_present": present,
        "required_field_count": len(present),
        "required_fields_ready": len(present) == len(required),
    }


def _live_cross_domain_probes(root: Path) -> dict[str, Any]:
    graph = _safe_call(lambda: build_codebase_graph(root, include_tests=True, max_files=400))
    contracts = _safe_call(lambda: evaluate_architecture_contracts(root, include_tests=True, max_files=400))
    ui = _safe_call(lambda: blackhole_ui_structure(root))
    ui_missing = list(ui.get("missing_ids") or []) + list(ui.get("missing_functions") or [])
    return {
        "codebase_graph": {
            "ready": graph.get("status") == "ready",
            "status": graph.get("status", ""),
            "file_count": (graph.get("summary") or {}).get("file_count", 0),
            "edge_count": (graph.get("summary") or {}).get("edge_count", 0),
            "hotspot_count": (graph.get("summary") or {}).get("hotspot_count", 0),
        },
        "architecture_contracts": {
            "ready": contracts.get("status") == "passed",
            "status": contracts.get("status", ""),
            "contract_count": (contracts.get("summary") or {}).get("contract_count", 0),
            "violation_count": (contracts.get("summary") or {}).get("violation_count", 0),
        },
        "blackhole_ui": {
            "ready": bool(ui.get("index_exists")) and bool(ui.get("app_exists")) and not ui_missing and bool(ui.get("has_animation_loop")),
            "index_exists": ui.get("index_exists", False),
            "app_exists": ui.get("app_exists", False),
            "canvas_visual": ui.get("canvas_visual", ""),
            "missing_count": len(ui_missing),
            "has_animation_loop": ui.get("has_animation_loop", False),
        },
    }


def _cross_domain_ready(probes: dict[str, Any]) -> bool:
    return all(bool((probes.get(name) or {}).get("ready")) for name in ("codebase_graph", "architecture_contracts", "blackhole_ui"))


def _stage(name: str, title: str, ready: bool, evidence: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "evidence": evidence,
    }


def _latest_real_absorption_run(root: Path) -> dict[str, Any]:
    run_dir = root / ".retort" / "real_absorption_runs"
    if not run_dir.is_dir():
        return {}
    for path in sorted(run_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _read_json(path)
        if not payload:
            continue
        payload.setdefault("run_record_path", str(path))
        return payload
    return {}


def _code_graph_ready(run: dict[str, Any]) -> bool:
    proof = run.get("code_graph_proof") if isinstance(run.get("code_graph_proof"), dict) else {}
    return bool(proof.get("passed") and proof.get("per_run_required"))


def _location_evidence(run: dict[str, Any]) -> dict[str, Any]:
    proof = run.get("code_graph_proof") if isinstance(run.get("code_graph_proof"), dict) else {}
    has_pre_focus = bool(run.get("pre_absorption_focus"))
    has_graph_focus = bool(proof.get("changed_focus_files") or proof.get("changed_hotspots") or proof.get("dependency_impact"))
    kind = "pre_absorption_focus" if has_pre_focus else "post_absorption_code_graph_focus" if has_graph_focus else "missing"
    return {
        "ready": has_pre_focus or has_graph_focus,
        "kind": kind,
        "post_absorption_graph_focus": has_graph_focus,
    }


def _release_inputs_ready(root: Path) -> bool:
    docs = root / "docs"
    quality = _read_json(docs / "retort_quality_gate_bundle.json")
    continuity = _read_json(docs / "retort_absorption_continuity_probe.json")
    long_run = _read_json(docs / "retort_pr_long_run_review.json")
    holdout = _read_json(docs / "retort_pr_holdout_blind_eval.json")
    failure_rollback = _read_json(docs / "retort_pr_failure_rollback_replay.json")
    recovery = _read_json(docs / "retort_production_recovery_drill.json")
    patch = _read_json(docs / "retort_employee_patch_closure.json")
    benchmark = _read_json(docs / "retort_review_quality_benchmark.json")
    external_matrix = _read_json(docs / "retort_external_advantage_matrix.json")
    external_repeat = _read_json(docs / "retort_external_advantage_repeat.json")
    heterogeneous_replay = _read_json(docs / "retort_heterogeneous_absorption_replay.json")
    external_merge_landing = _read_json(docs / "retort_external_merge_landing.json")
    return (
        quality.get("summary", {}).get("all_gates_passed") is True
        and continuity.get("status") == "ready"
        and long_run.get("status") == "ready"
        and holdout.get("status") == "ready"
        and failure_rollback.get("status") == "ready"
        and recovery.get("status") == "ready"
        and patch.get("status") == "ready"
        and benchmark.get("status") == "ready"
        and int(benchmark.get("summary", {}).get("post_absorption_score_delta") or 0) > 0
        and external_matrix.get("status") == "ready"
        and int(external_matrix.get("summary", {}).get("score_delta") or 0) > 0
        and external_repeat.get("status") == "ready"
        and external_repeat.get("summary", {}).get("stable_case_set") is True
        and external_repeat.get("summary", {}).get("stable_score_delta") is True
        and heterogeneous_replay.get("status") == "ready"
        and heterogeneous_replay.get("summary", {}).get("all_before_failed_after_passed") is True
        and heterogeneous_replay.get("summary", {}).get("cross_language_absorption_verified") is True
        and external_merge_landing.get("status") == "ready"
        and external_merge_landing.get("summary", {}).get("all_branch_diff_merge_tests_passed") is True
        and int(external_merge_landing.get("summary", {}).get("merge_commit_count") or 0) >= 2
    )


def _write_manifest(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result["summary"]["run_id"],
        "status": result["status"],
        "summary": result["summary"],
        "stages": result["stages"],
        "artifacts": result["artifacts"],
        "replay": result["replay"],
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _safe_call(fn: Any) -> dict[str, Any]:
    try:
        result = fn()
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__, "message": str(exc)[-300:]}
    return result if isinstance(result, dict) else {"status": "invalid"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
