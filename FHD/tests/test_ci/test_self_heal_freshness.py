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

import ai_self_heal as heal
import self_heal_freshness as fr

REPO = "o/r"
OLD, NEW = "a" * 40, "b" * 40
WF = "CI - Backend Python"
WF_PATH = ".github/workflows/modstore-ci-backend-python.yml"
CI_PATH = ".github/workflows/fhd-ci-cd.yml"


def _scan_pr(*, labels: list[str] | None = None, run_sha: str = OLD) -> tuple[dict, dict]:
    pr = {
        "number": 5,
        "state": "open",
        "draft": False,
        "user": {"login": "42433422"},
        "labels": [{"name": name} for name in (labels or [])],
        "head": {"ref": "feat/x", "sha": OLD, "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO}},
    }
    run = {
        "id": 7,
        "name": WF,
        "workflow_id": 99,
        "path": WF_PATH,
        "head_sha": run_sha,
        "head_branch": "feat/x",
        "event": "pull_request",
        "run_attempt": 1,
        "conclusion": "failure",
        "status": "completed",
        "created_at": "2026-10-10T10:00:00Z",
        "pull_requests": [{"number": 5}],
    }
    return pr, run


@pytest.mark.parametrize(
    ("labels", "run_sha", "expected"),
    [([], OLD, [7]), (["hold-merge"], OLD, []), ([], NEW, [])],
)
def test_scheduled_pr_scan_only_dispatches_authorized_exact_head_failures(
    monkeypatch, capsys, labels: list[str], run_sha: str, expected: list[int]
) -> None:
    pr, run = _scan_pr(labels=labels, run_sha=run_sha)
    calls: list[str] = []

    def get(path: str, params: dict) -> tuple[int, object]:
        if path.endswith("/pulls"):
            return 200, [pr]
        if path.endswith("/actions/runs"):
            return 200, {"workflow_runs": [run]}
        if path.endswith("/pulls/5"):
            return 200, pr
        raise AssertionError(f"unexpected GitHub read: {path}")

    monkeypatch.setattr(heal, "_github_getter", lambda token, repo: get)
    monkeypatch.setattr(
        heal,
        "check_freshness",
        lambda workflow, run_id, token, repo: (
            calls.append(str(run_id))
            or fr.Decision(fr.SKIP, "already_dispositioned", run_id=run_id)
        ),
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert heal.scan_open_prs("token", REPO) == 0
    assert calls == [str(item) for item in expected]
    assert f"eligible exact-HEAD PR failures={len(expected)}" in capsys.readouterr().out


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
            "path": WF_PATH,
            "head_sha": OLD,
            "head_branch": "feat/x",
            "event": "pull_request",
            "run_attempt": 1,
            "conclusion": "failure",
            "status": "completed",
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
        for issue in self.issues:
            if path == f"/repos/{REPO}/issues/{issue.get('number')}":
                return 200, issue
        return 500, None


def _event(**over: Any) -> dict[str, Any]:
    return {
        "id": 7,
        "name": WF,
        "path": WF_PATH,
        "workflow_id": 99,
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
    fields = {
        "head_sha": OLD,
        "workflow_id": 99,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
    }
    later = {**fields, "id": 8, "created_at": "2026-10-10T11:00:00Z"}
    earlier = {**fields, "id": 6, "created_at": "2026-10-10T09:00:00Z"}
    assert _eval(FakeGitHub(pr_head=OLD, successes=[earlier])).action == fr.PROCEED
    d = _eval(FakeGitHub(pr_head=OLD, successes=[earlier, later]))
    assert (d.action, d.reason) == (fr.SKIP, "same_sha_succeeded_in_run_8")


# 4. 重复事件只产生一个任务（标记查重）
def test_markers_find_existing_issue() -> None:
    d = _eval(FakeGitHub(pr_head=OLD))
    marks = fr.source_markers(d)
    assert marks == [
        "Self-Heal-Run: `7/1`",
        f"Self-Heal-Workflow: `99@{WF_PATH}`",
        f"Self-Heal-Source: `{WF_PATH}@{OLD}`",
    ]
    hit = {"state": "open", "html_url": "https://x/issues/1", "body": f"- {marks[2]}\n"}
    assert (
        fr.find_marked_issue(FakeGitHub(issues=[{"body": "other"}, hit]), REPO, marks)
        == "https://x/issues/1"
    )
    assert fr.find_marked_issue(FakeGitHub(issues=[]), REPO, marks) == ""
    assert fr.source_markers(d, include_source=False) == marks[:2]


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
    path = CI_PATH if workflow == "CI/CD Pipeline" else ".github/workflows/deploy.yml"
    gh = FakeGitHub(pr_head=NEW, run={"name": workflow, "event": event, "path": path})
    d = _eval(gh, workflow=workflow, event=_event(name=workflow, event=event, path=path))
    assert d.action == fr.PROCEED and gh.calls == [f"/repos/{REPO}/actions/runs/7"]
    assert d.disposition == "unfiltered"


def test_ci_cd_pipeline_pr_is_filtered() -> None:
    d = _eval(
        FakeGitHub(run={"name": "CI/CD Pipeline", "path": CI_PATH}, pr_head=NEW),
        workflow="CI/CD Pipeline",
        event=_event(name="CI/CD Pipeline", path=CI_PATH),
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
        heal,
        "check_incident_budget",
        lambda *a, **k: heal.IncidentBudgetDecision(True, "ok"),
    )
    monkeypatch.setattr(heal, "find_existing_remediation_issue", lambda *a, **k: "")
    monkeypatch.setattr(
        heal,
        "create_remediation_issue",
        lambda **k: calls["issue"].append(k) or f"https://github.com/{REPO}/issues/9",
    )
    monkeypatch.setattr(
        heal,
        "dispatch_issue_implementation",
        lambda *a, **k: calls["dispatch"].append(1) or True,
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
    assert f"Self-Heal-Source: `{WF_PATH}@{OLD}`" in main_env["issue"][0]["markers"]


def test_main_duplicate_event_creates_no_second_task(
    monkeypatch: pytest.MonkeyPatch, main_env: dict
) -> None:
    dup = {
        "state": "open",
        "number": 1,
        "html_url": f"https://github.com/{REPO}/issues/1",
        "body": "- Self-Heal-Run: `7/1`\n",
    }
    _use(monkeypatch, FakeGitHub(pr_head=OLD, issues=[dup]))
    assert _run_main(main_env) == 2  # Existing, but no trusted execution receipt: unresolved.
    assert main_env["issue"] == [] and main_env["dispatch"] == [] and main_env["llm"] == []


# 5. 排队/处理期间提交更新能被拦住
def test_main_head_moves_before_dispatch(monkeypatch: pytest.MonkeyPatch, main_env: dict) -> None:
    _use(
        monkeypatch,
        FakeGitHub(pr_head=OLD),
        FakeGitHub(pr_head=OLD),
        FakeGitHub(pr_head=NEW),
    )
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
        json.dumps(
            {
                "workflow_run": _event(
                    name="fhd-deploy",
                    event="push",
                    path=".github/workflows/fhd-deploy.yml",
                )
            }
        ),
        encoding="utf-8",
    )
    _use(
        monkeypatch,
        FakeGitHub(
            pr_head=NEW,
            issues=[],
            run={
                "name": "fhd-deploy",
                "event": "push",
                "path": ".github/workflows/fhd-deploy.yml",
            },
        ),
    )
    assert _run_main(main_env, workflow="fhd-deploy") == 2
    assert len(main_env["issue"]) == 1 and main_env["dispatch"] == [1]
    assert main_env["issue"][0]["markers"] == [
        "Self-Heal-Run: `7/1`",
        "Self-Heal-Workflow: `99@.github/workflows/fhd-deploy.yml`",
    ]


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


@pytest.mark.parametrize(("name", "path"), [(f"CI/CD {OLD}", CI_PATH), (f"{WF} {OLD}", WF_PATH)])
def test_dynamic_run_titles_use_verified_path(name: str, path: str) -> None:
    run = {"name": name, "path": path}
    decision = _eval(FakeGitHub(run=run), workflow=name, event=_event(**run))
    assert (decision.action, decision.disposition, decision.workflow_path) == (
        fr.SKIP,
        "superseded",
        path,
    )


@pytest.mark.parametrize(
    "over",
    [{"path": ""}, {"workflow_id": 0}, {"path": ".github/workflows/unrelated.yml"}],
)
def test_unverified_code_identity_is_unresolved(over: dict) -> None:
    decision = _eval(
        FakeGitHub(run={"name": f"CI/CD {OLD}", **over}),
        workflow=f"CI/CD {OLD}",
        event={},
    )
    assert decision.action == fr.BLOCK and decision.disposition == "unresolved"


def test_workflow_marker_alone_cannot_deduplicate_distinct_sources() -> None:
    marks = fr.source_markers(_eval(FakeGitHub(pr_head=OLD)))
    other = {"body": f"- {marks[1]}\n", "html_url": "https://x/issues/other"}
    assert fr.find_marked_issue(FakeGitHub(issues=[other]), REPO, marks) == ""


BOT = {"login": "github-actions[bot]", "type": "Bot"}


def _incident(**over: Any) -> dict:
    return {
        "number": 1,
        "state": "open",
        "user": BOT,
        "labels": [{"name": "auto-incident"}, {"name": "ai-implement"}],
        "html_url": f"https://github.com/{REPO}/issues/1",
        "body": f"- Workflow: `{WF}`\n- Run ID: `7`\n- Branch: `feat/x`\n- Head Repository: `{REPO}`\n- Self-Heal-Run: `7/1`\n",
        **over,
    }


def _para_receipt(task: str = "control-1", status: str = "timeout", **over: Any) -> dict:
    identity = {
        "repo": REPO,
        "issue_number": 1,
        "base_branch": "feat/x",
        "control_task_id": task,
    }
    return {
        "user": BOT,
        "body": heal.recovery.para.RECEIPT_MARKER
        + json.dumps(identity)
        + " -->\n"
        + f"处理结果：`{status}`。\n- 工作流：https://github.com/{REPO}/actions/runs/9",
        **over,
    }


def _dispatch_receipt(status: str, run: int = 0) -> dict:
    return {
        "user": BOT,
        "body": heal.recovery.receipt_body(
            {
                "repo": REPO,
                "issue_number": 1,
                "base_branch": "feat/x",
                "control_task_id": "",
                "status": status,
                "dispatch_run_id": run,
            }
        ),
    }


class RecoveryGitHub(FakeGitHub):
    def __init__(self, *, comments=None, implementation_run=None, **kw):
        super().__init__(
            pr_head=kw.pop("pr_head", OLD), issues=kw.pop("issues", [_incident()]), **kw
        )
        self.comments = comments or []
        self.implementation_run = {
            "id": 9,
            "workflow_id": 100,
            "path": heal.recovery.IMPLEMENT_PATH,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "failure",
            "run_attempt": 1,
            **(implementation_run or {}),
        }

    def __call__(self, path, params):
        if path == f"/repos/{REPO}/issues/1/comments":
            return 200, self.comments
        if path == f"/repos/{REPO}/actions/runs/9":
            return 200, self.implementation_run
        return super().__call__(path, params)


def _recover(gh: RecoveryGitHub, *, dry_run=False, rerun_status=201):
    writes, dispatches = [], []

    def write(method, path, body):
        writes.append((method, path, body))
        if path.endswith("/rerun-failed-jobs"):
            return rerun_status, {}
        return (201 if method == "POST" else 200), {"id": 900 + len(writes)}

    result = heal.recovery.reconcile_one(
        gh.issues[0],
        repo=REPO,
        get=gh,
        write=write,
        dry_run=dry_run,
        dispatch=lambda *a, **kw: dispatches.append((a, kw)) or True,
    )
    return result, writes, dispatches


def test_source_observes_and_serial_reconciler_resumes_despite_full_budget(
    monkeypatch, main_env
) -> None:
    gh = RecoveryGitHub(comments=[_para_receipt()])
    _use(monkeypatch, gh)
    budget_calls, dispatches = [], []
    monkeypatch.setattr(
        heal,
        "check_incident_budget",
        lambda *a, **k: (
            budget_calls.append(1)
            or heal.IncidentBudgetDecision(False, "global_open_incidents:20>=20", 20)
        ),
    )
    monkeypatch.setattr(
        heal,
        "dispatch_issue_implementation",
        lambda *a, **kw: dispatches.append(kw) or True,
    )
    monkeypatch.setattr(
        heal.recovery.para.DispatchClient,
        "create",
        lambda *a, **kw: pytest.fail("resume must never create a task"),
    )
    assert _run_main(main_env) == 2
    assert budget_calls == [] and main_env["issue"] == [] and main_env["logs"] == []
    assert dispatches == []
    output = Path(main_env["store"][0]).parent / "reconciliation.json"
    assert heal.reconcile_incidents("tok", REPO, dry_run=False, report_path=output) == 2
    assert len(dispatches) == 1 and dispatches[0]["control_task_id"] == "control-1"
    assert dispatches[0]["target_branch"] == "feat/x" and budget_calls == []


@pytest.mark.parametrize("status", ["unknown", "pending", "accepted_unknown_run"])
def test_unknown_dispatch_is_not_blindly_reissued(status) -> None:
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[_dispatch_receipt(status)]))
    assert result["state"] == "unresolved" and result["reason"] == f"dispatch_{status}"
    assert writes == dispatches == []


def test_failed_exact_run_reuses_original_request_key_by_rerunning_it() -> None:
    result, writes, dispatches = _recover(
        RecoveryGitHub(comments=[_dispatch_receipt("accepted", 9)])
    )
    assert result["state"] == "resumed" and result["reason"] == "rerun_original_run"
    assert len(writes) == 2 and '"operation": "rerun"' in writes[0][2]["body"]
    assert writes[-1] == ("POST", f"/repos/{REPO}/actions/runs/9/rerun-failed-jobs", {})
    assert dispatches == []


def test_rerun_pending_receipt_prevents_repost_until_attempt_advances(
    monkeypatch,
) -> None:
    initial = _dispatch_receipt("accepted", 9)
    _, writes, _ = _recover(RecoveryGitHub(comments=[initial]))
    pending = {"user": BOT, "body": writes[0][2]["body"]}
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[initial, pending]))
    assert result["reason"] == "rerun_pending_observation" and writes == dispatches == []
    now = heal.recovery.time.time()
    monkeypatch.setattr(
        heal.recovery.time,
        "time",
        lambda: now + heal.recovery.RECOVERY_VISIBILITY_SECONDS + 1,
    )
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[initial, pending]))
    assert result["state"] == "unresolved" and result["reason"] == "rerun_result_unconfirmed"
    assert writes == dispatches == []
    result, writes, dispatches = _recover(
        RecoveryGitHub(
            comments=[initial, pending],
            implementation_run={"run_attempt": 2, "status": "in_progress"},
        )
    )
    assert result["reason"] == "implementation_run_active" and writes == dispatches == []


