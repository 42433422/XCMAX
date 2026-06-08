from __future__ import annotations

import asyncio

from modstore_server.workbench_script_runner import (
    _looks_like_non_python,
    run_script_agent_job,
    run_script_job,
    validate_script,
)


def test_validate_script_blocks_dangerous_import():
    errors = validate_script("import subprocess\nprint('x')\n")
    assert errors
    assert "subprocess" in ";".join(errors)


def test_run_script_job_requires_llm_when_no_provider(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    result = asyncio.run(
        run_script_job(
            db=None,
            user_id=1,
            session_id="test-session",
            brief="汇总 Excel",
            files=[{"filename": "input.xlsx", "content": _xlsx_bytes()}],
            provider=None,
            model=None,
        )
    )
    assert result["ok"] is False
    assert result["outputs"] == []
    assert result["errors"]
    assert "LLM" in "".join(result["errors"]) or "供应商" in "".join(result["errors"])


def test_non_python_llm_text_is_detected():
    assert _looks_like_non_python("这是一个文档归纳助手。它会读取文档并输出 Markdown。")
    assert not _looks_like_non_python("import os\nprint('ok')\n")


def test_run_script_job_reports_non_python_llm_output_before_static_check(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    async def fake_chat_dispatch(*args, **kwargs):
        return {"ok": True, "content": "这是一个文档归纳助手。它会读取文档并输出 Markdown。"}

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "chat_dispatch", fake_chat_dispatch)

    result = asyncio.run(
        run_script_job(
            db=object(),
            user_id=1,
            session_id="test-session",
            brief="文档归纳",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    joined = "；".join(result["errors"])
    assert result["ok"] is False
    assert "模型未按要求返回 Python 代码" in joined
    assert "invalid character" not in joined


def test_run_script_job_repairs_static_syntax_error_once(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    calls = []

    async def fake_chat_dispatch(*args, **kwargs):
        calls.append(kwargs["messages"][-1]["content"])
        if len(calls) == 1:
            return {
                "ok": True,
                "content": "```python\nfrom pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\ntext = '''broken\nPath('outputs/r.txt').write_text(text)\n```",
            }
        return {
            "ok": True,
            "content": "```python\nfrom pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\nPath('outputs/r.txt').write_text('ok', encoding='utf-8')\nprint('ok')\n```",
        }

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "chat_dispatch", fake_chat_dispatch)

    result = asyncio.run(
        run_script_job(
            db=object(),
            user_id=1,
            session_id="repair-session",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert len(calls) == 2
    assert result["repair_trace"]
    assert any(x.get("phase") == "repair" and x.get("ok") for x in result["repair_trace"])
    assert any(x.get("phase") == "run" and x.get("ok") for x in result["repair_trace"])


def test_run_script_job_repairs_static_syntax_error_multiple_rounds(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    calls = []

    async def fake_chat_dispatch(*args, **kwargs):
        calls.append(kwargs["messages"][-1]["content"])
        if len(calls) < 3:
            return {
                "ok": True,
                "content": "```python\nfrom pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\ntext = '''still broken\nPath('outputs/r.txt').write_text(text)\n```",
            }
        return {
            "ok": True,
            "content": "```python\nfrom pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\nPath('outputs/r.txt').write_text('ok', encoding='utf-8')\nprint('ok')\n```",
        }

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "chat_dispatch", fake_chat_dispatch)

    result = asyncio.run(
        run_script_job(
            db=object(),
            user_id=1,
            session_id="multi-repair-session",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert len(calls) == 3
    repairs = [x for x in result["repair_trace"] if x.get("phase") == "repair"]
    assert [x.get("iteration") for x in repairs] == [1, 2]


def test_run_script_job_repairs_runtime_failure(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    calls = []

    async def fake_chat_dispatch(*args, **kwargs):
        calls.append(kwargs["messages"][-1]["content"])
        if len(calls) == 1:
            return {
                "ok": True,
                "content": "```python\nraise RuntimeError('boom')\n```",
            }
        return {
            "ok": True,
            "content": "```python\nfrom pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\nPath('outputs/r.txt').write_text('ok', encoding='utf-8')\nprint('ok')\n```",
        }

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "chat_dispatch", fake_chat_dispatch)

    result = asyncio.run(
        run_script_job(
            db=object(),
            user_id=1,
            session_id="runtime-repair-session",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert len(calls) == 2
    assert any(
        x.get("phase") == "repair" and x.get("reason") == "run_or_acceptance"
        for x in result["repair_trace"]
    )


def test_run_script_job_repairs_no_outputs(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    calls = []

    async def fake_chat_dispatch(*args, **kwargs):
        calls.append(kwargs["messages"][-1]["content"])
        if len(calls) == 1:
            return {
                "ok": True,
                "content": "```python\nprint('ok but no file')\n```",
            }
        return {
            "ok": True,
            "content": "```python\nfrom pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\nPath('outputs/r.txt').write_text('ok', encoding='utf-8')\nprint('ok')\n```",
        }

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "chat_dispatch", fake_chat_dispatch)

    result = asyncio.run(
        run_script_job(
            db=object(),
            user_id=1,
            session_id="no-output-repair-session",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert len(calls) == 1
    assert any(o["filename"] == "summary.md" for o in result["outputs"])
    assert "_modstore_artifact_guard" in result["script"]


def test_run_script_job_wraps_helper_only_script_with_outputs_guard(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    calls = []

    async def fake_chat_dispatch(*args, **kwargs):
        calls.append(kwargs["messages"][-1]["content"])
        return {
            "ok": True,
            "content": ("```python\n" "def parse_url_list(file_path):\n" "    return []\n" "```"),
        }

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "chat_dispatch", fake_chat_dispatch)

    result = asyncio.run(
        run_script_job(
            db=object(),
            user_id=1,
            session_id="helper-only-session",
            brief="SEO 静态文件维护：生成自检清单",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert result["outputs"]
    assert any(o["filename"] == "summary.md" for o in result["outputs"])
    assert "_modstore_artifact_guard" in result["script"]
    assert len(calls) == 1


def test_run_script_agent_job_adapts_agent_loop_success(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    async def fake_loop(*args, **kwargs):
        from modstore_server.script_agent.brief import AgentEvent

        yield AgentEvent("context", 0, {"brief_md": "b", "inputs_summary": "(无)"})
        yield AgentEvent("plan", 0, {"plan_md": "plan"})
        yield AgentEvent("code", 0, {"code": "print('x')"})
        yield AgentEvent("check", 0, {"ok": True, "errors": []})
        yield AgentEvent("run", 0, {"ok": True, "outputs": [{"filename": "r.txt"}]})
        yield AgentEvent("observe", 0, {"ok": True, "reason": "ok", "suggestions": []})
        yield AgentEvent(
            "done",
            0,
            {
                "code": "print('x')",
                "outputs": [{"filename": "r.txt"}],
                "outcome": {
                    "ok": True,
                    "iterations": 1,
                    "final_code": "print('x')",
                    "last_result": {
                        "ok": True,
                        "returncode": 0,
                        "stdout_tail": "ok",
                        "stderr_tail": "",
                        "outputs": [{"filename": "r.txt"}],
                        "errors": [],
                        "sdk_calls": [],
                        "work_dir": str(tmp_path),
                    },
                    "trace": [],
                },
            },
        )

    messages = []
    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "run_agent_loop", fake_loop)

    async def hook(msg):
        messages.append(msg)

    result = asyncio.run(
        run_script_agent_job(
            db=object(),
            user_id=1,
            session_id="agent-success",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
            status_hook=hook,
        )
    )

    assert result["ok"] is True
    assert result["script"] == "print('x')"
    assert result["outputs"] == [{"filename": "r.txt"}]
    assert result["repair_trace"]
    assert any("生成脚本计划" in m for m in messages)


def test_run_script_agent_job_salvages_timeout_with_summary(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    async def fake_loop(*args, **kwargs):
        from modstore_server.script_agent.brief import AgentEvent

        yield AgentEvent("context", 0, {"brief_md": "b"})
        yield AgentEvent(
            "error",
            0,
            {
                "reason": "脚本运行超时",
                "outcome": {
                    "ok": False,
                    "iterations": 1,
                    "final_code": "while True:\n    pass",
                    "error": "脚本运行超时",
                    "last_result": {
                        "ok": False,
                        "returncode": -1,
                        "stdout_tail": "",
                        "stderr_tail": "",
                        "outputs": [],
                        "errors": ["脚本运行超时（>45s）"],
                        "timed_out": True,
                        "sdk_calls": [],
                        "work_dir": str(tmp_path),
                    },
                    "trace": [],
                },
            },
        )

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "run_agent_loop", fake_loop)

    result = asyncio.run(
        run_script_agent_job(
            db=object(),
            user_id=1,
            session_id="agent-timeout",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["outputs"]
    assert (tmp_path / "outputs" / "summary.md").exists()


def test_run_script_agent_job_default_iterations_is_strong_agent():
    from modstore_server.workbench_script_runner import (
        DEFAULT_SCRIPT_AGENT_ITERATIONS,
        MAX_SCRIPT_AGENT_ITERATIONS,
    )

    assert DEFAULT_SCRIPT_AGENT_ITERATIONS >= 20
    assert MAX_SCRIPT_AGENT_ITERATIONS >= DEFAULT_SCRIPT_AGENT_ITERATIONS


def test_run_script_agent_job_failure_message_includes_verdict_and_stderr(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    async def fake_loop(*args, **kwargs):
        from modstore_server.script_agent.brief import AgentEvent

        yield AgentEvent("context", 0, {"brief_md": "b"})
        yield AgentEvent(
            "observe",
            1,
            {
                "ok": False,
                "reason": "outputs 缺少 summary.md",
                "suggestions": ["写入 outputs/summary.md", "处理空 inputs/"],
            },
        )
        yield AgentEvent(
            "error",
            5,
            {
                "reason": "已达最大迭代轮数仍未通过验收",
                "outcome": {
                    "ok": False,
                    "iterations": 6,
                    "final_code": "print('x')",
                    "error": "已达最大迭代轮数仍未通过验收",
                    "last_result": {
                        "ok": True,
                        "returncode": 0,
                        "stdout_tail": "ok",
                        "stderr_tail": "Traceback boom",
                        "outputs": [],
                        "errors": [],
                        "sdk_calls": [],
                        "work_dir": str(tmp_path),
                    },
                    "trace": [],
                },
            },
        )

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "run_agent_loop", fake_loop)

    result = asyncio.run(
        run_script_agent_job(
            db=object(),
            user_id=1,
            session_id="agent-rich-failure",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["outputs"]
    assert any(o["filename"] == "summary.md" for o in result["outputs"])


def test_run_script_agent_job_adapts_agent_loop_failure(tmp_path, monkeypatch):
    import modstore_server.workbench_script_runner as runner

    async def fake_loop(*args, **kwargs):
        from modstore_server.script_agent.brief import AgentEvent

        yield AgentEvent("context", 0, {"brief_md": "b"})
        yield AgentEvent(
            "error",
            2,
            {
                "reason": "已达最大迭代轮数仍未通过验收",
                "outcome": {
                    "ok": False,
                    "iterations": 3,
                    "final_code": "print('bad')",
                    "error": "已达最大迭代轮数仍未通过验收",
                    "last_result": {
                        "ok": False,
                        "returncode": 1,
                        "stdout_tail": "",
                        "stderr_tail": "boom",
                        "outputs": [],
                        "errors": ["boom"],
                        "sdk_calls": [],
                        "work_dir": str(tmp_path),
                    },
                    "trace": [],
                },
            },
        )

    monkeypatch.setattr(runner, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "resolve_api_key", lambda *args, **kwargs: ("key", "test"))
    monkeypatch.setattr(
        runner, "resolve_base_url", lambda *args, **kwargs: "https://example.test/v1"
    )
    monkeypatch.setattr(runner, "run_agent_loop", fake_loop)

    result = asyncio.run(
        run_script_agent_job(
            db=object(),
            user_id=1,
            session_id="agent-failure",
            brief="生成摘要文件",
            files=[],
            provider="deepseek",
            model="deepseek-chat",
        )
    )

    assert result["ok"] is False
    assert "脚本代理运行 3 轮仍未通过" in "；".join(result["errors"])
    assert result["script"] == "print('bad')"


def _xlsx_bytes() -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["姓名", "工资"])
    ws.append(["张三", 100])
    raw = io.BytesIO()
    wb.save(raw)
    return raw.getvalue()
