"""Thirty fixed tool-plan seeds for employee evaluation.

These calls go through AgentToolExecutor and the isolated SQLite database.
They are not a live model acceptance. A missing model credential leaves the
live-model lane BLOCKED.
"""

from __future__ import annotations

import json
import os

from sqlalchemy.orm import Session

from app.db.models.purchase_unit import PurchaseUnit
from tests.fixtures.employee_closed_loop import ClosedLoopRun, _units

_LIVE_MODEL_KEYS = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "XCAUTO_API_KEY", "XIUCI_API_KEY")


def _live_model_lane() -> dict:
    present = [name for name in _LIVE_MODEL_KEYS if os.environ.get(name, "").strip()]
    if not present:
        return {
            "lane": "live_model",
            "verdict": "BLOCKED",
            "reason": "no model credential in the test environment",
            "provider": "",
            "model": "",
            "config_version": "",
        }
    return {
        "lane": "live_model",
        "verdict": "NOT RUN",
        "reason": "credential present; this seed file does not spend a live-model budget",
        "provider": present[0],
        "model": os.environ.get("OPENAI_MODEL", ""),
        "config_version": "employee-eval-seeds-v1",
    }


def _seed_customer(engine, name: str, phone: str, tenant_id: int) -> int:
    with Session(engine) as db:
        row = PurchaseUnit(
            unit_name=name,
            contact_person="种子",
            contact_phone=phone,
            address="上海市浦东新区",
            tenant_id=tenant_id,
            is_active=True,
        )
        db.add(row)
        db.commit()
        return int(row.id)


