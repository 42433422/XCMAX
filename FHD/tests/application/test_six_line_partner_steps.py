"""六线伙伴步 B1/B2/B4 SSOT。"""

from __future__ import annotations

import json
from pathlib import Path


def test_partner_steps_present_in_ssot() -> None:
    path = Path(__file__).resolve().parents[2] / "config" / "six_line_event_routes.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    catalog = doc.get("step_catalog") or {}
    for step_id, title in {
        "B1": "投资方/生态伙伴接入",
        "B2": "联合 Catalog",
        "B4": "投资方只读 Portal",
    }.items():
        assert step_id in catalog
        assert catalog[step_id].get("title") == title
    ops = doc.get("operations_line") or []
    op_ids = {str(x.get("step_id")) for x in ops if isinstance(x, dict)}
    assert {"B1", "B2", "B3", "B4", "B5"}.issubset(op_ids)
