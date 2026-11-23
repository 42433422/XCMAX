"""Execute the trusted cleanup's inline JavaScript against an isolated Octokit API."""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/cancel-superseded-ci.yml"
CURRENT = "a" * 40
OLD = "b" * 40
REPOSITORY = 1262665373
NODE = shutil.which("node")

# The real Octokit v14 iterator normalizes the response list into an array and
# preserves its total_count. Each mocked page below follows that upstream shape.
HARNESS = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const fixture = input.fixture;
const calls = [], timers = [], messages = [];
const indexes = new Map();
const clone = value => structuredClone(value);
function sequence(key, values, fallback) {
  const index = indexes.get(key) || 0;
  indexes.set(key, index + 1);
  return values?.length ? values[Math.min(index, values.length - 1)] : fallback;
}
function response(value) {
  if (value?.error) throw Object.assign(new Error(value.message || 'mock API failure'), {status: value.error});
  return {status: 200, data: clone(value)};
}
const endpoint = kind => Object.assign(() => { throw new Error('Unexpected direct pagination call'); }, {kind});
const actions = {
  getWorkflow: async params => { calls.push({api: 'workflow', params}); return response(fixture.workflow); },
  getWorkflowRun: async params => {
    calls.push({api: 'run', params});
    return response(sequence('run-' + params.run_id, fixture.run_reads?.[params.run_id], fixture.runs[params.run_id]));
  },
  listWorkflowRuns: endpoint('runs'),
  listJobsForWorkflowRunAttempt: endpoint('jobs'),
  cancelWorkflowRun: async params => {
    calls.push({api: 'cancel', params});
    response(fixture.cancel_response || {});
    return {status: 202};
  },
  forceCancelWorkflowRun: async params => {
    calls.push({api: 'force', params});
    response(fixture.force_response || {});
    return {status: 202};
  },
};
const github = {
  rest: {
    actions,
    pulls: {get: async params => {
      calls.push({api: 'pr', params});
      return response(sequence('pr', fixture.pr_reads, fixture.live_pr));
    }},
  },
  paginate: {iterator: async function* (method, params) {
    calls.push({api: method.kind, params});
    const pages = method.kind === 'runs' ? fixture.run_pages
      : sequence('jobs-' + params.run_id, fixture.job_reads?.[params.run_id], fixture.job_pages[params.run_id]);
    for (const [index, page] of pages.entries()) {
      calls.push({api: 'page', kind: method.kind, run_id: params.run_id, index});
      response(page);
      const data = page.raw === undefined ? clone(page.items) : clone(page.raw);
      if ('total_count' in page) data.total_count = page.total_count;
      if ('incomplete_results' in page) data.incomplete_results = page.incomplete_results;
      yield {status: 200, data};
    }
  }},
};
globalThis.setTimeout = (callback, milliseconds) => { timers.push(milliseconds); callback(); return 0; };
const core = {info: message => messages.push(message)};
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
(async () => {
  let error = null;
  try { await new AsyncFunction('github', 'context', 'core', input.script)(github, fixture.context, core); }
  catch (failure) { error = {message: failure.message, status: failure.status}; }
  process.stdout.write(JSON.stringify({calls, timers, messages, error}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def pages(items):
    return [{"items": items, "total_count": len(items)}]


@pytest.fixture
def scenario():
    pr = {
        "id": 5437205272,
        "number": 3483,
        "state": "open",
        "created_at": "2026-11-22T00:00:00Z",
        "updated_at": "2026-11-22T02:00:00Z",
        "head": {"repo": {"id": REPOSITORY}, "ref": "perf/ci", "sha": CURRENT},
        "base": {"repo": {"id": REPOSITORY}},
    }
    run = {
        "id": 100,
        "workflow_id": 77,
        "path": ".github/workflows/fhd-ci-cd.yml",
        "event": "pull_request",
        "repository": {"id": REPOSITORY},
        "head_repository": {"id": REPOSITORY},
        "head_branch": "perf/ci",
        "head_sha": OLD,
        "run_attempt": 1,
        "created_at": "2026-11-22T01:00:00Z",
        "run_started_at": "2026-11-22T01:00:00Z",
        "status": "in_progress",
        "conclusion": None,
        "pull_requests": [copy.deepcopy(pr)],
    }
    job = {
        "id": 500,
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "head_sha": run["head_sha"],
        "status": "completed",
        "conclusion": "cancelled",
    }
    return {
        "context": {
            "eventName": "pull_request_target",
            "repo": {"owner": "42433422", "repo": "XCMAX"},
            "payload": {
                "action": "synchronize",
                "repository": {"id": REPOSITORY, "full_name": "42433422/XCMAX"},
                "number": pr["number"],
                "pull_request": copy.deepcopy(pr),
            },
        },
        "live_pr": pr,
        "workflow": {"id": run["workflow_id"], "path": run["path"]},
        "runs": {"100": run},
        "run_pages": pages([run]),
        "job_pages": {"100": pages([job])},
    }


def execute(scenario):
    assert NODE, "Node is required to execute the trusted workflow's actual JavaScript"
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    script = workflow["jobs"]["complete-cancellation"]["steps"][0]["with"]["script"]
    result = subprocess.run(
        [NODE, "-e", HARNESS],
        input=json.dumps({"fixture": scenario, "script": script}),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def writes(result):
    return [call for call in result["calls"] if call["api"] in {"cancel", "force"}]


def replace_path(value, path, replacement):
    parts = path.split(".")
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    value[parts[-1]] = replacement


def test_trusted_trigger_has_no_pr_code_execution_or_broad_write_permissions():
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"pull_request_target": {"types": ["synchronize"]}}
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["complete-cancellation"]
    assert job["runs-on"] == "ubuntu-slim"
    assert job["permissions"] == {"actions": "write", "pull-requests": "read"}
    assert len(job["steps"]) == 1
    step = job["steps"][0]
    assert step["uses"] == "actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3"
    assert step["with"]["retries"] == "0"
    assert "${{" not in step["with"]["script"]
    assert "run" not in step and "env" not in step and "secrets" not in job


def test_superseded_cancelled_attempt_is_rechecked_before_one_force(scenario):
    result = execute(scenario)
    assert result["error"] is None and len(writes(result)) == 1
    assert writes(result)[0]["params"]["run_id"] == 100
    assert result["timers"] == []
    calls = [call["api"] for call in result["calls"] if call["api"] != "page"]
    assert calls == [
        "pr",
        "workflow",
        "runs",
        "pr",
        "run",
        "jobs",
        "pr",
        "run",
        "jobs",
        "pr",
        "run",
        "force",
    ]
    for call in result["calls"]:
        if "params" in call:
            assert call["params"]["headers"] == {"X-GitHub-Api-Version": "2022-11-28"}
    listing = next(call["params"] for call in result["calls"] if call["api"] == "runs")
    assert listing["workflow_id"] == "fhd-ci-cd.yml"
    assert listing["event"] == "pull_request" and listing["branch"] == "perf/ci"
    assert listing["created"] == "2026-11-22T00:00:00Z..2026-11-22T02:00:00Z"
    assert all(
        call["params"]["attempt_number"] == 1 for call in result["calls"] if call["api"] == "jobs"
    )


@pytest.mark.parametrize(
    "path,value",
    [
        ("head_sha", CURRENT),
        ("head_sha", None),
        ("head_sha", "invalid"),
        ("event", "push"),
        ("event", "pull_request_target"),
        ("workflow_id", 78),
        ("path", ".github/workflows/fhd-deploy.yml"),
        ("head_repository.id", 9),
        ("repository.id", 9),
        ("head_repository", None),
        ("head_branch", "other/branch"),
        ("run_attempt", None),
        ("run_attempt", 0),
        ("status", "completed"),
        ("status", "unknown"),
        ("conclusion", "failure"),
        ("pull_requests", []),
        ("pull_requests", [{"id": 1}, {"id": 2}]),
        ("pull_requests.0.id", 9),
        ("pull_requests.0.number", 9),
        ("pull_requests.0.base.repo.id", 9),
        ("pull_requests.0.head.repo.id", 9),
        ("created_at", None),
        ("created_at", "invalid"),
        ("created_at", "2026-11-21T23:59:59Z"),
        ("created_at", "2026-11-22T02:00:01Z"),
        ("run_started_at", None),
        ("run_started_at", "2026-11-22T02:00:01Z"),
    ],
)
def test_non_candidates_never_reach_jobs_or_write(scenario, path, value):
    replace_path(scenario["runs"]["100"], path, value)
    result = execute(scenario)
    assert writes(result) == [] and result["timers"] == []
    assert not any(call["api"] == "jobs" for call in result["calls"])


@pytest.mark.parametrize(
    "path,value",
    [
        ("eventName", "pull_request"),
        ("payload.action", "opened"),
        ("payload.number", 999),
        ("payload.repository.id", None),
        ("payload.repository.full_name", "someone/else"),
        ("payload.pull_request.id", None),
        ("payload.pull_request.state", "closed"),
        ("payload.pull_request.head.repo.id", 9),
        ("payload.pull_request.base.repo.id", 9),
        ("payload.pull_request.head.sha", None),
        ("payload.pull_request.head.ref", ""),
        ("payload.pull_request.created_at", None),
        ("payload.pull_request.created_at", "invalid"),
        ("payload.pull_request.updated_at", None),
        ("payload.pull_request.updated_at", "2026-11-31T02:00:00Z"),
        ("payload.pull_request.updated_at", "2026-11-21T00:00:00Z"),
    ],
)
def test_untrusted_event_stops_before_any_api_request(scenario, path, value):
    replace_path(scenario["context"], path, value)
    result = execute(scenario)
    assert result["calls"] == [] and result["timers"] == []


@pytest.mark.parametrize(
    "ordinary,read", [(False, read) for read in range(4)] + [(True, read) for read in range(6)]
)
def test_live_head_change_at_any_check_stops_cleanup(scenario, ordinary, read):
    if ordinary:
        scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    changed = copy.deepcopy(scenario["live_pr"])
    changed["head"]["sha"] = "c" * 40
    scenario["pr_reads"] = [scenario["live_pr"]] * read + [changed]
    assert writes(execute(scenario)) == []


@pytest.mark.parametrize(
    "ordinary,read", [(False, read) for read in range(3)] + [(True, read) for read in range(5)]
)
@pytest.mark.parametrize(
    "field,value",
    [
        ("run_attempt", 2),
        ("head_sha", "c" * 40),
        ("run_started_at", "2026-11-22T01:01:00Z"),
        ("status", "completed"),
    ],
)
def test_run_attempt_or_identity_change_at_any_recheck_stops_write(
    scenario, ordinary, read, field, value
):
    if ordinary:
        scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    changed = copy.deepcopy(scenario["runs"]["100"])
    changed[field] = value
    scenario["run_reads"] = {"100": [scenario["runs"]["100"]] * read + [changed]}
    assert writes(execute(scenario)) == []


@pytest.mark.parametrize(
    "field,value", [("run_id", 9), ("run_attempt", 2), ("head_sha", CURRENT), ("head_sha", None)]
)
@pytest.mark.parametrize(
    "ordinary,read", [(False, read) for read in range(2)] + [(True, read) for read in range(4)]
)
def test_job_proof_must_belong_to_the_same_run_sha_and_attempt(
    scenario, field, value, ordinary, read
):
    if ordinary:
        scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    changed = copy.deepcopy(scenario["job_pages"]["100"])
    changed[0]["items"][0][field] = value
    scenario["job_reads"] = {"100": [scenario["job_pages"]["100"]] * read + [changed]}
    assert writes(execute(scenario)) == []


def test_conflicting_new_head_requests_ordinary_cancellation_after_wait(scenario):
    scenario["live_pr"]["mergeable"] = False
    scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    result = execute(scenario)
    assert result["error"] is None and result["timers"] == [5000, 5000]
    assert len(writes(result)) == 1 and writes(result)[0]["api"] == "cancel"
    assert writes(result)[0]["params"]["run_id"] == 100
    calls = [call["api"] for call in result["calls"] if call["api"] != "page"]
    assert calls[-6:] == ["pr", "run", "jobs", "pr", "run", "cancel"]
    assert sum(call["api"] == "jobs" for call in result["calls"]) == 4


def test_empty_job_queue_never_authorizes_force(scenario):
    scenario["job_pages"]["100"] = pages([])
    result = execute(scenario)
    assert result["error"] is None and len(writes(result)) == 1
    assert writes(result)[0]["api"] == "cancel"


@pytest.mark.parametrize("cancelled", [False, True])
def test_only_existing_cancelled_proof_authorizes_cleanup_of_a_rerun(scenario, cancelled):
    scenario["runs"]["100"]["run_attempt"] = 2
    scenario["job_pages"]["100"][0]["items"][0].update(
        run_attempt=2, conclusion="cancelled" if cancelled else "success"
    )
    result = execute(scenario)
    assert result["error"] is None
    assert [call["api"] for call in writes(result)] == (["force"] if cancelled else [])


def test_normal_cancellation_arriving_after_synchronize_is_observed(scenario):
    not_yet = copy.deepcopy(scenario["job_pages"]["100"])
    not_yet[0]["items"][0].update(status="in_progress", conclusion=None)
    scenario["job_reads"] = {"100": [not_yet, scenario["job_pages"]["100"]]}
    result = execute(scenario)
    assert len(writes(result)) == 1 and result["timers"] == [5000]
    assert sum(call["api"] == "jobs" for call in result["calls"]) == 3


def test_attempt_change_during_read_only_wait_is_not_cancelled(scenario):
    scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    changed = copy.deepcopy(scenario["runs"]["100"])
    changed["run_attempt"] = 2
    scenario["run_reads"] = {"100": [scenario["runs"]["100"], changed]}
    result = execute(scenario)
    assert writes(result) == [] and result["timers"] == [5000]


@pytest.mark.parametrize("status", ["completed", "in_progress"])
@pytest.mark.parametrize("ordinary", [False, True])
def test_cancel_409_gets_one_read_without_another_write(scenario, status, ordinary):
    if ordinary:
        scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    after = copy.deepcopy(scenario["runs"]["100"])
    after.update(status=status, run_attempt=2)
    scenario["cancel_response" if ordinary else "force_response"] = {"error": 409}
    scenario["run_reads"] = {"100": [scenario["runs"]["100"]] * (5 if ordinary else 3) + [after]}
    result = execute(scenario)
    assert result["error"] is None and len(writes(result)) == 1
    method = "cancel" if ordinary else "force"
    write_index = next(i for i, call in enumerate(result["calls"]) if call["api"] == method)
    assert [call["api"] for call in result["calls"][write_index + 1 :]] == ["run"]
    assert result["timers"] == ([5000, 5000] if ordinary else [])


@pytest.mark.parametrize("ordinary", [False, True])
def test_other_api_write_error_is_not_retried_or_hidden(scenario, ordinary):
    if ordinary:
        scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    scenario["cancel_response" if ordinary else "force_response"] = {"error": 403}
    result = execute(scenario)
    assert len(writes(result)) == 1 and result["error"]["status"] == 403
    assert result["calls"][-1]["api"] == ("cancel" if ordinary else "force")


@pytest.mark.parametrize("collection", ["run_pages", "job_pages"])
@pytest.mark.parametrize("ordinary", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        "missing_count",
        "missing_page",
        "duplicate",
        "changing_count",
        "incomplete",
        "not_normalized",
        "read_error",
    ],
)
def test_incomplete_pagination_never_authorizes_a_write(scenario, collection, fault, ordinary):
    if ordinary:
        scenario["job_pages"]["100"][0]["items"][0]["conclusion"] = "success"
    selected = scenario["run_pages"] if collection == "run_pages" else scenario["job_pages"]["100"]
    first = selected[0]
    if fault == "missing_count":
        first.pop("total_count")
    elif fault == "missing_page":
        first["total_count"] = 2
    elif fault == "duplicate":
        first["items"] *= 2
        first["total_count"] = 2
    elif fault == "changing_count":
        first["total_count"] = 2
        selected.append({"items": [], "total_count": 1})
    elif fault == "incomplete":
        first["incomplete_results"] = True
    elif fault == "not_normalized":
        first["raw"] = {"workflow_runs": first["items"]}
    else:
        selected.append({"error": 500, "items": [], "total_count": 1})
    result = execute(scenario)
    assert writes(result) == [] and result["error"] is not None


@pytest.mark.parametrize("count", [1000, 1001])
def test_workflow_search_limit_is_fail_closed(scenario, count):
    scenario["run_pages"][0]["total_count"] = count
    result = execute(scenario)
    assert writes(result) == [] and result["error"] is not None


@pytest.mark.parametrize("ordinary", [False, True])
def test_all_candidate_and_job_pages_are_read_before_the_first_write(scenario, ordinary):
    second = copy.deepcopy(scenario["runs"]["100"])
    second.update(id=101, head_sha="c" * 40)
    scenario["runs"]["101"] = second
    scenario["run_pages"] = [
        {"items": [scenario["runs"]["100"]], "total_count": 2},
        {"items": [second], "total_count": 2},
    ]
    for run_id in (100, 101):
        cancelled = copy.deepcopy(scenario["job_pages"]["100"][0]["items"][0])
        cancelled.update(
            id=run_id * 10,
            run_id=run_id,
            head_sha=scenario["runs"][str(run_id)]["head_sha"],
            conclusion="success" if ordinary else "cancelled",
        )
        finished = {**cancelled, "id": run_id * 10 + 1, "conclusion": "success"}
        scenario["job_pages"][str(run_id)] = [
            {"items": [finished], "total_count": 2},
            {"items": [cancelled], "total_count": 2},
        ]
    result = execute(scenario)
    assert result["error"] is None and len(writes(result)) == 2
    method = "cancel" if ordinary else "force"
    assert all(call["api"] == method for call in writes(result))
    first_write = next(i for i, call in enumerate(result["calls"]) if call["api"] == method)
    before_write = result["calls"][:first_write]
    assert sum(call["api"] == "page" and call["kind"] == "runs" for call in before_write) == 2
    assert any(
        call["api"] == "page" and call.get("run_id") == 101 and call["index"] == 1
        for call in before_write
    )
