"""Deterministic, read-only knowledge fact curation gate."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    facts = payload.get("facts")
    if not isinstance(facts, list):
        return _failed("facts must be a non-empty list", "missing_facts")
    if not facts:
        return {
            "ok": True,
            "status": "no_data",
            "summary": "已只读查询知识文档数据源，当前没有可筛选的已验证事实；未写入知识库。",
            "accepted_entries": [],
            "rejected_entries": [],
            "evidence": ["input.facts", "authoritative_empty_observation"],
            "read_only": True,
            "side_effects": [],
            "no_effect": True,
        }

    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(facts):
        fact = raw if isinstance(raw, dict) else {}
        statement = str(fact.get("statement") or "").strip()
        source = str(fact.get("source") or "").strip()
        reasons: list[str] = []
        if not statement:
            reasons.append("statement_missing")
        if not source:
            reasons.append("source_missing")
        if fact.get("verified") is not True:
            reasons.append("not_verified")
        if reasons:
            rejected.append({"index": index, "reasons": reasons})
        else:
            accepted.append({"statement": statement, "source": source})

    approved = bool(accepted) and not rejected
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"知识事实已完成只读筛选：{len(accepted)} 条可追溯事实通过，"
            f"{len(rejected)} 条因缺来源或未验证被阻断；未写入知识库。"
        ),
        "accepted_entries": accepted,
        "rejected_entries": rejected,
        "evidence": ["facts[].statement", "facts[].source", "facts[].verified"],
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
