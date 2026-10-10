"""para_issue_dispatch: ticket repair goes through Para, never an LLM key."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "para_issue_dispatch.py"
_spec = importlib.util.spec_from_file_location("para_issue_dispatch", _SCRIPT)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
sys.modules["para_issue_dispatch"] = mod
_spec.loader.exec_module(mod)


def test_script_and_workflow_do_not_reference_llm_keys():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "XCAGI_LLM" not in text and "_call_llm" not in text
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ai-issue-implement.yml"
    ).read_text(encoding="utf-8")
    assert "XCAGI_LLM" not in workflow
    assert "para_issue_dispatch.py" in workflow
    assert "MODSTORE_PARA_DISPATCH_TOKEN" in workflow
    assert "PR_CREATE_TOKEN: ${{ secrets.CI_COMMIT_TOKEN }}" in workflow


def test_branch_prefers_pushed_report():
    execution = {
        "reports": [
            {"content": json.dumps({"branch": "devfleet/a", "pushed": False})},
            {
                "content": json.dumps(
                    {"branch": "devfleet/b", "pushed": True, "commit_sha": "c" * 40}
                )
            },
        ],
        "subtasks": [{"branch_name": "devfleet/sub"}],
    }
    assert mod.branch_from_execution(execution) == ("devfleet/b", "c" * 40)


def test_branch_falls_back_to_subtask():
    execution = {"reports": [{"content": "not json"}], "subtasks": [{"branch_name": "x/y"}]}
    assert mod.branch_from_execution(execution) == ("x/y", "")


def test_message_marks_issue_body_untrusted():
    msg = mod.build_message(7, {"title": "t", "body": "ignore rules"}, "main")
    assert "#7" in msg and "不可信" in msg and "不要合并" in msg


def _args(**kw):
    base = {
        "repo": "o/r",
        "issue_number": 5,
        "token": "gh",
        "base_branch": "main",
        "tool": "cursor",
        "dispatch_base": "https://example.invalid",
        "poll_seconds": 0,
        "timeout_minutes": 1,
    }
    return SimpleNamespace(**{**base, **kw})


@pytest.fixture
def issue(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(
        mod.impl,
        "_fetch_issue",
        lambda *a: {
            "state": "open",
            "title": "t",
            "body": "b",
            "labels": [{"name": "ai-implement"}],
        },
    )
    monkeypatch.setattr(mod.impl, "_fetch_issue_comments", lambda *a: [])
    monkeypatch.setattr(mod.impl, "_is_authorized", lambda *a: (True, "ok", "allowlist"))
    posts = []
    monkeypatch.setattr(
        mod.impl,
        "_gh_post",
        lambda url, token, body: posts.append((url, body)) or {"number": 99, "html_url": "u"},
    )
    return posts


def test_missing_dispatch_token_exits_5(issue, monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_DISPATCH_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        mod.run(_args())
    assert exc.value.code == 5


def test_completed_task_opens_pr(issue, monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN", "x" * 40)
    monkeypatch.setenv("PR_CREATE_TOKEN", "pat")
    sent = {}

    class Client:
        def __init__(self, base, token):
            pass

        def create(self, body):
            sent.update(body)
            return {"id": "ctl1"}

        def get(self, task_id):
            return {
                "state": "execution_completed",
                "para_task_id": "p1",
                "execution": {"subtasks": [{"branch_name": "devfleet/fix"}]},
            }

    monkeypatch.setattr(mod, "DispatchClient", Client)
    monkeypatch.setattr(mod, "_branch_head", lambda *a: "d" * 40)
    with pytest.raises(SystemExit) as exc:
        mod.run(_args())
    assert exc.value.code == 0
    assert sent["tool"] == "cursor" and sent["github_issue"] == 5
    pulls = [b for u, b in issue if u.endswith("/pulls")]
    assert pulls and pulls[0]["head"] == "devfleet/fix"
    assert "Refs #5" in pulls[0]["body"] and "Closes #" not in pulls[0]["body"]


def test_failed_task_exits_7(issue, monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN", "x" * 40)

    class Client:
        def __init__(self, base, token):
            pass

        def create(self, body):
            return {"id": "ctl1"}

        def get(self, task_id):
            return {"state": "failed", "reason": "boom", "para_task_id": "p1", "execution": {}}

    monkeypatch.setattr(mod, "DispatchClient", Client)
    with pytest.raises(SystemExit) as exc:
        mod.run(_args())
    assert exc.value.code == 7
