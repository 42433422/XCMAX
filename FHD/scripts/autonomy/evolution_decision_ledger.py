#!/usr/bin/env python3
"""演化决策 ledger CLI - 5 连接点统一入口。

连接点 1: collect-signals    - 聚合 legacy/intent/slo 信号 → signal_detected 事件
连接点 2: propose-pack       - LLM 生成 employee_pack 提案 → proposal_generated 事件
连接点 3: open-issue         - 把提案转 GitHub issue → issue_opened 事件
连接点 4: implement-pack     - 触发 ai-issue-implement 实现 → implement_succeeded/failed 事件
连接点 5: publish-pack       - PR 合并后上架 MODstore → pack_listed 事件

每个子命令都:
1. 调用对应 MODstore_deploy 模块的 Python API
2. 调用 evolution_ledger.append_event() 记录到 ledger
3. 输出 event_id 便于追踪

dry-run 模式: 不真实创建 issue / PR / 上架,只记录 ledger 事件 + 输出预期动作。

使用示例::

    # 完整闭环 dry-run（最常用）
    python scripts/autonomy/evolution_decision_ledger.py dry-run

    # 单连接点
    python scripts/autonomy/evolution_decision_ledger.py collect-signals --dry-run
    python scripts/autonomy/evolution_decision_ledger.py list --since-days 1
    python scripts/autonomy/evolution_decision_ledger.py audit --event-id <uuid> --verdict approved
"""
from __future__ import annotations

# 防止本脚本所在目录（含 types.py 等）污染 stdlib import 顺序。
# 必须在 import os/pathlib/argparse 等之前完成 sys.path 清理。
# 只用 sys + 字符串操作，不引入任何会触发 `from types import ...` 的模块。
import sys as _sys

_SCRIPT_DIR = _sys.path[0]  # 直接脚本执行时，sys.path[0] 就是脚本所在目录
if _SCRIPT_DIR:
    _sys.path = [p for p in _sys.path if p != _SCRIPT_DIR]

import argparse  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

# 添加 MODstore_deploy 到 sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]  # XCMAX/
MODSTORE_DEPLOY = REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
sys.path.insert(0, str(MODSTORE_DEPLOY))

from modstore_server.evolution_ledger import (  # noqa: E402
    append_event,
    list_events,
    mark_audited,
)
from modstore_server.evolution_signal_collector import aggregate_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_trace_id() -> str:
    """生成 trace_id（同一 dry-run 的所有事件共享）。"""
    return uuid.uuid4().hex[:12]


def _set_env_report_paths(
    *,
    legacy_report: Optional[str],
    intent_report: Optional[str],
    slo_report: Optional[str],
) -> None:
    """把 CLI 参数映射到 aggregate_signals() 读取的环境变量。"""
    if legacy_report:
        os.environ["MODSTORE_LEGACY_REPORT_PATH"] = legacy_report
    if intent_report:
        os.environ["MODSTORE_INTENT_REPORT_PATH"] = intent_report
    if slo_report:
        os.environ["MODSTORE_SLO_REPORT_PATH"] = slo_report


def _synthetic_signals() -> Dict[str, Any]:
    """dry-run 用的合成信号：故意触发 1 个低于阈值源（保持 5 事件闭环）。"""
    return {
        "legacy_usage": {
            "report": {"legacy_ratio": 0.32, "total_files": 120, "legacy_files": 38},
            "below_threshold": True,
            "signal_score": 0.07,
        },
        "intent_benchmark": {
            "report": {"accuracy": 0.92, "samples": 200, "errors": 16},
            "accuracy": 0.92,
            "below_threshold": False,
            "signal_score": 0.0,
        },
        "slo_metrics": {
            "report": {"availability": 0.995, "error_rate": 0.005},
            "below_threshold": False,
            "signal_score": 0.0,
        },
        "total_score": 0.07,
        "signals_to_propose": 1,
    }


