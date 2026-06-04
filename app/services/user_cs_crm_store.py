"""销售 CRM 持久化：线索/商机/报价，与 Pipeline JSON、landing_contact、ERP 客户打通。"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2


class CrmSyncError(RuntimeError):
    """CRM 同步失败且当前阶段要求商机已入库。"""

    def __init__(self, message: str, *, market_user_id: int = 0, details: str = ""):
        super().__init__(message)
        self.market_user_id = market_user_id
        self.details = details


def _crm_db_path() -> Path:
    from app.utils.path_utils import get_base_dir, get_data_dir

    for root in (
        Path(get_data_dir()) / "customer_service",
        Path(get_base_dir()) / "data" / "customer_service",
    ):
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root / "crm.sqlite3"
        except OSError:
            continue
    fallback = Path(get_data_dir()) / "customer_service"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / "crm.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_crm_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_crm_schema() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cs_crm_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cs_crm_opportunities (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              market_user_id INTEGER NOT NULL UNIQUE,
              landing_contact_id INTEGER,
              erp_customer_id INTEGER,
              stage TEXT NOT NULL DEFAULT 'idle',
              title TEXT NOT NULL DEFAULT '',
              company TEXT NOT NULL DEFAULT '',
              contact_name TEXT NOT NULL DEFAULT '',
              contact_email TEXT NOT NULL DEFAULT '',
              contact_phone TEXT NOT NULL DEFAULT '',
              intake_message TEXT NOT NULL DEFAULT '',
              audit_code TEXT NOT NULL DEFAULT '',
              owner_username TEXT NOT NULL DEFAULT '',
              meta_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_cs_crm_opp_landing
              ON cs_crm_opportunities(landing_contact_id);
            CREATE INDEX IF NOT EXISTS ix_cs_crm_opp_erp
              ON cs_crm_opportunities(erp_customer_id);
            CREATE INDEX IF NOT EXISTS ix_cs_crm_opp_stage
              ON cs_crm_opportunities(stage);
            CREATE TABLE IF NOT EXISTS cs_crm_quotes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              opportunity_id INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'draft',
              amount_cents INTEGER,
              currency TEXT NOT NULL DEFAULT 'CNY',
              summary TEXT NOT NULL DEFAULT '',
              line_items_json TEXT NOT NULL DEFAULT '[]',
              notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(opportunity_id) REFERENCES cs_crm_opportunities(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_cs_crm_quote_opp
              ON cs_crm_quotes(opportunity_id);
            CREATE TABLE IF NOT EXISTS cs_crm_deliveries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              opportunity_id INTEGER NOT NULL UNIQUE,
              expected_delivery_at TEXT NOT NULL DEFAULT '',
              progress_percent INTEGER NOT NULL DEFAULT 0,
              milestones_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL DEFAULT 'planning',
              started_at TEXT,
              completed_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(opportunity_id) REFERENCES cs_crm_opportunities(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS cs_crm_invoices (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              opportunity_id INTEGER NOT NULL,
              quote_id INTEGER,
              invoice_no TEXT NOT NULL UNIQUE,
              amount_cents INTEGER,
              currency TEXT NOT NULL DEFAULT 'CNY',
              status TEXT NOT NULL DEFAULT 'issued',
              payment_reference TEXT NOT NULL DEFAULT '',
              payment_detected_at TEXT,
              issued_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(opportunity_id) REFERENCES cs_crm_opportunities(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_cs_crm_invoice_opp
              ON cs_crm_invoices(opportunity_id);
            CREATE TABLE IF NOT EXISTS cs_pipeline_snapshots (
              market_user_id INTEGER NOT NULL PRIMARY KEY,
              doc_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO cs_crm_meta(key, value) VALUES('schema_version', ?)",
            (str(_SCHEMA_VERSION),),
        )
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_code_from_landing(landing_contact_id: int | None) -> str:
    if not landing_contact_id:
        return ""
    return f"XC-{int(landing_contact_id):06d}"


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def get_opportunity_by_market_user(market_user_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cs_crm_opportunities WHERE market_user_id = ?",
            (int(market_user_id),),
        ).fetchone()
    return _row_to_dict(row)


def list_quotes_for_opportunity(opportunity_id: int) -> list[dict[str, Any]]:
    ensure_crm_schema()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cs_crm_quotes WHERE opportunity_id = ? ORDER BY id DESC",
            (int(opportunity_id),),
        ).fetchall()
    return [_row_to_dict(r) for r in rows if r]


def _build_quote_payload(doc: dict[str, Any], *, stage: str) -> dict[str, Any]:
    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = str(form.get("company") or doc.get("erp_customer_name") or "").strip()
    name = str(form.get("name") or doc.get("username") or "").strip()
    message = str(form.get("message") or "")[:8000]
    existing = doc.get("quote_draft") if isinstance(doc.get("quote_draft"), dict) else {}
    summary = str(existing.get("summary") or "").strip()
    if not summary:
        summary = f"定制软件服务报价 — {company or name or '客户'}"
    status = "sent" if stage in ("quoted", "negotiating", "contract_pending", "signed") else "draft"
    if stage == "negotiating":
        status = "negotiating"
    if stage in ("delivering", "delivered"):
        status = "won"
    amount = existing.get("amount_cents")
    try:
        amount_cents = int(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_cents = None
    line_items = existing.get("line_items")
    if not isinstance(line_items, list):
        line_items = [
            {
                "desc": "需求范围",
                "detail": message[:500] if message else "见官网需求表单",
            }
        ]
    return {
        "status": status,
        "amount_cents": amount_cents,
        "currency": str(existing.get("currency") or "CNY"),
        "summary": summary[:512],
        "line_items_json": json.dumps(line_items, ensure_ascii=False),
        "notes": str(existing.get("note") or "")[:2000],
    }


def upsert_quote_for_opportunity(
    opportunity_id: int,
    doc: dict[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    ensure_crm_schema()
    payload = _build_quote_payload(doc, stage=stage)
    now = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM cs_crm_quotes WHERE opportunity_id = ? ORDER BY id DESC LIMIT 1",
            (int(opportunity_id),),
        ).fetchone()
        if row:
            qid = int(row["id"])
            conn.execute(
                """
                UPDATE cs_crm_quotes SET
                  status = ?, amount_cents = ?, currency = ?, summary = ?,
                  line_items_json = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["status"],
                    payload["amount_cents"],
                    payload["currency"],
                    payload["summary"],
                    payload["line_items_json"],
                    payload["notes"],
                    now,
                    qid,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO cs_crm_quotes (
                  opportunity_id, status, amount_cents, currency, summary,
                  line_items_json, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(opportunity_id),
                    payload["status"],
                    payload["amount_cents"],
                    payload["currency"],
                    payload["summary"],
                    payload["line_items_json"],
                    payload["notes"],
                    now,
                    now,
                ),
            )
            qid = int(cur.lastrowid)
        conn.commit()
        out = conn.execute("SELECT * FROM cs_crm_quotes WHERE id = ?", (qid,)).fetchone()
    return _row_to_dict(out) or {}


