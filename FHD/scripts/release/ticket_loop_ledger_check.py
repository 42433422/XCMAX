#!/usr/bin/env python3
"""工单闭环验收总账（ticket-loop.run.json）判定校验。

只读校验，不改总账。核心规则：
  1. 任何一项判 PASS 都必须有 observed_at 与非空 evidence（不能预填）。
  2. 「发版解决问题」必须走 Para：AI 处理相关条目（processor_policy.applies_to_items）
     判 PASS 时，每张已填工单的 processing 记录里必须有一次 para_delegate
     成功完成（accepted+completed+ok，且有 Para 任务号），并且不能出现任何
     本地大模型 / 本地执行回退（agent、vibe_*、cursor_delegate、direct_python、
     llm_md 等）。检测到回退即判失败，不算通过。
  3. B–I 段有 PASS 时，冻结版本、两个不同租户的客户账号、已解决工单号必须已填；
     重开条目 PASS 时重开工单号必须已填且不同于已解决工单号。
  4. gates.json 中引用本总账的闸门判 GREEN 时，其来源条目必须全部 PASS 且本校验无错误。

用法：python ticket_loop_ledger_check.py [--ledger PATH] [--gates PATH]
退出码 0 = 无违规；1 = 有违规（stdout 打印 JSON 违规列表）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "evidence" / "e2e" / "final-acceptance-1.0.0.5"
)

PARA_HANDLER = "para_delegate"
# 与 modstore_server.employee_executor 的 _LOCAL_FALLBACK_HANDLERS 对齐，并额外包含 llm_md
# （llm_md 不受 skip_local_after_para_ok 约束，Para 成功后仍可能执行，同样视为回退）。
DEFAULT_FORBIDDEN = (
    "agent",
    "vibe_edit",
    "vibe_heal",
    "vibe_code",
    "cursor_delegate",
    "direct_python",
    "llm_md",
)
DEFAULT_PARA_ITEMS = tuple(range(17, 28)) + (41, 48, 49)
IDENTITY_SECTIONS = set("BCDEFGHI")
REOPEN_ITEMS = (36, 37, 52)


def _items(ledger: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(i["no"]): i for i in ledger.get("items", []) if "no" in i}


def _passed(items: dict[int, dict[str, Any]], nos) -> list[int]:
    return [n for n in nos if (items.get(n) or {}).get("result") == "PASS"]


def _para_task_id(entry: dict[str, Any]) -> str:
    for key in ("para_task_id", "task_id"):
        if entry.get(key):
            return str(entry[key])
    snap = entry.get("para_result")
    if isinstance(snap, dict):
        if snap.get("id"):
            return str(snap["id"])
        task = snap.get("task")
        if isinstance(task, dict) and task.get("id"):
            return str(task["id"])
    return ""


def _load_attempts(processing: dict[str, Any], base: Path) -> tuple[list[dict[str, Any]], str]:
    attempts = processing.get("handlers_attempted")
    ref = processing.get("handler_outputs_evidence")
    if not attempts and ref:
        path = (base / str(ref)).resolve()
        if not path.is_file():
            return [], f"handler_outputs_evidence 文件不存在：{ref}"
        raw = json.loads(path.read_text(encoding="utf-8"))
        attempts = raw.get("outputs") if isinstance(raw, dict) else raw
    if not isinstance(attempts, list):
        return [], "handlers_attempted 必须是 handler 输出列表"
    return [a for a in attempts if isinstance(a, dict)], ""


def check_para_processing(
    name: str, processing: dict[str, Any] | None, policy: dict[str, Any], base: Path
) -> list[dict[str, Any]]:
    """单张工单的 Para 处理证据判定；返回违规列表（空 = 通过）。"""
    errs: list[dict[str, Any]] = []
    if not isinstance(processing, dict):
        return [{"code": "para_evidence_missing", "ticket": name}]
    attempts, load_err = _load_attempts(processing, base)
    if load_err:
        return [{"code": "para_evidence_missing", "ticket": name, "detail": load_err}]
    if not attempts:
        return [{"code": "para_evidence_missing", "ticket": name, "detail": "无 handler 执行记录"}]
    forbidden = set(policy.get("forbidden_local_handlers") or DEFAULT_FORBIDDEN)
    fallback = sorted(
        {str(a.get("handler")) for a in attempts if str(a.get("handler")) in forbidden}
    )
    if fallback:
        errs.append({"code": "para_fallback_detected", "ticket": name, "handlers": fallback})
    para_ok = [
        a
        for a in attempts
        if a.get("handler") == PARA_HANDLER
        and a.get("ok") is True
        and a.get("accepted", True) is True
        and a.get("completed") is True
        and _para_task_id(a)
    ]
    if not para_ok:
        errs.append({"code": "para_not_completed", "ticket": name})
    declared = str(processing.get("para_task_id") or "")
    if para_ok and declared and declared not in {_para_task_id(a) for a in para_ok}:
        errs.append({"code": "para_task_id_mismatch", "ticket": name, "declared": declared})
    if para_ok and not declared:
        errs.append({"code": "para_task_id_not_recorded", "ticket": name})
    return errs


def check_ledger(
    ledger: dict[str, Any], gates: dict[str, Any] | None = None, base: Path | None = None
) -> list[dict[str, Any]]:
    base = base or DEFAULT_DIR
    items = _items(ledger)
    errs: list[dict[str, Any]] = []

    for no, item in sorted(items.items()):
        if item.get("result") == "PASS":
            if not item.get("observed_at"):
                errs.append({"code": "pass_without_observed_at", "item": no})
            if not [e for e in item.get("evidence") or [] if str(e).strip()]:
                errs.append({"code": "pass_without_evidence", "item": no})

    policy = ledger.get("processor_policy") or {}
    para_items = tuple(policy.get("applies_to_items") or DEFAULT_PARA_ITEMS)
    tickets = ledger.get("tickets") or {}
    if _passed(items, para_items):
        for name in ("resolved", "reopened"):
            t = tickets.get(name) or {}
            if name == "resolved" or t.get("ticket_id"):
                errs.extend(check_para_processing(name, t.get("processing"), policy, base))

    identity_pass = [
        n
        for n, i in items.items()
        if i.get("section") in IDENTITY_SECTIONS and i.get("result") == "PASS"
    ]
    if identity_pass:
        cand = ledger.get("candidate") or {}
        for key in ("source_sha", "installer_sha256"):
            if not cand.get(key):
                errs.append({"code": "frozen_candidate_missing", "field": f"candidate.{key}"})
        accounts = ledger.get("accounts") or {}
        tenants = []
        for acc in ("customer_a", "customer_b"):
            a = accounts.get(acc) or {}
            if not a.get("alias") or not a.get("tenant"):
                errs.append({"code": "account_missing", "field": f"accounts.{acc}"})
            tenants.append(a.get("tenant"))
        if all(tenants) and tenants[0] == tenants[1]:
            errs.append({"code": "accounts_same_tenant"})
        if not (tickets.get("resolved") or {}).get("ticket_id"):
            errs.append({"code": "resolved_ticket_missing"})
    if _passed(items, REOPEN_ITEMS):
        r = (tickets.get("reopened") or {}).get("ticket_id")
        if not r:
            errs.append({"code": "reopened_ticket_missing"})
        elif r == (tickets.get("resolved") or {}).get("ticket_id"):
            errs.append({"code": "reopened_ticket_same_as_resolved"})

    for gate in (gates or {}).get("gates", []):
        if gate.get("status") != "GREEN":
            continue
        for src in gate.get("sources") or []:
            if src.get("run") != "ticket-loop.run.json" or not isinstance(src.get("items"), list):
                continue
            missing = [n for n in src["items"] if (items.get(n) or {}).get("result") != "PASS"]
            if missing or errs:
                errs.append(
                    {"code": "gate_green_without_pass", "gate": gate.get("no"), "items": missing}
                )
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=Path, default=DEFAULT_DIR / "ticket-loop.run.json")
    ap.add_argument("--gates", type=Path, default=DEFAULT_DIR / "gates.json")
    args = ap.parse_args(argv)
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8")) if args.gates.is_file() else None
    errs = check_ledger(ledger, gates, args.ledger.resolve().parent)
    print(json.dumps({"ok": not errs, "violations": errs}, ensure_ascii=False, indent=1))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
