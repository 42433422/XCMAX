"""Preserve bounded-loop evidence across every supported review protocol."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CI_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import ai_review as review

# The original scoped-replay wait: the exits occur after the fourth loop line.
REPLAY_WAIT = """    deadline = time.monotonic() + chat_stream_replay.LEASE_TTL_SECONDS + 5
    try:
        while True:
            if not await authorize():
                yield revoked
                return
            rows = chat_stream_replay.events_after(turn_id, owner=owner, tenant=tenant, limit=1)
            if rows:
                break
            if (
                time.monotonic() >= deadline
                or chat_stream_replay.finish_status(turn_id, owner=owner, tenant=tenant)
                or not chat_stream_replay.lease_alive(turn_id, owner=owner, tenant=tenant)
            ):
                raise chat_stream_replay.ReplayBackendUnavailable("原流缺少范围证据")
            await asyncio.sleep(0.1)"""


@pytest.mark.parametrize("route", ["endpoint", "openai", "anthropic"])
def test_replay_wait_sends_exits_and_yield_without_overriding_verdict(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    lines = [
        (258 + offset, "+" if line.strip() == "while True:" else " ", line)
        for offset, line in enumerate(REPLAY_WAIT.splitlines())
    ]
    lines.extend(
        [(240, " ", "unrelated_before"), (280, " ", "unrelated_after"), (0, "-", "deleted_exit")]
    )
    hunk = review.DiffHunk("compat_routes.py", 258, lines, "@@ -258,16 +258,16 @@")
    finding = next(
        f for f in review.match_high_risk_rules([hunk]) if f.rule == "unbounded-while-true"
    )
    assert (finding.line, finding.severity) == (260, "medium")
    monkeypatch.setenv(
        "XCAGI_LLM_ENDPOINT", "https://review.example.test/v1/review" if route == "endpoint" else ""
    )
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://review.example.test")
    monkeypatch.setenv("XCAGI_LLM_MODEL", "review-model")
    client = MagicMock()
    client.post.return_value.status_code = 200
    client.post.return_value.json.return_value = {"verdict": "medium"}
    key = "sk-cp-test" if route == "anthropic" else "test-key"
    assert review.call_llm_review(finding, api_key=key, client=client) == "medium"
    payload = client.post.call_args.kwargs["json"]
    evidence = (
        payload
        if route == "endpoint"
        else json.loads(payload["messages"][0]["content"].split("Evidence: ", 1)[1])
    )
    assert evidence["snippet"] == "while True:"
    for proof in (
        "deadline = time.monotonic()",
        "if not await authorize()",
        "break",
        "time.monotonic() >= deadline",
        "chat_stream_replay.finish_status",
        "chat_stream_replay.lease_alive",
        "raise chat_stream_replay.ReplayBackendUnavailable",
        "await asyncio.sleep(0.1)",
    ):
        assert proof in evidence["context"]
    for excluded in ("unrelated_before", "unrelated_after", "deleted_exit"):
        assert excluded not in evidence["context"]
    assert len(evidence["context"].splitlines()) <= 33