def _merge_anonymous_landing_opportunity(
    conn: sqlite3.Connection,
    *,
    market_user_id: int,
    landing_contact_id: int,
) -> int | None:
    """将匿名线索（market_user_id = -landing_id）合并到企业用户商机，返回合并后的 opp id。"""
    lid = int(landing_contact_id)
    uid = int(market_user_id)
    if lid <= 0 or uid <= 0:
        return None
    synthetic_uid = -lid
    anon = conn.execute(
        """
        SELECT id, market_user_id FROM cs_crm_opportunities
        WHERE landing_contact_id = ? AND market_user_id < 0
        ORDER BY id DESC LIMIT 1
        """,
        (lid,),
    ).fetchone()
    if not anon:
        anon = conn.execute(
            "SELECT id, market_user_id FROM cs_crm_opportunities WHERE market_user_id = ?",
            (synthetic_uid,),
        ).fetchone()
    if not anon:
        return None
    anon_id = int(anon["id"])
    user_row = conn.execute(
        "SELECT id FROM cs_crm_opportunities WHERE market_user_id = ?",
        (uid,),
    ).fetchone()
    if user_row:
        user_opp_id = int(user_row["id"])
        if user_opp_id != anon_id:
            conn.execute(
                """
                UPDATE cs_crm_quotes SET opportunity_id = ?
                WHERE opportunity_id = ?
                """,
                (user_opp_id, anon_id),
            )
            conn.execute(
                """
                UPDATE cs_crm_deliveries SET opportunity_id = ?
                WHERE opportunity_id = ? AND NOT EXISTS (
                  SELECT 1 FROM cs_crm_deliveries WHERE opportunity_id = ?
                )
                """,
                (user_opp_id, anon_id, user_opp_id),
            )
            conn.execute("DELETE FROM cs_crm_deliveries WHERE opportunity_id = ?", (anon_id,))
            conn.execute("DELETE FROM cs_crm_opportunities WHERE id = ?", (anon_id,))
        return user_opp_id
    conn.execute(
        "UPDATE cs_crm_opportunities SET market_user_id = ? WHERE id = ?",
        (uid, anon_id),
    )
    return anon_id


