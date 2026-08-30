from __future__ import annotations

import importlib.util
from pathlib import Path

CONVERTER = (
    Path(__file__).resolve().parents[1]
    / "modstore_server"
    / "catalog_data"
    / "files"
    / "autonomy-gap-analyst@1.0.2"
    / "backend"
    / "vendor"
    / "autonomy_gap_analyst"
    / "convert.py"
)


def _analyze(payload):
    spec = importlib.util.spec_from_file_location("autonomy_gap_analyst_102", CONVERTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.analyze_scorecard(payload)


def test_detects_incomplete_public_projection_dimensions_without_false_ready_gaps():
    result = _analyze(
        {
            "scorecard": {
                "dimensions": [
                    {
                        "id": "founder",
                        "label": "创始人状态",
                        "progress": 100,
                        "remaining": 0,
                        "status": "ready",
                        "next_gap": "继续积累运行证据",
                    },
                    {
                        "id": "customer",
                        "label": "客户状态",
                        "progress": 25,
                        "remaining": 75,
                        "status": "early",
                        "next_gap": "真实付费",
                    },
                    {
                        "id": "evolution",
                        "label": "进化状态",
                        "progress": 50,
                        "remaining": 50,
                        "status": "building",
                        "next_gap": "实现能力",
                    },
                ]
            }
        }
    )

    gaps = {row["gate"]: row for row in result["failed_gates"]}
    assert "创始人状态" not in gaps
    assert gaps["客户状态"]["missing_receipt"] == "真实付费"
    assert gaps["进化状态"]["missing_receipt"] == "实现能力"
    assert "25/100" in gaps["客户状态"]["recommendation"]
    assert result["warnings"] == []


def test_preserves_explicit_failed_gate_contract():
    result = _analyze(
        {
            "scorecard": {
                "gates": [
                    {
                        "id": "paid_delivery",
                        "passed": False,
                        "required_receipt": "third-party payment plus accepted delivery",
                    }
                ]
            }
        }
    )

    assert result["failed_gates"][0]["gate"] == "paid_delivery"
    assert result["failed_gates"][0]["missing_receipt"] == (
        "third-party payment plus accepted delivery"
    )