@pytest.mark.parametrize(
    "status",
    ["rejected_too_large", "waiting_confirmation", "para_failed", "pr_created"],
)
def test_terminal_or_policy_receipt_never_starts_another_task(status) -> None:
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[_para_receipt(status=status)]))
    assert result["state"] == "unresolved" and result["reason"] == status
    assert writes == dispatches == []


def test_untrusted_or_foreign_task_receipts_cannot_resume() -> None:
    comment = _para_receipt(user={"login": "attacker", "type": "User"})
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[comment]))
    assert result["reason"] == "dispatch_receipt_missing" and writes == dispatches == []
    foreign = _para_receipt()
    foreign["body"] = foreign["body"].replace('"issue_number": 1', '"issue_number": 2')
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[foreign]))
    assert result["reason"] == "dispatch_receipt_missing" and writes == dispatches == []


@pytest.mark.parametrize(
    ("run", "reason"),
    [
        ({"status": "in_progress"}, "implementation_run_active"),
        ({"path": CI_PATH}, "implementation_run_identity_mismatch"),
        ({"run_attempt": 3}, "run_attempt_budget_exhausted"),
    ],
)
def test_exact_run_recovery_checks_identity_activity_and_retry_bound(run, reason) -> None:
    result, writes, dispatches = _recover(
        RecoveryGitHub(comments=[_dispatch_receipt("accepted", 9)], implementation_run=run)
    )
    assert result["reason"] == reason and writes == dispatches == []