def upsert_opportunity_from_pipeline(doc: dict[str, Any]) -> dict[str, Any]:
    """从 Pipeline 文档 upsert 商机；quoted/negotiating 时同步报价单。"""
    ensure_crm_schema()
    uid = int(doc.get("market_user_id") or 0)
    if uid <= 0:
        raise ValueError("market_user_id required")

    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    stage = str(doc.get("stage") or "idle")
    landing_id = doc.get("landing_contact_id")
    landing_id_i = int(landing_id) if landing_id is not None else None
    erp_id = doc.get("erp_customer_id")
    erp_id_i = int(erp_id) if erp_id is not None else None
    company = str(form.get("company") or doc.get("erp_customer_name") or "").strip()
    contact_name = str(form.get("name") or doc.get("username") or "").strip()
    title = company or contact_name or f"企业客户#{uid}"
    audit = _audit_code_from_landing(landing_id_i)
    meta = {
        "pipeline_updated_at": doc.get("updated_at"),
        "crm_funnel_synced_at": doc.get("crm_funnel_synced_at"),
        "intake_submitted_at": doc.get("intake_submitted_at"),
    }
    now = _now_iso()

    with _connect() as conn:
        if landing_id_i and landing_id_i > 0:
            _merge_anonymous_landing_opportunity(
                conn, market_user_id=uid, landing_contact_id=landing_id_i
            )
        existing = conn.execute(
            "SELECT id FROM cs_crm_opportunities WHERE market_user_id = ?",
            (uid,),
        ).fetchone()
        if existing:
            opp_id = int(existing["id"])
            conn.execute(
                """
                UPDATE cs_crm_opportunities SET
                  landing_contact_id = COALESCE(?, landing_contact_id),
                  erp_customer_id = COALESCE(?, erp_customer_id),
                  stage = ?, title = ?, company = ?, contact_name = ?,
                  contact_email = ?, contact_phone = ?, intake_message = ?,
                  audit_code = COALESCE(NULLIF(?, ''), audit_code),
                  owner_username = COALESCE(NULLIF(?, ''), owner_username),
                  meta_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    landing_id_i,
                    erp_id_i,
                    stage,
                    title[:256],
                    company[:256],
                    contact_name[:128],
                    str(form.get("email") or "")[:256],
                    str(form.get("phone") or "")[:64],
                    str(form.get("message") or "")[:8000],
                    audit,
                    str(doc.get("username") or "")[:128],
                    json.dumps(meta, ensure_ascii=False),
                    now,
                    opp_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO cs_crm_opportunities (
                  market_user_id, landing_contact_id, erp_customer_id, stage,
                  title, company, contact_name, contact_email, contact_phone,
                  intake_message, audit_code, owner_username, meta_json,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    landing_id_i,
                    erp_id_i,
                    stage,
                    title[:256],
                    company[:256],
                    contact_name[:128],
                    str(form.get("email") or "")[:256],
                    str(form.get("phone") or "")[:64],
                    str(form.get("message") or "")[:8000],
                    audit,
                    str(doc.get("username") or "")[:128],
                    json.dumps(meta, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            opp_id = int(cur.lastrowid)
        conn.commit()
        opp_row = conn.execute(
            "SELECT * FROM cs_crm_opportunities WHERE id = ?", (opp_id,)
        ).fetchone()

    opp = _row_to_dict(opp_row) or {}
    quote: dict[str, Any] | None = None
    if stage in (
        "intake_done",
        "quoted",
        "negotiating",
        "contract_pending",
        "signed",
        "delivering",
        "delivered",
    ):
        quote = upsert_quote_for_opportunity(opp_id, doc, stage=stage)
    delivery = upsert_delivery_for_opportunity(opp_id, doc)
    return {"opportunity": opp, "quote": quote, "delivery": delivery}


def sync_crm_from_pipeline_doc(
    doc: dict[str, Any],
    *,
    raise_on_failure: bool = False,
) -> dict[str, Any]:
    """写入 CRM DB，并把 crm_opportunity_id / crm_quote_id 回写到 pipeline 文档。"""
    uid = int(doc.get("market_user_id") or 0)
    try:
        bundle = upsert_opportunity_from_pipeline(doc)
    except Exception as exc:
        logger.exception("sync_crm_from_pipeline_doc failed uid=%s", uid)
        doc = dict(doc)
        doc["crm_sync_last_error"] = str(exc)[:500]
        if raise_on_failure:
            raise CrmSyncError(
                f"CRM 同步失败: {exc}",
                market_user_id=uid,
                details=str(exc)[:500],
            ) from exc
        return doc

    opp = bundle.get("opportunity") or {}
    quote = bundle.get("quote")
    doc = dict(doc)
    if opp.get("id"):
        doc["crm_opportunity_id"] = int(opp["id"])
        doc.pop("crm_sync_last_error", None)
    elif raise_on_failure:
        raise CrmSyncError(
            "商机未写入 CRM",
            market_user_id=uid,
            details="upsert_opportunity_from_pipeline returned no id",
        )
    if quote and quote.get("id"):
        doc["crm_quote_id"] = int(quote["id"])
        doc["quote_draft"] = {
            "status": quote.get("status"),
            "summary": quote.get("summary"),
            "amount_cents": quote.get("amount_cents"),
            "currency": quote.get("currency"),
            "crm_quote_id": quote.get("id"),
            "line_items": json.loads(quote.get("line_items_json") or "[]"),
        }
    doc["crm_db_synced_at"] = _now_iso()
    try:
        from app.services.external_crm_adapter import push_opportunity_to_external_crm

        if opp:
            doc = _apply_external_crm_push(doc, push_opportunity_to_external_crm(opp, doc))
    except Exception as exc:
        doc["external_crm_last_error"] = str(exc)[:500]
        logger.debug("external crm push skipped", exc_info=True)
    try:
        from app.services.user_cs_delivery import ensure_delivery_on_doc

        doc = ensure_delivery_on_doc(doc)
        doc = sync_delivery_and_invoice_from_pipeline(doc)
    except Exception:
        logger.exception("delivery sync in crm_from_pipeline failed")
    return doc


def get_delivery_for_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cs_crm_deliveries WHERE opportunity_id = ?",
            (int(opportunity_id),),
        ).fetchone()
    return _row_to_dict(row)


def get_latest_invoice_for_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cs_crm_invoices WHERE opportunity_id = ? ORDER BY id DESC LIMIT 1",
            (int(opportunity_id),),
        ).fetchone()
    return _row_to_dict(row)


def _enrich_crm_invoice_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["market_user_id"] = int(out.get("market_user_id") or 0)
    out["opportunity_id"] = int(out.get("opportunity_id") or 0)
    return out


def list_crm_invoices(
    *,
    market_user_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """分页列出 CRM 合同轨发票（含商机与客户字段）。"""
    ensure_crm_schema()
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))
    sql_base = """
        FROM cs_crm_invoices i
        JOIN cs_crm_opportunities o ON o.id = i.opportunity_id
        WHERE 1=1
    """
    params: list[Any] = []
    if market_user_id is not None and int(market_user_id) > 0:
        sql_base += " AND o.market_user_id = ?"
        params.append(int(market_user_id))
    st = (status or "").strip()
    if st:
        sql_base += " AND i.status = ?"
        params.append(st[:32])
    with _connect() as conn:
        total_row = conn.execute(f"SELECT COUNT(*) AS c {sql_base}", params).fetchone()
        total = int(total_row["c"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT i.*, o.market_user_id, o.title AS opp_title, o.company AS opp_company,
                   o.stage AS pipeline_stage, o.contact_name AS opp_contact_name
            {sql_base}
            ORDER BY i.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, lim, off],
        ).fetchall()
    items = [_enrich_crm_invoice_row(dict(r)) for r in rows]
    try:
        from app.services.finance_unified_archive import map_voucher_ids_for_crm_invoices

        voucher_map = map_voucher_ids_for_crm_invoices([int(x.get("id") or 0) for x in items])
        for item in items:
            iid = int(item.get("id") or 0)
            vid = voucher_map.get(iid)
            item["financial_transaction_id"] = vid
            item["archived_in_fin_txn"] = bool(vid)
    except Exception:
        logger.debug("voucher map for crm invoices skipped", exc_info=True)
    return {"items": items, "total": total, "limit": lim, "offset": off}


def get_crm_invoice_by_id(invoice_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    iid = int(invoice_id)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT i.*, o.market_user_id, o.title AS opp_title, o.company AS opp_company,
                   o.stage AS pipeline_stage, o.contact_name AS opp_contact_name
            FROM cs_crm_invoices i
            JOIN cs_crm_opportunities o ON o.id = i.opportunity_id
            WHERE i.id = ?
            """,
            (iid,),
        ).fetchone()
    if not row:
        return None
    inv = _enrich_crm_invoice_row(dict(row))
    try:
        from app.services.finance_unified_archive import (
            list_vouchers_for_crm_invoice,
            map_voucher_ids_for_crm_invoices,
        )

        inv["vouchers"] = list_vouchers_for_crm_invoice(iid)
        vid = map_voucher_ids_for_crm_invoices([iid]).get(iid)
        inv["financial_transaction_id"] = vid
        inv["archived_in_fin_txn"] = bool(vid)
    except Exception:
        inv["vouchers"] = []
        inv["archived_in_fin_txn"] = False
    return inv


