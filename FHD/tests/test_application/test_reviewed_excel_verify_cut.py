"""Smoke tests for general verify-after-cut heuristics (no workbook-title hardcodes)."""

from openpyxl import Workbook

from app.application.reviewed_excel_template import inspect_workbook
from app.application.reviewed_excel_verify_cut import inspect_cut, verify_after_cut


def _book_bytes(build):
    book = Workbook()
    build(book)
    from io import BytesIO

    buf = BytesIO()
    book.save(buf)
    return buf.getvalue()


def test_title_blocks_resplit_two_period_documents():
    def build(book):
        ws = book.active
        ws.title = "ledger"
        ws["A1"] = "2025年12月26起客户回款明细"
        ws["A2"] = "日期"
        ws["B2"] = "金额"
        ws["A3"] = "2025-12-27"
        ws["B3"] = 100
        ws["A36"] = "2025年6月起客户回款明细"
        ws["A37"] = "日期"
        ws["B37"] = "金额"
        ws["A38"] = "2025-06-01"
        ws["B38"] = 50

    body = _book_bytes(build)
    review = inspect_workbook(body)
    groups = [
        {
            "document_id": "source-sticky-titles",
            "fragments": [{"sheet": "ledger", "range": "A1:B40"}],
            "evidence": [],
            "reason": "whole sheet",
        }
    ]
    inspection = inspect_cut(review, groups[0])
    assert inspection["sticky"] is True
    assert inspection["status"] == "sticky_titles"
    assert len(inspection["title_blocks"]) >= 2
    out = verify_after_cut(review, groups, resplit=True)
    assert out["stats"]["sticky_caught"] == 1
    assert out["stats"]["resplit_groups"] == 1
    assert len(out["groups"]) == 2
    ranges = {g["fragments"][0]["range"] for g in out["groups"]}
    assert "A1:B35" in ranges
    assert "A36:B40" in ranges


def test_order_ledger_runs_flag_and_resplit():
    def build(book):
        ws = book.active
        ws.title = "ship"
        ws["A1"] = "出货台账"
        # date serial-ish + order ids forming 4 runs
        rows = [
            (2, 46080, 9),
            (3, 46080, 9),
            (4, 46082, "2号"),
            (5, 46082, "2号"),
            (6, 46090, 15),
            (7, 46090, 15),
            (8, 46092, 25),
            (9, 46092, 25),
            (10, 46094, 29),
            (11, 46094, 29),
        ]
        for r, d, o in rows:
            ws.cell(r, 1, value="客户")
            ws.cell(r, 2, value=d)
            ws.cell(r, 3, value=o)
            ws.cell(r, 4, value="item")

    body = _book_bytes(build)
    review = inspect_workbook(body)
    groups = [
        {
            "document_id": "source-sticky-ledger",
            "fragments": [{"sheet": "ship", "range": "A1:D11"}],
            "evidence": [],
            "reason": "whole ledger",
        }
    ]
    inspection = inspect_cut(review, groups[0])
    assert inspection["status"] == "sticky_ledger"
    assert inspection["ledger"]["run_count"] >= 3
    out = verify_after_cut(review, groups, resplit=True)
    assert out["stats"]["resplit_groups"] == 1
    assert len(out["groups"]) >= 3


def test_circular_self_sum_detected():
    def build(book):
        ws = book.active
        ws.title = "tail"
        ws["A1"] = "2026年09月购货明细"
        for r in range(2, 6):
            ws.cell(r, 3, value=r)
        ws["C6"] = "=SUM(C2:C6)"

    body = _book_bytes(build)
    review = inspect_workbook(body)
    group = {
        "document_id": "source-circular",
        "fragments": [{"sheet": "tail", "range": "A1:C6"}],
        "evidence": [],
        "reason": "period",
    }
    inspection = inspect_cut(review, group)
    assert inspection["status"] == "circular_quarantine"
    assert inspection["formula"]["circular_count"] >= 1
    assert inspection["ok"] is True
    out = verify_after_cut(review, [group], resplit=True)
    assert out["stats"]["circular_caught"] == 1
    assert out["groups"][0].get("circular_quarantine") is True
    assert out["groups"][0].get("verify_fail_closed") is False


def test_atomic_single_title_passes():
    def build(book):
        ws = book.active
        ws.title = "one"
        ws["A1"] = "2026年09月27日-10月24购货明细"
        ws["A2"] = 1
        ws["B2"] = 2

    body = _book_bytes(build)
    review = inspect_workbook(body)
    group = {
        "document_id": "source-ok",
        "fragments": [{"sheet": "one", "range": "A1:B2"}],
        "evidence": [],
        "reason": "one block",
    }
    inspection = inspect_cut(review, group)
    assert inspection["ok"] is True
    assert inspection["sticky"] is False


def test_two_order_runs_resplit_atomic():
    def build(book):
        ws = book.active
        ws.title = "ship"
        # Detector needs >=6 data rows and majority date/order hits.
        rows = [
            (2, 46080, 9),
            (3, 46080, 9),
            (4, 46080, 9),
            (5, 46082, "2号"),
            (6, 46082, "2号"),
            (7, 46082, "2号"),
        ]
        for r, d, o in rows:
            ws.cell(r, 1, value="客户")
            ws.cell(r, 2, value=d)
            ws.cell(r, 3, value=o)

    body = _book_bytes(build)
    review = inspect_workbook(body)
    groups = [
        {
            "document_id": "source-two-runs",
            "fragments": [{"sheet": "ship", "range": "A1:C7"}],
            "evidence": [],
            "reason": "glued",
        }
    ]
    inspection = inspect_cut(review, groups[0])
    assert inspection["status"] == "sticky_ledger"
    assert inspection["ledger"]["run_count"] == 2
    out = verify_after_cut(review, groups, resplit=True)
    assert out["stats"]["resplit_groups"] == 1
    assert len(out["groups"]) == 2


def test_delivery_note_agreement_lines_do_not_sticky_resplit():
    """One contiguous 送货单 with agreement/meta lines stays one document after verify."""

    def build(book):
        ws = book.active
        ws.title = "送货"
        ws["A1"] = "成都某公司送货单"
        ws["A2"] = "购货单位（乙方）：甲厂    联系人：李    日期：2026年01月01日   订单编号：26-1"
        ws["A5"] = "品名"
        ws["B5"] = "数量"
        ws["A6"] = "漆"
        ws["B6"] = 2
        ws["A16"] = "销售协议 | 1.甲方所供上列产品均属检验合格产品，送货单一式四联"
        ws["A18"] = "法律效力，必须按期付清货款（月结三十天），由甲方所在地方人民法院受理起诉。"
        ws["A19"] = "3.本送货单一式四联，白色联为存根联，粉红色为客户联"

    body = _book_bytes(build)
    review = inspect_workbook(body)
    # Attach structural index so verify sees agreement lines as block_title_rows.
    from app.application.reviewed_excel_structural_index import ensure_review_structural_index

    ensure_review_structural_index(review, body)
    groups = [
        {
            "document_id": "source-delivery",
            "fragments": [{"sheet": "送货", "range": "A1:B19"}],
            "evidence": [],
            "reason": "one delivery note",
        }
    ]
    inspection = inspect_cut(review, groups[0])
    assert inspection["sticky"] is False
    assert inspection["status"] == "ok"
    out = verify_after_cut(review, groups, resplit=True)
    assert out["stats"]["resplit_groups"] == 0
    assert len(out["groups"]) == 1