@pytest.mark.parametrize(
    ("run", "head", "state", "close_reason"),
    [
        ({}, NEW, "superseded", "not_planned"),
        ({"conclusion": "success"}, OLD, "recovered", "completed"),
    ],
)
def test_verified_recovery_and_supersession_close_with_different_meaning(
    run, head, state, close_reason
) -> None:
    result, writes, dispatches = _recover(RecoveryGitHub(run=run, pr_head=head))
    assert result["state"] == state and dispatches == []
    assert writes[-1] == (
        "PATCH",
        f"/repos/{REPO}/issues/1",
        {"state": "closed", "state_reason": close_reason},
    )
    assert state in writes[0][2]["body"]


@pytest.mark.parametrize("missing", ["/actions/runs/7", "/pulls/5", "/runs"])
def test_missing_evidence_cannot_close_or_dispatch(missing) -> None:
    result, writes, dispatches = _recover(RecoveryGitHub(fail=missing))
    assert result["state"] == "unresolved" and writes == dispatches == []


def test_missing_run_status_and_deployment_head_drift_never_close() -> None:
    result, writes, dispatches = _recover(RecoveryGitHub(run={"status": None}, pr_head=NEW))
    assert result["state"] == "unresolved" and writes == dispatches == []
    issue = _incident()
    issue["body"] = issue["body"].replace(WF, "CI/CD Pipeline")
    result, writes, dispatches = _recover(
        RecoveryGitHub(
            run={"name": "CI/CD Pipeline", "path": CI_PATH, "event": "push"},
            pr_head=NEW,
            issues=[issue],
        )
    )
    assert result["state"] == "unresolved" and writes == dispatches == []