def upsert_delivery_for_opportunity(
    opportunity_id: int,
    doc: dict[str, Any],
) -> dict[str, Any] | None:
    delivery = doc.get("delivery")
    if not isinstance(delivery, dict):
        return None
    ensure_crm_schema()
    milestones = delivery.get("milestones") or []
    if not isinstance(milestones, list):
        milestones = []
    try:
        pct = int(delivery.get("progress_percent") or 0)
    except (TypeError, ValueError):
        pct = 0
    stage = str(doc.get("stage") or "idle")
    if stage == "delivered" or pct >= 100:
        status = "delivered"
    elif stage == "delivering" or delivery.get("started_at"):
        status = "in_progress"
    else:
        status = "planning"
    now = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM cs_crm_deliveries WHERE opportunity_id = ?",
            (int(opportunity_id),),
        ).fetchone()
        if row:
            did = int(row["id"])
            conn.execute(
                """
                UPDATE cs_crm_deliveries SET
                  expected_delivery_at = ?, progress_percent = ?, milestones_json = ?,
                  status = ?, started_at = COALESCE(?, started_at),
                  completed_at = COALESCE(?, completed_at), updated_at = ?
                WHERE id = ?
                """,
                (
                    str(delivery.get("expected_delivery_at") or "")[:32],
                    pct,
                    json.dumps(milestones, ensure_ascii=False),
                    status,
                    delivery.get("started_at"),
                    delivery.get("completed_at"),
                    now,
                    did,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO cs_crm_deliveries (
                  opportunity_id, expected_delivery_at, progress_percent, milestones_json,
                  status, started_at, completed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(opportunity_id),
                    str(delivery.get("expected_delivery_at") or "")[:32],
                    pct,
                    json.dumps(milestones, ensure_ascii=False),
                    status,
                    delivery.get("started_at"),
                    delivery.get("completed_at"),
                    now,
                    now,
                ),
            )
            did = int(cur.lastrowid)
        conn.commit()
        out = conn.execute("SELECT * FROM cs_crm_deliveries WHERE id = ?", (did,)).fetchone()
    return _row_to_dict(out)


def create_invoice_for_opportunity(
    opportunity_id: int,
    *,
    amount_cents: int | None,
    payment_reference: str = "",
    quote_id: int | None = None,
) -> dict[str, Any]:
    ensure_crm_schema()
    now = _now_iso()
    invoice_no = f"XC-INV-{int(opportunity_id):06d}-{int(datetime.now(timezone.utc).timestamp()) % 1000000:06d}"
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM cs_crm_invoices WHERE opportunity_id = ? AND status = 'issued' ORDER BY id DESC LIMIT 1",
            (int(opportunity_id),),
        ).fetchone()
        if existing:
            out = conn.execute(
                "SELECT * FROM cs_crm_invoices WHERE id = ?",
                (int(existing["id"]),),
            ).fetchone()
            existing_inv = _row_to_dict(out) or {}
            _archive_invoice_if_present(existing_inv, opportunity_id)
            return existing_inv
        cur = conn.execute(
            """
            INSERT INTO cs_crm_invoices (
              opportunity_id, quote_id, invoice_no, amount_cents, currency, status,
              payment_reference, payment_detected_at, issued_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'CNY', 'issued', ?, ?, ?, ?, ?)
            """,
            (
                int(opportunity_id),
                int(quote_id) if quote_id else None,
                invoice_no,
                amount_cents,
                (payment_reference or "")[:200],
                now,
                now,
                now,
                now,
            ),
        )
        iid = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM cs_crm_invoices WHERE id = ?", (iid,)).fetchone()
    inv = _row_to_dict(row) or {}
    _archive_invoice_if_present(inv, opportunity_id)
    return inv


