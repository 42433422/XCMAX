"""Tests for digest_vibe_prep helpers."""

from __future__ import annotations

from modstore_server.digest_vibe_prep import (
    _apply_version_stamp,
    _build_template_vibe_markdowns,
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


def test_template_fallback_versions_match() -> None:
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