def test_dry_reconciliation_records_evidence_without_mutating(monkeypatch, tmp_path) -> None:
    _use(monkeypatch, RecoveryGitHub(pr_head=NEW))
    monkeypatch.setattr(
        heal,
        "_github_writer",
        lambda *a: lambda *x: pytest.fail("dry-run wrote to GitHub"),
    )
    monkeypatch.setattr(
        heal,
        "dispatch_issue_implementation",
        lambda *a, **kw: pytest.fail("dry-run dispatched"),
    )
    output = tmp_path / "report.json"
    assert heal.reconcile_incidents("tok", REPO, dry_run=True, report_path=output) == 0
    report = json.loads(output.read_text())
    assert report["dry_run"] and report["incidents"][0]["state"] == "superseded"


def test_pagination_limit_is_unresolved_not_evidence_of_absence() -> None:
    get = lambda *a: (200, [{"body": "unrelated"}] * 100)
    with pytest.raises(fr.LookupFailed, match="pagination limit"):
        fr.find_marked_issue(get, REPO, ["missing"])


def test_incident_log_cannot_override_source_metadata() -> None:
    issue = _incident()
    issue["body"] += "\n### 运行日志摘录\n```text\n- Run ID: `999`\n- Branch: `main`\n```"
    source = fr.reconcile_source(issue, REPO, RecoveryGitHub())
    assert source.action == fr.PROCEED and source.run_id == 7 and source.head_branch == "feat/x"


