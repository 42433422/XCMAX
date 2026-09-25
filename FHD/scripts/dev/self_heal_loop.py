#!/usr/bin/env python3
"""AI 自愈生产闭环编排器：真实客户问题 → AI 修复 → 人工审批 → 客户复验。

一个工单（``wo_id``）贯穿全程，不中途另起新单。本脚本只做四件事，
其余每一步都复用仓库既有能力（不重造）：

  1. **建单**：真实信号 → Work Order SSOT（``upsert_candidate`` + ``routed``）
  2. **执行**：``run <stage> --cmd ...`` 真实执行该阶段命令，按真实结果落闸门收据，
     并沿状态机把工单推进到该阶段应有的状态（收据与状态必须同时前进）
  3. **闸门**：fail-closed 依赖判定——上一步没有真实凭据，下一步不允许开跑
  4. **审批**：发布前硬门，只接受明确 approve / reject / hold；没有 approve 不放行

闸门收据写在 ``app.services.work_order_gate``（同一条工单事件流），因此
「走到哪一步」与「凭哪份证据过的」可用同一个 ``wo_id`` 核对。

阶段与依赖（fail-closed）：

    intake → evidence → diagnosis → repro_red → fix_green → pull_request
        → owner_instance → approval → merge → release → customer_retest → close → knowledge

典型用法：

    # 1) 建单（真实信号）
    python scripts/dev/self_heal_loop.py start --signal signal.json

    # 2) 逐阶段执行（命令退出码即判定；证据留原文摘要 + SHA256）
    python scripts/dev/self_heal_loop.py run repro_red --wo WO-xxx --cmd "bash red.sh"

    # 3) 发布前人工审批（硬门，必须人工调用）
    python scripts/dev/self_heal_loop.py approval --wo WO-xxx \
        --decision approve --approver owner --reason "客户现场已复现且回归通过"

    # 4) 客户机复验 → 自动关单 / 自动 reopen
    python scripts/dev/self_heal_loop.py retest --wo WO-xxx --spec repro.json \
        --base-url http://127.0.0.1:17500 --expect-version 1.0.0.6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
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
    upsert_candidate,
)
from app.services.work_order_state import _ALLOWED_TRANSITIONS  # noqa: E402

logger = logging.getLogger("self_heal_loop")

_LOOP_DIR = Path(
    os.environ.get("SELF_HEAL_LOOP_DIR") or (_FHD_ROOT / "test_reports" / "self_heal_loop")
)

# 阶段 → (闸门名, 依赖闸门, 依赖必须命中的状态集合)
_STAGES: dict[str, tuple[str, str, frozenset[str]]] = {
    "evidence": ("evidence", "intake", frozenset({"ROUTED"})),
    "diagnosis": ("diagnosis", "evidence", frozenset({"COLLECTED"})),
    "repro_red": ("repro", "diagnosis", frozenset({"DIAGNOSED"})),
    "fix_green": ("fix", "repro", frozenset({"RED"})),
    "pull_request": ("pull_request", "fix", frozenset({"FIX_VALIDATED_IN_DEV"})),
    "owner_instance": ("owner_instance", "pull_request", frozenset({"OPEN"})),
    # 审批的依赖是「自有实例已复验通过」；审批本身不改状态机，只落决策收据
    "approval": ("approval", "owner_instance", frozenset({"OWNER_INSTANCE_VERIFIED"})),
    # 合入 main 是独立闸门：状态机的 merged 只能由真实合并结果换取，
    # 不允许在 release 阶段「顺路」把状态推过 merged（那是假闭环）。
    "merge": ("merge", "approval", frozenset({"approved"})),
    "release": ("release", "merge", frozenset({"MERGED"})),
    "customer_retest": ("customer_retest", "release", frozenset({"RELEASED"})),
    "close": ("close", "customer_retest", frozenset({"PASS"})),
    "knowledge": ("knowledge", "close", frozenset({"CLOSED"})),
}

# 执行成功时该阶段应落的闸门状态（调用方可用 --status 覆盖为真实结果）
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
# 审批身份的硬要求：必须是人（非空），并留下时间戳；空身份直接拒绝。
_MIN_APPROVER_LEN = 2

# 阶段执行成功后应收敛到的工单状态（缺省表示该阶段不动状态机）
_PASS_STATE: dict[str, str] = {
    "fix_green": "in_dev",
    "merge": "merged",
    "release": "released",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _retest_dir() -> Path:
    """与 customer_retest.py 同一解析规则：两侧落在不同目录会把 PASS 读成 FAIL。"""
    return Path(os.environ.get("WORK_ORDER_RETEST_DIR") or (_FHD_ROOT / "test_reports" / "retest"))


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _receipt(wo_id: str, stage: str, status: str, **extra: Any) -> dict[str, Any]:
    """落一条闸门收据 + 一份本地 JSON 副本，返回收据内容。"""
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
    """fail-closed：依赖闸门没有真实凭据时拒绝推进。"""
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
    """状态机上的最短合法路径（不含起点）；不可达时返回空列表。"""
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
    """按状态机允许的路径把工单推进到 target；路径不可达时 fail-closed 阻断。

    闸门收据回答「凭哪份证据过的」，状态机回答「走到哪一步」；两者必须同时前进，
    否则会出现「收据说已发布、工单还停在 routed」的假闭环。
    """
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
    """真实信号 → 唯一工单（幂等：同 dedup_key 不重复建单）。"""
    signal = json.loads(Path(args.signal).read_text(encoding="utf-8"))
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
    """真实执行某阶段命令，按退出码落闸门收据。"""
    wo_id = args.wo
    _require_gate(wo_id, args.stage)
    timeout = float(args.timeout)
    started = _utc_now()
    # repro_red 的「通过」语义是命令**失败**——复现用例红，才叫复现成功；
    # 其余阶段沿用退出码 0 为通过。可用 --expect-exit / --expect-nonzero 覆盖。
    expect_nonzero = (
        args.expect_nonzero if args.expect_nonzero is not None else (args.stage == "repro_red")
    )
    try:
        completed = subprocess.run(
            args.cmd,
            shell=True,
            cwd=str(args.cwd or _FHD_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout or "", completed.stderr or ""
    except subprocess.TimeoutExpired:
        exit_code, stdout, stderr = 124, "", f"timeout after {timeout}s"
    passed = exit_code != 0 if expect_nonzero else exit_code == int(args.expect_exit)
    status = args.status or (_PASS_STATUS.get(args.stage, "OK") if passed else args.fail_status)
    if not status:
        raise SystemExit("失败时必须给出 --fail-status，避免把失败写成模糊状态")
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
            "exit_code": exit_code,
            "expected": "non-zero" if expect_nonzero else int(args.expect_exit),
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
    """发布前人工审批硬门：approve / reject / hold，无 approve 不放行。"""
    wo_id, decision = args.wo, str(args.decision)
    if decision not in _APPROVAL_DECISIONS:
        raise SystemExit(f"未知审批决定 {decision}；只允许 {sorted(_APPROVAL_DECISIONS)}")
    approver = str(args.approver or "").strip()
    if len(approver) < _MIN_APPROVER_LEN:
        raise SystemExit("审批必须记录真实审批人身份（--approver），不接受匿名放行")
    if decision == "approve":
        # 硬门：未在自有实例复验通过前，不允许批准发布
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
    """打印工单状态 + 全部闸门收据（对外可核对视图）。"""
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
    """客户机复验 → PASS 自动关单、FAIL 自动 reopen（不另起新单）。"""
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
    p_run.add_argument("--expect-exit", type=int, default=0)
    p_run.add_argument(
        "--expect-nonzero",
        action="store_true",
        default=None,
        help="该阶段以命令失败为通过（默认仅 repro_red 如此）",
    )
    p_run.add_argument("--status", default="")
    p_run.add_argument("--fail-status", default="FAILED")
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
