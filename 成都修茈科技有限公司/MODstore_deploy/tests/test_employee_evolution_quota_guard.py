"""自进化引擎「配额失败不触发 prompt 重写」契约。

复现并守护「403 配额死亡螺旋」修复：
- quota_middleware.require_llm_credit 额度耗尽抛 403 → executor 记 metric 时分类为 quota；
- 进化引擎选取重写候选时排除 quota 类失败；
- 全窗口被配额主导时熔断本轮、给出告警与结构化原因，而不是继续烧 LLM 调用。
"""

from __future__ import annotations

from modstore_server.llm_failure_classifier import (
    FAILURE_KIND_PROMPT,
    FAILURE_KIND_QUOTA,
    FAILURE_KIND_TRANSIENT,
    classify_failure_kind,
)


def _fresh_db(tmp_path, monkeypatch, name: str):
    """指向独立临时 SQLite 并重建 schema（含 failure_kind 列）。返回 models 模块。"""
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / name))
    monkeypatch.setenv("MODSTORE_EMPLOYEE_EVOLUTION_ENABLED", "1")
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()
    return models


def _seed_failures(models, *, employee_id: str, status: str, failure_kind: str, count: int) -> int:
    from modstore_server.models import EmployeeExecutionMetric, User

    sf = models.get_session_factory()
    with sf() as session:
        u = session.query(User).first()
        if u is None:
            u = User(username="actor", email="a@a.a", password_hash="x", is_admin=False)
            session.add(u)
            session.commit()
        uid = u.id
        session.add_all(
            [
                EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id=employee_id,
                    task="t",
                    status=status,
                    duration_ms=1.0,
                    llm_tokens=0,
                    error="boom",
                    failure_kind=failure_kind,
                )
                for _ in range(count)
            ]
        )
        session.commit()
        return uid


# ── 分类器：用生产实际错误串锁定行为 ──────────────────────────────────────────


def test_classify_internal_quota_gate_403():
    # quota_middleware.require_llm_credit 抛 HTTPException(403, "配额不足: llm_calls")
    assert classify_failure_kind("403: 配额不足: llm_calls") == FAILURE_KIND_QUOTA


def test_classify_quota_variants():
    assert classify_failure_kind("缺少配额: llm_calls") == FAILURE_KIND_QUOTA
    assert classify_failure_kind("insufficient_quota: you exceeded your current quota") == (
        FAILURE_KIND_QUOTA
    )
    assert classify_failure_kind("Your credit balance is too low") == FAILURE_KIND_QUOTA
    assert classify_failure_kind("upstream error", status_code=403) == FAILURE_KIND_QUOTA
    # OpenAI 把额度耗尽放在 429 下返回 —— 配额优先于瞬时，不能当成可重试限流。
    assert classify_failure_kind("Error 429: insufficient_quota") == FAILURE_KIND_QUOTA


def test_classify_transient_vs_prompt():
    assert classify_failure_kind("429: rate limit, please try again") == FAILURE_KIND_TRANSIENT
    assert classify_failure_kind("upstream 503 service unavailable") == FAILURE_KIND_TRANSIENT
    # 真正可能由 prompt/逻辑导致的失败
    assert classify_failure_kind("JSONDecodeError: expecting value") == FAILURE_KIND_PROMPT
    assert classify_failure_kind("") == ""


# ── 进化引擎契约 ──────────────────────────────────────────────────────────────


def test_quota_only_failures_circuit_break_and_no_rewrite(tmp_path, monkeypatch):
    """全部失败都是配额(403)时：不选任何重写候选、熔断本轮、refine_system_prompt 绝不被调用。"""
    models = _fresh_db(tmp_path, monkeypatch, "evo_quota.sqlite")
    _seed_failures(
        models, employee_id="emp-quota", status="failed", failure_kind=FAILURE_KIND_QUOTA, count=8
    )

    called = {"refine": 0}

    async def _never_called(**_kwargs):  # pragma: no cover - 被调用即测试失败
        called["refine"] += 1
        return {"improved_prompt": "x", "diff_explanation": "x"}, ""

    import modstore_server.employee_ai_pipeline as pipeline

    monkeypatch.setattr(pipeline, "refine_system_prompt", _never_called)

    from modstore_server.employee_autonomy_service import run_employee_evolution_scan

    out = run_employee_evolution_scan(lookback_hours=24, min_failures=3, limit=20)

    assert called["refine"] == 0, "配额失败绝不能触发 prompt 重写"
    assert out["processed"] == 0
    assert out["created"] == 0
    assert out["circuit_broken"] is True
    assert out["skipped_reason"] == "quota_exhausted"
    assert out["quota_failures"] == 8


