"""三端 audit 查询 CLI：统一查询桌面/服务器/CI 端的 audit.jsonl。

三端 audit 路径：
- desktop: %APPDATA%/XCAGI/autonomy/audit.jsonl（macOS: ~/Library/Application Support/XCAGI/autonomy/）
- server:  /opt/fhd-full/autonomy/audit.jsonl
- ci:      ./.trae/autonomy-ci/audit.jsonl

用法：
    python audit_query.py --source all
    python audit_query.py --source desktop --since 24h
    python audit_query.py --source server --filter action.type=rollback_to_last_tarball
    python audit_query.py --source ci --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass
class AuditEntry:
    """audit.jsonl 单行结构（与桌面端 AuditEntry 对称）。"""

    ts: str
    source_signal: dict | None
    diagnosis: dict | None
    action: dict | None
    result: dict | None
    truth_snapshot: dict | None

    @classmethod
    def from_dict(cls, raw: dict) -> AuditEntry:
        return cls(
            ts=raw.get("ts", ""),
            source_signal=raw.get("source_signal"),
            diagnosis=raw.get("diagnosis"),
            action=raw.get("action"),
            result=raw.get("result"),
            truth_snapshot=raw.get("truth_snapshot"),
        )


def default_audit_path(source: str) -> Path:
    """返回某端的默认 audit.jsonl 路径。"""
    if source == "desktop":
        # macOS: ~/Library/Application Support/XCAGI/autonomy/audit.jsonl
        # Windows: %APPDATA%/XCAGI/autonomy/audit.jsonl
        home = Path.home()
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "XCAGI" / "autonomy" / "audit.jsonl"
        elif sys.platform == "win32":
            appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
            return Path(appdata) / "XCAGI" / "autonomy" / "audit.jsonl"
        else:
            return home / ".config" / "XCAGI" / "autonomy" / "audit.jsonl"
    if source == "server":
        return Path("/opt/fhd-full/autonomy/audit.jsonl")
    if source == "ci":
        return Path(".trae/autonomy-ci/audit.jsonl")
    raise ValueError(f"unknown source: {source}")


def parse_since(since: str) -> datetime:
    """解析 --since 参数为 UTC datetime。

    支持格式：'24h' / '30m' / '7d' / ISO8601 字符串
    """
    now = datetime.now(UTC)
    since = since.strip().lower()
    # 相对时间：Nh / Nm / Nd
    if since.endswith("h"):
        hours = int(since[:-1])
        return now - timedelta(hours=hours)
    if since.endswith("m"):
        minutes = int(since[:-1])
        return now - timedelta(minutes=minutes)
    if since.endswith("d"):
        days = int(since[:-1])
        return now - timedelta(days=days)
    # ISO8601
    try:
        dt = datetime.fromisoformat(since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid --since format: {since}")


def parse_filter(filter_str: str) -> tuple[str, str]:
    """解析 --filter key=value 参数。"""
    if "=" not in filter_str:
        raise argparse.ArgumentTypeError(
            f"invalid --filter format (expected key=value): {filter_str}"
        )
    key, value = filter_str.split("=", 1)
    return key.strip(), value.strip()


def get_nested(d: dict, key_path: str) -> object:
    """获取嵌套 dict 值，支持 a.b.c 路径。"""
    keys = key_path.split(".")
    cur: object = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def matches_filter(entry: AuditEntry, filters: list[tuple[str, str]]) -> bool:
    """检查 entry 是否匹配所有 filter。"""
    raw = {
        "ts": entry.ts,
        "source_signal": entry.source_signal,
        "diagnosis": entry.diagnosis,
        "action": entry.action,
        "result": entry.result,
        "truth_snapshot": entry.truth_snapshot,
    }
    for key, value in filters:
        actual = get_nested(raw, key)
        if actual is None:
            return False
        if str(actual) != value:
            return False
    return True


def load_entries(path: Path) -> list[AuditEntry]:
    """从 jsonl 文件加载 entries（文件不存在返回空列表）。"""
    if not path.exists():
        return []
    entries: list[AuditEntry] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                entries.append(AuditEntry.from_dict(raw))
            except json.JSONDecodeError:
                # 损坏行跳过，不崩溃
                print(f"warn: {path}:{line_num} JSON 解析失败，跳过", file=sys.stderr)
    return entries


def format_entry(entry: AuditEntry, idx: int) -> str:
    """格式化单条 entry 为可读字符串。"""
    action_type = "?"
    if entry.action:
        if isinstance(entry.action, dict):
            action_type = entry.action.get("type", "?")
    result_ok = "?"
    if entry.result:
        result_ok = str(entry.result.get("ok", "?"))
    diagnosis_cause = "?"
    if entry.diagnosis:
        diagnosis_cause = entry.diagnosis.get("root_cause", "?")
    signal_kind = "?"
    if entry.source_signal:
        signal_kind = entry.source_signal.get("kind", "?")
    return (
        f"[{idx:04d}] {entry.ts} | signal={signal_kind} | "
        f"diagnosis={diagnosis_cause} | action={action_type} | ok={result_ok}"
    )


def query(
    source: str,
    since: datetime | None,
    filters: list[tuple[str, str]],
    limit: int,
    path: Path | None = None,
) -> list[AuditEntry]:
    """查询 audit entries。"""
    if path is None:
        path = default_audit_path(source)
    entries = load_entries(path)
    # 时间过滤
    if since is not None:
        cutoff = since

        def _at_or_after_cutoff(entry: AuditEntry) -> bool:
            parsed = _parse_entry_ts(entry.ts)
            return parsed is None or parsed >= cutoff

        entries = [entry for entry in entries if _at_or_after_cutoff(entry)]
    # 字段过滤
    if filters:
        entries = [e for e in entries if matches_filter(e, filters)]
    # limit（取最后 N 条，最新在末尾）
    if limit > 0:
        entries = entries[-limit:]
    return entries


def _parse_entry_ts(ts: str) -> datetime | None:
    """解析 entry ts（ISO8601）为 datetime，失败返回 None。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="三端 audit 查询 CLI")
    parser.add_argument(
        "--source",
        choices=["desktop", "server", "ci", "all"],
        default="all",
        help="audit 来源（默认 all）",
    )
    parser.add_argument("--since", help="时间过滤：'24h' / '30m' / '7d' / ISO8601")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="字段过滤：key=value（可多次指定，支持 a.b.c 路径）",
    )
    parser.add_argument("--limit", type=int, default=100, help="最大条数（默认 100，0=不限）")
    parser.add_argument("--path", help="自定义 audit.jsonl 路径（覆盖 --source 默认路径）")
    args = parser.parse_args(argv)

    since_dt = parse_since(args.since) if args.since else None
    filters = [parse_filter(f) for f in args.filter]

    sources = ["desktop", "server", "ci"] if args.source == "all" else [args.source]
    total = 0
    for src in sources:
        path = Path(args.path) if args.path else default_audit_path(src)
        entries = query(src, since_dt, filters, args.limit, path)
        if entries:
            print(f"=== {src} ({path}) ===")
            for idx, entry in enumerate(entries, 1):
                print(format_entry(entry, idx))
            print(f"--- {src}: {len(entries)} 条 ---\n")
            total += len(entries)
        else:
            print(f"=== {src} ({path}) === 无记录\n")

    print(f"总计: {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