def _archive_invoice_if_present(inv: dict[str, Any], opportunity_id: int) -> None:
    if not inv.get("id"):
        return
    try:
        with _connect() as conn:
            opp = conn.execute(
                "SELECT market_user_id FROM cs_crm_opportunities WHERE id = ?",
                (int(opportunity_id),),
            ).fetchone()
        uid = int(opp["market_user_id"]) if opp and opp["market_user_id"] is not None else 0
        from app.services.finance_unified_archive import archive_from_crm_invoice

        archive_from_crm_invoice({**inv, "market_user_id": uid})
    except Exception:
        logger.exception("finance archive for crm invoice opp=%s", opportunity_id)


def sync_delivery_and_invoice_from_pipeline(doc: dict[str, Any]) -> dict[str, Any]:
    """同步交付与账单字段到 pipeline 文档。"""
    from app.services.user_cs_delivery import ensure_delivery_on_doc

    doc = ensure_delivery_on_doc(doc)
    opp_id = int(doc.get("crm_opportunity_id") or 0)
    if opp_id <= 0:
        uid = int(doc.get("market_user_id") or 0)
        if uid > 0:
            opp = get_opportunity_by_market_user(uid)
            if opp:
                opp_id = int(opp["id"])
                doc["crm_opportunity_id"] = opp_id
    if opp_id <= 0:
        return doc
    del_row = upsert_delivery_for_opportunity(opp_id, doc)
    if del_row:
        doc["crm_delivery_id"] = del_row.get("id")
    inv = get_latest_invoice_for_opportunity(opp_id)
    if inv:
        doc["crm_invoice_id"] = inv.get("id")
        doc["invoice"] = {
            "id": inv.get("id"),
            "invoice_no": inv.get("invoice_no"),
            "status": inv.get("status"),
            "amount_cents": inv.get("amount_cents"),
            "issued_at": inv.get("issued_at"),
        }
    return doc


