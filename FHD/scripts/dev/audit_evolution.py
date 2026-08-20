#!/usr/bin/env python3
"""owner 审计演化决策 ledger 的 CLI。

复用 modstore_server.evolution_ledger 的 list_events / mark_audited API。
与 FHD/scripts/autonomy/evolution_decision_ledger.py 的 list/audit 子命令等价，
但保留独立入口便于 owner 习惯用法（spec 中规定）。

Usage::

    python audit_evolution.py --since 7d
    python audit_evolution.py --event pack_listed
    python audit_evolution.py --status needs_human
    python audit_evolution.py --summary
    python audit_evolution.py --mark-audited <event_id> --verdict approved
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODSTORE_DEPLOY = _REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
sys.path.insert(0, str(_MODSTORE_DEPLOY))

from modstore_server.evolution_ledger import list_events, mark_audited  # noqa: E402


def _parse_since(since: str | None) -> float | None:
    """支持 7d / 24h / 30d 等格式，返回天数（可为小数）。"""
    if not since:
        return None
    s = since.strip().lower()
    if s.endswith("d"):
        return float(s[:-1])
    if s.endswith("h"):
        return float(s[:-1]) / 24
    print(f"ERROR: invalid --since format: {since} (use 7d, 24h)", file=sys.stderr)
    sys.exit(2)


def _print_table(events: list[dict]) -> None:
    if not events:
        print("(no events)")
        return
    print(
        f"{'timestamp':<26} {'event_id':<10} {'event_type':<22} "
        f"{'trace_id':<14} {'pack_id':<28} {'cost':<8} {'status':<22}"
    )
    print("-" * 130)
    for e in events:
        ts = e.get("timestamp", "")[:19]
        eid = e.get("event_id", "")[:8]
        et = e.get("event_type", "")
        tid = e.get("trace_id", "")[:12]
        proposal = e.get("llm_proposal") or {}
        pid = e.get("pack_id") or proposal.get("employee_pack", {}).get("name", "") or ""
        cost = str(e.get("cost_tokens", ""))
        status = e.get("final_status", "")
        print(f"{ts:<26} {eid:<10} {et:<22} {tid:<14} {pid:<28} {cost:<8} {status:<22}")


def _print_summary(events: list[dict], since_label: str) -> None:
    print(f"Total events ({since_label}): {len(events)}")
    if not events:
        return
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_trace: dict[str, int] = {}
    unaudited = 0
    for e in events:
        by_type[e.get("event_type", "?")] = by_type.get(e.get("event_type", "?"), 0) + 1
        by_status[e.get("final_status", "?")] = by_status.get(e.get("final_status", "?"), 0) + 1
        tid = e.get("trace_id", "<none>")
        by_trace[tid] = by_trace.get(tid, 0) + 1
        if not (e.get("owner_audit") or {}).get("audited"):
            unaudited += 1
    print(f"Unaudited: {unaudited}")
    print()
    print("By event_type:")
    for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {k:<28} {v}")
    print()
    print("By final_status:")
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {k:<28} {v}")
    print()
    print(f"Distinct trace_ids: {len(by_trace)}")
    for tid, n in sorted(by_trace.items(), key=lambda x: -x[1])[:10]:
        print(f"  {tid:<14} {n} events")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit evolution decisions ledger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--since", help="Time window, e.g. 7d, 24h, 30d")
    parser.add_argument("--event", help="Filter by event_type")
    parser.add_argument("--status", help="Filter by final_status")
    parser.add_argument("--trace-id", help="Filter by trace_id")
    parser.add_argument("--summary", action="store_true", help="输出统计而非明细")
    parser.add_argument("--mark-audited", metavar="EVENT_ID", help="Mark event as audited")
    parser.add_argument(
        "--verdict",
        help="Verdict when marking audited (approved/rejected/needs-review)",
    )
    args = parser.parse_args()

    if args.mark_audited:
        if not args.verdict:
            print("ERROR: --verdict required with --mark-audited", file=sys.stderr)
            return 2
        ok = mark_audited(args.mark_audited, args.verdict)
        if ok:
            print(f"Event {args.mark_audited} marked as {args.verdict}")
            return 0
        print(f"Event {args.mark_audited} not found", file=sys.stderr)
        return 1

    since_days = _parse_since(args.since) if args.since else None
    events = list_events(
        event_type=args.event,
        final_status=args.status,
        since_days=since_days,
    )
    if args.trace_id:
        events = [e for e in events if e.get("trace_id") == args.trace_id]

    if args.summary:
        since_label = args.since or "all"
        _print_summary(events, since_label)
    else:
        _print_table(events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
