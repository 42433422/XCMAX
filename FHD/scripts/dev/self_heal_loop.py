#!/usr/bin/env python3
"""Approval-gated Work Order repair orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from app.services.work_order_gate import gate_receipts, record_gate  # noqa: E402
from app.services.work_order_ssot import (  # noqa: E402
    get_work_order,
    record_transition,
    upsert_candidate,
)
from app.services.work_order_state import _ALLOWED_TRANSITIONS  # noqa: E402

logger = logging.getLogger("self_heal_loop")

_LOOP_DIR = Path(
    os.environ.get("SELF_HEAL_LOOP_DIR") or (_FHD_ROOT / "test_reports" / "self_heal_loop")
)

_STAGES: dict[str, tuple[str, str, frozenset[str]]] = {
    "evidence": ("evidence", "intake", frozenset({"ROUTED"})),
    "diagnosis": ("diagnosis", "evidence", frozenset({"COLLECTED"})),
    "repro_red": ("repro", "diagnosis", frozenset({"DIAGNOSED"})),
    "fix_green": ("fix", "repro", frozenset({"RED"})),
    "pull_request": ("pull_request", "fix", frozenset({"FIX_VALIDATED_IN_DEV"})),
    "owner_instance": ("owner_instance", "pull_request", frozenset({"OPEN"})),
    "approval": ("approval", "owner_instance", frozenset({"OWNER_INSTANCE_VERIFIED"})),
    "merge": ("merge", "approval", frozenset({"approved"})),
    "release": ("release", "merge", frozenset({"MERGED"})),
    "customer_retest": ("customer_retest", "release", frozenset({"RELEASED"})),
    "close": ("close", "customer_retest", frozenset({"PASS"})),
    "knowledge": ("knowledge", "close", frozenset({"CLOSED"})),
}

_PASS_STATUS: dict[str, str] = {
    "evidence": "COLLECTED",
    "diagnosis": "DIAGNOSED",
    "repro_red": "RED",
    "fix_green": "FIX_VALIDATED_IN_DEV",
    "pull_request": "OPEN",
    "owner_instance": "OWNER_INSTANCE_VERIFIED",
    "merge": "MERGED",
    "release": "RELEASED",
    "customer_retest": "PASS",
    "close": "CLOSED",
    "knowledge": "RECORDED",
}

_APPROVAL_DECISIONS = frozenset({"approve", "reject", "hold"})
_MIN_APPROVER_LEN = 2

_PASS_STATE: dict[str, str] = {
    "fix_green": "in_dev",
    "merge": "merged",
    "release": "released",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _retest_dir() -> Path:
    return Path(os.environ.get("WORK_ORDER_RETEST_DIR") or (_FHD_ROOT / "test_reports" / "retest"))


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _receipt(wo_id: str, stage: str, status: str, **extra: Any) -> dict[str, Any]:
    _LOOP_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "wo_id": wo_id,
        "stage": stage,
        "status": status,
        "at": _utc_now(),
        **extra,
    }
    blob = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    path = _LOOP_DIR / f"{stage}-{wo_id}.json"
    path.write_bytes(blob)
    result = record_gate(
        wo_id,
        _STAGES.get(stage, (stage,))[0],
        status,
        evidence={"receipt": str(path), "sha256": _sha256_bytes(blob), **extra.get("evidence", {})},
        note=str(extra.get("note") or ""),
        source="self_heal_loop",
    )
    if not result.get("ok"):
        raise SystemExit(f"闸门写入失败 {stage}: {result.get('reason')}（工单 {wo_id}）")
    return record


def _require_gate(wo_id: str, stage: str) -> None:
    if stage == "intake":
        return
    _gate, dep_gate, allowed = _STAGES[stage]
    receipt = gate_receipts(wo_id).get(dep_gate)
    status = str((receipt or {}).get("gate_status") or "")
    if status not in allowed:
        raise SystemExit(
            f"门禁阻断：{stage} 需要 {dep_gate}={sorted(allowed)}，"
            f"当前 {dep_gate}={status or '（无收据）'}（工单 {wo_id}）"
        )


def _shortest_path(start: str, target: str) -> list[str]:
    if start == target:
        return []
    queue: list[tuple[str, list[str]]] = [(start, [])]
    seen = {start}
    while queue:
        node, path = queue.pop(0)
        for nxt in sorted(_ALLOWED_TRANSITIONS.get(node, frozenset())):
            if nxt == target:
                return [*path, nxt]
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return []


def _advance(wo_id: str, target: str) -> None:
    current = str((get_work_order(wo_id) or {}).get("status") or "")
    for nxt in _shortest_path(current, target):
        result = record_transition(
            wo_id,
            nxt,
            note=f"闭环编排器按实测结果推进（{current} → {target}）",
            source="self_heal_loop",
        )
        if not result.get("ok") and result.get("reason") != "already_in_state":
            raise SystemExit(
                f"状态迁移被拒 {current}→{nxt}: {result.get('reason')}（工单 {wo_id}）"
            )
        current = nxt
    if current != target:
        raise SystemExit(f"状态机阻断：{current} 无法到达 {target}（工单 {wo_id}）")


def cmd_start(args: argparse.Namespace) -> int:
    signal = json.loads(Path(args.signal).read_text(encoding="utf-8"))
    wo_id = str(signal.get("work_order_id") or "").strip()
    if wo_id:
        view = get_work_order(wo_id)
        context = view.get("context") if isinstance(view, dict) else {}
        context = context if isinstance(context, dict) else {}
        bundle_sha = str(signal.get("support_bundle_sha256") or "")
        if (
            not view
            or view.get("source") != "client_ai_product_issue"
            or not context.get("customer_reported")
            or not re.fullmatch(r"[0-9a-f]{64}", bundle_sha)
            or (
                signal.get("user_id") is not None
                and int(context.get("customer_user_id") or 0) != int(signal["user_id"])
            )
        ):
            raise SystemExit(f"客户事件与 Work Order 不匹配：拒绝重新建单（{wo_id}）")
        if view.get("status") == "candidate":
            result = record_transition(
                wo_id,
                "routed",
                ref={
                    "track": str(signal.get("track") or "product_line"),
                    "customer_ticket_id": signal.get("ticket_id"),
                    "customer_ticket_no": signal.get("ticket_no"),
                },
                note="客户端缺陷工单已送达 Owner",
                source="customer_issue_intake",
            )
            if not result.get("ok"):
                raise SystemExit(f"既有 Work Order 无法派发：{result.get('reason')}（{wo_id}）")
        elif view.get("status") != "routed":
            raise SystemExit(f"Work Order 已进入后续阶段，拒绝覆盖：{wo_id}={view.get('status')}")
        _receipt(
            wo_id,
            "intake",
            "ROUTED",
            note="客户事件复用已创建的 Work Order",
            evidence={"customer_ticket_id": signal.get("ticket_id")},
        )
        _receipt(
            wo_id,
            "evidence",
            "COLLECTED",
            note="客户事件复用已创建的 Work Order",
            evidence={
                "customer_ticket_id": signal.get("ticket_id"),
                "customer_ticket_no": signal.get("ticket_no"),
                "support_bundle_sha256": signal.get("support_bundle_sha256"),
            },
        )
        print(json.dumps({"wo_id": wo_id, "created": False}, ensure_ascii=False))
        return 0
    key = str(signal.get("dedup_key") or "").strip()
    if not key:
        raise SystemExit("signal.dedup_key 缺失：无法保证复验回到同一工单")
    res = upsert_candidate(
        source=str(signal.get("source") or "customer_instance"),
        dedup_key=key,
        reason=str(signal.get("reason") or "functional_failure"),
        context=dict(signal.get("context") or {}),
        evidence_ref=signal.get("evidence_ref") or None,
    )
    wo_id = str(res.get("wo_id") or "")
    if not wo_id:
        raise SystemExit(f"建单失败：{res.get('reason') or 'unknown'}")
    if res.get("created"):
        track = str(signal.get("track") or "").strip()
        record_transition(
            wo_id,
            "routed",
            ref={"track": track} if track else None,
            note="闭环编排器建单",
            source="self_heal_loop",
        )
    _receipt(
        wo_id,
        "intake",
        "ROUTED",
        note="真实信号已入工单",
        evidence={"source": str(signal.get("source") or ""), "dedup_key": key},
    )
    print(json.dumps({"wo_id": wo_id, "created": bool(res.get("created"))}, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    wo_id = args.wo
    _require_gate(wo_id, args.stage)
    timeout = float(args.timeout)
    started = _utc_now()
    cwd = str(Path(args.cwd or _FHD_ROOT).resolve())
    signature = str(args.expected_signature or "").strip()
    if args.stage == "repro_red" and not signature:
        raise SystemExit("repro_red 必须给出 --expected-signature，避免把无关命令失败误认成复现")
    if args.stage == "fix_green":
        red = gate_receipts(wo_id).get("repro", {}).get("evidence", {})
        if red.get("command") != args.cmd or red.get("cwd") != cwd:
            raise SystemExit("fix_green 必须重跑与 repro_red 相同的命令和工作目录")
    try:
        completed = subprocess.run(
            args.cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout or "", completed.stderr or ""
    except subprocess.TimeoutExpired:
        exit_code, stdout, stderr = 124, "", f"timeout after {timeout}s"
    output = f"{stdout}\n{stderr}"
    passed = exit_code != 0 and signature in output if args.stage == "repro_red" else exit_code == 0
    status = _PASS_STATUS.get(args.stage, "OK") if passed else "FAILED"
    log_dir = _LOOP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{args.stage}-{wo_id}.log"
    log_path.write_text(f"$ {args.cmd}\n\n{stdout}\n{stderr}", encoding="utf-8")
    identity = {}
    if args.artifact_sha256:
        identity["artifact_sha256"] = str(args.artifact_sha256)
    if args.release_sha:
        identity["release_sha"] = str(args.release_sha)
    _receipt(
        wo_id,
        args.stage,
        status,
        note=str(args.note or ""),
        evidence={
            "command": args.cmd,
            "cwd": cwd,
            "exit_code": exit_code,
            "expected": {"signature": signature} if args.stage == "repro_red" else {"exit_code": 0},
            "started_at": started,
            "log": str(log_path),
            "log_sha256": _sha256_bytes(log_path.read_bytes()),
            **identity,
        },
    )
    if passed and args.stage in _PASS_STATE:
        _advance(wo_id, _PASS_STATE[args.stage])
    print(json.dumps({"wo_id": wo_id, "stage": args.stage, "status": status}, ensure_ascii=False))
    return 0 if passed else 1


def cmd_approval(args: argparse.Namespace) -> int:
    wo_id, decision = args.wo, str(args.decision)
    if decision not in _APPROVAL_DECISIONS:
        raise SystemExit(f"未知审批决定 {decision}；只允许 {sorted(_APPROVAL_DECISIONS)}")
    approver = str(args.approver or "").strip()
    if len(approver) < _MIN_APPROVER_LEN:
        raise SystemExit("审批必须记录真实审批人身份（--approver），不接受匿名放行")
    if decision == "approve":
        _require_gate(wo_id, "approval")
    status = {"approve": "approved", "reject": "rejected", "hold": "held"}[decision]
    _receipt(
        wo_id,
        "approval",
        status,
        note=str(args.reason or ""),
        evidence={"approver": approver, "decision": decision, "decided_at": _utc_now()},
    )
    print(
        json.dumps({"wo_id": wo_id, "approval": status, "approver": approver}, ensure_ascii=False)
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    view = get_work_order(args.wo)
    if view is None:
        raise SystemExit(f"未知工单 {args.wo}")
    receipts = gate_receipts(args.wo)
    out = {
        "wo_id": args.wo,
        "status": view.get("status"),
        "issue_number": view.get("issue_number"),
        "gates": {
            name: {"status": rec.get("gate_status"), "at": rec.get("at")}
            for name, rec in sorted(receipts.items())
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_retest(args: argparse.Namespace) -> int:
    wo_id = args.wo
    _require_gate(wo_id, "customer_retest")
    script = _FHD_ROOT / "scripts" / "dev" / "customer_retest.py"
    command = [
        sys.executable,
        str(script),
        "--spec",
        str(args.spec),
        "--base-url",
        str(args.base_url),
    ]
    if args.expect_version:
        command += ["--expect-version", str(args.expect_version)]
    if args.issue_comment:
        command += ["--issue-comment", str(args.issue_comment)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=300)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    key12 = str(spec.get("dedup_key") or Path(args.spec).stem.removeprefix("repro-"))[:12]
    receipt_path = _retest_dir() / f"receipt-{key12}.json"
    verdict = "fail"
    if receipt_path.is_file():
        verdict = str(json.loads(receipt_path.read_text(encoding="utf-8")).get("verdict") or "fail")
    passed = completed.returncode == 0 and verdict == "pass"
    _receipt(
        wo_id,
        "customer_retest",
        "PASS" if passed else "FAIL",
        note="客户机自动重测原失败场景",
        evidence={"receipt": str(receipt_path), "verdict": verdict},
    )
    if passed:
        _advance(wo_id, "verifying")
        _advance(wo_id, "closed")
        _receipt(wo_id, "close", "CLOSED", note="客户机自证问题已解决")
        return 0
    _advance(wo_id, "verifying")
    _advance(wo_id, "reopened")
    _receipt(wo_id, "close", "REOPENED", note="客户机复验失败，原单重开")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    p_start = sub.add_parser("start", help="真实信号建单（幂等）")
    p_start.add_argument("--signal", required=True)

    p_run = sub.add_parser("run", help="执行阶段命令并按真实结果落闸门")
    p_run.add_argument("stage", choices=sorted(_STAGES))
    p_run.add_argument("--wo", required=True)
    p_run.add_argument("--cmd", required=True)
    p_run.add_argument("--cwd", default="")
    p_run.add_argument(
        "--expected-signature", default="", help="repro_red 输出中必须命中的原始错误签名"
    )
    p_run.add_argument("--note", default="")
    p_run.add_argument("--artifact-sha256", default="", help="发布阶段：制品 SHA256（可追溯身份）")
    p_run.add_argument("--release-sha", default="", help="发布阶段：制品对应的 git commit sha")
    p_run.add_argument("--timeout", type=float, default=1800.0)

    p_appr = sub.add_parser("approval", help="发布前人工审批（硬门）")
    p_appr.add_argument("--wo", required=True)
    p_appr.add_argument("--decision", required=True, choices=sorted(_APPROVAL_DECISIONS))
    p_appr.add_argument("--approver", required=True)
    p_appr.add_argument("--reason", default="")

    p_st = sub.add_parser("status", help="工单状态与闸门收据")
    p_st.add_argument("--wo", required=True)

    p_rt = sub.add_parser("retest", help="客户机复验并关单/reopen")
    p_rt.add_argument("--wo", required=True)
    p_rt.add_argument("--spec", required=True)
    p_rt.add_argument("--base-url", required=True)
    p_rt.add_argument("--expect-version", default="")
    p_rt.add_argument("--issue-comment", default="")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    handlers = {
        "start": cmd_start,
        "run": cmd_run,
        "approval": cmd_approval,
        "status": cmd_status,
        "retest": cmd_retest,
    }
    return handlers[args.action](args)


if __name__ == "__main__":
    raise SystemExit(main())
