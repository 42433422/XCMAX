"""Production HTTP/worker/SQL round trip: business text must remain unchanged."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_inventory_http_preserves_text_and_tenant_isolation(tmp_path):
    # A fresh interpreter avoids fixture-created sessions and parent-only mocks:
    # the production tool worker must reopen the same on-disk database itself.
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.test_application.test_inventory_input_fidelity",
                str(tmp_path),
            ],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            text=True,
            capture_output=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            "Inventory HTTP/worker verification exceeded 300 seconds. "
            f"stdout={(exc.stdout or b'')[-4000:]!r}; "
            f"stderr={(exc.stderr or b'')[-12000:]!r}"
        ) from exc
    if completed.returncode:
        raise AssertionError(
            f"Inventory HTTP/worker verification exited {completed.returncode}.\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-12000:]}"
        )
    result = json.loads(completed.stdout.rsplit("INVENTORY_FIDELITY=", 1)[1])
    assert result == {
        "anonymous_status": 401,
        "agent_status": "completed",
        "remark": "synthetic<A&B> 中文 'quoted' \"text\"\nsecond line",
        "quantity": 10,
        "cross_tenant_success": False,
        "transaction_count": 1,
    }


def _exercise(root: Path) -> None:
    from datetime import timedelta

    root.mkdir(parents=True, exist_ok=True)
    (root / "mods").mkdir(exist_ok=True)
    database = root / "business.sqlite3"
    os.environ.update(
        {
            "DATABASE_URL": f"sqlite:///{database}",
            "VECTOR_DB_URL": f"sqlite:///{database}",
            "DATABASE_PATH": str(root),
            "XCAGI_DATA_DIR": str(root),
            "XCAGI_DESKTOP_FAST_START": "0",
            "XCAGI_DESKTOP_MODE": "0",
            "XCAGI_DEBUG": "0",
            "XCAGI_PRODUCT_SKU": "enterprise",
            "XCAGI_AGENT_RUN_REQUIRE_DURABLE": "1",
            "XCAGI_TOOL_IDEMPOTENCY_PATH": str(root / "tool-idempotency.sqlite3"),
            "XCAGI_MODS_ROOT": str(root / "mods"),
            "XCAGI_MODS_DIR": str(root / "mods"),
            "XCAGI_CLIENT_MODS_OFF": "1",
            "XCAGI_SKIP_LEGACY_COMPAT_ROUTES": "0",
            "SECRET_KEY": "inventory-fidelity-test-only-not-a-production-key",
            "FHD_INTENT_SEMANTIC_ENABLED": "0",
            "CACHE_REDIS_URL": "",
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_LEDGER_PATH": str(root / "usage.json"),
            "UPLOAD_FOLDER": str(root / "uploads"),
            "XCAGI_AUTONOMY_DATA_DIR": str(root / "autonomy"),
            "XCAGI_AUTONOMY_AUDIT_DB_PATH": str(root / "autonomy.sqlite3"),
            "XCAGI_AUTONOMY_AUDIT_LOG_PATH": str(root / "autonomy.jsonl"),
            "XIUCI_PLATFORM_MADE_TOKENS_PATH": str(root / "tokens.json"),
            "XCAGI_SLA_SNAPSHOT_PATH": str(root / "sla.json"),
            "XCAGI_PLAN_GRAPH_LOG": str(root / "plans.jsonl"),
            "DATASET_RAG_STORE_PATH": str(root / "rag.json"),
            "DATASET_RAG_VECTOR_INDEX_PATH": str(root / "vectors.sqlite3"),
        }
    )
    os.environ.pop("MODEL_USAGE_WALLET_REQUIRED", None)
    from fastapi.testclient import TestClient

    from app.db import HostSessionLocal, engine
    from app.db.db_base import Base
    from app.db.models import Product, Warehouse
    from app.db.models.approval import ApprovalRequest
    from app.db.models.permission import Permission, Role
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.fastapi_app import create_fastapi_app
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.time import utc_now_naive

    Base.metadata.create_all(engine)
    with HostSessionLocal() as db, db.begin():
        role = Role(name="inventory-fidelity")
        role.permissions = [
            Permission(code=code, name=code)
            for code in (
                "tool.inventory.stock_in",
                "tool.inventory.stock_out",
                "tool.inventory.query_transactions",
            )
        ]
        db.add(role)
        reviewer_role = Role(name="inventory-fidelity-reviewer")
        reviewer_role.permissions = [Permission(code="approval.workflow", name="Approve workflow")]
        db.add(reviewer_role)
        for tenant in (9101, 9102):
            user = User(
                username=f"inventory-fidelity-{tenant}",
                password="synthetic-session-not-used-for-login",
                tenant_id=tenant,
                role=role.name,
                tier="enterprise",
            )
            db.add(user)
            db.flush()
            db.add(
                UserSession(
                    session_id=f"inventory-fidelity-session-{tenant}",
                    user_id=user.id,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    entitled_mod_ids_json="[]",
                )
            )
            reviewer = User(
                username=f"inventory-fidelity-reviewer-{tenant}",
                password="synthetic-reviewer-session-not-used-for-login",
                tenant_id=tenant,
                role=reviewer_role.name,
                tier="enterprise",
            )
            db.add(reviewer)
            db.flush()
            db.add(
                UserSession(
                    session_id=f"inventory-fidelity-reviewer-{tenant}",
                    user_id=reviewer.id,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    entitled_mod_ids_json="[]",
                )
            )
    with tenant_scope(9101), HostSessionLocal() as db, db.begin():
        product = Product(name="合成验收产品", quantity=0, unit="个")
        warehouse = Warehouse(code="FIDELITY-9101", name="合成验收仓库")
        db.add_all([product, warehouse])
        db.flush()
        product_id, warehouse_id = product.id, warehouse.id

    # Factory and middleware are real. No lifecycle schedulers or external
    # services are needed for this synchronous HTTP business transaction.
    app = create_fastapi_app()
    client = TestClient(app, raise_server_exceptions=False)
    client.get("/api/health")
    csrf = {"X-CSRF-Token": client.cookies.get("csrf_token", "")}
    remark = "synthetic<A&B> 中文 'quoted' \"text\"\nsecond line"
    payload = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "quantity": 10,
        "remark": remark,
    }
    denied = client.post("/api/inventory/in", json=payload, headers=csrf)
    assert denied.status_code == 401, denied.text

    def reviewed_post(path: str, body: dict, tenant: int, key: str):
        headers = {
            **csrf,
            "X-Session-ID": f"inventory-fidelity-session-{tenant}",
            "Idempotency-Key": key,
        }
        pending = client.post(path, json=body, headers=headers)
        assert pending.status_code == 202 and pending.json().get("pending_approval"), pending.text
        with tenant_scope(tenant), HostSessionLocal() as db:
            approval = (
                db.query(ApprovalRequest)
                .filter_by(request_no=pending.json()["approval_request_id"])
                .one()
            )
            approval_path = f"/api/approval/requests/{approval.id}/approve"
        # The applicant has tool access but no approval permission. The review
        # is submitted by a separate same-tenant account through the real API.
        self_approval = client.post(approval_path, json={}, headers=headers)
        assert self_approval.status_code == 403, self_approval.text
        approved = client.post(
            approval_path,
            json={"opinion": "合成验收独立审批"},
            headers={**csrf, "X-Session-ID": f"inventory-fidelity-reviewer-{tenant}"},
        )
        # A successful stock-in must complete. The other tenant has no stock:
        # the existing write-result guard preserves that failed execution as
        # uncertain, so approval alone must never be treated as its success.
        expected_review_status = 200 if tenant == 9101 else 202
        assert approved.status_code == expected_review_status, approved.text
        completed = client.post(path, json=body, headers=headers)
        assert completed.json().get("run_id") == pending.json()["run_id"], completed.text
        assert completed.json().get("deduplicated") is True, completed.text
        return completed

    response = reviewed_post("/api/inventory/in", payload, 9101, "inventory-fidelity-in-9101")
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["success"] is True and receipt["agent_status"] == "completed", receipt
    foreign = reviewed_post(
        "/api/inventory/out", {**payload, "quantity": 1}, 9102, "inventory-fidelity-out-9102"
    )
    foreign_receipt = foreign.json()
    assert foreign.status_code == 202 and foreign_receipt["success"] is False, foreign.text
    assert foreign_receipt["agent_status"] == "blocked", foreign.text
    assert foreign_receipt["execution_state"] == "unknown", foreign.text
    assert foreign_receipt["reconciliation_required"] is True, foreign.text
    assert foreign_receipt["retryable"] is False, foreign.text
    client.close()

    # Independent sqlite3 connection bypasses ORM caches and all application
    # response serializers: only the committed business facts count.
    import sqlite3

    with sqlite3.connect(database) as connection:
        actual = connection.execute(
            "SELECT remark, quantity FROM inventory_transactions WHERE product_id = ?",
            (product_id,),
        ).fetchmany(2)
        stock = connection.execute(
            "SELECT quantity FROM inventory_ledger WHERE product_id = ? AND tenant_id = ?",
            (product_id, 9101),
        ).fetchone()
    assert actual == [(remark, 10)], actual
    assert stock == (10,), stock
    print(
        "INVENTORY_FIDELITY="
        + json.dumps(
            {
                "anonymous_status": denied.status_code,
                "agent_status": receipt["agent_status"],
                "remark": actual[0][0],
                "quantity": stock[0],
                "cross_tenant_success": foreign.json()["success"],
                "transaction_count": len(actual),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    _exercise(Path(sys.argv[1]))
