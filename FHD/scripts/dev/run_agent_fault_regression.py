"""Run WG10's existing fault paths; require original live-model receipts for acceptance.

--faults-only is the credential-free PR lane. It never declares WG10 accepted.
The default also verifies the existing protected-main 13x3 holdout artifacts;
it does not create credentials, qualify a route or substitute a model response.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

from defusedxml import ElementTree

ROOT = Path(__file__).resolve().parents[2]
APP = "tests/test_application/"
WORKERS = APP + "test_agent_worker_fault_injection.py"
STATES = APP + "test_agent_state_fault_properties.py"
CASES = {
    "J01": ("tests/stability/test_model_transport_faults.py",),
    "J02": ("tests/stability/test_continuity_fault_injection.py",),
    "J03": (
        WORKERS + "::test_random_checkpoint_kill_preserves_progress_and_has_one_takeover",
        APP
        + "test_native_task_recovery.py::test_process_exit_real_startup_resumes_native_checkpoint_without_repeating_receipt",
        APP
        + "test_native_task_recovery.py::test_restart_preserves_exact_queued_approval_before_first_write",
    ),
    "J04": (WORKERS + "::test_sqlite_write_lock_retries_in_dispatcher_without_losing_task",),
    "J05": (
        APP + "test_idempotency_recovery_e23_e24.py",
        APP + "test_tool_idempotency.py",
    ),
    "J06": (
        WORKERS + "::test_random_checkpoint_kill_preserves_progress_and_has_one_takeover",
        APP
        + "test_task_execution_repository.py::test_independent_processes_cannot_claim_the_same_run",
    ),
    "J07": (STATES + "::TestDurableLifecycleFaultMachine",),
    "J08": (
        STATES + "::test_cancel_fences_late_result_after_sql_reconnect",
        STATES + "::test_nonterminal_pause_allows_fresh_control_generation",
        APP
        + "test_xiaox_queued_runtime.py::test_control_after_claim_does_not_let_generation_zero_start",
    ),
    "J09": (
        APP + "test_stale_run_reconciler.py",
        APP + "test_stale_handoff_recovery.py",
        APP + "test_xiaox_queued_runtime.py",
        APP + "test_xiaox_goal_verifier.py",
        APP + "test_xiaox_goal_source_evidence.py",
        APP + "test_xiaox_goal_verifier_transport.py",
        APP + "test_conversation_turn_receipts.py",
        APP
        + "test_native_task_recovery_receipts.py::test_concurrent_retry_preserves_original_write_receipt_and_atomically_requeues_same_run",
        APP + "test_agent_run_repository.py",
        APP + "test_chat_stream_run_interruption.py",
    ),
}
_DESELECTED = 0


def pytest_deselected(items):
    global _DESELECTED
    _DESELECTED += len(items)


def pytest_collection_finish(session):
    """Native pytest hook: record the exact matrix before execution."""
    destination = os.environ.get("XCAGI_FAULT_COLLECTION_PATH")
    if destination:
        Path(destination).write_text(
            json.dumps(
                {"nodes": [item.nodeid for item in session.items], "deselected": _DESELECTED}
            ),
            encoding="utf-8",
        )


def selectors() -> list[str]:
    selected = {selector for group in CASES.values() for selector in group}
    return sorted(s for s in selected if "::" not in s or s.split("::")[0] not in selected)


def _matches(case, selector: str) -> bool:
    module, *names = selector.split("::")
    prefix = ".".join([module.removesuffix(".py").replace("/", "."), *names])
    actual = case.attrib.get("classname", "") + "." + case.attrib.get("name", "").split("[")[0]
    return actual == prefix or actual.startswith(prefix + ".")


def summarize_faults(path: Path, collection: Path) -> dict:
    """Reject omissions, skips, xfails and failures using native pytest JUnit."""
    cases = list(ElementTree.parse(path).getroot().iter("testcase"))
    collected = json.loads(collection.read_text())
    expected_ids = {
        ".".join([parts[0].removesuffix(".py").replace("/", "."), *parts[1:]])
        for node in collected["nodes"]
        if isinstance(node, str)
        for parts in [node.split("::")]
    }
    actual_ids = [
        case.attrib.get("classname", "") + "." + case.attrib.get("name", "") for case in cases
    ]
    if (
        collected["deselected"] != 0
        or not expected_ids
        or len(expected_ids) != len(collected["nodes"])
        or len(actual_ids) != len(expected_ids)
        or set(actual_ids) != expected_ids
    ):
        raise ValueError("fault matrix was deselected, duplicated or not completely executed")
    groups = {}
    for key, expected in CASES.items():
        selected = [case for case in cases if any(_matches(case, item) for item in expected)]
        missing = [item for item in expected if not any(_matches(case, item) for case in cases)]
        failed = sum(
            case.find("failure") is not None or case.find("error") is not None for case in selected
        )
        skipped = sum(case.find("skipped") is not None for case in selected)
        groups[key] = {
            "status": "FAIL" if failed else "BLOCKED" if missing or skipped else "PASS",
            "tests": len(selected),
            "failed": failed,
            "skipped": skipped,
            "missing": missing,
        }
    return groups


def verify_real_model(directory: Path, source_sha: str) -> dict:
    from scripts.dev.verify_task_benchmark_evidence import write_task_evidence

    previous = os.environ.get("XCAGI_BENCHMARK_REPORT_DIR")
    os.environ["XCAGI_BENCHMARK_REPORT_DIR"] = str(directory)
    try:
        marker = write_task_evidence("holdout", minimum=0.4)
    finally:
        if previous is None:
            os.environ.pop("XCAGI_BENCHMARK_REPORT_DIR", None)
        else:
            os.environ["XCAGI_BENCHMARK_REPORT_DIR"] = previous
    if (
        marker["status"] != "VERIFIED"
        or marker["gate_passed"] is not True
        or marker["execution_mode"] != "model_workflow"
        or marker["evidence"]["total_tasks"] != 13
        or marker["evidence"]["trials"] != 3
        or marker["source_sha"] != source_sha
    ):
        raise ValueError(
            "J10 requires the same-source original complete 13x3 real-model acceptance gate"
        )
    return {"status": "PASS", "evidence": marker["evidence"], "source_sha": marker["source_sha"]}


def run_pytest(command: list[str], environment: dict[str, str]) -> int:
    import psutil

    with subprocess.Popen(command, cwd=ROOT, env=environment) as process:
        owned = psutil.Process(process.pid)
        try:
            return process.wait(timeout=1200)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Only this invocation's Process identities; never a machine-wide
            # worker name/PID search. Leave enough room inside the CI job limit.
            try:
                owned.suspend()
                children = owned.children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            for child in [*reversed(children), owned]:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            process.wait(timeout=5)
            psutil.wait_procs(children, timeout=5)
            return 124


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--faults-only", action="store_true", help="PR evidence only; J10 remains BLOCKED"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "test_reports/agent_fault_regression")
    parser.add_argument("--model-reports", type=Path, default=ROOT / "test_reports")
    args = parser.parse_args(argv)
    from scripts.dev.benchmark_evidence import evidence_identity, trial_artifact

    args.output.mkdir(parents=True, exist_ok=True)
    junit = args.output.resolve() / "faults-junit.xml"
    collection = args.output.resolve() / "faults-collected.json"
    report_path = args.output.resolve() / "wg10.json"
    for path in (junit, collection, report_path):
        path.unlink(missing_ok=True)
    identity = evidence_identity(Path(__file__), execution_mode="fault_injection")
    versions = {
        name: importlib.metadata.version(name)
        for name in ("pytest", "hypothesis", "sqlalchemy", "httpx", "langgraph")
    }
    # Resolve vendored packages from this checkout, even with editable installs
    # pointing to another worktree. Pytest owns the isolated DB/tool fixtures.
    packages = ROOT / "packages"
    module_paths = [ROOT, *sorted(packages.glob("xcagi_langgraph_*"))]
    module_paths.extend(
        sorted((packages / "xcagi_langgraph_checkpoint_backends").glob("checkpoint-*"))
    )
    environment = {
        **os.environ,
        "REQUIRE_RESILIENCE_TOOLS": "1",
        "XCAGI_SKIP_INTENT_LLM": "1",
        "PYTEST_ADDOPTS": "",
        "XCAGI_FAULT_COLLECTION_PATH": str(collection),
        "PYTHONPATH": os.pathsep.join(map(str, module_paths)),
    }
    exit_code = run_pytest(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.dev.run_agent_fault_regression",
            "-o",
            "addopts=-p no:xdist --import-mode=importlib",
            "-o",
            "xfail_strict=true",
            *selectors(),
            "-q",
            "--no-cov",
            "--tb=short",
            f"--junitxml={junit}",
        ],
        environment,
    )
    try:
        groups = summarize_faults(junit, collection)
    except (OSError, ValueError, KeyError, TypeError, ElementTree.ParseError) as error:
        groups = {key: {"status": "BLOCKED", "reason": str(error)} for key in CASES}
    after = evidence_identity(Path(__file__), execution_mode="fault_injection")
    unchanged = all(identity[key] == after[key] for key in ("source_sha", "dataset_sha256"))
    faults_passed = (
        exit_code == 0 and unchanged and all(g["status"] == "PASS" for g in groups.values())
    )
    groups["J10"] = {"status": "BLOCKED", "reason": "live_model_evidence_not_requested"}
    if not args.faults_only:
        try:
            groups["J10"] = verify_real_model(args.model_reports.resolve(), identity["source_sha"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            groups["J10"] = {"status": "BLOCKED", "reason": str(error)}
    final = evidence_identity(Path(__file__), execution_mode="fault_injection")
    clean = (
        unchanged
        and not any(stage["tracked_source_dirty"] for stage in (identity, after, final))
        and all(identity[key] == final[key] for key in ("source_sha", "dataset_sha256"))
    )
    accepted = faults_passed and clean and groups["J10"]["status"] == "PASS"
    report = {
        **identity,
        "tracked_source_dirty": not clean,
        "scope": "WG10 fault regressions; excludes long-running production acceptance",
        "versions": versions,
        "pytest_exit_code": exit_code,
        "junit": trial_artifact(junit) if junit.is_file() else None,
        "collection": trial_artifact(collection) if collection.is_file() else None,
        "groups": groups,
        "faults_passed": faults_passed,
        "wg10_accepted": accepted,
        "status": "PASS" if accepted else "FAIL" if not faults_passed else "BLOCKED",
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"faults_passed": faults_passed, "wg10_accepted": accepted, "report": str(report_path)}
        )
    )
    return 0 if accepted or (args.faults_only and faults_passed) else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
