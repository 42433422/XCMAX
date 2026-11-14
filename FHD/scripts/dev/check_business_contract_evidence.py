#!/usr/bin/env python3
"""业务契约目录与执行证据校验。

``catalog`` 只检查契约形状，以及必跑场景没有被从目录里拿掉。
``ci-gate`` 只接受本次分片 JUnit 里的结果，不读取手写的 PASS。
后端被分类器跳过时，必跑场景记为 NOT APPLICABLE，不能记成 PASS。
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
CATALOG = FHD_ROOT / "config" / "business_contracts.json"
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT RUN", "NOT APPLICABLE"}
MINIMUM_REQUIRED = (
    "R08-e23-readback",
    "R05-approved-shipment-export",
    "R04-export-submitted-result",
    "R03-confirm-binding",
    "R02-empty-preview",
    "R07-same-key-different-params",
    "R09-two-recoveries",
    "R10-tenant-scope",
)
REQUIRED_TESTS = {
    "R08-e23-readback": (
        "tests/test_application/test_idempotency_recovery_e23_e24.py"
        "::test_e23_kill_after_commit_returns_the_same_row"
    ),
    "R05-approved-shipment-export": (
        "tests/test_application/test_shipment_records_agent_routes.py"
        "::test_approved_shipment_then_export_uses_full_persisted_plan"
    ),
    "R02-empty-preview": (
        "tests/test_application/test_etl_preview_task_boundaries.py"
        "::test_empty_preview_is_not_confirmable"
    ),
    "R07-same-key-different-params": (
        "tests/test_application/test_idempotency_recovery_e23_e24.py"
        "::test_same_key_with_different_phone_does_not_reuse_the_row"
    ),
    "R09-two-recoveries": (
        "tests/test_application/test_idempotency_recovery_e23_e24.py"
        "::test_e24_two_recoveries_leave_one_row"
    ),
    "R04-export-submitted-result": (
        "tests/test_application/test_shipment_records_agent_routes.py"
        "::test_approved_shipment_then_export_uses_full_persisted_plan"
    ),
    "R03-confirm-binding": (
        "tests/test_application/test_etl_preview_confirmation.py"
        "::test_missing_or_wrong_approval_does_not_write_or_claim_run"
    ),
    "R10-tenant-scope": (
        "tests/test_application/test_etl_knowledge_isolation.py"
        "::test_identical_content_in_two_tenants_never_replaces_first"
    ),
}


def load_catalog(path: Path | None = None) -> dict:
    target = path or CATALOG
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("contracts"), list):
        raise ValueError("catalog is not an object with contracts")
    return data


def catalog_errors(data: dict) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    required: set[str] = set()
    for item in data.get("contracts") or []:
        if not isinstance(item, dict):
            errors.append("contract entry is not an object")
            continue
        scenario_id = str(item.get("scenario_id") or "")
        if not scenario_id or scenario_id in seen:
            errors.append(f"missing or duplicate scenario_id: {scenario_id}")
        seen.add(scenario_id)
        for field in (
            "requirement_id",
            "rule",
            "source",
            "preconditions",
            "inputs",
            "allowed",
            "forbidden_effects",
            "oracle",
            "tests",
            "boundary",
            "fault_version",
            "platforms",
            "database_modes",
            "required_for_merge",
        ):
            if field not in item:
                errors.append(f"{scenario_id}: missing {field}")
        boundary = item.get("boundary") if isinstance(item.get("boundary"), dict) else {}
        execution = boundary.get("execution")
        if item.get("required_for_merge") is True:
            required.add(scenario_id)
            if execution != "real":
                errors.append(f"{scenario_id}: required scenario is not a real execution")
            if not item.get("tests"):
                errors.append(f"{scenario_id}: required scenario has no test")
        elif execution == "PASS":
            errors.append(f"{scenario_id}: catalog cannot declare PASS")
    missing = [item for item in MINIMUM_REQUIRED if item not in required]
    if missing:
        errors.append("required scenarios removed: " + ", ".join(missing))
    wired = {
        test
        for item in data.get("contracts") or []
        if isinstance(item, dict) and item.get("scenario_id") in MINIMUM_REQUIRED
        for test in item.get("tests") or []
    }
    for scenario_id, node_id in REQUIRED_TESTS.items():
        if node_id not in wired:
            errors.append(f"required test removed: {scenario_id} {node_id}")
    return errors


def floor_errors(floor: dict) -> list[str]:
    """Fail when this change drops a scenario or test that the floor still requires.

    CI loads the floor from ``origin/main`` once that file exists there. Editing
    the copy in the pull request does not replace that floor.
    """
    errors: list[str] = []
    required = floor.get("required_scenarios")
    tests = floor.get("required_tests")
    if not isinstance(required, list) or not isinstance(tests, dict):
        return ["floor file is missing required_scenarios or required_tests"]
    for scenario_id in required:
        if scenario_id not in MINIMUM_REQUIRED:
            errors.append(f"main still requires {scenario_id}")
    for scenario_id, node_id in tests.items():
        if REQUIRED_TESTS.get(str(scenario_id)) != node_id:
            errors.append(f"main still requires {scenario_id} {node_id}")
    return errors


def _case_status(case: ET.Element) -> tuple[str, str]:
    for child in case:
        if child.tag == "failure":
            return "FAIL", (child.get("message") or child.text or "failed").strip()
        if child.tag == "error":
            return "FAIL", (child.get("message") or child.text or "error").strip()
        if child.tag == "skipped":
            return "NOT RUN", (child.get("message") or "skipped").strip()
    return "PASS", ""


def junit_attempts(paths: list[Path], node_id: str) -> list[dict]:
    module, _, name = node_id.partition("::")
    module_tail = module[:-3].replace("/", ".") if module.endswith(".py") else module
    attempts: list[dict] = []
    for path in paths:
        root = ET.fromstring(path.read_bytes())
        for case in root.iter("testcase"):
            case_name = case.get("name") or ""
            classname = case.get("classname") or case.get("file") or ""
            if not case_name.startswith(name):
                continue
            if module_tail not in classname and module not in classname:
                continue
            status, detail = _case_status(case)
            attempts.append(
                {
                    "n": len(attempts) + 1,
                    "status": status,
                    "failure": detail,
                    "evidence_path": str(path),
                }
            )
    return attempts


def scenario_from_attempts(scenario_id: str, attempts: list[dict]) -> dict:
    if not attempts:
        status = "NOT RUN"
    elif any(item["status"] != "PASS" for item in attempts):
        status = "FAIL" if any(item["status"] == "FAIL" for item in attempts) else "NOT RUN"
    else:
        status = "PASS"
    return {"scenario_id": scenario_id, "status": status, "attempts": attempts}


def validate(
    evidence: dict, *, expected_sha: str, required_ids: tuple[str, ...], allow_not_applicable: bool
) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, dict):
        return ["evidence is not an object"]
    if evidence.get("source_sha") != expected_sha or not expected_sha:
        errors.append("source sha does not match the candidate")
    scenarios = evidence.get("scenarios")
    if not isinstance(scenarios, list):
        return errors + ["scenarios missing"]
    by_id = {}
    for item in scenarios:
        if not isinstance(item, dict) or not item.get("scenario_id"):
            errors.append("scenario entry is damaged")
            continue
        by_id[item["scenario_id"]] = item
    for scenario_id in required_ids:
        item = by_id.get(scenario_id)
        if item is None:
            errors.append(f"{scenario_id}: no result")
            continue
        status = item.get("status")
        attempts = item.get("attempts")
        if status not in STATUSES or not isinstance(attempts, list):
            errors.append(f"{scenario_id}: damaged result")
            continue
        if (
            status == "FAIL"
            or status in {"NOT RUN", "BLOCKED"}
            or (status == "NOT APPLICABLE" and not allow_not_applicable)
        ):
            errors.append(f"{scenario_id}: {status} is not PASS")
        if status == "NOT APPLICABLE" and not str(item.get("reason") or "").strip():
            errors.append(f"{scenario_id}: NOT APPLICABLE without a reason")
        if status == "PASS":
            if not attempts or any(entry.get("status") != "PASS" for entry in attempts):
                errors.append(f"{scenario_id}: PASS hides an earlier or missing failure")
            if attempts and attempts[0].get("status") != "PASS":
                errors.append(f"{scenario_id}: first result was not kept")
    return errors


def evidence_from_junit(
    paths: list[Path], *, source_sha: str, run_id: str, run_attempt: str
) -> dict:
    return {
        "source_sha": source_sha,
        "test_sha": source_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "platform": "github-actions",
        "database_mode": "sqlite",
        "configuration": {"process": "spawn", "database": "temporary sqlite"},
        "real": ["sqlite", "approval resume", "inventory", "shipment rows", "xlsx"],
        "doubles": ["fixed approval plan"],
        "scenarios": [
            scenario_from_attempts(scenario_id, junit_attempts(paths, node_id))
            for scenario_id, node_id in REQUIRED_TESTS.items()
        ],
    }


def not_applicable_evidence(*, source_sha: str, run_id: str, run_attempt: str, reason: str) -> dict:
    return {
        "source_sha": source_sha,
        "test_sha": source_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "platform": "github-actions",
        "database_mode": "not-started",
        "configuration": {},
        "real": [],
        "doubles": [],
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "status": "NOT APPLICABLE",
                "reason": reason,
                "attempts": [],
            }
            for scenario_id in MINIMUM_REQUIRED
        ],
    }


def ci_gate(shards: Path, *, source_sha: str, run_id: str, run_attempt: str, backend: str) -> dict:
    if backend == "skipped":
        evidence = not_applicable_evidence(
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            reason="change classifier found no backend-relevant paths; the scenario was not started",
        )
        errors = validate(
            evidence,
            expected_sha=source_sha,
            required_ids=MINIMUM_REQUIRED,
            allow_not_applicable=True,
        )
    else:
        reports = sorted(shards.glob("**/full.xml"))
        if not reports:
            raise ValueError("backend ran but no junit evidence was produced")
        evidence = evidence_from_junit(
            reports,
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
        )
        errors = validate(
            evidence,
            expected_sha=source_sha,
            required_ids=MINIMUM_REQUIRED,
            allow_not_applicable=False,
        )
    if errors:
        raise ValueError("; ".join(errors))
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    floor = sub.add_parser("floor")
    floor.add_argument("--floor", type=Path, required=True)
    gate = sub.add_parser("ci-gate")
    gate.add_argument("--source-sha", required=True)
    gate.add_argument("--run-id", required=True)
    gate.add_argument("--run-attempt", required=True)
    gate.add_argument("--shards", type=Path, default=Path("shards"))
    gate.add_argument("--backend", choices=["ran", "skipped"], required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            errors = catalog_errors(load_catalog())
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"business contracts ok: required={','.join(MINIMUM_REQUIRED)}")
            return 0
        if args.command == "floor":
            errors = floor_errors(json.loads(args.floor.read_text(encoding="utf-8")))
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"business contract floor held: required={','.join(MINIMUM_REQUIRED)}")
            return 0
        evidence = ci_gate(
            args.shards,
            source_sha=args.source_sha,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            backend=args.backend,
        )
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"business contract evidence rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
