#!/usr/bin/env python3
"""Evaluate evidence-bound ETL document understanding without business writes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_MANIFEST = ROOT / "tests" / "fixtures" / "network_forms" / "document_eval_manifest.json"


def _roles(documents: list[dict[str, Any]], key: str) -> set[str]:
    result: set[str] = set()
    for document in documents:
        if key == "header":
            result.update(
                str(item.get("role") or "")
                for item in document.get("header_fields") or []
                if isinstance(item, dict)
            )
            continue
        for table in document.get("tables") or []:
            if not isinstance(table, dict):
                continue
            result.update(
                str(item.get("role") or "")
                for item in table.get("columns") or []
                if isinstance(item, dict)
            )
    return {item for item in result if item and item != "other"}


def evaluate(manifest_path: Path, *, require_llm: bool) -> dict[str, Any]:
    from app.application.etl.document_understanding import understand_workbook
    from app.application.etl.target_detection import detect_etl_target

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    fixture_dir = manifest_path.parent
    for case in manifest.get("cases") or []:
        path = fixture_dir / str(case["file"])
        detection = detect_etl_target(path, suffix=path.suffix)
        plan = understand_workbook(
            path,
            hinted_target_type=str(detection.get("target_type") or "export_xlsx"),
            hint_confidence=float(detection.get("confidence") or 0.0),
        )
        documents = list(plan.get("documents") or [])
        actual_types = {str(document.get("document_type") or "") for document in documents}
        expected_types = set(case.get("expected_document_types") or [])
        header_roles = _roles(documents, "header")
        column_roles = _roles(documents, "column")
        checks = {
            "llm_used": plan.get("source") == "llm",
            "document_type": bool(actual_types & expected_types),
            "document_count": len(documents) >= int(case.get("minimum_documents") or 1),
            "header_roles": set(case.get("required_header_roles") or []).issubset(header_roles),
            "column_roles": set(case.get("required_column_roles") or []).issubset(column_roles),
            "confirmation_gate": plan.get("requires_confirmation") is True,
        }
        passed = all(value for key, value in checks.items() if key != "llm_used" or require_llm)
        results.append(
            {
                "file": path.name,
                "source_kind": case.get("source_kind"),
                "understanding_source": plan.get("source"),
                "expected_types": sorted(expected_types),
                "actual_types": sorted(actual_types),
                "document_count": len(documents),
                "header_roles": sorted(header_roles),
                "column_roles": sorted(column_roles),
                "recommended_target_type": plan.get("recommended_target_type"),
                "checks": checks,
                "passed": passed,
            }
        )
    return {
        "manifest": str(manifest_path),
        "require_llm": require_llm,
        "passed": sum(1 for item in results if item["passed"]),
        "total": len(results),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--llm",
        choices=("auto", "on", "off"),
        default="auto",
        help="Select the software-account LLM mode for this read-only evaluation.",
    )
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="Fail cases whose semantic plan did not come from the LLM.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["FHD_ETL_LLM"] = args.llm
    report = evaluate(args.manifest.resolve(), require_llm=args.require_llm)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