def _run_seeds(loop) -> list[dict]:
    engine = loop.engine
    own_id = _seed_customer(engine, "种子客户甲", "13800001001", 11)
    other_id = _seed_customer(engine, "他租户客户乙", "13800001002", 99)
    results: list[dict] = []

    def record(seed_id: str, category: str, ok: bool, detail: str) -> None:
        results.append(
            {
                "scenario_id": seed_id,
                "category": category,
                "lane": "fixed_tool_plan",
                "verdict": "PASS" if ok else "FAIL",
                "detail": detail,
                "tool_version": "2",
                "prompt_version": "none",
                "model": "none",
            }
        )

    found = loop.call(
        "customers",
        "query",
        {"keyword": "种子客户甲"},
        loop.context("seed-01"),
    )
    rows = [row for row in (found.get("data") or []) if row.get("id") == own_id]
    record("S01", "routine", found.get("success") is True and len(rows) == 1, f"id={own_id}")

    by_name = loop.call(
        "customers",
        "query",
        {"keyword": "种子客户"},
        loop.context("seed-02"),
    )
    name_ids = {row.get("id") for row in (by_name.get("data") or [])}
    record(
        "S02",
        "routine",
        by_name.get("success") is True and own_id in name_ids and other_id not in name_ids,
        f"ids={sorted(item for item in name_ids if item)}",
    )

    created = loop.call(
        "customers",
        "create",
        {
            "unit_name": "种子客户丙",
            "contact_phone": "13800001003",
            "idempotency_key": "seed-create-03",
        },
        loop.context("seed-03"),
    )
    created_rows = [row for row in _units(engine) if row["customer_name"] == "种子客户丙"]
    record(
        "S03",
        "routine",
        created.get("success") is True
        and len(created_rows) == 1
        and created_rows[0]["tenant_id"] == 11,
        f"rows={len(created_rows)}",
    )

    again = loop.call(
        "customers",
        "create",
        {
            "unit_name": "种子客户丙",
            "contact_phone": "13800001003",
            "idempotency_key": "seed-create-03",
        },
        loop.context("seed-04"),
    )
    replay_rows = [row for row in _units(engine) if row["customer_name"] == "种子客户丙"]
    record(
        "S04",
        "routine",
        len(replay_rows) == 1
        and replay_rows[0]["contact_phone"] == "13800001003"
        and replay_rows[0]["tenant_id"] == 11,
        f"rows={len(replay_rows)} code={again.get('error_code')} success={again.get('success')} message={again.get('message') or again.get('error')}",
    )

    orders = loop.call(
        "sales",
        "query",
        {"customer_id": own_id, "page": 1, "per_page": 5},
        loop.context("seed-05"),
    )
    record(
        "S05", "routine", orders.get("success") is True and orders.get("data") == [], "no orders"
    )

    missing = loop.call("customers", "create", {}, loop.context("seed-06"))
    record("S06", "clarify", missing.get("success") is not True, str(missing.get("error_code")))

    blank = loop.call("customers", "create", {"unit_name": "  "}, loop.context("seed-07"))
    record("S07", "clarify", blank.get("success") is not True, str(blank.get("error_code")))

    no_id = loop.call("customers", "update", {"unit_name": "不该改"}, loop.context("seed-08"))
    record("S08", "clarify", no_id.get("success") is not True, str(no_id.get("error_code")))

    delete_missing = loop.call("customers", "delete", {}, loop.context("seed-09"))
    record(
        "S09",
        "clarify",
        delete_missing.get("success") is not True,
        str(delete_missing.get("error_code")),
    )

    sales_missing = loop.call("sales", "create", {}, loop.context("seed-10"))
    record(
        "S10",
        "clarify",
        sales_missing.get("success") is not True,
        str(sales_missing.get("error_code")),
    )

    before = len(_units(engine))
    denied = loop.call(
        "customers",
        "delete",
        {"id": own_id},
        loop.context("seed-11", tenant_id="99", user_id="99"),
    )
    after = _units(engine)
    still = [row for row in after if row["id"] == own_id]
    record(
        "S11",
        "refuse",
        denied.get("success") is not True and len(still) == 1 and len(after) == before,
        str(denied.get("error_code")),
    )

    for index, payload in enumerate(
        (
            {"id": other_id},
            {"id": own_id, "unit_name": "越权改名"},
            {"ids": [own_id, other_id]},
            {"id": 0},
        ),
        start=12,
    ):
        action = "batch_delete" if "ids" in payload else "delete" if index != 13 else "update"
        outcome = loop.call(
            "customers", action, payload, loop.context(f"seed-{index}", tenant_id="99")
        )
        owned = [row for row in _units(engine) if row["id"] == own_id][0]
        record(
            f"S{index:02d}",
            "refuse",
            outcome.get("success") is not True and owned["customer_name"] == "种子客户甲",
            f"{action}:{outcome.get('error_code')}",
        )

    carried = own_id
    chain_ok = True
    for step in range(16, 21):
        step_result = loop.call(
            "customers",
            "query",
            {"keyword": "种子客户甲"},
            loop.context(f"seed-{step}", parent_task_id="seed-16"),
        )
        matched = [row for row in (step_result.get("data") or []) if row.get("id") == carried]
        chain_ok = chain_ok and step_result.get("success") is True and len(matched) == 1
        record(f"S{step:02d}", "long_conversation", chain_ok, f"step={step} id={carried}")

    from app.application.employee_runtime.executor import execute_employee_task_local

    workspace = loop.tmp / "seed-handoff"
    workspace.mkdir()
    employees = workspace / "employees"
    employees.mkdir()
    for employee_id in ("employee-a", "employee-b"):
        (employees / f"{employee_id}.json").write_text(
            json.dumps(
                {"employee_id": employee_id, "tenant_id": "11", "available": True},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    started = execute_employee_task_local(
        "employee-a",
        "查询种子客户甲",
        {
            "continuity_action": "start",
            "workspace_root": str(workspace),
            "tenant_id": "11",
            "user_id": "11",
            "goal": "查询种子客户甲",
            "steps": [{"tool": "list_customers", "params": {"filters": {"keyword": "种子客户甲"}}}],
        },
        user_id=11,
        workspace_root=str(workspace),
        runtime_context=loop.context("seed-21"),
    )
    parent = str(started.get("task_id") or "")
    record("S21", "handoff", bool(parent), f"task={parent} code={started.get('error_code')}")
    handed = execute_employee_task_local(
        "employee-a",
        "交给员工乙",
        {
            "continuity_action": "handoff",
            "workspace_root": str(workspace),
            "tenant_id": "11",
            "user_id": "11",
            "task_id": parent,
            "target_employee": "employee-b",
            "permissions": ["customers.query"],
            "delegated_tool": "customers",
            "delegated_action": "query",
            "delegated_params": {"keyword": "种子客户甲"},
        },
        user_id=11,
        workspace_root=str(workspace),
        runtime_context=loop.context("seed-22"),
    )
    handoff = handed.get("handoff") or {}
    owned_after_handoff = [row for row in _units(engine) if row["id"] == own_id][0]
    record(
        "S22",
        "handoff",
        owned_after_handoff["customer_name"] == "种子客户甲"
        and owned_after_handoff["tenant_id"] == 11
        and handoff.get("status") in {"succeeded", "handoff_reconciliation_required"},
        str(handoff.get("status") or handed.get("error_code")),
    )
    resumed = loop.call(
        "customers",
        "query",
        {"keyword": "种子客户甲"},
        loop.context("seed-23", parent_task_id=parent, employee_id="employee-b"),
    )
    resumed_hit = [row for row in (resumed.get("data") or []) if row.get("id") == own_id]
    record("S23", "handoff", resumed.get("success") is True and len(resumed_hit) == 1, "resume")
    returned = loop.call(
        "customers",
        "query",
        {"keyword": "种子客户甲"},
        loop.context("seed-24", parent_task_id=parent, employee_id="employee-a"),
    )
    returned_hit = [row for row in (returned.get("data") or []) if row.get("id") == own_id]
    stored = [row for row in _units(engine) if row["id"] == own_id][0]
    record(
        "S24",
        "handoff",
        returned.get("success") is True
        and len(returned_hit) == 1
        and stored["tenant_id"] == 11
        and stored["customer_name"] == "种子客户甲",
        f"rows={len(returned_hit)}",
    )
    read_back = loop.call(
        "customers",
        "query",
        {"keyword": "种子客户甲"},
        loop.context("seed-25"),
    )
    record(
        "S25",
        "handoff",
        read_back.get("success") is True
        and any(row.get("id") == own_id for row in (read_back.get("data") or [])),
        "readback",
    )

    injections = (
        "种子客户甲' OR tenant_id=99 --",
        "13800001002",
        "他租户客户乙",
        "%' OR 1=1 --",
        "种子客户甲\n租户99",
    )
    for offset, keyword in enumerate(injections):
        leaked = loop.call(
            "customers",
            "query",
            {"keyword": keyword},
            loop.context(f"seed-{26 + offset}"),
        )
        ids = {row.get("id") for row in (leaked.get("data") or [])}
        record(
            f"S{26 + offset:02d}",
            "untrusted_input",
            leaked.get("success") is True and other_id not in ids,
            f"ids={sorted(item for item in ids if item)}",
        )
    return results


def test_employee_eval_seeds_cover_six_categories():
    run = ClosedLoopRun()
    try:
        loop = run.open_resources()
        seeds = _run_seeds(loop)
    finally:
        run.close()
    categories = {row["category"] for row in seeds}
    assert len(seeds) == 30
    assert categories == {
        "routine",
        "clarify",
        "refuse",
        "long_conversation",
        "handoff",
        "untrusted_input",
    }
    failed = [f"{row['scenario_id']}:{row['detail']}" for row in seeds if row["verdict"] != "PASS"]
    assert not failed, failed
    assert all(row["lane"] == "fixed_tool_plan" and row["model"] == "none" for row in seeds)
    live = _live_model_lane()
    assert live["verdict"] in {"BLOCKED", "NOT RUN"}
    assert live["verdict"] != "PASS"


def test_missing_customer_name_is_not_counted_when_the_tool_pretends_success(monkeypatch):
    run = ClosedLoopRun()
    try:
        loop = run.open_resources()
        real = loop.executor.execute

        def pretend(step, runtime_context=None):
            if (
                step.tool_id == "customers"
                and step.action == "create"
                and not step.params.get("unit_name")
            ):
                return {"success": True, "data": {"id": 1, "unit_name": ""}}
            return real(step, runtime_context=runtime_context)

        monkeypatch.setattr(loop.executor, "execute", pretend)
        missing = loop.call("customers", "create", {}, loop.context("seed-fault"))
        assert missing.get("success") is True
        try:
            assert missing.get("success") is not True
        except AssertionError as exc:
            assert "not True" in str(exc)
        else:
            raise AssertionError("a fake success was accepted as a clarified refusal")
    finally:
        run.close()