def test_definite_rerun_rejection_is_retryable_without_losing_task_identity() -> None:
    initial = _dispatch_receipt("accepted", 9)
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[initial]), rerun_status=403)
    assert result["state"] == "unresolved" and dispatches == []
    assert writes[-1][0] == "PATCH" and '"status": "rejected"' in writes[-1][2]["body"]
    rejected = {"user": BOT, "body": writes[-1][2]["body"]}
    result, writes, dispatches = _recover(RecoveryGitHub(comments=[initial, rejected]))
    assert result["state"] == "resumed" and dispatches == []
    assert writes[-1][1].endswith("/actions/runs/9/rerun-failed-jobs")


def test_closed_same_sha_incident_cannot_suppress_new_failed_run(monkeypatch, main_env) -> None:
    old = _incident(state="closed")
    old["body"] = old["body"].replace("`7`", "`6`").replace("`7/1`", "`6/1`")
    old["body"] += f"- Self-Heal-Source: `{WF_PATH}@{OLD}`\n"
    _use(monkeypatch, RecoveryGitHub(issues=[old]))
    assert _run_main(main_env) == 2
    assert len(main_env["issue"]) == 1 and main_env["dispatch"] == [1]


@pytest.mark.parametrize(
    ("status", "conclusion"), [("completed", "failure"), ("in_progress", "success")]
)
def test_newer_attempt_without_proven_recovery_keeps_current_failure_tracked(
    status, conclusion
) -> None:
    result, writes, dispatches = _recover(
        RecoveryGitHub(run={"run_attempt": 2, "status": status, "conclusion": conclusion})
    )
    assert result["state"] == "unresolved" and "newer_attempt_unresolved:2:" in result["reason"]
    assert writes == dispatches == []
