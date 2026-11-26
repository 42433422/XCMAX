from app.infrastructure.billing.platform_made_tokens import build_public_snapshot


def test_public_breakdown_preserves_collector_key_and_total():
    summary = {
        "sources": {"codex": {"available": True, "total_tokens": 37}},
        "grand_total_tokens": 37,
    }
    snapshot = build_public_snapshot(summary)
    source = next(item for item in snapshot["sources"] if item["key"] == "codex")
    assert source["available"] and source["total_tokens"] == 37
    assert source["label"] == "Xiaox"
    assert (
        sum(item["total_tokens"] for item in snapshot["sources"])
        == snapshot["platform_made_tokens"]
    )
