"""真实行为测试（第二波）：app/services/user_cs_crm_store.py 未覆盖分支。

覆盖目标：
- get_crm_bundle_for_market_user 的 invoice 分支
- push/pull_external_crm_for_market_user 异步副作用
- _now_iso / get_opportunity_by_market_user / _ensure_opportunity 新建路径
- create_crm_invoice_for_pipeline 完整插入
- list_crm_invoices 的 status 过滤 + get_crm_invoice_by_id 命中/未命中

所有 DB 写入隔离到 tmp 路径（patch _crm_db_path），pipeline IO 全部 mock。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest

import app.services.user_cs_crm_store as store


@pytest.fixture
def crm_db(tmp_path):
    """把 CRM SQLite 落到 tmp，并确保 schema 就绪。"""
    db_file = tmp_path / "crm.db"
    with patch.object(store, "_crm_db_path", return_value=db_file):
        store.ensure_crm_schema()
        yield db_file


# ──────────────────────────────────────────────────────────────────────────────
# get_crm_bundle_for_market_user —— invoice 分支 (line 50)
# ──────────────────────────────────────────────────────────────────────────────


class TestGetCrmBundleInvoiceBranch:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_invoice_present(self, mock_load):
        mock_load.return_value = {
            "crm_invoice_id": 77,
            "invoice_no": "INV-2026-XYZ",
            "crm_db_synced_at": "2026-06-01T00:00:00+00:00",
        }
        result = store.get_crm_bundle_for_market_user(5)
        assert result["invoice"] == {"id": 77, "invoice_no": "INV-2026-XYZ"}
        # synced_at 优先取 crm_db_synced_at
        assert result["synced_at"] == "2026-06-01T00:00:00+00:00"

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_invoice_no_missing_defaults_empty(self, mock_load):
        mock_load.return_value = {"crm_invoice_id": 12}
        result = store.get_crm_bundle_for_market_user(5)
        assert result["invoice"] == {"id": 12, "invoice_no": ""}

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_synced_at_falls_back_to_funnel(self, mock_load):
        mock_load.return_value = {"crm_funnel_synced_at": "2026-05-05"}
        result = store.get_crm_bundle_for_market_user(5)
        assert result["invoice"] is None
        assert result["synced_at"] == "2026-05-05"


# ──────────────────────────────────────────────────────────────────────────────
# push/pull external CRM —— async 副作用 (lines 70,72-76 / 82,84-88)
# ──────────────────────────────────────────────────────────────────────────────


class TestPushExternalCrm:
    async def test_push_sets_last_at_and_saves(self):
        loaded = {"market_user_id": 9, "updated_at": "2026-06-10T01:02:03+00:00"}
        with (
            patch("app.services.user_cs_pipeline.load_pipeline", return_value=loaded) as ml,
            patch("app.services.user_cs_pipeline.save_pipeline") as ms,
        ):
            result = await store.push_external_crm_for_market_user(9, username="alice")
        ml.assert_called_once_with(9, username="alice")
        ms.assert_called_once()
        saved_doc = ms.call_args.args[0]
        assert saved_doc["external_crm_last_at"] == "2026-06-10T01:02:03+00:00"
        assert saved_doc["external_crm_last_error"] == ""
        assert result["pushed"] is True
        assert result["pipeline"]["external_crm_last_at"] == "2026-06-10T01:02:03+00:00"


class TestPullExternalCrm:
    async def test_pull_sets_last_pull_at_and_saves(self):
        # pull 的函数内只 import save_pipeline；load_pipeline 走模块级符号
        loaded = {"market_user_id": 11, "updated_at": "2026-06-11T05:06:07+00:00"}
        with (
            patch.object(store, "load_pipeline", return_value=loaded) as ml,
            patch("app.services.user_cs_pipeline.save_pipeline") as ms,
        ):
            result = await store.pull_external_crm_for_market_user(11, username="bob")
        ml.assert_called_once_with(11, username="bob")
        ms.assert_called_once()
        saved_doc = ms.call_args.args[0]
        assert saved_doc["external_crm_last_pull_at"] == "2026-06-11T05:06:07+00:00"
        assert saved_doc["external_crm_last_pull_error"] == ""
        assert result["pulled"] is True
        assert result["pipeline"]["external_crm_last_pull_at"] == "2026-06-11T05:06:07+00:00"


# ──────────────────────────────────────────────────────────────────────────────
# _now_iso (line 144)
# ──────────────────────────────────────────────────────────────────────────────


class TestNowIso:
    def test_returns_parseable_utc_iso(self):
        value = store._now_iso()
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None
        # 偏移为 0（UTC）
        assert parsed.utcoffset().total_seconds() == 0


# ──────────────────────────────────────────────────────────────────────────────
# get_opportunity_by_market_user (lines 148-150,154)
# ──────────────────────────────────────────────────────────────────────────────


class TestGetOpportunityByMarketUser:
    def test_none_when_absent(self, crm_db):
        assert store.get_opportunity_by_market_user(999) is None

    def test_returns_latest_row(self, crm_db):
        conn = sqlite3.connect(str(crm_db))
        conn.execute(
            "INSERT INTO cs_crm_opportunities "
            "(market_user_id, company, status, payload_json, created_at, updated_at) "
            "VALUES (?, ?, 'open', '{}', ?, ?)",
            (42, "OldCo", "t0", "t0"),
        )
        conn.execute(
            "INSERT INTO cs_crm_opportunities "
            "(market_user_id, company, status, payload_json, created_at, updated_at) "
            "VALUES (?, ?, 'open', '{}', ?, ?)",
            (42, "NewCo", "t1", "t1"),
        )
        conn.commit()
        conn.close()
        row = store.get_opportunity_by_market_user(42)
        assert row is not None
        # ORDER BY id DESC LIMIT 1 -> 最新插入
        assert row["company"] == "NewCo"
        assert row["market_user_id"] == 42


# ──────────────────────────────────────────────────────────────────────────────
# _ensure_opportunity (lines 158-165,173-174)
# ──────────────────────────────────────────────────────────────────────────────


class TestEnsureOpportunity:
    def test_returns_existing(self, crm_db):
        conn = sqlite3.connect(str(crm_db))
        conn.execute(
            "INSERT INTO cs_crm_opportunities "
            "(market_user_id, company, status, payload_json, created_at, updated_at) "
            "VALUES (?, ?, 'open', '{}', ?, ?)",
            (50, "Existing", "t0", "t0"),
        )
        conn.commit()
        conn.close()
        with patch.object(store, "load_pipeline") as ml:
            result = store._ensure_opportunity(50)
        # 命中已有则不读取 pipeline
        ml.assert_not_called()
        assert result["company"] == "Existing"

    def test_creates_from_pipeline_erp_name(self, crm_db):
        with patch.object(
            store, "load_pipeline", return_value={"erp_customer_name": "AcmeCorp"}
        ) as ml:
            result = store._ensure_opportunity(60, username="carol")
        ml.assert_called_once_with(60, username="carol")
        assert result["company"] == "AcmeCorp"
        assert result["status"] == "open"
        assert result["market_user_id"] == 60
        assert isinstance(result["id"], int) and result["id"] > 0
        # 已真正写入 DB
        persisted = store.get_opportunity_by_market_user(60)
        assert persisted is not None
        assert persisted["company"] == "AcmeCorp"

    def test_creates_falls_back_to_username_field(self, crm_db):
        with patch.object(store, "load_pipeline", return_value={"username": "fallback_user"}):
            result = store._ensure_opportunity(61)
        assert result["company"] == "fallback_user"


# ──────────────────────────────────────────────────────────────────────────────
# create_crm_invoice_for_pipeline (lines 184-190,198-199)
# ──────────────────────────────────────────────────────────────────────────────


class TestCreateCrmInvoiceForPipeline:
    def test_creates_invoice_with_new_opportunity(self, crm_db):
        with patch.object(store, "load_pipeline", return_value={"erp_customer_name": "BillCo"}):
            inv = store.create_crm_invoice_for_pipeline(70, amount_cents=12345)
        assert inv["market_user_id"] == 70
        assert inv["amount_cents"] == 12345
        assert inv["status"] == "issued"
        assert inv["invoice_no"].startswith("INV-70-")
        assert inv["label"] == inv["invoice_no"]
        assert inv["opportunity_id"] > 0
        assert isinstance(inv["id"], int) and inv["id"] > 0
        # 落库可被查询
        fetched = store.get_crm_invoice_by_id(inv["id"])
        assert fetched is not None
        assert fetched["invoice_no"] == inv["invoice_no"]

    def test_explicit_opportunity_id_overrides(self, crm_db):
        with patch.object(store, "load_pipeline", return_value={"erp_customer_name": "X"}):
            inv = store.create_crm_invoice_for_pipeline(71, opportunity_id=4242, amount_cents=0)
        assert inv["opportunity_id"] == 4242
        assert inv["amount_cents"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# list_crm_invoices —— status 过滤 (lines 225-226) + get_crm_invoice_by_id (242-244,248)
# ──────────────────────────────────────────────────────────────────────────────


class TestListCrmInvoicesStatusFilter:
    def _seed(self, crm_db, market_user_id, invoice_no, status):
        conn = sqlite3.connect(str(crm_db))
        conn.execute(
            "INSERT INTO cs_crm_invoices "
            "(market_user_id, opportunity_id, invoice_no, amount_cents, status, "
            "issued_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (market_user_id, 1, invoice_no, 100, status, "t", "t"),
        )
        conn.commit()
        conn.close()

    def test_status_filter_narrows_results(self, crm_db):
        self._seed(crm_db, 80, "INV-A", "issued")
        self._seed(crm_db, 80, "INV-B", "paid")
        self._seed(crm_db, 80, "INV-C", "issued")

        result = store.list_crm_invoices(status="paid")
        assert result["total"] == 1
        assert [i["invoice_no"] for i in result["items"]] == ["INV-B"]

    def test_status_with_whitespace_is_stripped(self, crm_db):
        self._seed(crm_db, 81, "INV-D", "issued")
        result = store.list_crm_invoices(market_user_id=81, status="  issued  ")
        assert result["total"] == 1
        assert result["items"][0]["invoice_no"] == "INV-D"

    def test_combined_user_and_status_filter(self, crm_db):
        self._seed(crm_db, 82, "INV-E", "issued")
        self._seed(crm_db, 83, "INV-F", "issued")
        result = store.list_crm_invoices(market_user_id=82, status="issued")
        assert result["total"] == 1
        assert result["items"][0]["invoice_no"] == "INV-E"
        assert result["limit"] == 50
        assert result["offset"] == 0


class TestGetCrmInvoiceById:
    def test_hit(self, crm_db):
        conn = sqlite3.connect(str(crm_db))
        cur = conn.execute(
            "INSERT INTO cs_crm_invoices "
            "(market_user_id, opportunity_id, invoice_no, amount_cents, status, "
            "issued_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (90, 1, "INV-HIT", 500, "issued", "t", "t"),
        )
        iid = cur.lastrowid
        conn.commit()
        conn.close()
        row = store.get_crm_invoice_by_id(iid)
        assert row is not None
        assert row["invoice_no"] == "INV-HIT"
        assert row["amount_cents"] == 500

    def test_miss_returns_none(self, crm_db):
        assert store.get_crm_invoice_by_id(123456) is None
