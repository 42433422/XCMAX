"""Tests for the platform-only bench LLM path.

Covers:
- resolve_platform_bench_llm: env override, first-provider-with-key fallback, no-key returns (None, None)
- generate_bench_tasks with use_platform_dispatch=True + strict=True raises on LLM failure
- generate_bench_tasks with use_platform_dispatch=True succeeds when platform dispatch returns valid JSON
- run_and_score_bench passes bench_llm_override to _run_single_task (and hence to execute_employee_task)
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# bench execution ok / cognition_error
# ---------------------------------------------------------------------------


def test_derive_bench_ok_false_when_cognition_error():
    from modstore_server.employee_bench import _derive_bench_execution_ok

    assert _derive_bench_execution_ok({"cognition_error": "upstream timeout"}) is False
    assert _derive_bench_execution_ok({"result": {"outputs": []}}) is True


# ---------------------------------------------------------------------------
# resolve_platform_bench_llm
# ---------------------------------------------------------------------------


def test_resolve_platform_bench_llm_env_override(monkeypatch):
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", "deepseek")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_MODEL", "deepseek-reasoner")

    with patch("modstore_server.llm_key_resolver.platform_api_key", return_value="sk-test"):
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()

    assert prov == "deepseek"
    assert mdl == "deepseek-reasoner"


def test_resolve_platform_bench_llm_no_env_falls_back_to_first_provider(monkeypatch):
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", raising=False)
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_MODEL", raising=False)

    def _fake_platform_key(provider: str):
        return "sk-test" if provider == "deepseek" else None

    with patch("modstore_server.llm_key_resolver.platform_api_key", side_effect=_fake_platform_key):
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()

    assert prov == "deepseek"
    assert mdl  # comes from _BENCH_DEFAULT_MODELS["deepseek"]


def test_resolve_platform_bench_llm_returns_none_when_no_platform_key(monkeypatch):
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", raising=False)
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_MODEL", raising=False)

    with patch("modstore_server.llm_key_resolver.platform_api_key", return_value=None):
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()

    assert prov is None
    assert mdl is None


def test_resolve_platform_bench_llm_xiaomi_uses_current_default_model(monkeypatch):
    """Only xiaomi has a platform key → default model must be a live gateway id (not legacy 7B)."""
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", raising=False)
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_MODEL", raising=False)

    def _fake_platform_key(provider: str):
        return "sk-test" if provider == "xiaomi" else None

    with patch("modstore_server.llm_key_resolver.platform_api_key", side_effect=_fake_platform_key):
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()

    assert prov == "xiaomi"
    assert mdl == "mimo-v2.5-pro"


def test_xiaomi_legacy_7b_model_alias_maps_to_pro():
    from modstore_server.llm_chat_proxy import normalize_model

    assert normalize_model("xiaomi", "MiMo-7B-RL-Think") == "mimo-v2.5-pro"
    assert normalize_model("xiaomi", "mimo-v2-flash") == "mimo-v2.5-pro"


def test_dimensions_still_open():
    from modstore_server.employee_bench import AUDIT_DIMENSIONS, _dimensions_still_open

    env = {"manifest_compliance": "a"}
    holes = _dimensions_still_open(env, {"metadata_quality": "b"})
    assert "manifest_compliance" not in holes
    assert "metadata_quality" not in holes
    assert len(holes) == len(AUDIT_DIMENSIONS) - 2


def test_parse_machine_score_from_text():
    from modstore_server.employee_bench import _parse_machine_score_from_text

    assert _parse_machine_score_from_text("intro\n\nMACHINE_SCORE=72") == 72
    assert _parse_machine_score_from_text("MACHINE_SCORE=101") == 100
    assert _parse_machine_score_from_text("nope") is None


def test_peer_review_gate_env(monkeypatch):
    from modstore_server.employee_bench import _peer_review_gate_enabled, _peer_review_min_score

    monkeypatch.delenv("MODSTORE_BENCH_PEER_REVIEW_GATE", raising=False)
    assert _peer_review_gate_enabled() is False
    monkeypatch.setenv("MODSTORE_BENCH_PEER_REVIEW_GATE", "1")
    assert _peer_review_gate_enabled() is True
    monkeypatch.setenv("MODSTORE_BENCH_PEER_REVIEW_MIN_SCORE", "60")
    assert _peer_review_min_score() == 60.0


@pytest.mark.asyncio
async def test_run_pack_peer_review_skips_without_platform_llm(monkeypatch):
    monkeypatch.setenv("MODSTORE_PACK_PEER_REVIEW_EMPLOYEE", "employee-pack-quality-interviewer")
    from unittest.mock import MagicMock

    from modstore_server.employee_bench import _run_pack_peer_review_optional

    peer = await _run_pack_peer_review_optional(
        "some-pack-id",
        db=MagicMock(),
        user=MagicMock(),
        bench_llm_override=None,
    )
    assert peer is not None
    assert peer.get("skipped") is True
    assert peer.get("reason") == "no_platform_bench_llm"


# ---------------------------------------------------------------------------
# chat_dispatch_via_platform_only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_dispatch_via_platform_only_no_key():
    with patch("modstore_server.llm_key_resolver.platform_api_key", return_value=None):
        from modstore_server.services.llm import chat_dispatch_via_platform_only

        result = await chat_dispatch_via_platform_only("deepseek", "deepseek-chat", [])

    assert result["ok"] is False
    assert "no platform api key" in result["error"]


@pytest.mark.asyncio
async def test_chat_dispatch_via_platform_only_calls_dispatch_without_byok():
    """Verify chat_dispatch is called with the platform key, not a user BYOK."""
    fake_result = {"ok": True, "content": "hello"}

    with (
        patch("modstore_server.llm_key_resolver.platform_api_key", return_value="sk-platform"),
        patch(
            "modstore_server.llm_key_resolver.platform_base_url",
            return_value="https://api.deepseek.com",
        ),
        patch(
            "modstore_server.llm_chat_proxy.chat_dispatch", new=AsyncMock(return_value=fake_result)
        ) as mock_dispatch,
    ):
        from modstore_server.services.llm import chat_dispatch_via_platform_only

        result = await chat_dispatch_via_platform_only(
            "deepseek", "deepseek-chat", [{"role": "user", "content": "hi"}], max_tokens=100
        )

    assert result["ok"] is True
    call_kwargs = mock_dispatch.call_args
    assert call_kwargs.kwargs.get("api_key") == "sk-platform"


# ---------------------------------------------------------------------------
# generate_bench_tasks — strict + use_platform_dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_bench_tasks_strict_raises_when_llm_fails():
    from modstore_server.employee_bench import generate_bench_tasks

    with patch(
        "modstore_server.services.llm.chat_dispatch_via_platform_only",
        new=AsyncMock(return_value={"ok": False, "error": "upstream down"}),
    ):
        with pytest.raises(RuntimeError, match="LLM error"):
            await generate_bench_tasks(
                "test brief",
                "",
                db=MagicMock(),
                user_id=1,
                provider="deepseek",
                model="deepseek-chat",
                use_platform_dispatch=True,
                strict=True,
            )


@pytest.mark.asyncio
async def test_generate_bench_tasks_strict_raises_on_empty_provider():
    from modstore_server.employee_bench import generate_bench_tasks

    with pytest.raises(RuntimeError, match="无 provider/model"):
        await generate_bench_tasks(
            "test brief",
            "",
            db=MagicMock(),
            user_id=1,
            provider=None,
            model=None,
            use_platform_dispatch=True,
            strict=True,
        )


@pytest.mark.asyncio
async def test_generate_bench_tasks_platform_dispatch_returns_valid_tasks():
    task_json = json.dumps(
        [
            {"level": lv, "tasks": [{"id": f"{lv}-1", "task_desc": f"task {lv}"}]}
            for lv in range(1, 6)
        ]
    )

    with patch(
        "modstore_server.services.llm.chat_dispatch_via_platform_only",
        new=AsyncMock(return_value={"ok": True, "content": task_json}),
    ):
        from modstore_server.employee_bench import generate_bench_tasks

        result = await generate_bench_tasks(
            "brief",
            "summary",
            db=MagicMock(),
            user_id=1,
            provider="deepseek",
            model="deepseek-chat",
            use_platform_dispatch=True,
            strict=True,
        )

    assert len(result) == 5
    for item in result:
        assert item["tasks"]


@pytest.mark.asyncio
async def test_generate_bench_tasks_non_strict_falls_back_silently():
    """Without strict=True, a failed LLM call returns placeholder tasks."""
    from modstore_server.employee_bench import _fallback_tasks, generate_bench_tasks

    with patch(
        "modstore_server.services.llm.chat_dispatch_via_platform_only",
        new=AsyncMock(return_value={"ok": False, "error": "timeout"}),
    ):
        result = await generate_bench_tasks(
            "some brief",
            "",
            db=MagicMock(),
            user_id=1,
            provider="deepseek",
            model="deepseek-chat",
            use_platform_dispatch=True,
            strict=False,
        )

    # Should still return 5 levels of placeholder tasks
    assert len(result) == 5


# ---------------------------------------------------------------------------
# run_and_score_bench — bench_llm_override propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_and_score_bench_passes_override_to_single_task():
    """bench_llm_override must reach _run_single_task."""
    captured: list = []

    def fake_run_single_task(emp_id, task_desc, user_id, bench_llm_override=None):
        captured.append(bench_llm_override)
        return {"ok": True, "cost_tokens": 10, "duration_ms": 50.0, "raw": {}}

    fake_audit = {
        "ok": True,
        "dimensions": {},
        "summary": {"average": 80, "pass": True},
    }

    task_list = [{"level": 1, "tasks": [{"id": "1-1", "task_desc": "do thing"}]}]
    user = MagicMock(id=1)

    rubric_json = '[{"task_id":"1-1","score":85,"note":"符合任务"}]'

    with (
        patch("modstore_server.employee_bench._run_single_task", side_effect=fake_run_single_task),
        patch(
            "modstore_server.employee_bench._run_five_dim_audit",
            new=AsyncMock(return_value=fake_audit),
        ),
        patch(
            "modstore_server.services.llm.chat_dispatch_via_platform_only",
            new=AsyncMock(return_value={"ok": True, "content": rubric_json}),
        ),
    ):
        from modstore_server.employee_bench import run_and_score_bench

        rep = await run_and_score_bench(
            "emp-1",
            task_list,
            db=MagicMock(),
            user=user,
            bench_llm_override=("deepseek", "deepseek-chat"),
        )

    assert captured == [("deepseek", "deepseek-chat")]
    assert rep["scoring"]["method"] == "llm_rubric_platform"
    assert rep["tasks_result"][0]["score"] == 85.0
    assert rep["tasks_result"][0]["score_source"] == "llm_rubric"
