"""后台 loop 走平台派发：LLM 成本记平台、不查/扣用户 llm_calls 配额。

修复生产实测根因——员工执行/自维护 loop 跑在真实 user_id(>0) → chat_dispatch_via_session
→ require_llm_credit → 403 配额不足。改法：loop 入口解析平台 bench (provider, model) 作为
bench_llm_override 透传到 cognition → use_platform_dispatch=True → chat_dispatch_via_platform_only。
"""

import asyncio
from unittest.mock import MagicMock

import modstore_server.services.llm as llm_mod
from modstore_server import digest_line_executor as dle


# ─────────────── digest 产线 _platform_bench_override ───────────────


def test_digest_override_enabled_returns_platform_bench(monkeypatch):
    monkeypatch.delenv("MODSTORE_DAILY_VIBE_EXECUTE_PLATFORM_LLM", raising=False)
    monkeypatch.setattr(llm_mod, "resolve_platform_bench_llm", lambda: ("xiaomi", "mimo-v2.5-pro"))
    assert dle._platform_bench_override() == ("xiaomi", "mimo-v2.5-pro")


def test_digest_override_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_PLATFORM_LLM", "0")
    monkeypatch.setattr(llm_mod, "resolve_platform_bench_llm", lambda: ("xiaomi", "mimo-v2.5-pro"))
    assert dle._platform_bench_override() is None


def test_digest_override_no_platform_key_returns_none(monkeypatch):
    monkeypatch.delenv("MODSTORE_DAILY_VIBE_EXECUTE_PLATFORM_LLM", raising=False)
    monkeypatch.setattr(llm_mod, "resolve_platform_bench_llm", lambda: (None, None))
    assert dle._platform_bench_override() is None


# ─────────────── self_maintenance _loop_platform_bench_override ───────────────


def test_self_maintenance_override_enabled(monkeypatch):
    from modstore_server import self_maintenance_loop_runner as smr

    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM", raising=False)
    monkeypatch.setattr(llm_mod, "resolve_platform_bench_llm", lambda: ("openai", "gpt-4o-mini"))
    assert smr._loop_platform_bench_override() == ("openai", "gpt-4o-mini")


def test_self_maintenance_override_disabled(monkeypatch):
    from modstore_server import self_maintenance_loop_runner as smr

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM", "0")
    monkeypatch.setattr(llm_mod, "resolve_platform_bench_llm", lambda: ("openai", "gpt-4o-mini"))
    assert smr._loop_platform_bench_override() is None


# ─────────────── orchestrator 透传 bench_llm_override 到 execute_employee_task ───────────────


def test_run_layer_threads_bench_override(monkeypatch):
    import modstore_server.employee_executor as ee
    from modstore_server import employee_orchestrator as orch
    from modstore_server.task_router import SubTask

    captured = {}

    def fake_execute(employee_id, task_brief, input_data, *, user_id, bench_llm_override=None):
        captured["bench_llm_override"] = bench_llm_override
        captured["user_id"] = user_id
        return {"ok": True}

    monkeypatch.setattr(ee, "execute_employee_task", fake_execute)

    layer = [SubTask(employee_id="e1", task_brief="修复", input_data={})]
    out = orch._run_layer(
        layer,
        uid=7,
        completed={},
        max_concurrency=1,
        allow_high_risk_real_run=False,
        bench_llm_override=("xiaomi", "mimo-v2.5-pro"),
    )

    # 平台 override 已透传; user_id 仍是真实 loop 用户(给 RAG/指标)
    assert captured["bench_llm_override"] == ("xiaomi", "mimo-v2.5-pro")
    assert captured["user_id"] == 7
    assert out and out[0]["employee_id"] == "e1"


def test_run_layer_default_no_override(monkeypatch):
    import modstore_server.employee_executor as ee
    from modstore_server import employee_orchestrator as orch
    from modstore_server.task_router import SubTask

    captured = {}

    def fake_execute(employee_id, task_brief, input_data, *, user_id, bench_llm_override=None):
        captured["bench_llm_override"] = bench_llm_override
        return {"ok": True}

    monkeypatch.setattr(ee, "execute_employee_task", fake_execute)

    orch._run_layer(
        [SubTask(employee_id="e1", task_brief="t", input_data={})],
        uid=1,
        completed={},
        max_concurrency=1,
        allow_high_risk_real_run=False,
    )
    # 不传 override 时默认 None（web/交互路径保持原按用户配额行为）
    assert captured["bench_llm_override"] is None


# ─────────────── 端到端：平台 key 在场时 loop 真能产出（桩底层 HTTP，不联网/不花钱） ───────────────


def test_loop_cognition_runs_via_platform_dispatch(monkeypatch):
    """证明：配了平台 key（env），loop 的员工认知经 bench_llm_override → 平台派发 → 真出内容，
    且**绝不**触碰用户配额/计费路径（碰了就炸）。生产里平台 key 就是这种 env（OPENAI_API_KEY 等）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake-platform")  # 平台 key（生产同形态）

    async def _fake_chat_dispatch(provider, **kw):
        # 底层 HTTP 被桩：不联网、不花钱；校验用的是平台 key
        assert kw.get("api_key") == "sk-fake-platform"
        return {
            "ok": True,
            "content": "[小C调研产出] 竞品A定价偏高，建议错位定价……",
            "usage": {"prompt_tokens": 120, "completion_tokens": 60},
            "raw": {},
        }

    import modstore_server.llm_chat_proxy as proxy

    monkeypatch.setattr(proxy, "chat_dispatch", _fake_chat_dispatch)

    # 平台派发不该走用户配额/计费——走了就炸
    import modstore_server.quota_middleware as qmw

    def _boom(*a, **k):
        raise AssertionError("平台派发不应调用 require/consume_llm_credit（那是被烧穿的用户配额路径）")

    monkeypatch.setattr(qmw, "require_llm_credit", _boom)
    monkeypatch.setattr(qmw, "consume_llm_credit", _boom)

    from modstore_server.employee_executor import _cognition_real

    config = {
        "cognition": {
            "agent": {
                "system_prompt": "你是调研员工",
                "model": {"provider": "auto", "model_name": "auto"},
            }
        }
    }
    perceived = {"normalized_input": {"task": "调研竞品定价"}}
    result = asyncio.run(
        _cognition_real(
            config,
            perceived,
            {},
            MagicMock(),  # session：本路径(无RAG)不查库
            1,
            employee_id="researcher",
            task="调研竞品定价",
            bench_llm_override=("deepseek", "deepseek-chat"),
        )
    )

    assert result.get("error") in (None, ""), result
    assert "竞品A" in result["reasoning"]  # loop 真产出了内容
    assert result["_bench_platform_only"] is True  # 走的是平台派发，非用户配额
    assert result["provider"] == "deepseek"
