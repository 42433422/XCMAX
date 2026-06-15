"""内部客服 CRM 视图聚合（本地 pipeline 字段 · 远端同步留待 MODstore）。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.user_cs_pipeline import _pipeline_roots, load_pipeline


class CrmSyncError(Exception):
    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.details = details


def get_crm_bundle_for_market_user(market_user_id: int) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline

    doc = load_pipeline(int(market_user_id))
    opp_id = int(doc.get("crm_opportunity_id") or 0)
    quote_id = int(doc.get("crm_quote_id") or 0)
    invoice_id = int(doc.get("crm_invoice_id") or 0)
    quote_draft = doc.get("quote_draft") if isinstance(doc.get("quote_draft"), dict) else None
    delivery = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else None

    opportunity = None
    if opp_id > 0 or doc.get("landing_contact_id") or doc.get("erp_customer_name"):
        opportunity = {
            "id": opp_id or None,
            "landing_contact_id": int(doc.get("landing_contact_id") or 0) or None,
            "company": str(doc.get("erp_customer_name") or ""),
        }

    quote = None
    if quote_id > 0 or quote_draft:
        quote = {
            "id": quote_id or None,
            "status": str((quote_draft or {}).get("status") or doc.get("stage") or ""),
            "summary": str((quote_draft or {}).get("summary") or ""),
        }

    invoice = None
    if invoice_id > 0:
        invoice = {"id": invoice_id, "invoice_no": str(doc.get("invoice_no") or "")}

    return {
        "opportunity": opportunity,
        "quote": quote,
        "invoice": invoice,
        "delivery": delivery,
        "synced_at": str(doc.get("crm_db_synced_at") or doc.get("crm_funnel_synced_at") or ""),
    }


def sync_crm_from_pipeline_doc(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["crm_funnel_synced_at"] = doc.get("crm_funnel_synced_at") or doc.get("updated_at") or ""
    return doc


async def push_external_crm_for_market_user(
    market_user_id: int, *, username: str = ""
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    doc = load_pipeline(int(market_user_id), username=username)
    doc["external_crm_last_at"] = doc.get("updated_at")
    doc["external_crm_last_error"] = ""
    save_pipeline(doc)
    return {"pipeline": doc, "pushed": True}


async def pull_external_crm_for_market_user(
    market_user_id: int, *, username: str = ""
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import save_pipeline

    doc = load_pipeline(int(market_user_id), username=username)
    doc["external_crm_last_pull_at"] = doc.get("updated_at")
    doc["external_crm_last_pull_error"] = ""
    save_pipeline(doc)
    return {"pipeline": doc, "pulled": True}


def _crm_db_path() -> Path:
    root = _pipeline_roots()[0].parent / "user_cs_crm"
    root.mkdir(parents=True, exist_ok=True)
    return root / "crm.db"


@contextmanager
def _connect():
    ensure_crm_schema()
    conn = sqlite3.connect(str(_crm_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_crm_schema() -> None:
    with sqlite3.connect(str(_crm_db_path())) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cs_crm_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_user_id INTEGER NOT NULL,
                company TEXT,
                status TEXT DEFAULT 'open',
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cs_crm_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_user_id INTEGER NOT NULL,
                opportunity_id INTEGER,
                invoice_no TEXT NOT NULL,
                amount_cents INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'issued',
                payment_reference TEXT,
                payload_json TEXT,
                issued_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_opportunity_by_market_user(market_user_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cs_crm_opportunities WHERE market_user_id = ? ORDER BY id DESC LIMIT 1",
            (int(market_user_id),),
        ).fetchone()
    return dict(row) if row else None


def _ensure_opportunity(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    existing = get_opportunity_by_market_user(market_user_id)
    if existing:
        return existing
    doc = load_pipeline(int(market_user_id), username=username)
    now = _now_iso()
    company = str(doc.get("erp_customer_name") or doc.get("username") or "")
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO cs_crm_opportunities
            (market_user_id, company, status, payload_json, created_at, updated_at)
            VALUES (?, ?, 'open', ?, ?, ?)
            """,
            (int(market_user_id), company, json.dumps({"username": username}), now, now),
        )
        oid = int(cur.lastrowid)
    return {"id": oid, "market_user_id": int(market_user_id), "company": company, "status": "open"}


def create_crm_invoice_for_pipeline(
    market_user_id: int,
    *,
    opportunity_id: int | None = None,
    amount_cents: int = 0,
    username: str = "",
) -> dict[str, Any]:
    _ = username
    opp = _ensure_opportunity(int(market_user_id))
    oid = int(opportunity_id or opp.get("id") or 0)
    now = _now_iso()
    invoice_no = f"INV-{int(market_user_id)}-{uuid.uuid4().hex[:8].upper()}"
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO cs_crm_invoices
            (market_user_id, opportunity_id, invoice_no, amount_cents, status, issued_at, created_at)
            VALUES (?, ?, ?, ?, 'issued', ?, ?)
            """,
            (int(market_user_id), oid, invoice_no, int(amount_cents), now, now),
        )
        iid = int(cur.lastrowid)
    return {
        "id": iid,
        "market_user_id": int(market_user_id),
        "opportunity_id": oid,
        "invoice_no": invoice_no,
        "amount_cents": int(amount_cents),
        "status": "issued",
        "issued_at": now,
        "label": invoice_no,
    }


def list_crm_invoices(
    *,
    market_user_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    ensure_crm_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if market_user_id:
        clauses.append("market_user_id = ?")
        params.append(int(market_user_id))
    if status:
        clauses.append("status = ?")
        params.append(str(status).strip())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM cs_crm_invoices " + where,
            params,
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM cs_crm_invoices "
            + where
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, int(limit), int(offset)],
        ).fetchall()
    items = [dict(r) for r in rows]
    return {"items": items, "total": int(total), "limit": int(limit), "offset": int(offset)}


def get_crm_invoice_by_id(invoice_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cs_crm_invoices WHERE id = ?",
            (int(invoice_id),),
        ).fetchone()
    return dict(row) if row else None


__all__ = [
    "CrmSyncError",
    "_connect",
    "create_crm_invoice_for_pipeline",
    "ensure_crm_schema",
    "get_crm_bundle_for_market_user",
    "get_crm_invoice_by_id",
    "get_opportunity_by_market_user",
    "list_crm_invoices",
    "pull_external_crm_for_market_user",
    "push_external_crm_for_market_user",
    "sync_crm_from_pipeline_doc",
]
