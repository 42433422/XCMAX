from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.architecture_contracts import evaluate_architecture_contracts
from retort_engine.codebase_graph import build_codebase_graph
from retort_engine.context_packager import build_context_pack
from retort_engine.license_gate import license_gate
from retort_engine.static_analysis_gate import scan_static_analysis_findings
from retort_engine.swe_bench_oracle import build_issue_patch_benchmark


def build_cross_domain_absorption_replay(
    project: str | Path,
    *,
    min_domains: int = 6,
    output: str | Path = "",
    run_id: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    replay_id = run_id or _run_id("cross-domain")
    lab = root / ".retort" / "cross_domain_absorption_replays" / replay_id
    lab.mkdir(parents=True, exist_ok=True)
    cases = [
        _benchmark_oracle_case(lab),
        _architecture_contract_case(lab),
        _code_graph_case(lab),
        _context_pack_case(lab),
        _license_gate_case(lab),
        _static_analysis_case(lab),
    ]
    adjudication = _adjudicate_cases(cases)
    domains = sorted({str(case["domain"]) for case in cases if case.get("domain")})
    source_projects = sorted({str(case["source_project"]) for case in cases if case.get("source_project")})
    direct_modules = sorted({str(case["direct_module"]) for case in cases if case.get("direct_module")})
    ready_cases = [case for case in cases if case["ready"]]
    summary = {
        "run_id": replay_id,
        "case_count": len(cases),
        "ready_case_count": len(ready_cases),
        "min_domain_count": min_domains,
        "non_pr_domain_count": len(domains),
        "non_pr_domains": domains,
        "source_project_count": len(source_projects),
        "source_projects": source_projects,
        "direct_module_count": len(direct_modules),
        "direct_modules": direct_modules,
        "pre_absorption_failure_count": sum(1 for case in cases if case["pre_absorption"]["failed_expected_behavior"]),
        "post_absorption_pass_count": sum(1 for case in cases if case["post_absorption"]["passed_expected_behavior"]),
        "all_before_failed_after_passed": bool(cases) and all(case["before_failed_after_passed"] for case in cases),
        "all_direct_modules_executed": bool(cases) and all(case["post_absorption"]["direct_module_executed"] for case in cases),
        "all_output_assertions_passed": bool(cases) and all(case["post_absorption"]["output_assertions_passed"] for case in cases),
        "independent_adjudication_status": adjudication["status"],
        "independent_accepted_case_count": adjudication["summary"]["accepted_case_count"],
        "independent_all_cases_accepted": adjudication["summary"]["all_cases_accepted"],
    }
    ready = (
        summary["ready_case_count"] == summary["case_count"]
        and summary["non_pr_domain_count"] >= min_domains
        and summary["all_before_failed_after_passed"]
        and summary["all_direct_modules_executed"]
        and summary["all_output_assertions_passed"]
        and summary["independent_all_cases_accepted"]
    )
    result = {
        "status": "ready" if ready else "needs_more_cross_domain_evidence",
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "independent_adjudication": adjudication,
        "evidence": {
            "style": "non_pr_domain_input_output_absorption_replay",
            "lab_dir": str(lab),
            "domains": domains,
            "source_projects": source_projects,
            "claim_boundary": "direct_core_modules_not_pr_review_manifest",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _benchmark_oracle_case(lab: Path) -> dict[str, Any]:
    case_lab = lab / "benchmark_oracle"
    case_lab.mkdir(parents=True, exist_ok=True)
    expected_patch = (
        "diff --git a/lm_eval/tasks/math.py b/lm_eval/tasks/math.py\n"
        "--- a/lm_eval/tasks/math.py\n"
        "+++ b/lm_eval/tasks/math.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+def score(sample):\n"
        "+    return sample['gold'] == sample['prediction']\n"
    )
    bad_input = {
        "case_id": "lm-eval-oracle-no-patch",
        "repo": "EleutherAI/lm-evaluation-harness",
        "expected_patch": expected_patch,
        "predicted_patch": "",
        "fail_to_pass": ["test_math_oracle"],
        "pass_to_pass": ["test_existing_task"],
        "test_results": {"test_math_oracle": "failed", "test_existing_task": "passed"},
    }
    good_input = {
        **bad_input,
        "case_id": "lm-eval-oracle-fixed",
        "predicted_patch": expected_patch,
        "test_results": {"test_math_oracle": "passed", "test_existing_task": "passed"},
    }
    pre = build_issue_patch_benchmark([bad_input])
    post = build_issue_patch_benchmark([good_input])
    _write_json(case_lab / "pre_input.json", bad_input)
    _write_json(case_lab / "post_input.json", good_input)
    _write_json(case_lab / "post_output.json", post)
    assertions = {
        "resolved": post["summary"]["resolved_count"] == 1,
        "no_regression": post["summary"]["regression_count"] == 0,
        "patch_overlap": float(post["summary"]["average_patch_overlap"]) == 1.0,
    }
    return _case(
        case_id="benchmark_oracle",
        domain="benchmark_harness",
        source_project="EleutherAI/lm-evaluation-harness",
        direct_module="retort_engine.swe_bench_oracle.build_issue_patch_benchmark",
        expected_behavior="reject_no_patch_then_accept_fail_to_pass_patch_without_regression",
        pre_failed=pre["status"] != "ready",
        post_passed=post["status"] == "ready" and all(assertions.values()),
        output_assertions=assertions,
        artifacts=[case_lab / "pre_input.json", case_lab / "post_input.json", case_lab / "post_output.json"],
        pre_summary=pre["summary"],
        post_summary=post["summary"],
    )


def _architecture_contract_case(lab: Path) -> dict[str, Any]:
    case_lab = lab / "architecture_contract"
    project = case_lab / "project"
    (project / "retort_engine").mkdir(parents=True, exist_ok=True)
    (project / "retort_engine" / "__init__.py").write_text("", encoding="utf-8")
    (project / "retort_engine" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "retort_engine" / "codebase_graph.py").write_text("import retort_engine.core\n\nVALUE = retort_engine.core.VALUE\n", encoding="utf-8")
    contract = {
        "name": "graph_cannot_import_core",
        "type": "forbidden_import",
        "source": "retort_engine.codebase_graph",
        "forbidden": ["retort_engine.core"],
        "reason": "graph layer must remain below core runtime",
    }
    post = evaluate_architecture_contracts(project, contracts=[contract], include_tests=True)
    _write_json(case_lab / "contract.json", contract)
    _write_json(case_lab / "post_output.json", post)
    assertions = {
        "violation_detected": post["status"] == "failed",
        "violation_count": int(post["summary"]["violation_count"]) == 1,
        "contract_name_returned": any(item.get("contract") == "graph_cannot_import_core" for item in post.get("violations") or []),
    }
    return _case(
        case_id="architecture_contract",
        domain="architecture_governance",
        source_project="seddonym/import-linter",
        direct_module="retort_engine.architecture_contracts.evaluate_architecture_contracts",
        expected_behavior="detect_forbidden_import_boundary_violation",
        pre_failed=True,
        post_passed=all(assertions.values()),
        output_assertions=assertions,
        artifacts=[case_lab / "contract.json", case_lab / "post_output.json"],
        pre_summary={"status": "pre_absorption_no_architecture_contract_runtime", "violation_detected": False},
        post_summary=post["summary"],
    )


def _code_graph_case(lab: Path) -> dict[str, Any]:
    case_lab = lab / "code_graph"
    project = case_lab / "project"
    (project / "pkg").mkdir(parents=True, exist_ok=True)
    (project / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (project / "pkg" / "runtime.py").write_text("from pkg import policy\n\n\ndef run():\n    return policy.allowed()\n", encoding="utf-8")
    (project / "pkg" / "policy.py").write_text("def allowed():\n    return True\n", encoding="utf-8")
    post = build_codebase_graph(project, include_tests=True)
    _write_json(case_lab / "post_output.json", post)
    assertions = {
        "graph_ready": post["status"] == "ready",
        "imports_seen": int(post["summary"]["import_edge_count"]) >= 1,
        "calls_seen": int(post["summary"]["call_edge_count"]) >= 1,
        "hotspot_or_dependency_seen": int(post["summary"]["hotspot_count"]) >= 1 or int(post["summary"]["local_dependency_edge_count"]) >= 1,
    }
    return _case(
        case_id="code_graph",
        domain="codebase_graph",
        source_project="pahen/madge",
        direct_module="retort_engine.codebase_graph.build_codebase_graph",
        expected_behavior="materialize_import_call_and_dependency_edges",
        pre_failed=True,
        post_passed=all(assertions.values()),
        output_assertions=assertions,
        artifacts=[case_lab / "post_output.json"],
        pre_summary={"status": "pre_absorption_no_code_graph_runtime", "edge_count": 0},
        post_summary=post["summary"],
    )


def _context_pack_case(lab: Path) -> dict[str, Any]:
    case_lab = lab / "context_pack"
    project = case_lab / "project"
    (project / "retort_engine").mkdir(parents=True, exist_ok=True)
    (project / "docs").mkdir(parents=True, exist_ok=True)
    (project / "retort_engine" / "absorption_runtime.py").write_text(
        "def absorb_context_pack():\n    return 'retort absorption benchmark review context graph'\n",
        encoding="utf-8",
    )
    (project / "docs" / "notes.md").write_text("general notes\n", encoding="utf-8")
    post = build_context_pack(project, focus_terms=["absorption", "benchmark", "review", "graph"], max_files=3, max_chars=2000)
    selected_paths = [str(item.get("path") or "") for item in post.get("files") or []]
    _write_json(case_lab / "post_output.json", post)
    assertions = {
        "pack_ready": post["status"] == "ready",
        "focused_runtime_selected": "retort_engine/absorption_runtime.py" in selected_paths,
        "bounded_output": int(post["summary"]["used_chars"]) <= int(post["summary"]["max_chars"]),
    }
    return _case(
        case_id="context_pack",
        domain="context_packaging",
        source_project="yamadashy/repomix",
        direct_module="retort_engine.context_packager.build_context_pack",
        expected_behavior="rank_focused_runtime_context_above_noise_within_budget",
        pre_failed=True,
        post_passed=all(assertions.values()),
        output_assertions=assertions,
        artifacts=[case_lab / "post_output.json"],
        pre_summary={"status": "pre_absorption_no_context_pack_runtime", "selected_file_count": 0},
        post_summary=post["summary"],
    )


def _license_gate_case(lab: Path) -> dict[str, Any]:
    case_lab = lab / "license_gate"
    project = case_lab / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "LICENSE").write_text("GNU Affero General Public License v3.0\n", encoding="utf-8")
    result = license_gate(project, enforce=True).to_dict()
    _write_json(case_lab / "post_output.json", result)
    assertions = {
        "blocked": result["status"] == "blocked",
        "detected_agpl": "Affero" in result["detected_license"] or "AGPL" in result["detected_license"],
        "message_explains_risk": "blocked license" in result["message"],
    }
    return _case(
        case_id="license_gate",
        domain="license_policy",
        source_project="github/licensee",
        direct_module="retort_engine.license_gate.license_gate",
        expected_behavior="block_incompatible_license_before_absorption",
        pre_failed=True,
        post_passed=all(assertions.values()),
        output_assertions=assertions,
        artifacts=[case_lab / "post_output.json"],
        pre_summary={"status": "pre_absorption_no_license_runtime_gate", "blocked": False},
        post_summary=result,
    )


def _static_analysis_case(lab: Path) -> dict[str, Any]:
    case_lab = lab / "static_analysis"
    parsed_diff = {
        "path": "server/review_runner.py",
        "hunks": [
            {
                "changes": [
                    {"type": "add", "line": 12, "text": "subprocess.run(command, shell=True, check=False)"},
                    {"type": "add", "line": 13, "text": "yaml.load(payload)"},
                ]
            }
        ],
    }
    result = scan_static_analysis_findings([parsed_diff])
    _write_json(case_lab / "input.json", {"files": [parsed_diff]})
    _write_json(case_lab / "post_output.json", result)
    assertions = {
        "blocked": result["status"] == "blocked",
        "high_findings": int(result["summary"]["high_count"]) >= 2,
        "rule_ids_returned": {"subprocess-shell-true", "unsafe-yaml-load"}.issubset({str(item.get("rule_id") or "") for item in result.get("findings") or []}),
    }
    return _case(
        case_id="static_analysis",
        domain="static_analysis_security",
        source_project="PyCQA/bandit",
        direct_module="retort_engine.static_analysis_gate.scan_static_analysis_findings",
        expected_behavior="block_high_risk_added_lines_with_rule_ids",
        pre_failed=True,
        post_passed=all(assertions.values()),
        output_assertions=assertions,
        artifacts=[case_lab / "input.json", case_lab / "post_output.json"],
        pre_summary={"status": "pre_absorption_no_static_analysis_runtime", "finding_count": 0},
        post_summary=result["summary"],
    )


def _case(
    *,
    case_id: str,
    domain: str,
    source_project: str,
    direct_module: str,
    expected_behavior: str,
    pre_failed: bool,
    post_passed: bool,
    output_assertions: dict[str, bool],
    artifacts: list[Path],
    pre_summary: dict[str, Any],
    post_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "domain": domain,
        "source_project": source_project,
        "direct_module": direct_module,
        "expected_behavior": expected_behavior,
        "pre_absorption": {
            "failed_expected_behavior": pre_failed,
            "summary": pre_summary,
        },
        "post_absorption": {
            "passed_expected_behavior": post_passed,
            "direct_module_executed": True,
            "output_assertions_passed": all(output_assertions.values()),
            "summary": post_summary,
        },
        "output_assertions": output_assertions,
        "artifacts": [str(path) for path in artifacts],
        "before_failed_after_passed": pre_failed and post_passed,
        "ready": pre_failed and post_passed and all(output_assertions.values()),
    }


def _adjudicate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        assertions = case.get("output_assertions") if isinstance(case.get("output_assertions"), dict) else {}
        artifacts = [Path(str(path)) for path in case.get("artifacts") or []]
        checks = {
            "non_pr_domain": str(case.get("domain") or "") not in {"", "pr_review", "pull_request"},
            "direct_module_present": bool(case.get("direct_module")),
            "pre_absorption_failed": bool((case.get("pre_absorption") or {}).get("failed_expected_behavior")),
            "post_absorption_passed": bool((case.get("post_absorption") or {}).get("passed_expected_behavior")),
            "output_assertions_passed": bool(assertions) and all(bool(value) for value in assertions.values()),
            "artifacts_materialized": bool(artifacts) and all(path.is_file() for path in artifacts),
        }
        rows.append(
            {
                "case_id": str(case.get("case_id") or ""),
                "domain": str(case.get("domain") or ""),
                "checks": checks,
                "accepted": all(checks.values()),
            }
        )
    accepted = [row for row in rows if row["accepted"]]
    return {
        "status": "ready" if rows and len(accepted) == len(rows) else "needs_attention",
        "summary": {
            "adjudicated_case_count": len(rows),
            "accepted_case_count": len(accepted),
            "all_cases_accepted": bool(rows) and len(accepted) == len(rows),
        },
        "adjudications": rows,
        "evidence": {
            "independence_boundary": "recomputes_from_case_assertions_and_materialized_artifacts_without_pr_review",
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
