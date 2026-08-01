#!/usr/bin/env python3
"""客服工单闭环生产验收脚本。

SSOT 验收口径（来自 FHD/docs/architecture/CUSTOMER_TICKET_BUS_SSOT.md）：
    一张 `CS*` 工单：dispatched_count > 0，_cs_progress.lifecycle_* 非空，且非全员 handler_failed。

用法：
    # 1) 仅核查最近一张 CS* 工单（推荐生产首次验收）
    python3 ops/xcmax_verify_customer_ticket_closed_loop.py --check-latest

    # 2) 触发一张新工单并跟踪到闭环（需要生产 API 可达 + 用户 token）
    MODSTORE_BASE_URL=https://xiu-ci.com \
    MODSTORE_AUTH_TOKEN=<user-jwt> \
    python3 ops/xcmax_verify_customer_ticket_closed_loop.py --trigger

    # 3) 指定工单号核查
    python3 ops/xcmax_verify_customer_ticket_closed_loop.py --ticket-no CS20260724153100001

环境变量：
    MODSTORE_DB_PATH       生产 SQLite 路径（默认 /opt/fhd-full/data/modstore.db）
    MODSTORE_BASE_URL      生产 API 根（仅 --trigger 需要）
    MODSTORE_AUTH_TOKEN    用户 JWT（仅 --trigger 需要）
    MODSTORE_VERIFY_TIMEOUT 等待闭环秒数（默认 300）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

DEFAULT_DB_PATH = "/opt/fhd-full/data/modstore.db"
DEFAULT_TIMEOUT = 300


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def _load_sqlite():
    try:
        import sqlite3
    except ImportError:
        _log("ERROR: sqlite3 not available")
        sys.exit(EXIT_ERROR)
    return sqlite3


def _connect(db_path: str):
    sqlite3 = _load_sqlite()
    if not Path(db_path).exists():
        _log(f"ERROR: DB not found at {db_path}")
        sys.exit(EXIT_ERROR)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ticket_lifecycle_stage(status: str | None, decision_status: str | None) -> int:
    """与 modstore_server.customer_service_orchestrator.ticket_lifecycle_stage 完全一致。

    用户侧五阶段：1已收到 → 2处理中 → 3有结果 → 4待补充 → 5已完成。
    """
    s = (status or "").strip().lower()
    d = (decision_status or "").strip().lower()
    if s in {"resolved", "closed", "done", "rejected"}:
        return 5
    if s == "waiting_user" or d == "needs_more_info":
        return 4
    if s in {"open", "pending", "queued"}:
        return 1
    if s == "processing":
        if d in {"approved", "rejected"}:
            return 3
        return 2
    if d in {"approved", "rejected"}:
        return 3
    return 1


def _fetch_latest_cs_ticket(conn) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT id, ticket_no, title, status, decision_status, user_id, session_id,
               evidence_json, created_at, updated_at, closed_at
        FROM customer_service_tickets
        WHERE ticket_no LIKE 'CS%'
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def _fetch_ticket_by_no(conn, ticket_no: str) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT id, ticket_no, title, status, decision_status, user_id, session_id,
               evidence_json, created_at, updated_at, closed_at
        FROM customer_service_tickets
        WHERE ticket_no = ?
        """,
        (ticket_no,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _fetch_incident_events_for_ticket(conn, ticket_id: int) -> list[dict[str, Any]]:
    """通过 payload_json 中的 ticket_id 关联 incident_event。

    incident_bus.publish 把 enriched payload 写入 IncidentEvent.payload_json（截断 8000 字符）。
    """
    cur = conn.execute(
        """
        SELECT id, event_type, source, fingerprint, dispatched_count,
               payload_json, created_at
        FROM incident_events
        WHERE event_type = 'ops.intake.customer_ticket'
          AND (payload_json LIKE ? OR payload_json LIKE ?)
        ORDER BY id DESC
        LIMIT 10
        """,
        (f'%{ticket_id}%', f'%"ticket_id": {ticket_id}%'),
    )
    # 查询已带 LIMIT 10；直接迭代游标避免无界 fetchall 模式
    return [dict(r) for r in cur]


def _fetch_handler_failures(conn, event_id: int) -> list[dict[str, Any]]:
    """检查 incident team 执行记录中是否有 handler_failed=True。

    回写路径把 team_rows 写到 customer_service_actions.result_json.request.roles。
    """
    cur = conn.execute(
        """
        SELECT id, ticket_id, action_type, status, result_json, created_at
        FROM customer_service_actions
        WHERE target_type = 'incident_team'
          AND target_id = ?
        ORDER BY id DESC
        """,
        (str(event_id),),
    )
    # 按 target_id 过滤的有界查询；直接迭代游标避免无界 fetchall 模式
    return [dict(r) for r in cur]


def _check_handler_failed_all(action_rows: list[dict[str, Any]]) -> tuple[bool, str]:
    """返回 (是否全员失败, 摘要)。"""
    if not action_rows:
        return False, "no incident_team action recorded"
    total_roles = 0
    failed_roles = 0
    for row in action_rows:
        try:
            rj = json.loads(row.get("result_json") or "{}")
        except json.JSONDecodeError:
            continue
        req = rj.get("request") or {}
        for role in req.get("roles") or []:
            if not isinstance(role, dict):
                continue
            total_roles += 1
            # ok=False 或 status 中含 failed 标记视为失败
            ok = bool(role.get("ok"))
            status = str(role.get("status") or "").lower()
            if not ok or "fail" in status:
                failed_roles += 1
    if total_roles == 0:
        return False, "no roles recorded in action.result_json"
    all_failed = failed_roles == total_roles
    return all_failed, f"roles={total_roles} failed={failed_roles}"


def _verify_ticket(conn, ticket: dict[str, Any]) -> dict[str, Any]:
    """对单张工单执行 SSOT 三条验收。"""
    ticket_id = int(ticket["id"])
    ticket_no = str(ticket["ticket_no"] or "")
    status = ticket.get("status")
    decision_status = ticket.get("decision_status")

    # 条件 1：dispatched_count > 0
    events = _fetch_incident_events_for_ticket(conn, ticket_id)
    dispatched_counts = [int(e.get("dispatched_count") or 0) for e in events]
    max_dispatched = max(dispatched_counts) if dispatched_counts else 0
    cond_dispatched = max_dispatched > 0

    # 条件 2：lifecycle_stage 非空（>= 2 表示已进入处理中或更后阶段）
    lifecycle = _ticket_lifecycle_stage(status, decision_status)
    cond_lifecycle = lifecycle >= 2

    # 条件 3：非全员 handler_failed
    handler_summary = "no incident event"
    all_failed = False
    if events:
        latest_event_id = int(events[0]["id"])
        action_rows = _fetch_handler_failures(conn, latest_event_id)
        all_failed, handler_summary = _check_handler_failed_all(action_rows)
    cond_no_all_failed = not all_failed

    return {
        "ticket_id": ticket_id,
        "ticket_no": ticket_no,
        "status": status,
        "decision_status": decision_status,
        "lifecycle_stage": lifecycle,
        "incident_events": [
            {
                "id": e["id"],
                "dispatched_count": e["dispatched_count"],
                "source": e["source"],
                "created_at": e["created_at"],
            }
            for e in events
        ],
        "max_dispatched_count": max_dispatched,
        "handler_summary": handler_summary,
        "conditions": {
            "dispatched_count_gt_0": cond_dispatched,
            "lifecycle_non_empty": cond_lifecycle,
            "not_all_handler_failed": cond_no_all_failed,
        },
        "passed": cond_dispatched and cond_lifecycle and cond_no_all_failed,
    }


def _print_report(result: dict[str, Any]) -> None:
    _log("=" * 64)
    _log(f"客服工单闭环验收报告")
    _log("=" * 64)
    _log(f"工单号:       {result['ticket_no']}  (id={result['ticket_id']})")
    _log(f"status:       {result['status']}")
    _log(f"decision:     {result['decision_status']}")
    _log(f"lifecycle:    {result['lifecycle_stage']}  (>=2 处理中, >=3 有结果, =5 已完成)")
    _log(f"事件数:       {len(result['incident_events'])}")
    for e in result["incident_events"]:
        _log(f"  - event_id={e['id']} dispatched={e['dispatched_count']} source={e['source']}")
    _log(f"max_dispatched_count: {result['max_dispatched_count']}")
    _log(f"handler_summary:      {result['handler_summary']}")
    _log("-" * 64)
    _log("SSOT 三条件:")
    for k, v in result["conditions"].items():
        mark = "PASS" if v else "FAIL"
        _log(f"  [{mark}] {k}")
    _log("-" * 64)
    _log(f"综合: {'PASS ✅' if result['passed'] else 'FAIL ❌'}")


def _trigger_new_ticket(base_url: str, token: str) -> tuple[str, str]:
    """通过 HTTP 创建一张新工单，返回 (ticket_no, session_id)。"""
    import urllib.request

    summary = (
        "[生产验收] 客服工单闭环实跑验证 - "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )

    def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # 1) 开 session
    r1 = _post("/api/customer-service/chat", {"message": summary, "context": {}})
    sid = r1.get("session", {}).get("id")
    if not sid:
        _log(f"ERROR: no session id in response: {r1}")
        sys.exit(EXIT_ERROR)

    # 2) 提交工单
    r2 = _post(
        "/api/customer-service/chat",
        {"message": "提交工单", "session_id": sid, "context": {"reason": summary}},
    )
    ticket = r2.get("ticket") or {}
    ticket_no = str(ticket.get("ticket_no") or "")
    if not ticket_no.startswith("CS"):
        _log(f"ERROR: no CS* ticket_no in response: {r2}")
        sys.exit(EXIT_ERROR)
    return ticket_no, str(sid)


def _wait_for_closure(conn, ticket_no: str, timeout: int) -> dict[str, Any] | None:
    deadline = time.time() + timeout
    last_lifecycle = -1
    while time.time() < deadline:
        ticket = _fetch_ticket_by_no(conn, ticket_no)
        if not ticket:
            _log(f"waiting: ticket {ticket_no} not yet visible in DB...")
            threading.Event().wait(3)
            continue
        result = _verify_ticket(conn, ticket)
        if result["lifecycle_stage"] != last_lifecycle:
            _log(
                f"progress: lifecycle={result['lifecycle_stage']} "
                f"dispatched={result['max_dispatched_count']} "
                f"handler={result['handler_summary']}"
            )
            last_lifecycle = result["lifecycle_stage"]
        # 闭环完成：lifecycle >= 3（有结果）或 dispatched > 0 且非全员失败
        if result["passed"] and result["lifecycle_stage"] >= 3:
            return result
        threading.Event().wait(5)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="客服工单闭环生产验收")
    parser.add_argument("--check-latest", action="store_true", help="核查最近一张 CS* 工单")
    parser.add_argument("--ticket-no", help="指定工单号核查")
    parser.add_argument("--trigger", action="store_true", help="触发一张新工单并跟踪到闭环")
    parser.add_argument("--db-path", default=os.environ.get("MODSTORE_DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("MODSTORE_VERIFY_TIMEOUT", str(DEFAULT_TIMEOUT))),
    )
    args = parser.parse_args()

    if not (args.check_latest or args.ticket_no or args.trigger):
        parser.error("至少指定 --check-latest / --ticket-no / --trigger 之一")

    _log(f"DB: {args.db_path}")
    conn = _connect(args.db_path)

    try:
        if args.trigger:
            base_url = os.environ.get("MODSTORE_BASE_URL", "").strip()
            token = os.environ.get("MODSTORE_AUTH_TOKEN", "").strip()
            if not base_url or not token:
                _log("ERROR: --trigger 需要 MODSTORE_BASE_URL + MODSTORE_AUTH_TOKEN")
                return EXIT_ERROR
            _log(f"BASE_URL: {base_url}")
            ticket_no, sid = _trigger_new_ticket(base_url, token)
            _log(f"triggered: ticket_no={ticket_no} session_id={sid}")
            _log(f"waiting up to {args.timeout}s for closure...")
            result = _wait_for_closure(conn, ticket_no, args.timeout)
            if not result:
                _log(f"FAIL: ticket {ticket_no} 未在 {args.timeout}s 内闭环")
                ticket = _fetch_ticket_by_no(conn, ticket_no)
                if ticket:
                    result = _verify_ticket(conn, ticket)
                    _print_report(result)
                return EXIT_FAIL
            _print_report(result)
            return EXIT_PASS if result["passed"] else EXIT_FAIL

        if args.ticket_no:
            ticket = _fetch_ticket_by_no(conn, args.ticket_no)
            if not ticket:
                _log(f"ERROR: ticket {args.ticket_no} not found")
                return EXIT_ERROR
            result = _verify_ticket(conn, ticket)
            _print_report(result)
            return EXIT_PASS if result["passed"] else EXIT_FAIL

        if args.check_latest:
            ticket = _fetch_latest_cs_ticket(conn)
            if not ticket:
                _log("FAIL: 没有找到任何 CS* 工单（生产可能从未跑过客服闭环）")
                return EXIT_FAIL
            result = _verify_ticket(conn, ticket)
            _print_report(result)
            return EXIT_PASS if result["passed"] else EXIT_FAIL

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