def get_crm_bundle_for_market_user(market_user_id: int) -> dict[str, Any]:
    """供 API 返回：商机 + 报价 + 交付 + 账单。"""
    opp = get_opportunity_by_market_user(int(market_user_id))
    if not opp:
        return {"opportunity": None, "quotes": [], "delivery": None, "invoice": None}
    oid = int(opp["id"])
    quotes = list_quotes_for_opportunity(oid)
    return {
        "opportunity": opp,
        "quotes": quotes,
        "quote": quotes[0] if quotes else None,
        "delivery": get_delivery_for_opportunity(oid),
        "invoice": get_latest_invoice_for_opportunity(oid),
    }


def _apply_external_crm_push(doc: dict[str, Any], ext: dict[str, Any]) -> dict[str, Any]:
    doc["external_crm_last_at"] = _now_iso()
    doc["external_crm_last_result"] = ext
    if ext.get("skipped") or ext.get("ok"):
        doc.pop("external_crm_last_error", None)
    else:
        doc["external_crm_last_error"] = str(
            ext.get("error") or ext.get("reason") or "external_crm_failed"
        )[:500]
    deal_id = str(ext.get("deal_id") or "").strip()
    if deal_id:
        doc["external_crm_deal_id"] = deal_id
    return doc


def _apply_external_crm_pull_meta(doc: dict[str, Any], pull: dict[str, Any]) -> dict[str, Any]:
    doc["external_crm_last_pull_at"] = _now_iso()
    doc["external_crm_last_pull_result"] = pull
    if pull.get("ok"):
        doc.pop("external_crm_last_pull_error", None)
    elif not pull.get("skipped"):
        doc["external_crm_last_pull_error"] = str(
            pull.get("error") or pull.get("reason") or "external_crm_pull_failed"
        )[:500]
    return doc


