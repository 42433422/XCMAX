"""自进化闭环补强：窄 CI / 编排 ok 判定 / 信号采集 / 产线灰度 / prompt A/B / cursor delegate。"""

from __future__ import annotations

from modstore_server import employee_orchestrator as eo
from modstore_server.cr_narrow_ci import infer_related_test_files, run_narrow_ci_validation
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
    text = format_evolution_signals_for_prompt(sig)
    assert isinstance(text, str)


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
