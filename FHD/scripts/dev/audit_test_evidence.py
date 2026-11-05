"""Read JUnit cases, not aggregate success labels; strict acceptance rejects skips.

Usage: python scripts/dev/audit_test_evidence.py report.xml [report2.xml ...]
Repeat --required 'classname::name' for mandatory cases. This checks recorded
results only, not whether the tested artifact was installed or externally audited.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

MAX_REPORT_BYTES = 10 * 1024 * 1024
_OUTCOMES = {"failure": "failed", "error": "errors", "skipped": "skipped"}
# Standard JUnit omits these attributes; GoogleTest emits run/completed.
_EXECUTED = {
    "status": {"run", "passed", "success", "completed"},
    "result": {"completed", "passed", "success"},
}


def inspect_reports(paths: list[Path], required: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a fail-closed accounting of every recorded case and collection skip."""
    cases: list[dict[str, str]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_REPORT_BYTES + 1)
            if len(raw) > MAX_REPORT_BYTES:
                raise ValueError("report exceeds size limit")
            if b"\x00" in raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("DTD/entity declarations are not accepted")
            root = ET.fromstring(raw)
            if root.tag not in {"testsuite", "testsuites"}:
                raise ValueError("expected testsuite or testsuites")
            report_cases = list(root.iter("testcase"))
            if not report_cases:
                raise ValueError("report contains no test cases")
            for parent in root.iter():
                if parent.tag != "testcase" and any(child.tag in _OUTCOMES for child in parent):
                    problems.append(f"{path.name}: outcome outside a test case")
            for suite in root.iter():
                if suite.tag not in {"testsuite", "testsuites"}:
                    continue
                children = list(suite.iter("testcase"))
                actual = {"tests": len(children)}
                actual.update(
                    {
                        key: sum(c.find(tag) is not None for c in children)
                        for tag, key in (
                            ("failure", "failures"),
                            ("error", "errors"),
                            ("skipped", "skipped"),
                        )
                    }
                )
                for key, count in actual.items():
                    if key in suite.attrib and int(suite.attrib[key]) != count:
                        problems.append(f"{path.name}: declared {key} does not match cases")
            for case in report_cases:
                name = case.get("name", "").strip()
                scope = (case.get("classname") or case.get("file") or "").strip()
                outcomes = [child for child in case if child.tag in _OUTCOMES]
                identity = f"{scope}::{name}"
                if (not name or not scope) and outcomes and outcomes[0].tag in {"error", "skipped"}:
                    identity = f"collection::{name or case.get('file', '')}"
                    if not (name or case.get("file")):
                        problems.append(f"{path.name}: collection identity is missing")
                elif not name or not scope:
                    problems.append(f"{path.name}: case identity is missing")
                if identity in seen:
                    problems.append(f"duplicate case: {identity}")
                    continue
                seen.add(identity)
                if len(outcomes) > 1:
                    problems.append(f"{identity}: contradictory or repeated outcomes")
                if any(
                    child.tag not in {*_OUTCOMES, "properties", "system-out", "system-err"}
                    for child in case
                ):
                    problems.append(f"{identity}: unrecognized outcome element")
                status = _OUTCOMES[outcomes[0].tag] if outcomes else "passed"
                for attribute, accepted in _EXECUTED.items():
                    if attribute in case.attrib and case.attrib[attribute] not in accepted:
                        problems.append(f"{identity}: unsupported execution {attribute}")
                        if not outcomes:
                            status = "errors"
                reason = ""
                if outcomes and status == "skipped":
                    reason = (outcomes[0].get("message") or outcomes[0].text or "").strip()
                    if not reason:
                        problems.append(f"{identity}: skipped without a reason")
                cases.append({"id": identity, "status": status, "skip_reason": reason[:2048]})
        except (OSError, ValueError, ET.ParseError) as exc:
            problems.append(f"{path.name}: invalid report ({type(exc).__name__})")
    counts = Counter(case["status"] for case in cases)
    by_id = {case["id"]: case["status"] for case in cases}
    for identity in required:
        if by_id.get(identity) != "passed":
            problems.append(f"required case did not pass: {identity}")
    if not paths or not cases:
        problems.append("no executable case evidence")
    status = (
        "FAIL"
        if problems or counts["failed"] or counts["errors"]
        else ("INCOMPLETE" if counts["skipped"] else "PASS")
    )
    return {
        "status": status,
        "counts": {key: counts[key] for key in ("passed", "failed", "errors", "skipped")},
        "problems": problems,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--required", action="append", default=[])
    args = parser.parse_args()
    result = inspect_reports(args.reports, tuple(args.required))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