def _apply_pipeline_stage_from_external(
    doc: dict[str, Any],
    new_stage: str,
    *,
    username: str = "",
    note: str = "",
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline, set_pipeline_stage

    uid = int(doc.get("market_user_id") or 0)
    old_stage = str(doc.get("stage") or "idle")
    if new_stage == old_stage:
        return doc
    try:
        return set_pipeline_stage(
            uid,
            new_stage,
            username=username,
            source="external_crm_pull",
            note=note,
        )
    except Exception as exc:
        logger.warning(
            "external crm pull stage via set_pipeline_stage failed uid=%s %s→%s: %s",
            uid,
            old_stage,
            new_stage,
            exc,
        )
        doc = load_pipeline(uid, username=username)
        now = _now_iso()
        doc["stage"] = new_stage
        timeline = doc.get("stage_timeline")
        if not isinstance(timeline, list):
            timeline = []
        timeline.append(
            {
                "stage": new_stage,
                "at": now,
                "source": "external_crm_pull",
                "from": old_stage,
                "note": note or str(exc)[:200],
            }
        )
        doc["stage_timeline"] = timeline
        return save_pipeline(doc, strict_crm=False)


def push_external_crm_for_market_user(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    """同步自建 CRM 后出站推送外部 CRM（HubSpot 等），写回 pipeline external_crm_* 字段。"""
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    doc = sync_crm_from_pipeline_doc(doc)
    opp = get_opportunity_by_market_user(uid)
    ext: dict[str, Any] = {"ok": False, "skipped": True, "reason": "no_opportunity"}
    if opp:
        from app.services.external_crm_adapter import push_opportunity_to_external_crm

        ext = push_opportunity_to_external_crm(opp, doc)
        doc = _apply_external_crm_push(doc, ext)
    else:
        doc["external_crm_last_error"] = "商机未入库，无法推送"
    doc = save_pipeline(doc)
    return {"pipeline": doc, "external": ext, "crm": get_crm_bundle_for_market_user(uid)}


def pull_external_crm_for_market_user(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    """从外部 CRM（HubSpot / Salesforce）拉取 Deal 阶段并回写 Pipeline（手动/按需，非 webhook）。"""
    from app.services.external_crm_adapter import (
        pull_stage_from_external_deal,
        resolve_external_deal_id,
    )
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    deal_id = resolve_external_deal_id(doc)
    if not deal_id:
        pull = {"ok": False, "error": "尚未推送或缺少 external_crm_deal_id，请先推送到外部 CRM"}
        doc = _apply_external_crm_pull_meta(doc, pull)
        doc = save_pipeline(doc, strict_crm=False)
        return {"pipeline": doc, "pull": pull, "crm": get_crm_bundle_for_market_user(uid)}

    pull = pull_stage_from_external_deal(deal_id, doc)
    doc = _apply_external_crm_pull_meta(doc, pull)
    stage_changed = False
    if pull.get("ok") and pull.get("pipeline_stage"):
        new_stage = str(pull["pipeline_stage"])
        ext_stage = pull.get("hubspot_stage") or pull.get("salesforce_stage") or ""
        provider = str(pull.get("provider") or "external_crm")
        note = f"{provider} {ext_stage}".strip()
        before = str(doc.get("stage") or "idle")
        doc = _apply_pipeline_stage_from_external(doc, new_stage, username=username, note=note)
        stage_changed = before != new_stage
        pull["stage_changed"] = stage_changed
        doc["external_crm_last_pull_result"] = pull
    doc = save_pipeline(doc, strict_crm=False)
    return {"pipeline": doc, "pull": pull, "crm": get_crm_bundle_for_market_user(uid)}
