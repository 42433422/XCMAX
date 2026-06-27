from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.core import RetortService, absorb, record_closed_loop_proof
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.task_prioritization import build_task_prioritization_report
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
    evolve.add_argument("--max-rounds", type=int, default=8)
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
    review.add_argument("--max-comments", type=int, default=20)
    review.add_argument("--json", action="store_true")
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
    replay = sub.add_parser("cross-project-replay")
    replay.add_argument("--project", default=".")
    replay.add_argument("--output", default="")
    replay.add_argument("--json", action="store_true")
    task_report = sub.add_parser("task-prioritization-report")
    task_report.add_argument("--project", default=".")
    task_report.add_argument("--output", default="")
    task_report.add_argument("--json", action="store_true")
    ui = sub.add_parser("ui")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    if args.command == "project-assess":
        result = RetortService().assess({"project": args.project, "run_local_gates": args.run_local_gates, "use_llm": True, "wait_llm_sec": args.wait_llm_sec, "require_deep_review": True})
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _format_scores("Retort assessment", result["scores"]))
        return 0
    if args.command == "self-evolve":
        result = RetortService().self_evolve({"project": args.project, "run_local_gates": args.run_local_gates, "max_rounds": args.max_rounds, "use_llm": True, "wait_llm_sec": args.wait_llm_sec, "require_deep_review": True})
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
        result = review_diff(diff_text, max_comments=args.max_comments, previous_diff_text=previous_diff_text)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Retort diff review status: {result['status']}")
            print(f"Comments: {result['summary']['comment_count']}")
            print(f"Skipped existing changes: {result['summary']['skipped_existing_change_count']}")
        return 0 if result["status"] in {"reviewed", "no_new_changes"} else 1
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
