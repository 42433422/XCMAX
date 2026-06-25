"""自进化闭环补强：窄 CI / 编排 ok 判定 / 信号采集 / 产线灰度 / prompt A/B / cursor delegate。"""

from __future__ import annotations

import json

from modstore_server import employee_orchestrator as eo
from modstore_server.cr_narrow_ci import (
    _copytree_filtered,
    infer_related_test_files,
    run_narrow_ci_validation,
)
from modstore_server.cursor_delegate_handler import dispatch_cursor_delegate
from modstore_server.evolution_signal_collector import (
    collect_evolution_signals,
    format_evolution_signals_for_prompt,
)
from modstore_server.line_rollout_policy import (
    primary_lines,
    resolve_line_execution_mode,
    shadow_lines_override,
)
from modstore_server.prompt_evolution_ab import (
    apply_prompt_override,
    get_effective_system_prompt,
    revert_prompt_override,
)


def test_infer_related_test_files_for_auto_approve_module(tmp_path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_auto_approve_policy_extra.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    found = infer_related_test_files(
        "modstore_server/auto_approve_policy.py",
        root=tmp_path,
    )
    assert any("test_auto_approve" in f for f in found)


def test_run_narrow_ci_validation_py_compile_ok():
    out = run_narrow_ci_validation(
        "modstore_server/foo.py",
        "def hello():\n    return 1\n",
    )
    assert out.get("ok") is True
    steps = out.get("steps") or []
    assert any(s.get("step") == "py_compile" for s in steps)


def test_run_narrow_ci_validation_pytest_uses_modstore_deploy_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CR_NARROW_CI_RUFF", "0")
    deploy = tmp_path / "MODstore_deploy"
    (deploy / "modstore_server").mkdir(parents=True)
    tests = deploy / "tests"
    tests.mkdir()
    (tests / "test_proposed_target.py").write_text(
        "def test_proposed_target_overlay():\n"
        "    from modstore_server import proposed_target\n"
        "    assert proposed_target.value() == 42\n",
        encoding="utf-8",
    )

    out = run_narrow_ci_validation(
        "MODstore_deploy/modstore_server/proposed_target.py",
        "def value():\n    return 42\n",
        project_root=str(tmp_path),
    )

    assert out.get("ok") is True
    pytest_steps = [step for step in out.get("steps") or [] if step.get("step") == "pytest"]
    assert pytest_steps
    assert pytest_steps[0].get("skipped") is not True
    assert "MODstore_deploy/tests/test_proposed_target.py" in pytest_steps[0]["command"]


def test_copytree_filtered_excludes_runtime_state_files(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "modstore_server" / "vector_data").mkdir(parents=True)
    (source / "modstore_server" / "vector_data" / "chroma.sqlite3").write_text(
        "db",
        encoding="utf-8",
    )
    (source / "modstore_server" / "live.py").write_text("value = 1\n", encoding="utf-8")

    _copytree_filtered(source, target)

    assert (target / "modstore_server" / "live.py").exists()
    assert not (target / "modstore_server" / "vector_data").exists()


def test_run_narrow_ci_validation_overlay_prepare_failure_is_structured(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CR_NARROW_CI_RUFF", "0")
    deploy = tmp_path / "MODstore_deploy"
    (deploy / "modstore_server").mkdir(parents=True)

    def fail_copytree(*_args, **_kwargs):
        raise RuntimeError("copy failed")

    monkeypatch.setattr("modstore_server.cr_narrow_ci._copytree_filtered", fail_copytree)

    out = run_narrow_ci_validation(
        "MODstore_deploy/modstore_server/proposed_target.py",
        "def value():\n    return 42\n",
        project_root=str(tmp_path),
    )

    assert out["ok"] is False
    assert out["failed_step"] == "overlay_prepare"
    assert out["steps"][-1]["step"] == "overlay_prepare"


def test_run_narrow_ci_validation_keeps_smoke_fallback_for_prefixed_prod_root(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MODSTORE_CR_NARROW_CI_RUFF", "0")
    deploy = tmp_path / "成都修茈科技有限公司" / "MODstore_deploy"
    (deploy / "modstore_server").mkdir(parents=True)
    tests = deploy / "tests"
    tests.mkdir()
    (tests / "test_orchestration_modules_smoke_extra.py").write_text(
        "def test_smoke_fallback_runs():\n    assert True\n",
        encoding="utf-8",
    )

    out = run_narrow_ci_validation(
        "MODstore_deploy/modstore_server/unknown_module_without_named_test.py",
        "def value():\n    return 42\n",
        project_root=str(tmp_path),
    )

    assert out.get("ok") is True
    assert any("test_orchestration_modules_smoke_extra.py" in f for f in out["test_files"])
    pytest_steps = [step for step in out.get("steps") or [] if step.get("step") == "pytest"]
    assert pytest_steps
    assert pytest_steps[0].get("skipped") is not True


def test_run_narrow_ci_validation_syntax_error():
    out = run_narrow_ci_validation(
        "modstore_server/bad.py",
        "def oops(\n",
    )
    assert out.get("ok") is False
    assert out.get("failed_step") == "py_compile"


def test_evaluate_execution_success_handler_failed():
    ok, reason = eo._evaluate_execution_success(
        {
            "result": {
                "outputs": [
                    {"handler": "vibe_edit", "ok": False, "error": "boom"},
                ]
            }
        }
    )
    assert ok is False
    assert "handler_failed" in reason


def test_evaluate_execution_success_handlers_ok():
    ok, _ = eo._evaluate_execution_success(
        {
            "result": {
                "outputs": [
                    {"handler": "llm_md", "output": "done"},
                ]
            }
        }
    )
    assert ok is True


def test_collect_evolution_signals_shape():
    sig = collect_evolution_signals(lookback_hours=24)
    assert "pytest_failures" in sig
    assert "runtime_anomalies" in sig
    assert "performance_signals" in sig
    assert "loop_memory_signals" in sig
    text = format_evolution_signals_for_prompt(sig)
    assert isinstance(text, str)


def test_collect_evolution_signals_includes_loop_memory_with_timestamps(tmp_path, monkeypatch):
    memory_path = tmp_path / "self_maintenance_loop_memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "last_policy_decision": {
                    "action": "await_human_strategy_approval",
                    "reason": "review_or_qa_reported_risk",
                },
                "last_run": {
                    "completed_at": "2026-06-18T20:28:35+00:00",
                    "run_id": "run-last",
                },
                "open_items": [
                    {
                        "branch": "devfleet/codex/sub-1",
                        "created_at": "2026-06-18T20:28:35+00:00",
                        "kind": "human_strategy_approval",
                        "reason": "review_or_qa_reported_risk",
                        "run_id": "run-open",
                    }
                ],
                "recent_runs": [
                    {
                        "action": "await_human_strategy_approval",
                        "branch": "devfleet/codex/sub-1",
                        "completed_at": "2026-06-18T20:28:35+00:00",
                        "run_id": "run-recent",
                        "status": "completed_waiting_human_strategy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))

    sig = collect_evolution_signals(lookback_hours=24)
    text = format_evolution_signals_for_prompt(sig)

    assert sig["loop_memory_signals"]
    assert "自维护 loop 记忆" in text
    assert "2026-06-18T20:28:35+00:00" in text
    assert "review_or_qa_reported_risk" in text


def test_line_rollout_policy_ps_primary_default(monkeypatch):
    monkeypatch.delenv("MODSTORE_LINE_PRIMARY_LINES", raising=False)
    monkeypatch.delenv("MODSTORE_LINE_SHADOW_LINES", raising=False)
    assert "P-S" in primary_lines()
    assert "P-W" in shadow_lines_override()
    mode_ps = resolve_line_execution_mode("P-S", global_digest_mode="shadow")
    mode_pw = resolve_line_execution_mode("P-W", global_digest_mode="shadow")
    assert mode_ps == "auto"
    assert mode_pw == "shadow"


def test_prompt_override_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PROMPT_OVERRIDE_DIR", str(tmp_path / "overrides"))
    apply_prompt_override("test-emp", "prompt v2", meta={"test": True})
    assert get_effective_system_prompt("test-emp", "prompt v1") == "prompt v2"
    revert_prompt_override("test-emp")
    assert get_effective_system_prompt("test-emp", "prompt v1") == "prompt v1"


def test_cursor_delegate_disabled(monkeypatch):
    monkeypatch.setenv("MODSTORE_CURSOR_DELEGATE_ENABLED", "0")
    out = dispatch_cursor_delegate(task="fix bug", input_data={"project_root": "."})
    assert out.get("ok") is False
