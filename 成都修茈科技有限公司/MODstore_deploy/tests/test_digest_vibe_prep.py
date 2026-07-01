"""Tests for digest_vibe_prep helpers."""

from __future__ import annotations

from modstore_server.digest_vibe_prep import (
    _apply_version_stamp,
    _build_template_vibe_markdowns,
    _finalize_vibe_result,
    _strip_html_to_text,
    resolve_vibe_prep_version_context,
)


def test_strip_html_to_text_basic() -> None:
    raw = "<p>Hello <strong>MODstore</strong></p><script>x</script>"
    out = _strip_html_to_text(raw, max_chars=1000)
    assert "Hello" in out
    assert "MODstore" in out
    assert "script" not in out.lower() or "x" not in out


def test_strip_html_truncates() -> None:
    raw = "<p>" + ("a" * 200) + "</p>"
    out = _strip_html_to_text(raw, max_chars=50)
    assert len(out) <= 51
    assert out.endswith("…")


def test_resolve_vibe_prep_version_context() -> None:
    ctx = resolve_vibe_prep_version_context(
        digest_day="2026-06-03",
        digest_subject="MODstore 每日摘要 · 2026-06-03",
        record_id=42,
        mode="auto",
    )
    assert ctx["digest_day"] == "2026-06-03"
    assert ctx["digest_record_id"] == 42
    assert ctx["base_version"].startswith("2026-06-03#")
    assert ctx["base_version"].endswith("#r42")
    assert ctx["updates_version"] == f"{ctx['base_version']}-updates"
    assert ctx["patches_version"] == f"{ctx['base_version']}-patches"


def test_apply_version_stamp_injects_table() -> None:
    ctx = resolve_vibe_prep_version_context(
        digest_day="2026-06-03",
        digest_subject="subj",
        record_id=7,
        mode="auto",
    )
    body = "## [foo] bar\n\n- item"
    out = _apply_version_stamp("updates", body, ctx)
    assert out.startswith("# Vibe 预备 · 更新清单")
    assert f"`{ctx['updates_version']}`" in out
    assert f"`{ctx['base_version']}`" in out
    assert "## [foo] bar" in out


def test_template_fallback_versions_match(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_VIBE_PREP_INCLUDE_META_UPDATES", "1")
    ctx = resolve_vibe_prep_version_context(
        digest_day="2026-06-03",
        digest_subject="subj",
        record_id=3,
        mode="auto",
    )
    employees = [
        {
            "employee_id": "daily-orchestrator",
            "name": "编排",
            "pack_version": "1.0.0",
            "scope_globs": ["yuangon/**"],
            "depends_on": ["ops-handler"],
            "handlers": ["run_digest"],
            "recent_failures": [],
            "domain": "ops",
        }
    ]
    updates, patches = _build_template_vibe_markdowns(employees=employees, ctx=ctx)
    assert ctx["updates_version"] in updates
    assert ctx["patches_version"] in patches
    assert ctx["base_version"] in updates
    assert ctx["base_version"] in patches
    assert "v1.0.0" in updates


def test_template_fallback_ignores_surface_hints_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MODSTORE_VIBE_PREP_INCLUDE_SURFACE_HINTS", raising=False)
    ctx = resolve_vibe_prep_version_context(
        digest_day="2026-06-03",
        digest_subject="subj",
        record_id=4,
        mode="auto",
    )
    evidence = (
        "巡检显示多个业务路由标题均渲染为「智能对话 - XCAGI」。"
        " catalog/40、catalog/50、catalog/41 返回 404。"
        " 资源加载包含 ERR_CONNECTION_CLOSED / ERR_HTTP2_PING_FAILED。"
        " 沙箱测试页 403。"
    )
    updates, patches = _build_template_vibe_markdowns(
        employees=[],
        ctx=ctx,
        digest_excerpt=evidence,
        surface_audit_excerpt=evidence,
    )
    assert "P-S 页面标题" not in patches
    assert "catalog 404" not in patches
    assert "ERR_CONNECTION_CLOSED" not in patches
    assert "沙箱测试页 403" not in updates
    assert "（无证据驱动补丁）" in patches


def test_template_fallback_can_include_surface_hints_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_VIBE_PREP_INCLUDE_SURFACE_HINTS", "1")
    ctx = resolve_vibe_prep_version_context(
        digest_day="2026-06-03",
        digest_subject="subj",
        record_id=5,
        mode="auto",
    )
    evidence = (
        "巡检显示多个业务路由标题均渲染为「智能对话 - XCAGI」。"
        " catalog/40 返回 404。"
        " 资源加载包含 ERR_CONNECTION_CLOSED。"
        " 沙箱 sandbox 页面 403。"
    )
    updates, patches = _build_template_vibe_markdowns(
        employees=[],
        ctx=ctx,
        surface_audit_excerpt=evidence,
    )
    assert "P-S 页面标题" in patches
    assert "catalog 404" in patches
    assert "ERR_CONNECTION_CLOSED" in patches
    assert "沙箱测试页 403" in updates


def test_template_fallback_emits_generation_breakpoint(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_EVENT_BACKLOG_MERGE_ENABLED", "0")
    ctx = resolve_vibe_prep_version_context(
        digest_day="2026-06-28",
        digest_subject="subj",
        record_id=47,
        mode="auto",
    )
    out = _finalize_vibe_result(
        synth={
            "ok": False,
            "error": "LLM 未返回有效 JSON（缺少 updates_markdown / patches_markdown）",
            "model": "bench/model",
        },
        employees=[
            {
                "employee_id": "modstore-backend-api",
                "name": "MODstore 后端 API 员",
                "pack_version": "1.2.3",
                "scope_globs": ["modstore_server/digest_vibe_prep.py"],
            },
            {
                "employee_id": "task-router-officer",
                "name": "任务派发员",
                "pack_version": "2.3.4",
                "scope_globs": ["modstore_server/digest_action_items.py"],
            },
            {
                "employee_id": "test-qa-runner",
                "name": "测试质量运行员",
                "pack_version": "3.4.5",
                "scope_globs": ["tests/test_digest_vibe_prep.py"],
            },
        ],
        ctx=ctx,
    )

    assert out["ok"] is True
    assert out["synthesizer"] == "template"
    assert "LLM 未返回有效 JSON" in out["fallback_reason"]
    assert "## [daily-orchestrator]" not in out["patches_markdown"]
    assert "## [modstore-backend-api] MODstore 后端 API 员 · v1.2.3" in out["patches_markdown"]
    assert "## [task-router-officer] 任务派发员 · v2.3.4" in out["patches_markdown"]
    assert "## [test-qa-runner] 测试质量运行员 · v3.4.5" in out["patches_markdown"]
    assert "**P0** 修复 Vibe 预备任务生成断点" in out["patches_markdown"]
    assert "**P0** 修复 Vibe fallback 任务责任路由" in out["patches_markdown"]
    assert "action-items、产线执行和 AI 交流圈" in out["patches_markdown"]
