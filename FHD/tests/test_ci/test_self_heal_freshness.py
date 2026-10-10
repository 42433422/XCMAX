"""Self-Heal 过期失败过滤验收：判定规则 + main 集成（无网络，注入只读 GitHub 查询）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

CI_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import ai_self_heal as heal  # noqa: E402
import self_heal_freshness as fr  # noqa: E402

REPO = "o/r"
OLD, NEW = "a" * 40, "b" * 40
WF = "CI - Backend Python"


class FakeGitHub:
    """按 path 返回预置响应；记录调用。value 为 Exception 时抛出（模拟网络故障）。"""

    def __init__(
        self,
        *,
        run: dict[str, Any] | None = None,
        pr_head: str = NEW,
        pr_state: str = "open",
        branch_head: str | None = NEW,
        successes: list[dict[str, Any]] | None = None,
        issues: list[dict[str, Any]] | None = None,
        fail: str = "",
    ) -> None:
        self.run = {
            "id": 7,
            "name": WF,
            "workflow_id": 99,
            "head_sha": OLD,
            "head_branch": "feat/x",
            "event": "pull_request",
            "run_attempt": 1,
            "conclusion": "failure",
            "created_at": "2026-10-10T10:00:00Z",
            "pull_requests": [{"number": 5}],
            **(run or {}),
        }
        self.pr_head, self.pr_state, self.branch_head = pr_head, pr_state, branch_head
        self.successes, self.issues, self.fail = successes or [], issues or [], fail
        self.calls: list[str] = []

    def __call__(self, path: str, params: dict[str, Any]) -> tuple[int, Any]:
        self.calls.append(path)
        if self.fail and self.fail in path:
            raise fr.LookupFailed(f"simulated outage on {path}")
        if path == f"/repos/{REPO}/actions/runs/7":
            return 200, self.run
        if path.endswith("/runs"):
            return 200, {"workflow_runs": self.successes}
        if path == f"/repos/{REPO}/pulls/5":
            return 200, {"state": self.pr_state, "head": {"sha": self.pr_head}}
        if "/branches/" in path:
            return (
                (404, None)
                if self.branch_head is None
                else (200, {"commit": {"sha": self.branch_head}})
            )
        if path == f"/repos/{REPO}/issues":
            return 200, self.issues
        return 500, None


def _event(**over: Any) -> dict[str, Any]:
    return {
        "id": 7,
        "name": WF,
        "event": "pull_request",
        "head_sha": OLD,
        "run_attempt": 1,
        "head_branch": "feat/x",
        "conclusion": "failure",
        **over,
    }


def _eval(gh: FakeGitHub, workflow: str = WF, event: dict[str, Any] | None = None) -> fr.Decision:
    return fr.evaluate(
        workflow=workflow,
        run_id=7,
        repo=REPO,
        get=gh,
        event_run=_event() if event is None else event,
    )


# 1. 旧提交失败被跳过
def test_stale_pr_head_is_skipped_with_trail(tmp_path: Path) -> None:
    d = _eval(FakeGitHub(pr_head=NEW))
    assert (d.action, d.reason) == (fr.SKIP, "stale_head")
    assert (d.run_id, d.run_attempt, d.source_sha, d.current_sha) == (7, 1, OLD, NEW)
    summary = tmp_path / "summary.md"
    fr.record(d, summary_path=str(summary))
    text = summary.read_text(encoding="utf-8")
    assert all(s in text for s in ("stale_head", "`7`", OLD, NEW))


def test_stale_push_branch_head_is_skipped() -> None:
    gh = FakeGitHub(run={"event": "push", "pull_requests": []}, branch_head=NEW)
    d = _eval(gh, event=_event(event="push"))
    assert (d.action, d.reason) == (fr.SKIP, "stale_head")
    assert any("/branches/feat%2Fx" in c for c in gh.calls)


def test_closed_pr_and_deleted_branch_are_skipped() -> None:
    assert _eval(FakeGitHub(pr_head=OLD, pr_state="closed")).reason == "pr_closed"
    gh = FakeGitHub(run={"event": "push", "pull_requests": []}, branch_head=None)
    assert _eval(gh, event=_event(event="push")).reason == "branch_deleted"


# 2. 最新提交失败正常处理
def test_current_head_failure_proceeds() -> None:
    d = _eval(FakeGitHub(pr_head=OLD))
    assert (d.action, d.reason, d.current_sha) == (fr.PROCEED, "current_head", OLD)


# 3. 同一提交重跑成功后不再派单
def test_rerun_attempt_supersedes_failure() -> None:
    d = _eval(FakeGitHub(pr_head=OLD, run={"run_attempt": 2, "conclusion": "success"}))
    assert d.action == fr.SKIP and d.reason == "superseded_by_attempt_2:success"


def test_later_success_on_same_sha_skips() -> None:
    later = {"id": 8, "created_at": "2026-10-10T11:00:00Z"}
    earlier = {"id": 6, "created_at": "2026-10-10T09:00:00Z"}
    assert _eval(FakeGitHub(pr_head=OLD, successes=[earlier])).action == fr.PROCEED
    d = _eval(FakeGitHub(pr_head=OLD, successes=[earlier, later]))
    assert (d.action, d.reason) == (fr.SKIP, "same_sha_succeeded_in_run_8")


# 4. 重复事件只产生一个任务（标记查重）
def test_markers_find_existing_issue() -> None:
    d = _eval(FakeGitHub(pr_head=OLD))
    marks = fr.source_markers(d)
    assert marks == ["Self-Heal-Run: `7/1`", f"Self-Heal-Source: `{WF}@{OLD}`"]
    hit = {"html_url": "https://x/issues/1", "body": f"- {marks[1]}\n"}
    assert (
        fr.find_marked_issue(FakeGitHub(issues=[{"body": "other"}, hit]), REPO, marks)
        == "https://x/issues/1"
    )
    assert fr.find_marked_issue(FakeGitHub(issues=[]), REPO, marks) == ""
    assert fr.source_markers(d, include_source=False) == ["Self-Heal-Run: `7/1`"]


# 6. API 查询失败不误派单（fail-closed）
@pytest.mark.parametrize("fail", ["/actions/runs/7", "/runs", "/pulls/5"])
def test_lookup_failure_blocks(fail: str) -> None:
    d = _eval(FakeGitHub(pr_head=OLD, fail=fail))
    assert d.action == fr.BLOCK and d.reason.startswith("lookup_failed")


def test_event_api_mismatch_and_incomplete_run_block() -> None:
    assert (
        _eval(FakeGitHub(run={"head_sha": NEW})).reason == "source_mismatch_between_event_and_api"
    )
    assert _eval(FakeGitHub(run={"workflow_id": None})).action == fr.BLOCK
    with pytest.raises(fr.LookupFailed):
        fr.find_marked_issue(FakeGitHub(fail="/issues"), REPO, ["m"])


# 7. 部署 / 巡检 / 指定版本不被过滤
@pytest.mark.parametrize(
    ("workflow", "event"),
    [
        ("Deploy MODstore Production", "push"),
        ("fhd-deploy", "workflow_dispatch"),
        ("cvm-autonomy-watcher", "schedule"),
        ("Release gate CI", "push"),
        ("CI/CD Pipeline", "push"),
        ("CI/CD Pipeline", "workflow_dispatch"),
        ("CI/CD Pipeline", "schedule"),
    ],
)
def test_deploy_and_patrol_not_filtered(workflow: str, event: str) -> None:
    gh = FakeGitHub(pr_head=NEW, fail="/")  # 任何查询都会失败，证明根本不查
    d = _eval(gh, workflow=workflow, event=_event(name=workflow, event=event))
    assert d.action == fr.PROCEED and gh.calls == []


def test_ci_cd_pipeline_pr_is_filtered() -> None:
    d = _eval(
        FakeGitHub(run={"name": "CI/CD Pipeline"}, pr_head=NEW),
        workflow="CI/CD Pipeline",
        event=_event(name="CI/CD Pipeline"),
    )
    assert d.reason == "stale_head"


def test_event_payload_reader(tmp_path: Path) -> None:
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"workflow_run": _event()}), encoding="utf-8")
    assert fr.event_workflow_run(str(p))["head_sha"] == OLD
    assert fr.event_workflow_run(str(tmp_path / "missing.json")) == {}


# ---- main 集成：跳过/拦截发生在下载日志、LLM、建单、派单之前 ----
@pytest.fixture
def main_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, list[Any]]:
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"workflow_run": _event()}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    calls: dict[str, list[Any]] = {"logs": [], "llm": [], "issue": [], "dispatch": []}
    monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: calls["logs"].append(1) or "x")
    monkeypatch.setattr(heal, "call_llm", lambda *a, **k: calls["llm"].append(1))
    monkeypatch.setattr(
        heal, "check_incident_budget", lambda *a, **k: heal.IncidentBudgetDecision(True, "ok")
    )
    monkeypatch.setattr(heal, "find_existing_remediation_issue", lambda *a, **k: "")
    monkeypatch.setattr(
        heal,
        "create_remediation_issue",
        lambda **k: calls["issue"].append(k) or "https://x/issues/9",
    )
    monkeypatch.setattr(
        heal, "dispatch_issue_implementation", lambda *a, **k: calls["dispatch"].append(1) or True
    )
    calls["store"] = [str(tmp_path / "fps.jsonl")]
    return calls


def _run_main(calls: dict[str, list[Any]], workflow: str = WF) -> int:
    return heal.main(["--workflow", workflow, "--branch", "feat/x", "--store", calls["store"][0]])


def _use(monkeypatch: pytest.MonkeyPatch, *ghs: FakeGitHub) -> None:
    queue = list(ghs)
    monkeypatch.setattr(
        heal, "_github_getter", lambda *a: queue.pop(0) if len(queue) > 1 else queue[0]
    )


def test_main_stale_skips_everything(monkeypatch: pytest.MonkeyPatch, main_env: dict) -> None:
    _use(monkeypatch, FakeGitHub(pr_head=NEW))
    assert _run_main(main_env) == 0
    assert main_env["logs"] == main_env["llm"] == main_env["issue"] == main_env["dispatch"] == []


def test_main_current_failure_creates_marked_issue(
    monkeypatch: pytest.MonkeyPatch, main_env: dict
) -> None:
    _use(monkeypatch, FakeGitHub(pr_head=OLD))
    assert _run_main(main_env) == 2  # 原失败保持失败，incident 已创建并派单
    assert len(main_env["issue"]) == 1 and main_env["dispatch"] == [1]
    assert f"Self-Heal-Source: `{WF}@{OLD}`" in main_env["issue"][0]["markers"]


def test_main_duplicate_event_creates_no_second_task(
    monkeypatch: pytest.MonkeyPatch, main_env: dict
) -> None:
    dup = {"html_url": "https://x/issues/1", "body": "- Self-Heal-Run: `7/1`\n"}
    _use(monkeypatch, FakeGitHub(pr_head=OLD, issues=[dup]))
    assert _run_main(main_env) == 0
    assert main_env["issue"] == [] and main_env["dispatch"] == [] and main_env["llm"] == []


# 5. 排队/处理期间提交更新能被拦住
def test_main_head_moves_before_dispatch(monkeypatch: pytest.MonkeyPatch, main_env: dict) -> None:
    _use(monkeypatch, FakeGitHub(pr_head=OLD), FakeGitHub(pr_head=OLD), FakeGitHub(pr_head=NEW))
    assert _run_main(main_env) == 0
    assert main_env["issue"] == [] and main_env["dispatch"] == []


def test_main_lookup_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch, main_env: dict, tmp_path: Path
) -> None:
    _use(monkeypatch, FakeGitHub(fail="/actions/runs/7"))
    assert _run_main(main_env) == 2
    assert main_env["logs"] == main_env["issue"] == main_env["dispatch"] == []
    assert "block" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_main_marker_lookup_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch, main_env: dict
) -> None:
    _use(monkeypatch, FakeGitHub(pr_head=OLD), FakeGitHub(pr_head=OLD, fail="/issues"))
    assert _run_main(main_env) == 2
    assert main_env["issue"] == [] and main_env["dispatch"] == []


def test_main_deploy_failure_keeps_existing_flow(
    monkeypatch: pytest.MonkeyPatch, main_env: dict, tmp_path: Path
) -> None:
    ev = tmp_path / "event.json"
    ev.write_text(
        json.dumps({"workflow_run": _event(name="fhd-deploy", event="push")}), encoding="utf-8"
    )
    _use(monkeypatch, FakeGitHub(pr_head=NEW, issues=[]))  # head 已变也不过滤
    assert _run_main(main_env, workflow="fhd-deploy") == 2
    assert len(main_env["issue"]) == 1 and main_env["dispatch"] == [1]
    assert main_env["issue"][0]["markers"] == ["Self-Heal-Run: `7/1`"]


def test_main_uses_trigger_run_sha_not_github_sha(
    monkeypatch: pytest.MonkeyPatch, main_env: dict, tmp_path: Path
) -> None:
    """github.sha 在 workflow_run 下指向默认分支，判定必须用触发运行的 head_sha / run_attempt。"""
    monkeypatch.setenv("GITHUB_SHA", NEW)  # 自愈 workflow 自身的 sha = 默认分支 head
    gh = FakeGitHub(pr_head=NEW)  # PR 当前 head 恰好也等于 github.sha
    _use(monkeypatch, gh)
    assert _run_main(main_env) == 0  # 若误用 github.sha 会判为 current_head 并派单
    assert main_env["issue"] == [] and main_env["dispatch"] == []
    assert f"/repos/{REPO}/actions/runs/7" in gh.calls
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert all(s in text for s in ("stale_head", "run `7`", "attempt `1`", OLD, NEW))
