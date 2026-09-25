#!/usr/bin/env python3
"""Approval-gated Work Order repair orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
)
from app.services.work_order_state import _ALLOWED_TRANSITIONS  # noqa: E402

_LOOP_DIR = Path(
    os.environ.get("SELF_HEAL_LOOP_DIR") or (_FHD_ROOT / "test_reports" / "self_heal_loop")
)

_STAGES: dict[str, tuple[str, str, frozenset[str]]] = {
    "repro_red": ("repro", "diagnosis", frozenset({"DIAGNOSED"})),
    "fix_green": ("fix", "repro", frozenset({"RED"})),
    "customer_retest": ("customer_retest", "release", frozenset({"RELEASED"})),
}

_PASS_STATUS: dict[str, str] = {
    "repro_red": "RED",
    "fix_green": "FIX_VALIDATED_IN_DEV",
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
        },
    )
    if passed and args.stage == "fix_green":
        _advance(wo_id, "in_dev")
    print(json.dumps({"wo_id": wo_id, "stage": args.stage, "status": status}, ensure_ascii=False))
    return 0 if passed else 1


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

    p_run = sub.add_parser("run", help="执行阶段命令并按真实结果落闸门")
    p_run.add_argument("stage", choices=("repro_red", "fix_green"))
    p_run.add_argument("--wo", required=True)
    p_run.add_argument("--cmd", required=True)
    p_run.add_argument("--cwd", default="")
    p_run.add_argument(
        "--expected-signature", default="", help="repro_red 输出中必须命中的原始错误签名"
    )
    p_run.add_argument("--note", default="")
    p_run.add_argument("--timeout", type=float, default=1800.0)

    p_st = sub.add_parser("status", help="工单状态与闸门收据")
    p_st.add_argument("--wo", required=True)

    p_rt = sub.add_parser("retest", help="客户机复验并关单/reopen")
    p_rt.add_argument("--wo", required=True)
    p_rt.add_argument("--spec", required=True)
    p_rt.add_argument("--base-url", required=True)
    p_rt.add_argument("--expect-version", default="")
    p_rt.add_argument("--issue-comment", default="")

    args = parser.parse_args(argv)
    handlers = {
        "run": cmd_run,
        "status": cmd_status,
        "retest": cmd_retest,
    }
    return handlers[args.action](args)


if __name__ == "__main__":
    raise SystemExit(main())