def _synthetic_proposal(triggered_by: str, signal_score: float) -> Dict[str, Any]:
    """dry-run 用的合成 LLM 提议。"""
    return {
        "proposal_id": f"dry-run-{uuid.uuid4().hex[:8]}",
        "department": "engineering",
        "triggered_by": triggered_by,
        "signal_score": signal_score,
        "employee_pack": {
            "name": "intent-failure-triage-clerk",
            "responsibility": "scan intent benchmark failures, cluster by pattern, propose prompt fixes",
            "prompt_template": "You are an intent failure triage clerk...",
            "skills": ["intent-benchmark", "failure-clustering"],
            "tools": ["read_file", "write_pr_comment"],
            "acceptance_criteria": [
                "recall >= 0.7 on test set",
                "<= 5 files touched",
                "no HIGH_RISK_PATTERNS touched",
            ],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


def _print_event_line(label: str, event: Dict[str, Any], *, trace_id: str) -> None:
    """打印一行事件摘要。"""
    eid = event.get("event_id", "")[:8]
    print(f"  → {label}: event_id={eid} trace_id={trace_id}")


# ---------------------------------------------------------------------------
# Subcommands (5 connection points)
# ---------------------------------------------------------------------------


def cmd_collect_signals(args: argparse.Namespace) -> int:
    """连接点 1: 聚合信号 → signal_detected 事件。

    调用 evolution_signal_collector.aggregate_signals()，对每个 below_threshold
    的信号源写一条 signal_detected 事件。
    """
    trace_id = args.trace_id or _new_trace_id()
    print(f"[trace_id={trace_id}] Step 1: collect-signals (dry_run={args.dry_run})")

    if args.dry_run:
        signals = _synthetic_signals()
        print(f"  (dry-run) using synthetic signals: total_score={signals['total_score']}")
    else:
        _set_env_report_paths(
            legacy_report=args.legacy_report,
            intent_report=args.intent_report,
            slo_report=args.slo_report,
        )
        signals = aggregate_signals()
        print(f"  aggregated: total_score={signals.get('total_score', 0)}")

    event_ids: List[str] = []
    for source in ("legacy_usage", "intent_benchmark", "slo_metrics"):
        src = signals.get(source, {})
        if not src.get("below_threshold"):
            continue
        evt = append_event(
            {
                "event_type": "signal_detected",
                "trace_id": trace_id,
                "triggered_by": args.triggered_by,
                "signal_source": source,
                "signal_score": float(src.get("signal_score") or 0),
                "signal_report": src.get("report", {}),
                "dry_run": bool(args.dry_run),
                "final_status": "signal_detected",
            }
        )
        event_ids.append(evt["event_id"])
        _print_event_line("signal_detected", evt, trace_id=trace_id)
        print(f"    source={source} score={src.get('signal_score', 0):.3f}")

    if not event_ids:
        print("  (no signals below threshold; nothing written)")
    return 0


def cmd_propose_pack(args: argparse.Namespace) -> int:
    """连接点 2: LLM 生成 employee_pack 提案 → proposal_generated 事件。

    dry-run: 用合成提议，不调 LLM。
    实模式: 调 employee_autonomy_service.propose_employee_pack()。
    """
    trace_id = args.trace_id or _new_trace_id()
    print(f"[trace_id={trace_id}] Step 2: propose-pack (dry_run={args.dry_run})")

    if args.dry_run:
        proposal = _synthetic_proposal(
            triggered_by="dry-run", signal_score=0.15
        )
        print(f"  (dry-run) using synthetic proposal_id={proposal['proposal_id']}")
    else:
        # 实模式：复用 evolution-orchestrator.yml 中的 Python API 流程
        signals = aggregate_signals()
        if not signals.get("signals_to_propose"):
            print("  no signals to propose; nothing written")
            return 0
        from modstore_server.employee_autonomy_service import propose_employee_pack

        proposal = propose_employee_pack(signals)
        if not proposal:
            print("  LLM returned no proposal; nothing written")
            return 0

    evt = append_event(
        {
            "event_type": "proposal_generated",
            "trace_id": trace_id,
            "triggered_by": proposal.get("triggered_by", "manual"),
            "signal_score": float(proposal.get("signal_score") or 0),
            "llm_proposal": proposal,
            "dry_run": bool(args.dry_run),
            "final_status": "proposal_generated",
        }
    )
    pack_name = proposal.get("employee_pack", {}).get("name", "<unnamed>")
    _print_event_line("proposal_generated", evt, trace_id=trace_id)
    print(f"    pack_name={pack_name} department={proposal.get('department')}")
    return 0


def cmd_open_issue(args: argparse.Namespace) -> int:
    """连接点 3: 提案转 GitHub issue → issue_opened 事件。

    dry-run: 不调 gh CLI，写 issue_opened 事件带 dry_run=true。
    实模式: 调 modstore_server.gap_to_issue.open_issue_for_proposal()。
    """
    trace_id = args.trace_id or _new_trace_id()
    print(f"[trace_id={trace_id}] Step 3: open-issue (dry_run={args.dry_run})")

    # 从 ledger 取 proposal_generated 事件
    events = list_events(event_type="proposal_generated")
    proposal_evt = None
    if args.proposal_event_id:
        for e in events:
            if e.get("event_id") == args.proposal_event_id:
                proposal_evt = e
                break
        if not proposal_evt:
            print(f"  ERROR: proposal_event_id={args.proposal_event_id} not found", file=sys.stderr)
            return 2
    elif events:
        proposal_evt = events[-1]  # 取最新一条
        print(f"  using latest proposal event_id={proposal_evt['event_id'][:8]}")
    else:
        # dry-run 兜底：用合成提议
        if not args.dry_run:
            print("  ERROR: no proposal_generated event in ledger; pass --proposal-event-id", file=sys.stderr)
            return 2
        proposal_evt = {
            "llm_proposal": _synthetic_proposal("dry-run", 0.15),
            "triggered_by": "dry-run",
        }

    proposal = proposal_evt.get("llm_proposal") or {}
    pack_name = proposal.get("employee_pack", {}).get("name", "unnamed")

    if args.dry_run:
        issue_url = "https://github.com/example/repo/issues/0#dry-run"
        evt = append_event(
            {
                "event_type": "issue_opened",
                "trace_id": trace_id,
                "triggered_by": proposal_evt.get("triggered_by", "manual"),
                "signal_score": proposal.get("signal_score", 0),
                "llm_proposal": proposal,
                "issue_url": issue_url,
                "dry_run": True,
                "final_status": "issue_opened",
            }
        )
        _print_event_line("issue_opened", evt, trace_id=trace_id)
        print(f"    issue_url={issue_url} (dry-run, not actually created)")
        print(f"    pack_name={pack_name}")
        return 0

    # 实模式
    from modstore_server.gap_to_issue import open_issue_for_proposal

    try:
        issue_url = open_issue_for_proposal(proposal, add_implement_label=False)
    except Exception as exc:  # noqa: BLE001
        evt = append_event(
            {
                "event_type": "issue_open_failed",
                "trace_id": trace_id,
                "error": str(exc),
                "dry_run": False,
                "final_status": "needs_human",
            }
        )
        _print_event_line("issue_open_failed", evt, trace_id=trace_id)
        print(f"  ERROR: {exc}", file=sys.stderr)
        return 1

    # gap_to_issue 内部已经 append 了 issue_opened 事件，但 trace_id 没写进去。
    # 这里再 append 一条 trace_id 关联事件，便于追踪。
    evt = append_event(
        {
            "event_type": "issue_opened",
            "trace_id": trace_id,
            "issue_url": issue_url,
            "dry_run": False,
            "final_status": "issue_opened",
        }
    )
    _print_event_line("issue_opened", evt, trace_id=trace_id)
    print(f"    issue_url={issue_url}")
    return 0


def _parse_issue_number(issue_url: str) -> Optional[int]:
    """从 issue URL 解析编号。"""
    try:
        return int(issue_url.rstrip("/").split("/")[-1])
    except (TypeError, ValueError):
        return None


def _dispatch_implement_workflow(issue_number: int) -> subprocess.CompletedProcess[str]:
    """连接点 4 显式触发：gh workflow run（非仅靠 issue 标签间接流转）。"""
    workflow = os.environ.get(
        "EVOLUTION_IMPLEMENT_WORKFLOW", "fhd-ai-issue-implement.yml"
    )
    cmd = [
        "gh",
        "workflow",
        "run",
        workflow,
        "-f",
        f"issue_number={issue_number}",
    ]
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPO", "")
    if repo:
        cmd.extend(["--repo", repo])
    print(f"  dispatching: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_implement_local(issue_number: int) -> subprocess.CompletedProcess[str]:
    """本地 fallback：直接跑 ai_issue_implement.py --apply。"""
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPO", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    llm_api_key = os.environ.get("XCAGI_LLM_API_KEY", "")
    script = REPO_ROOT / "FHD" / "scripts" / "dev" / "ai_issue_implement.py"
    cmd = [
        sys.executable,
        str(script),
        "--issue-number",
        str(issue_number),
        "--repo",
        repo,
        "--token",
        token,
        "--llm-api-key",
        llm_api_key,
        "--apply",
    ]
    print(f"  invoking local: {' '.join(cmd[:6])} ... --apply")
    return subprocess.run(cmd, capture_output=True, text=True)


def cmd_implement_pack(args: argparse.Namespace) -> int:
    """连接点 4: 在 ledger 内显式触发 ai-issue-implement → implement_* 事件。

    dry-run: 不真实 dispatch，只写 implement_succeeded 事件。
    实模式默认: ``gh workflow run fhd-ai-issue-implement.yml -f issue_number=N``
    （EVOLUTION_IMPLEMENT_MODE=local 时改为 subprocess 调 ai_issue_implement.py）。
    """
    trace_id = args.trace_id or _new_trace_id()
    print(f"[trace_id={trace_id}] Step 4: implement-pack (dry_run={args.dry_run})")

    if args.dry_run:
        evt = append_event(
            {
                "event_type": "implement_succeeded",
                "trace_id": trace_id,
                "issue_url": args.issue_url,
                "pr_url": "https://github.com/example/repo/pull/0#dry-run",
                "files_written": ["prompt.txt", "skills.json", "manifest.json"],
                "cost_tokens": 0,
                "trigger": "ledger_explicit",
                "dry_run": True,
                "final_status": "implement_succeeded",
            }
        )
        _print_event_line("implement_succeeded", evt, trace_id=trace_id)
        print("    pr_url=https://github.com/example/repo/pull/0#dry-run (dry-run, not actually created)")
        return 0

    issue_url = args.issue_url
    issue_number_int = _parse_issue_number(issue_url)
    if issue_number_int is None:
        print(f"  ERROR: cannot parse issue_number from {issue_url}", file=sys.stderr)
        return 2

    mode = (os.environ.get("EVOLUTION_IMPLEMENT_MODE") or "workflow").strip().lower()
    if mode == "local":
        result = _run_implement_local(issue_number_int)
        trigger = "ledger_local_subprocess"
        success_type = "implement_succeeded"
    else:
        result = _dispatch_implement_workflow(issue_number_int)
        trigger = "ledger_gh_workflow_run"
        success_type = "implement_dispatched"

    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode == 0:
        evt = append_event(
            {
                "event_type": success_type,
                "trace_id": trace_id,
                "issue_url": issue_url,
                "issue_number": issue_number_int,
                "returncode": result.returncode,
                "trigger": trigger,
                "dry_run": False,
                "final_status": success_type,
            }
        )
        _print_event_line(success_type, evt, trace_id=trace_id)
        return 0

    evt = append_event(
        {
            "event_type": "implement_failed",
            "trace_id": trace_id,
            "issue_url": issue_url,
            "issue_number": issue_number_int,
            "returncode": result.returncode,
            "trigger": trigger,
            "stderr_excerpt": result.stderr[-1000:] if result.stderr else "",
            "dry_run": False,
            "final_status": "needs_human",
        }
    )
    _print_event_line("implement_failed", evt, trace_id=trace_id)
    return 1


def cmd_publish_pack(args: argparse.Namespace) -> int:
    """连接点 5: PR 合并后上架 MODstore → pack_listed 事件。

    dry-run: 不真实构建 employee_pack，只写 pack_listed 事件。
    实模式: 调 build_employee_pack.build_pack_from_commit()。
    """
    trace_id = args.trace_id or _new_trace_id()
    print(f"[trace_id={trace_id}] Step 5: publish-pack (dry_run={args.dry_run})")

    if args.dry_run:
        pack_id = "dry-run-pack@0.0.1"
        evt = append_event(
            {
                "event_type": "pack_listed",
                "trace_id": trace_id,
                "pack_id": pack_id,
                "commit_sha": args.commit_sha,
                "risk_level": "low",
                "risk_reason": "dry-run synthetic approval",
                "dry_run": True,
                "final_status": "closed_loop_completed",
            }
        )
        _print_event_line("pack_listed", evt, trace_id=trace_id)
        print(f"    pack_id={pack_id} (dry-run, not actually listed)")
        return 0

    # 实模式
    from modstore_server.build_employee_pack import build_pack_from_commit

    result = build_pack_from_commit(commit_sha=args.commit_sha, repo_root=REPO_ROOT)
    if result.get("skipped"):
        print(f"  skipped: {result.get('reason')}")
        return 0
    if result.get("approved"):
        evt = append_event(
            {
                "event_type": "pack_listed",
                "trace_id": trace_id,
                "pack_id": result.get("pack_id"),
                "commit_sha": args.commit_sha,
                "risk_level": result.get("risk_level"),
                "risk_reason": result.get("reason"),
                "dry_run": False,
                "final_status": "closed_loop_completed",
            }
        )
        _print_event_line("pack_listed", evt, trace_id=trace_id)
        print(f"    pack_id={result.get('pack_id')}")
        return 0

    # 不通过审核
    evt = append_event(
        {
            "event_type": "pack_rejected",
            "trace_id": trace_id,
            "pack_id": result.get("pack_id"),
            "commit_sha": args.commit_sha,
            "risk_level": result.get("risk_level"),
            "risk_reason": result.get("reason"),
            "dry_run": False,
            "final_status": "needs_human",
        }
    )
    _print_event_line("pack_rejected", evt, trace_id=trace_id)
    print(f"  rejected: {result.get('reason')}")
    return 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    """完整闭环 dry-run: 5 连接点全部走一遍,只写 ledger 不真实触发。

    同一 trace_id 贯穿 5 个事件，便于追踪全链路。
    """
    trace_id = _new_trace_id()
    print(f"=== Evolution closed-loop DRY-RUN (trace_id={trace_id}) ===")
    print()

    # 共享 trace_id 通过 --trace-id 传入每个子命令
    common = argparse.Namespace(
        trace_id=trace_id,
        dry_run=True,
        triggered_by="dry-run",
        legacy_report=None,
        intent_report=None,
        slo_report=None,
    )
    rc1 = cmd_collect_signals(common)
    print()
    if rc1 != 0:
        print(f"Step 1 failed (rc={rc1}); aborting dry-run")
        return rc1

    rc2 = cmd_propose_pack(
        argparse.Namespace(trace_id=trace_id, dry_run=True, signal_event_id=None)
    )
    print()
    if rc2 != 0:
        print(f"Step 2 failed (rc={rc2}); aborting dry-run")
        return rc2

    rc3 = cmd_open_issue(
        argparse.Namespace(trace_id=trace_id, dry_run=True, proposal_event_id=None)
    )
    print()
    if rc3 != 0:
        print(f"Step 3 failed (rc={rc3}); aborting dry-run")
        return rc3

    rc4 = cmd_implement_pack(
        argparse.Namespace(
            trace_id=trace_id,
            dry_run=True,
            issue_url="https://github.com/example/repo/issues/0#dry-run",
        )
    )
    print()
    if rc4 != 0:
        print(f"Step 4 failed (rc={rc4}); aborting dry-run")
        return rc4

    rc5 = cmd_publish_pack(
        argparse.Namespace(
            trace_id=trace_id,
            dry_run=True,
            commit_sha="dry-run-sha-0000000",
        )
    )
    print()

    print("=== Trace summary ===")
    events = [e for e in list_events() if e.get("trace_id") == trace_id]
    print(f"  trace_id: {trace_id}")
    print(f"  events: {len(events)}")
    if events:
        print(f"  final_status: {events[-1].get('final_status', '?')}")
    print()
    print("Events written:")
    for e in events:
        eid = e.get("event_id", "")[:8]
        etype = e.get("event_type", "?")
        status = e.get("final_status", "?")
        print(f"  [{e.get('timestamp', '')[:19]}] {eid} {etype} status={status}")
    print()
    return rc5


def cmd_list(args: argparse.Namespace) -> int:
    """列出 ledger 事件。"""
    events = list_events(
        event_type=args.event_type,
        final_status=args.final_status,
        since_days=args.since_days,
    )
    if args.trace_id:
        events = [e for e in events if e.get("trace_id") == args.trace_id]
    if not events:
        print("(no events)")
        return 0
    print(f"{'timestamp':<26} {'event_id':<10} {'event_type':<22} {'trace_id':<14} {'status':<24}")
    print("-" * 100)
    for e in events:
        ts = e.get("timestamp", "")[:19]
        eid = e.get("event_id", "")[:8]
        et = e.get("event_type", "")
        tid = e.get("trace_id", "")[:12]
        status = e.get("final_status", "")
        print(f"{ts:<26} {eid:<10} {et:<22} {tid:<14} {status:<24}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """owner 审计: 标记事件已审计。"""
    ok = mark_audited(args.event_id, args.verdict)
    if ok:
        print(f"mark_audited: ok event_id={args.event_id} verdict={args.verdict}")
        return 0
    print(f"mark_audited: FAILED event_id={args.event_id} not found", file=sys.stderr)
    return 1


def cmd_summary(args: argparse.Namespace) -> int:
    """输出 N 天内事件统计。"""
    events = list_events(since_days=args.since_days)
    by_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_trace: Dict[str, int] = {}
    for e in events:
        by_type[e.get("event_type", "?")] = by_type.get(e.get("event_type", "?"), 0) + 1
        by_status[e.get("final_status", "?")] = by_status.get(e.get("final_status", "?"), 0) + 1
        tid = e.get("trace_id", "<none>")
        by_trace[tid] = by_trace.get(tid, 0) + 1
    print(f"Total events (last {args.since_days}d): {len(events)}")
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
    return 0


# ---------------------------------------------------------------------------
# Main / argparse
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="演化决策 ledger CLI - 5 连接点统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # collect-signals
    p = subparsers.add_parser(
        "collect-signals", help="连接点 1: 聚合信号 → signal_detected"
    )
    p.add_argument("--legacy-report", help="legacy-usage-weekly 报告 JSON 路径")
    p.add_argument("--intent-report", help="intent-benchmark 报告 JSON 路径")
    p.add_argument("--slo-report", help="slo-metrics 报告 JSON 路径")
    p.add_argument("--triggered-by", default="manual")
    p.add_argument("--trace-id", help="复用已有 trace_id（dry-run 串联用）")
    p.add_argument("--dry-run", action="store_true", help="使用合成信号，不读真实报告")
    p.set_defaults(func=cmd_collect_signals)

    # propose-pack
    p = subparsers.add_parser(
        "propose-pack", help="连接点 2: LLM 生成提案 → proposal_generated"
    )
    p.add_argument("--signal-event-id", help="从指定 signal_detected 事件触发")
    p.add_argument("--trace-id", help="复用已有 trace_id")
    p.add_argument("--dry-run", action="store_true", help="用合成提议，不调 LLM")
    p.set_defaults(func=cmd_propose_pack)

    # open-issue
    p = subparsers.add_parser(
        "open-issue", help="连接点 3: 提案转 GitHub issue → issue_opened"
    )
    p.add_argument("--proposal-event-id", help="从指定 proposal_generated 事件触发")
    p.add_argument("--trace-id", help="复用已有 trace_id")
    p.add_argument("--dry-run", action="store_true", help="不调 gh CLI")
    p.set_defaults(func=cmd_open_issue)

    # implement-pack
    p = subparsers.add_parser(
        "implement-pack", help="连接点 4: 触发 ai-issue-implement → implement_succeeded/failed"
    )
    p.add_argument("--issue-url", required=True, help="GitHub issue URL")
    p.add_argument("--trace-id", help="复用已有 trace_id")
    p.add_argument("--dry-run", action="store_true", help="不真实创建 PR")
    p.set_defaults(func=cmd_implement_pack)

    # publish-pack
    p = subparsers.add_parser(
        "publish-pack", help="连接点 5: PR 合并后上架 MODstore → pack_listed"
    )
    p.add_argument("--commit-sha", required=True, help="合并 commit SHA")
    p.add_argument("--trace-id", help="复用已有 trace_id")
    p.add_argument("--dry-run", action="store_true", help="不真实上架")
    p.set_defaults(func=cmd_publish_pack)

    # dry-run (完整闭环)
    p = subparsers.add_parser(
        "dry-run", help="完整闭环 dry-run: 5 连接点全部走一遍"
    )
    p.set_defaults(func=cmd_dry_run)

    # list
    p = subparsers.add_parser("list", help="列出 ledger 事件")
    p.add_argument("--event-type", help="按 event_type 过滤")
    p.add_argument("--final-status", help="按 final_status 过滤")
    p.add_argument("--since-days", type=int, help="只看最近 N 天")
    p.add_argument("--trace-id", help="按 trace_id 过滤")
    p.set_defaults(func=cmd_list)

    # summary
    p = subparsers.add_parser("summary", help="统计最近 N 天事件分布")
    p.add_argument("--since-days", type=int, default=7)
    p.set_defaults(func=cmd_summary)

    # audit
    p = subparsers.add_parser("audit", help="owner 审计: 标记事件已审计")
    p.add_argument("--event-id", required=True, help="ledger 中的 event_id")
    p.add_argument(
        "--verdict",
        required=True,
        choices=["approved", "rejected", "needs-review"],
    )
    p.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
