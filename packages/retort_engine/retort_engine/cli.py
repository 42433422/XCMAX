from __future__ import annotations

import argparse
import json
import sys

from retort_engine.core import RetortSelfEvolutionRunner, RetortService, absorb, assess_project, record_closed_loop_proof
from retort_engine.real_absorption import apply_real_absorption
from retort_engine.ui_server import run_ui_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retort")
    sub = parser.add_subparsers(dest="command", required=True)
    assess = sub.add_parser("project-assess")
    assess.add_argument("--project", default=".")
    assess.add_argument("--run-local-gates", action="store_true")
    assess.add_argument("--use-llm", action="store_true")
    assess.add_argument("--wait-llm-sec", type=float, default=0)
    assess.add_argument("--json", action="store_true")
    evolve = sub.add_parser("self-evolve")
    evolve.add_argument("--project", default=".")
    evolve.add_argument("--run-local-gates", action="store_true")
    evolve.add_argument("--max-rounds", type=int, default=8)
    evolve.add_argument("--use-llm", action="store_true")
    evolve.add_argument("--wait-llm-sec", type=float, default=0)
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
    ui = sub.add_parser("ui")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    if args.command == "project-assess":
        if args.use_llm:
            result = RetortService().assess({"project": args.project, "run_local_gates": args.run_local_gates, "use_llm": True, "wait_llm_sec": args.wait_llm_sec})
        else:
            result = assess_project(args.project, run_local_gates=args.run_local_gates).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _format_scores("Retort assessment", result["scores"]))
        return 0
    if args.command == "self-evolve":
        if args.use_llm:
            result = RetortService().self_evolve({"project": args.project, "run_local_gates": args.run_local_gates, "max_rounds": args.max_rounds, "use_llm": True, "wait_llm_sec": args.wait_llm_sec})
        else:
            result = RetortSelfEvolutionRunner(max_rounds=args.max_rounds).run(args.project, run_local_gates=args.run_local_gates)
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
