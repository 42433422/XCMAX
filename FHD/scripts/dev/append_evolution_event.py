#!/usr/bin/env python3
"""CLI 写演化决策 ledger 事件（通用工具）。

复用 modstore_server.evolution_ledger.append_event API。
适用于 workflow 步骤中需要打点记录的场景。

Usage::

    python append_evolution_event.py --event pack_listed --pack-id x@1.0.0
    python append_evolution_event.py --event signal_detected \\
        --field signal_source=legacy \\
        --field signal_score=0.32 \\
        --field trace_id=abc123
    python append_evolution_event.py --event custom_event --data '{"foo": "bar"}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODSTORE_DEPLOY = _REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
sys.path.insert(0, str(_MODSTORE_DEPLOY))

from modstore_server.evolution_ledger import append_event  # noqa: E402


def _parse_field(s: str) -> tuple[str, str]:
    """解析 key=value 形式。值尝试 JSON 解析，失败则保持字符串。"""
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"--field expects key=value format, got: {s!r}")
    key, _, raw = s.partition("=")
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError(f"--field key cannot be empty: {s!r}")
    # 尝试 JSON 解析（支持 number/bool/null/list/dict）
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return key, value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append an event to evolution_decisions.jsonl ledger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--event", required=True, help="event_type")
    parser.add_argument("--pack-id", help="pack_id (shortcut for --field pack_id=...)")
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        type=_parse_field,
        help="key=value field (value auto-JSON-parsed if possible)",
    )
    parser.add_argument(
        "--data",
        help='JSON string with additional fields (e.g. \'{"foo": "bar"}\')',
    )
    args = parser.parse_args()

    event: dict = {"event_type": args.event}
    if args.pack_id:
        event["pack_id"] = args.pack_id
    for key, value in args.field:
        event[key] = value
    if args.data:
        try:
            event.update(json.loads(args.data))
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid --data JSON: {exc}", file=sys.stderr)
            return 2

    record = append_event(event)
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