def test_quota_failures_do_not_pad_threshold(tmp_path, monkeypatch):
    """配额失败不计入 min_failures 阈值：8 配额 + 1 真失败 仍不达标，不触发重写。"""
    models = _fresh_db(tmp_path, monkeypatch, "evo_mixed_low.sqlite")
    _seed_failures(
        models, employee_id="emp-mix", status="failed", failure_kind=FAILURE_KIND_QUOTA, count=8
    )
    _seed_failures(
        models, employee_id="emp-mix", status="failed", failure_kind=FAILURE_KIND_PROMPT, count=1
    )

    called = {"refine": 0}

    async def _never_called(**_kwargs):  # pragma: no cover - 被调用即测试失败
        called["refine"] += 1
        return {"improved_prompt": "x", "diff_explanation": "x"}, ""

    import modstore_server.employee_ai_pipeline as pipeline

    monkeypatch.setattr(pipeline, "refine_system_prompt", _never_called)

    from modstore_server.employee_autonomy_service import run_employee_evolution_scan

    out = run_employee_evolution_scan(lookback_hours=24, min_failures=3, limit=20)

    assert called["refine"] == 0
    assert out["processed"] == 0
    # 非配额真失败只有 1 < 3，没有可重写候选，但窗口存在配额失败 → 熔断告警。
    assert out["circuit_broken"] is True
    assert out["quota_failures"] == 8


def test_real_failures_still_trigger_rewrite(tmp_path, monkeypatch):
    """守护：非配额(可能由 prompt 导致)的真失败达标时，仍照常触发自进化重写 —— 排除不能过宽。"""
    models = _fresh_db(tmp_path, monkeypatch, "evo_real.sqlite")
    # 4 个 quota + 4 个 prompt：真失败已达阈值，配额噪声不应抑制对真问题的进化。
    _seed_failures(
        models, employee_id="emp-real", status="failed", failure_kind=FAILURE_KIND_QUOTA, count=4
    )
    _seed_failures(
        models, employee_id="emp-real", status="failed", failure_kind=FAILURE_KIND_PROMPT, count=4
    )

    seen = {"refine": 0, "prompt_in": ""}

    async def _fake_refine(*, current_prompt, instruction, role_context, llm):
        seen["refine"] += 1
        seen["prompt_in"] = current_prompt
        return {"improved_prompt": "改进后的 prompt", "diff_explanation": "更清晰"}, ""

    import modstore_server.employee_ai_pipeline as pipeline
    import modstore_server.employee_autonomy_service as svc
    import modstore_server.employee_runtime as runtime
    import modstore_server.employee_runtime_policy as policy
    import modstore_server.prompt_evolution_ab as ab

    monkeypatch.setattr(pipeline, "refine_system_prompt", _fake_refine)
    monkeypatch.setattr(
        runtime,
        "load_employee_pack",
        lambda _session, _eid: {"manifest": {"cognition": {"agent": {}}}},
    )
    monkeypatch.setattr(
        runtime,
        "parse_employee_config_v2",
        lambda _manifest: {"cognition": {"agent": {"system_prompt": "原始 system prompt"}}},
    )
    monkeypatch.setattr(policy, "record_employee_degradation", lambda **_kw: {"ok": True})

    def _fake_create_suggestion(**_kw):
        from modstore_server.models import EmployeeSuggestion

        sf = models.get_session_factory()
        with sf() as session:
            suggestion = EmployeeSuggestion(
                source_employee_id="emp-real",
                kind="employee_evolution",
            )
            session.add(suggestion)
            session.commit()
            return {"ok": True, "suggestion_id": int(suggestion.id)}

    monkeypatch.setattr(svc, "create_employee_suggestion", _fake_create_suggestion)
    monkeypatch.setattr(
        ab, "maybe_auto_apply_prompt_evolution", lambda **_kw: {"applied": False, "ab": {}}
    )
    monkeypatch.setattr(svc, "_publish_event", lambda *a, **k: None)

    out = svc.run_employee_evolution_scan(lookback_hours=24, min_failures=3, limit=20)

    assert seen["refine"] == 1, "达标的真失败必须触发 prompt 重写"
    assert seen["prompt_in"] == "原始 system prompt"
    assert out["processed"] == 1
    assert out["created"] == 1
    assert not out.get("circuit_broken")
