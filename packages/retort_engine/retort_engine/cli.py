from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from retort_engine.absorption_release_decision import build_absorption_release_decision
from retort_engine.absorption_continuity_probe import build_absorption_continuity_probe
from retort_engine.absorption_hardening_run import record_post_absorption_hardening_run
from retort_engine.architecture_contracts import evaluate_architecture_contracts, load_architecture_contracts
from retort_engine.codebase_graph import build_codebase_graph
from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.complex_pr_replay import build_complex_pr_replay_report
from retort_engine.context_packager import build_context_pack
from retort_engine.core import RetortService, absorb, record_closed_loop_proof
from retort_engine.employee_patch_closure import run_employee_patch_closure_suite
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress
from retort_engine.external_advantage_matrix import build_external_advantage_matrix
from retort_engine.external_advantage_repeat import build_external_advantage_repeat
from retort_engine.heterogeneous_absorption_replay import build_heterogeneous_absorption_replay
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_failure_rollback_replay import build_pr_failure_rollback_replay
from retort_engine.pr_holdout_blind_eval import build_pr_holdout_blind_eval
from retort_engine.pr_live_probe import write_live_pr_comment_probe, write_low_permission_pr_degradation_probe, write_readonly_pr_degradation_probe
from retort_engine.pr_long_run_review import build_pr_long_run_review
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.production_recovery_drill import build_production_recovery_drill
from retort_engine.multi_project_absorption_replay import build_multi_project_absorption_replay
from retort_engine.operator_journey_replay import build_operator_journey_replay
from retort_engine.quality_gate_bundle import run_quality_gate_bundle
from retort_engine.review_adjudication_calibration import build_review_adjudication_calibration
from retort_engine.review_pipeline import build_diff_pipeline_replay
from retort_engine.review_quality_benchmark import build_review_quality_benchmark
from retort_engine.similar_project_loop import build_absorption_saturation_report, build_similar_project_radar, run_similar_project_loop
from retort_engine.task_prioritization import build_task_prioritization_report
from retort_engine.task_dispatch_plan import build_task_dispatch_plan
from retort_engine.real_absorption import apply_real_absorption
from retort_engine.ui_server import run_ui_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retort")
    sub = parser.add_subparsers(dest="command", required=True)
    assess = sub.add_parser("project-assess")
    assess.add_argument("--project", default=".")
    assess.add_argument("--run-local-gates", action="store_true")
    assess.add_argument("--use-llm", action="store_true")
    assess.add_argument("--wait-llm-sec", type=float, default=240)
    assess.add_argument("--json", action="store_true")
    evolve = sub.add_parser("self-evolve")
    evolve.add_argument("--project", default=".")
    evolve.add_argument("--run-local-gates", action="store_true")
    evolve.add_argument("--use-llm", action="store_true")
    evolve.add_argument("--wait-llm-sec", type=float, default=240)
    evolve.add_argument("--json", action="store_true")
    absorb_cmd = sub.add_parser("absorb")
    absorb_cmd.add_argument("--own-project", default=".")
    source = absorb_cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("--github", default="")
    source.add_argument("--external-path", default="")
    absorb_cmd.add_argument("--employee-queue", default="")
    absorb_cmd.add_argument("--history-store", default="")
    absorb_cmd.add_argument("--run-local-gates", action="store_true")
    absorb_cmd.add_argument("--branch-workflow", action="store_true")
    absorb_cmd.add_argument("--absorption-branch", default="")
    absorb_cmd.add_argument("--merge-after", action="store_true")
    absorb_cmd.add_argument("--allow-dirty-branch", action="store_true")
    absorb_cmd.add_argument("--refresh", action="store_true")
    absorb_cmd.add_argument("--use-llm", action="store_true")
    absorb_cmd.add_argument("--no-execute-absorption", action="store_true")
    absorb_cmd.add_argument("--execution-timeout-sec", type=int, default=1800)
    absorb_cmd.add_argument("--json", action="store_true")
    apply_absorb = sub.add_parser("apply-absorption")
    apply_absorb.add_argument("--payload-file", required=True)
    apply_absorb.add_argument("--json", action="store_true")
    llm = sub.add_parser("llm-review")
    llm.add_argument("--project", default=".")
    llm.add_argument("--mode", default="manual")
    llm.add_argument("--github", default="")
    llm.add_argument("--external-path", default="")
    llm.add_argument("--run-local-gates", action="store_true")
    llm.add_argument("--json", action="store_true")
    llm_parallel = sub.add_parser("llm-review-parallel")
    llm_parallel.add_argument("--project", default=".")
    llm_parallel.add_argument("--mode", default="parallel_assess")
    llm_parallel.add_argument("--github", default="")
    llm_parallel.add_argument("--external-path", default="")
    llm_parallel.add_argument("--run-local-gates", action="store_true")
    llm_parallel.add_argument("--max-parallel", type=int, default=3)
    llm_parallel.add_argument("--json", action="store_true")
    llm_status = sub.add_parser("llm-review-status")
    llm_status.add_argument("--task-id", required=True)
    llm_status.add_argument("--json", action="store_true")
    llm_group_status = sub.add_parser("llm-review-group-status")
    llm_group_status.add_argument("--task-id", required=True)
    llm_group_status.add_argument("--json", action="store_true")
    proof = sub.add_parser("record-proof")
    proof.add_argument("--project", default=".")
    proof.add_argument("--branch-diff-verified", action="store_true")
    proof.add_argument("--employee-execution-verified", action="store_true")
    proof.add_argument("--post-absorption-tests-passed", action="store_true")
    proof.add_argument("--merge-verified", action="store_true")
    proof.add_argument("--external-advantage-reassessed", action="store_true")
    proof.add_argument("--evidence", action="append", default=[])
    proof.add_argument("--json", action="store_true")
    review = sub.add_parser("review-diff")
    review.add_argument("--diff-file", required=True)
    review.add_argument("--previous-diff-file", default="")
    review.add_argument("--issue-context-file", default="")
    review.add_argument("--pr-body-file", default="")
    review.add_argument("--max-comments", type=int, default=20)
    review.add_argument("--json", action="store_true")
    pipeline_replay = sub.add_parser("review-pipeline-diff-replay")
    pipeline_replay.add_argument("--diff-file", required=True)
    pipeline_replay.add_argument("--previous-diff-file", default="")
    pipeline_replay.add_argument("--issue-context-file", default="")
    pipeline_replay.add_argument("--max-comments", type=int, default=20)
    pipeline_replay.add_argument("--max-files-per-chunk", type=int, default=8)
    pipeline_replay.add_argument("--max-chars-per-chunk", type=int, default=30000)
    pipeline_replay.add_argument("--output", default="")
    pipeline_replay.add_argument("--json", action="store_true")
    review_pr = sub.add_parser("review-pr")
    review_pr.add_argument("--url", required=True)
    review_pr.add_argument("--previous-diff-file", default="")
    review_pr.add_argument("--max-comments", type=int, default=20)
    review_pr.add_argument("--max-bytes", type=int, default=500000)
    review_pr.add_argument("--output", default="")
    review_pr.add_argument("--json", action="store_true")
    publish_pr = sub.add_parser("publish-pr-dry-run")
    publish_pr.add_argument("--review-file", required=True)
    publish_pr.add_argument("--max-comments", type=int, default=50)
    publish_pr.add_argument("--output", default="")
    publish_pr.add_argument("--json", action="store_true")
    publish_sandbox = sub.add_parser("publish-pr-sandbox")
    publish_sandbox.add_argument("--dry-run-file", required=True)
    publish_sandbox.add_argument("--output", default="")
    publish_sandbox.add_argument("--json", action="store_true")
    live_probe = sub.add_parser("publish-pr-live-probe")
    live_probe.add_argument("--pr-url", required=True)
    live_probe.add_argument("--body", default="")
    live_probe.add_argument("--output", default="")
    live_probe.add_argument("--json", action="store_true")
    readonly_probe = sub.add_parser("publish-pr-readonly-probe")
    readonly_probe.add_argument("--pr-url", required=True)
    readonly_probe.add_argument("--output", default="")
    readonly_probe.add_argument("--json", action="store_true")
    low_permission_probe = sub.add_parser("publish-pr-low-permission-probe")
    low_permission_probe.add_argument("--pr-url", required=True)
    low_permission_probe.add_argument("--output", default="")
    low_permission_probe.add_argument("--json", action="store_true")
    long_run = sub.add_parser("pr-long-run-review")
    long_run.add_argument("--project", default=".")
    long_run.add_argument("--min-prs", type=int, default=10)
    long_run.add_argument("--output", default="")
    long_run.add_argument("--json", action="store_true")
    holdout_eval = sub.add_parser("pr-holdout-blind-eval")
    holdout_eval.add_argument("--project", default=".")
    holdout_eval.add_argument("--pr-url", action="append", default=[])
    holdout_eval.add_argument("--target-prs", type=int, default=20)
    holdout_eval.add_argument("--max-comments", type=int, default=12)
    holdout_eval.add_argument("--max-bytes", type=int, default=400000)
    holdout_eval.add_argument("--output", default="")
    holdout_eval.add_argument("--json", action="store_true")
    failure_rollback = sub.add_parser("pr-failure-rollback-replay")
    failure_rollback.add_argument("--project", default=".")
    failure_rollback.add_argument("--pr-url", action="append", default=[])
    failure_rollback.add_argument("--min-cases", type=int, default=3)
    failure_rollback.add_argument("--output", default="")
    failure_rollback.add_argument("--json", action="store_true")
    replay = sub.add_parser("cross-project-replay")
    replay.add_argument("--project", default=".")
    replay.add_argument("--output", default="")
    replay.add_argument("--json", action="store_true")
    multi_absorption_replay = sub.add_parser("multi-project-absorption-replay")
    multi_absorption_replay.add_argument("--project", default=".")
    multi_absorption_replay.add_argument("--min-projects", type=int, default=5)
    multi_absorption_replay.add_argument("--output", default="")
    multi_absorption_replay.add_argument("--json", action="store_true")
    continuity_probe = sub.add_parser("absorption-continuity-probe")
    continuity_probe.add_argument("--project", default=".")
    continuity_probe.add_argument("--min-runs", type=int, default=5)
    continuity_probe.add_argument("--output", default="")
    continuity_probe.add_argument("--json", action="store_true")
    hardening_run = sub.add_parser("record-hardening-run")
    hardening_run.add_argument("--project", default=".")
    hardening_run.add_argument("--worker-count", type=int, default=5)
    hardening_run.add_argument("--output", default="")
    hardening_run.add_argument("--json", action="store_true")
    complex_replay = sub.add_parser("complex-pr-replay")
    complex_replay.add_argument("--project", default=".")
    complex_replay.add_argument("--pr-url", action="append", default=[])
    complex_replay.add_argument("--max-comments", type=int, default=20)
    complex_replay.add_argument("--max-bytes", type=int, default=800000)
    complex_replay.add_argument("--output", default="")
    complex_replay.add_argument("--json", action="store_true")
    task_report = sub.add_parser("task-prioritization-report")
    task_report.add_argument("--project", default=".")
    task_report.add_argument("--output", default="")
    task_report.add_argument("--json", action="store_true")
    task_dispatch = sub.add_parser("task-dispatch-plan")
    task_dispatch.add_argument("--project", default=".")
    task_dispatch.add_argument("--enqueue", action="store_true")
    task_dispatch.add_argument("--output", default="")
    task_dispatch.add_argument("--json", action="store_true")
    quality_benchmark = sub.add_parser("quality-benchmark-report")
    quality_benchmark.add_argument("--project", default=".")
    quality_benchmark.add_argument("--sample-count", type=int, default=30)
    quality_benchmark.add_argument("--negative-sample-count", type=int, default=0)
    quality_benchmark.add_argument("--output", default="")
    quality_benchmark.add_argument("--json", action="store_true")
    external_advantage = sub.add_parser("external-advantage-matrix")
    external_advantage.add_argument("--project", default=".")
    external_advantage.add_argument("--min-cases", type=int, default=6)
    external_advantage.add_argument("--output", default="")
    external_advantage.add_argument("--json", action="store_true")
    external_repeat = sub.add_parser("external-advantage-repeat")
    external_repeat.add_argument("--project", default=".")
    external_repeat.add_argument("--repeats", type=int, default=2)
    external_repeat.add_argument("--min-cases", type=int, default=6)
    external_repeat.add_argument("--output", default="")
    external_repeat.add_argument("--json", action="store_true")
    heterogeneous_replay = sub.add_parser("heterogeneous-absorption-replay")
    heterogeneous_replay.add_argument("--project", default=".")
    heterogeneous_replay.add_argument("--min-cases", type=int, default=6)
    heterogeneous_replay.add_argument("--output", default="")
    heterogeneous_replay.add_argument("--json", action="store_true")
    adjudication = sub.add_parser("review-adjudication-calibration")
    adjudication.add_argument("--project", default=".")
    adjudication.add_argument("--output", default="")
    adjudication.add_argument("--json", action="store_true")
    scheduler_stress = sub.add_parser("employee-scheduler-stress")
    scheduler_stress.add_argument("--project", default=".")
    scheduler_stress.add_argument("--rounds", type=int, default=10)
    scheduler_stress.add_argument("--tasks-per-round", type=int, default=3)
    scheduler_stress.add_argument("--workers-per-round", type=int, default=1)
    scheduler_stress.add_argument("--output", default="")
    scheduler_stress.add_argument("--json", action="store_true")
    patch_closure = sub.add_parser("employee-patch-closure")
    patch_closure.add_argument("--project", default=".")
    patch_closure.add_argument("--output", default="")
    patch_closure.add_argument("--json", action="store_true")
    recovery_drill = sub.add_parser("production-recovery-drill")
    recovery_drill.add_argument("--project", default=".")
    recovery_drill.add_argument("--output", default="")
    recovery_drill.add_argument("--json", action="store_true")
    release_decision = sub.add_parser("absorption-release-decision")
    release_decision.add_argument("--project", default=".")
    release_decision.add_argument("--output", default="")
    release_decision.add_argument("--json", action="store_true")
    operator_journey = sub.add_parser("operator-journey-replay")
    operator_journey.add_argument("--project", default=".")
    operator_journey.add_argument("--output", default="")
    operator_journey.add_argument("--json", action="store_true")
    quality_gates = sub.add_parser("quality-gates")
    quality_gates.add_argument("--project", default=".")
    quality_gates.add_argument("--output", default="")
    quality_gates.add_argument("--json", action="store_true")
    codebase_graph = sub.add_parser("codebase-graph-report")
    codebase_graph.add_argument("--project", default=".")
    codebase_graph.add_argument("--include-tests", action="store_true")
    codebase_graph.add_argument("--max-files", type=int, default=400)
    codebase_graph.add_argument("--output", default="")
    codebase_graph.add_argument("--json", action="store_true")
    context_pack = sub.add_parser("context-pack-report")
    context_pack.add_argument("--project", default=".")
    context_pack.add_argument("--focus-term", action="append", default=[])
    context_pack.add_argument("--max-files", type=int, default=24)
    context_pack.add_argument("--max-chars", type=int, default=24000)
    context_pack.add_argument("--output", default="")
    context_pack.add_argument("--json", action="store_true")
    architecture_contract = sub.add_parser("architecture-contract-report")
    architecture_contract.add_argument("--project", default=".")
    architecture_contract.add_argument("--contract-file", default="")
    architecture_contract.add_argument("--include-tests", action="store_true")
    architecture_contract.add_argument("--max-files", type=int, default=400)
    architecture_contract.add_argument("--output", default="")
    architecture_contract.add_argument("--json", action="store_true")
    radar = sub.add_parser("similar-project-radar")
    radar.add_argument("--project", default=".")
    radar.add_argument("--query", default="AI PR reviewer")
    radar.add_argument("--limit", type=int, default=10)
    radar.add_argument("--min-score", type=int, default=55)
    radar.add_argument("--json", action="store_true")
    loop = sub.add_parser("similar-project-loop")
    loop.add_argument("--project", default=".")
    loop.add_argument("--source", action="append", default=[])
    loop.add_argument("--limit", type=int, default=3)
    loop.add_argument("--min-score", type=int, default=55)
    loop.add_argument("--run-local-gates", action="store_true")
    loop.add_argument("--branch-workflow", action="store_true")
    loop.add_argument("--merge-after", action="store_true")
    loop.add_argument("--allow-dirty-branch", action="store_true")
    loop.add_argument("--use-llm", action="store_true")
    loop.add_argument("--dry-run", action="store_true")
    loop.add_argument("--json", action="store_true")
    saturation = sub.add_parser("absorption-saturation")
    saturation.add_argument("--project", default=".")
    saturation.add_argument("--recent-limit", type=int, default=3)
    saturation.add_argument("--json", action="store_true")
    ui = sub.add_parser("ui")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    if args.command == "project-assess":
        result = RetortService().assess({"project": args.project, "run_local_gates": args.run_local_gates, "use_llm": True, "wait_llm_sec": args.wait_llm_sec, "require_deep_review": True})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _format_scores("Retort assessment", result["scores"]))
        return 0
    if args.command == "self-evolve":
        result = RetortService().self_evolve({"project": args.project, "run_local_gates": args.run_local_gates, "use_llm": True, "wait_llm_sec": args.wait_llm_sec, "require_deep_review": True})
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort self-evolution status: {result['status']}")
            print(f"Stop reason: {result['stop_reason']}")
            print(_format_scores("Final scores", result["final_assessment"]["scores"]))
        return 0 if result["status"] == "converged" else 1
    if args.command == "absorb":
        result = absorb({"own_project": args.own_project, "github_url": args.github, "external_path": args.external_path, "employee_queue": args.employee_queue, "history_store": args.history_store, "run_local_gates": args.run_local_gates, "branch_workflow": args.branch_workflow, "absorption_branch": args.absorption_branch, "merge_after": args.merge_after, "allow_dirty_branch": args.allow_dirty_branch, "refresh": args.refresh, "use_llm": args.use_llm, "execute_absorption": not args.no_execute_absorption, "execution_timeout_sec": args.execution_timeout_sec})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort absorption status: {result['status']}")
        return 0
    if args.command == "apply-absorption":
        with open(args.payload_file, encoding="utf-8") as handle:
            payload = json.load(handle)
        result = apply_real_absorption(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort apply absorption status: {result['status']}")
        return 0 if result["status"] in {"applied", "noop"} and result.get("gates_passed") else 1
    if args.command == "llm-review":
        result = RetortService().llm_review({"project": args.project, "mode": args.mode, "github_url": args.github, "external_path": args.external_path, "run_local_gates": args.run_local_gates})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort LLM review status: {result['status']}")
        return 0
    if args.command == "llm-review-parallel":
        result = RetortService().llm_parallel_review({"project": args.project, "mode": args.mode, "github_url": args.github, "external_path": args.external_path, "run_local_gates": args.run_local_gates, "max_parallel": args.max_parallel})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort parallel LLM review status: {result['status']}")
        return 0
    if args.command == "llm-review-status":
        result = RetortService().llm_review_status({"task_id": args.task_id})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort LLM task status: {result['status']}")
        return 0
    if args.command == "llm-review-group-status":
        result = RetortService().llm_parallel_status({"task_id": args.task_id})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort parallel LLM task status: {result['status']}")
        return 0
    if args.command == "record-proof":
        result = record_closed_loop_proof(args.project, {"branch_diff_verified": args.branch_diff_verified, "employee_execution_verified": args.employee_execution_verified, "post_absorption_tests_passed": args.post_absorption_tests_passed, "merge_verified": args.merge_verified, "external_advantage_reassessed": args.external_advantage_reassessed, "evidence": args.evidence})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Retort proof status: {result['status']}")
        return 0
    if args.command == "review-diff":
        with open(args.diff_file, encoding="utf-8") as handle:
            diff_text = handle.read()
        previous_diff_text = ""
        if args.previous_diff_file:
            with open(args.previous_diff_file, encoding="utf-8") as handle:
                previous_diff_text = handle.read()
        issue_context = ""
        if args.issue_context_file:
            with open(args.issue_context_file, encoding="utf-8") as handle:
                issue_context = handle.read()
        pr_body = ""
        if args.pr_body_file:
            with open(args.pr_body_file, encoding="utf-8") as handle:
                pr_body = handle.read()
        result = review_diff(
            diff_text,
            max_comments=args.max_comments,
            previous_diff_text=previous_diff_text,
            issue_context=issue_context,
            pr_body=pr_body,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort diff review status: {result['status']}")
            print(f"Comments: {result['summary']['comment_count']}")
            print(f"Skipped existing changes: {result['summary']['skipped_existing_change_count']}")
        return 0 if result["status"] in {"reviewed", "no_new_changes"} else 1
    if args.command == "review-pipeline-diff-replay":
        with open(args.diff_file, encoding="utf-8") as handle:
            diff_text = handle.read()
        previous_diff_text = ""
        if args.previous_diff_file:
            with open(args.previous_diff_file, encoding="utf-8") as handle:
                previous_diff_text = handle.read()
        issue_context = ""
        if args.issue_context_file:
            with open(args.issue_context_file, encoding="utf-8") as handle:
                issue_context = handle.read()
        result = build_diff_pipeline_replay(
            diff_text,
            previous_diff_text=previous_diff_text,
            issue_context=issue_context,
            max_comments=args.max_comments,
            max_files_per_chunk=args.max_files_per_chunk,
            max_chars_per_chunk=args.max_chars_per_chunk,
        )
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort diff pipeline replay status: {result['status']}")
            print(f"Depth score: {result['summary']['diff_grouping_depth_score']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] in {"ready", "no_new_changes", "empty_diff"} else 1
    if args.command == "review-pr":
        previous_diff_text = ""
        if args.previous_diff_file:
            with open(args.previous_diff_file, encoding="utf-8") as handle:
                previous_diff_text = handle.read()
        result = review_pr_url(args.url, max_comments=args.max_comments, previous_diff_text=previous_diff_text, max_bytes=args.max_bytes)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR dry-run status: {result['status']}")
            print(f"Comments: {result['summary']['comment_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "reviewed" else 1
    if args.command == "publish-pr-dry-run":
        result = build_publish_dry_run(args.review_file, max_comments=args.max_comments)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR publish dry-run status: {result['status']}")
            print(f"Would post: {result['summary']['would_post_comment_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "dry_run_ready" else 1
    if args.command == "publish-pr-sandbox":
        result = run_publish_sandbox(args.dry_run_file)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR publish sandbox status: {result['status']}")
            print(f"Rolled back: {result['summary']['rolled_back_comment_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "sandbox_rolled_back" else 1
    if args.command == "publish-pr-live-probe":
        output = args.output or "retort_pr_live_publish_probe.json"
        result = write_live_pr_comment_probe(args.pr_url, output, body=args.body)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR live publish probe status: {result['status']}")
            print(f"Created: {result['summary']['created_comment_count']}")
            print(f"Rolled back: {result['summary']['rolled_back_comment_count']}")
            print(f"Output: {output}")
        return 0 if result["status"] in {"live_rolled_back", "permission_denied_degraded"} else 1
    if args.command == "publish-pr-readonly-probe":
        output = args.output or "retort_pr_readonly_degradation_probe.json"
        result = write_readonly_pr_degradation_probe(args.pr_url, output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR readonly probe status: {result['status']}")
            print(f"Readable: {result['summary']['pull_status'] < 400}")
            print(f"Output: {output}")
        return 0 if result["status"] == "read_only_degraded" else 1
    if args.command == "publish-pr-low-permission-probe":
        output = args.output or "retort_pr_low_permission_probe.json"
        result = write_low_permission_pr_degradation_probe(args.pr_url, output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR low-permission probe status: {result['status']}")
            print(f"Write denied: {result['summary']['permission_denied']}")
            print(f"Output: {output}")
        return 0 if result["status"] == "permission_denied_degraded" else 1
    if args.command == "pr-long-run-review":
        result = build_pr_long_run_review(args.project, min_prs=args.min_prs, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR long-run review status: {result['status']}")
            print(f"Reviewed PRs: {result['summary']['reviewed_pr_count']}/{result['summary']['target_pr_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "pr-holdout-blind-eval":
        result = build_pr_holdout_blind_eval(
            args.project,
            pr_urls=args.pr_url or None,
            target_prs=args.target_prs,
            max_comments=args.max_comments,
            max_bytes=args.max_bytes,
            output=args.output,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR holdout blind eval status: {result['status']}")
            print(f"Accepted PRs: {result['summary']['accepted_pr_count']}/{result['summary']['target_pr_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "pr-failure-rollback-replay":
        result = build_pr_failure_rollback_replay(
            args.project,
            pr_urls=args.pr_url or None,
            min_cases=args.min_cases,
            output=args.output,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort PR failure rollback status: {result['status']}")
            print(f"Rolled back: {result['summary']['rollback_verified_count']}/{result['summary']['target_case_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "cross-project-replay":
        result = build_cross_project_replay(args.project)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort cross-project replay status: {result['status']}")
            print(f"External projects: {result['summary']['external_project_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "multi-project-absorption-replay":
        result = build_multi_project_absorption_replay(args.project, min_projects=args.min_projects, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort multi-project absorption replay status: {result['status']}")
            print(f"Ready projects: {result['summary']['ready_project_count']}/{result['summary']['min_project_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "absorption-continuity-probe":
        result = build_absorption_continuity_probe(args.project, min_runs=args.min_runs, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort absorption continuity status: {result['status']}")
            print(f"Ready runs: {result['summary']['ready_run_count']}/{result['summary']['min_run_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "record-hardening-run":
        result = record_post_absorption_hardening_run(args.project, output=args.output, worker_count=args.worker_count)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort hardening run status: {result['status']}")
            print(f"Behavior files: {result['summary']['behavior_source_file_count']} source / {result['summary']['behavior_test_file_count']} tests")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["gates_passed"] else 1
    if args.command == "complex-pr-replay":
        result = build_complex_pr_replay_report(args.project, pr_urls=args.pr_url or None, max_comments=args.max_comments, max_bytes=args.max_bytes)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort complex PR replay status: {result['status']}")
            print(f"Complex PRs: {result['summary']['complex_pr_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "task-prioritization-report":
        result = build_task_prioritization_report(args.project)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort task prioritization status: {result['status']}")
            print(f"Prioritized dimensions: {result['summary']['prioritized_dimension_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "task-dispatch-plan":
        result = build_task_dispatch_plan(args.project, enqueue=args.enqueue)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort task dispatch plan status: {result['status']}")
            print(f"Dispatch tasks: {result['summary']['dispatch_task_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "quality-benchmark-report":
        result = build_review_quality_benchmark(args.project, sample_count=args.sample_count, negative_sample_count=args.negative_sample_count)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort quality benchmark status: {result['status']}")
            print(f"Samples: {result['summary']['sample_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "external-advantage-matrix":
        result = build_external_advantage_matrix(args.project, min_cases=args.min_cases, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort external advantage matrix status: {result['status']}")
            print(f"Ready cases: {result['summary']['ready_case_count']}/{result['summary']['case_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "external-advantage-repeat":
        result = build_external_advantage_repeat(args.project, repeat_count=args.repeats, min_cases=args.min_cases, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort external advantage repeat status: {result['status']}")
            print(f"Repeats: {result['summary']['ready_repeat_count']}/{result['summary']['repeat_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "heterogeneous-absorption-replay":
        result = build_heterogeneous_absorption_replay(args.project, min_cases=args.min_cases, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort heterogeneous absorption replay status: {result['status']}")
            print(f"Ready cases: {result['summary']['ready_case_count']}/{result['summary']['case_count']}")
            print(f"Language families: {result['summary']['language_family_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "review-adjudication-calibration":
        result = build_review_adjudication_calibration(args.project, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort review adjudication calibration status: {result['status']}")
            print(f"Human labels: {result['summary']['human_label_count']}")
            print(f"Pass rate: {result['summary']['pass_rate']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "employee-scheduler-stress":
        result = run_employee_scheduler_stress(args.project, round_count=args.rounds, tasks_per_round=args.tasks_per_round, workers_per_round=args.workers_per_round)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort employee scheduler stress status: {result['status']}")
            print(f"Rounds: {result['summary']['round_count']}")
            print(f"Completed: {result['summary']['completed_result_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "employee-patch-closure":
        result = run_employee_patch_closure_suite(args.project, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort employee patch closure status: {result['status']}")
            print(f"Patch cases: {result['summary']['case_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "production-recovery-drill":
        result = build_production_recovery_drill(args.project, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort production recovery status: {result['status']}")
            print(f"Recovered: {result['summary']['recovered_count']}/{result['summary']['scenario_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "absorption-release-decision":
        result = build_absorption_release_decision(args.project, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort absorption release decision status: {result['status']}")
            print(f"Ready decisions: {result['summary']['ready_decision_count']}/{result['summary']['decision_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "operator-journey-replay":
        result = build_operator_journey_replay(args.project, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort operator journey replay status: {result['status']}")
            print(f"Ready stages: {result['summary']['ready_stage_count']}/{result['summary']['stage_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "quality-gates":
        result = run_quality_gate_bundle(args.project, output=args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort quality gates status: {result['status']}")
            print(f"Passed: {result['summary']['passed_count']}/{result['summary']['gate_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "codebase-graph-report":
        result = build_codebase_graph(args.project, include_tests=args.include_tests, max_files=args.max_files)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort codebase graph status: {result['status']}")
            print(f"Nodes: {result['summary']['node_count']}")
            print(f"Edges: {result['summary']['edge_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] in {"ready", "partial"} else 1
    if args.command == "context-pack-report":
        result = build_context_pack(
            args.project,
            focus_terms=args.focus_term or None,
            max_files=args.max_files,
            max_chars=args.max_chars,
        )
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort context pack status: {result['status']}")
            print(f"Files: {result['summary']['selected_file_count']}")
            print(f"Chars: {result['summary']['used_chars']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "architecture-contract-report":
        contracts = load_architecture_contracts(args.contract_file) if args.contract_file else None
        result = evaluate_architecture_contracts(args.project, contracts=contracts, include_tests=args.include_tests, max_files=args.max_files)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort architecture contract status: {result['status']}")
            print(f"Violations: {result['summary']['violation_count']}")
            if args.output:
                print(f"Output: {args.output}")
        return 0 if result["status"] == "passed" else 1
    if args.command == "similar-project-radar":
        result = build_similar_project_radar(args.project, query=args.query, limit=args.limit, min_score=args.min_score)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort similar-project radar status: {result['status']}")
            print(f"Accepted: {result['summary']['accepted_count']}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "similar-project-loop":
        result = run_similar_project_loop(
            args.project,
            sources=args.source,
            limit=args.limit,
            min_score=args.min_score,
            run_local_gates=args.run_local_gates,
            branch_workflow=args.branch_workflow,
            merge_after=args.merge_after,
            allow_dirty_branch=args.allow_dirty_branch,
            use_llm=args.use_llm,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort similar-project loop status: {result['status']}")
            print(f"Selected: {result['summary']['selected_count']}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "absorption-saturation":
        result = build_absorption_saturation_report(args.project, recent_limit=args.recent_limit)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort absorption saturation status: {result['status']}")
            print(f"Saturated: {result['summary']['saturated']}")
        return 0
    if args.command == "ui":
        run_ui_server(args.host, args.port)
        return 0
    return 2


def _format_scores(title: str, scores: list[dict[str, object]]) -> str:
    lines = [title + ":"]
    for score in scores:
        value = float(score["value"])
        lines.append(f"- {score['dimension']}: {value:.1f} ({'PASS' if value > 90 else 'NEEDS_WORK'})")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
