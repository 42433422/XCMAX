"""Deterministic, read-only ecosystem revenue-share reconciler."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return _failed("entries must be a non-empty list", "missing_entries")
    if not entries:
        return {
            "ok": True,
            "status": "no_data",
            "summary": "已只读查询作者分润账本，当前没有可对账条目；未发起任何资金操作。",
            "differences": [],
            "invalid_entries": [],
            "evidence": ["input.entries", "authoritative_empty_observation"],
            "read_only": True,
            "side_effects": [],
            "no_effect": True,
        }

    differences: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        row = raw if isinstance(raw, dict) else {}
        partner_id = str(row.get("partner_id") or "").strip()
        values = (
            row.get("gross_cents"),
            row.get("share_bps"),
            row.get("recorded_share_cents"),
        )
        if not partner_id or not all(isinstance(value, int) and value >= 0 for value in values):
            invalid.append({"index": index, "reason": "invalid_reconciliation_input"})
            continue
        gross_cents, share_bps, recorded_cents = values
        if share_bps > 10_000:
            invalid.append({"index": index, "reason": "share_bps_out_of_range"})
            continue
        expected_cents = gross_cents * share_bps // 10_000
        delta_cents = recorded_cents - expected_cents
        if delta_cents:
            differences.append(
                {
                    "partner_id": partner_id,
                    "expected_share_cents": expected_cents,
                    "recorded_share_cents": recorded_cents,
                    "delta_cents": delta_cents,
                }
            )

    approved = not invalid and not differences
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"伙伴分润已完成确定性只读核对：{len(entries)} 条记录，"
            f"{len(differences)} 条金额差异，{len(invalid)} 条无效输入；未发起资金操作。"
        ),
        "differences": differences,
        "invalid_entries": invalid,
        "evidence": [
            "entries[].gross_cents",
            "entries[].share_bps",
            "entries[].recorded_share_cents",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
