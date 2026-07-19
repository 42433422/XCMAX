#!/usr/bin/env python3
"""Report 30/90-day autonomy veto rates using the audit SSOT counting rule."""

from __future__ import annotations

import sys

# Direct execution places this directory first on sys.path, where local
# ``types.py`` would shadow Python's stdlib ``types`` module.
if __package__ in {None, ""} and sys.path:
    sys.path.pop(0)

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application.autonomy.audit_log import summarize_autonomy_audit  # noqa: E402


def evaluate_window(days: int) -> dict[str, object]:
    summary = summarize_autonomy_audit(days=days)
    observed = float(summary.get("observed_days") or 0.0)
    veto_rate = float(summary.get("veto_rate") or 0.0)
    total = int(summary.get("total") or 0)
    complete = total > 0 and observed >= days
    if not complete:
        status = "collecting"
        reason = f"observed {observed:.2f}/{days} days"
    elif days >= 90 and 1.0 <= veto_rate <= 5.0:
        status = "passed"
        reason = "90-day veto rate is within 1-5%"
    elif days >= 30 and veto_rate <= 5.0:
        status = "passed"
        reason = "30-day veto rate is at most 5%"
    else:
        status = "needs_tuning"
        reason = "veto rate is outside the target window"
    return {**summary, "status": status, "status_reason": reason, "complete": complete}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, choices=(30, 90), default=30)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    report = evaluate_window(args.days)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.strict and report["complete"] and report["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
