"""发布门禁：ETL 只认 B31 客户原件闭环，不认单项测试数量。"""

from __future__ import annotations

import pytest

from app.application.elt.customer_excel_gate import CHECK_IDS, release_status

pytestmark = pytest.mark.release_gate


def test_elt_release_gate_stays_blocked_without_customer_original(monkeypatch):
    monkeypatch.delenv("XCAGI_ELT_CUSTOMER_EXCEL", raising=False)
    monkeypatch.delenv("XCAGI_ELT_MANUAL_BASELINE", raising=False)
    report = release_status()
    assert report["id"] == "B31"
    assert report["status"] == "BLOCKED"
    assert report["release_pass"] is False
    assert len(report["checks"]) == len(CHECK_IDS)
    assert report["chain"][0] == "客户原件" and report["chain"][-1] == "人工对账"
