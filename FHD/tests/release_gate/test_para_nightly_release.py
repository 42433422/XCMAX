import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scripts.dev import push_preflight
from scripts.release import para_nightly_release as release

SOURCE = "a" * 40
REVIEWED = "b" * 40
MERGE = "c" * 40
CHECK_TIME = datetime(2026, 11, 20, 22, tzinfo=UTC)


def ready_fixtures():
    data = {
        "git/ref/heads/main": {"object": {"sha": SOURCE}},
        "pulls/41": {
            "number": 41,
            "merged": True,
            "head": {"sha": REVIEWED},
            "base": {"ref": "main", "repo": {"full_name": release.REPOSITORY}},
            "merge_commit_sha": MERGE,
            "merged_at": "2026-11-20T18:15:00Z",
            "created_at": "2026-11-19T17:00:00Z",
        },
        f"compare/{MERGE}...{SOURCE}": {"status": "ahead"},
    }
    data["pulls?state=all&sort=created&direction=desc&per_page=100&page=1"] = [data["pulls/41"]]
    return data


def test_queue_id_comes_from_approved_window_receipts():
    data = ready_fixtures()
    first = release.completed_batch({41: REVIEWED}, CHECK_TIME, data.__getitem__)
    data["git/ref/heads/main"]["object"]["sha"] = MERGE
    data[f"compare/{MERGE}...{MERGE}"] = {"status": "identical"}
    repeated = release.completed_batch({41: REVIEWED}, CHECK_TIME, data.__getitem__)
    assert first["source"] == SOURCE
    assert first["branch"].startswith("automation/para-release-2026-11-21-")
    assert repeated["branch"] == first["branch"]


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("merged", False, "missing_exact_merge_receipt"),
        ("merged_at", None, "missing_exact_merge_receipt"),
        ("head", {"sha": "d" * 40}, "missing_exact_merge_receipt"),
        ("merged_at", "2026-11-19T18:15:00Z", "no_new_merge_in_current_window"),
        ("merged_at", "2026-11-20T21:00:00Z", "no_new_merge_in_current_window"),
    ],
)
def test_unready_batch_cannot_create_a_version(key, value, expected):
    data = ready_fixtures()
    data["pulls/41"][key] = value
    result = release.completed_batch({41: REVIEWED}, CHECK_TIME, data.__getitem__)
    assert result["reason"] == expected
    assert "source" not in result


def test_github_clock_and_read_only_diagnostic():
    workflow = yaml.load(
        (release.FHD / ".github/workflows/para-nightly-release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert workflow["on"]["schedule"] == [{"cron": "0 22 * * *"}]
    assert "github.event_name == 'schedule'" in workflow["jobs"]["prepare-version"]["if"]
    proposal = workflow["jobs"]["prepare-version"]["steps"][-1]["run"]
    assert proposal.index("git commit") < proposal.index("push_preflight.py --fix")
    assert proposal.index("push_preflight.py --fix") < proposal.index("git push")
    assert "--label hold-merge" in proposal
    assert "gh pr merge" not in proposal
    assert "XCMAX_MAIN_MERGE_QUEUE" in proposal
    assert "build-private-candidates" not in workflow["jobs"]


@pytest.mark.parametrize("state", ["open", "closed"])
def test_unapproved_pr_does_not_veto_the_approved_release_batch(state):
    data = ready_fixtures()
    data["pulls?state=all&sort=created&direction=desc&per_page=100&page=1"].insert(
        0, {**data["pulls/41"], "number": 42, "merged_at": None, "state": state}
    )
    assert release.completed_batch({41: REVIEWED}, CHECK_TIME, data.__getitem__)["source"] == SOURCE


def test_empty_approved_queue_never_promotes_inventory_to_release_authorization():
    assert release.completed_batch({}, CHECK_TIME, ready_fixtures().__getitem__) == {
        "reason": "empty_integration_queue"
    }


@pytest.fixture
def nightly_checkout(tmp_path, monkeypatch):
    origin, checkout = tmp_path / "origin", tmp_path / "checkout"
    origin.mkdir()

    def git(cwd, *args):
        return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()

    git(origin, "init", "--initial-branch=main")
    git(origin, "config", "user.name", "Nightly regression")
    git(origin, "config", "user.email", "nightly@example.invalid")
    scripts = origin / "FHD/scripts/dev"
    scripts.mkdir(parents=True)
    for name in ("check_net_deletion.py", "verify_version_anchors.py"):
        shutil.copyfile(release.FHD / "scripts/dev" / name, scripts / name)
    (origin / "FHD/metrics").mkdir()
    (origin / "FHD/CHANGELOG.md").write_text("# Changes\n\n## Unreleased\n\n")
    (origin / "FHD/VERSION.md").write_text("**XCAGI 稳定产品版本**：`1.0.0.1`\n")
    git(origin, "add", ".")
    subprocess.run(
        [sys.executable, str(scripts / "check_net_deletion.py"), "--update"],
        check=True,
        capture_output=True,
    )
    git(origin, "add", ".")
    git(origin, "commit", "-m", "initial main")
    source = git(origin, "rev-parse", "HEAD")
    checkout.mkdir()
    git(checkout, "init", "--initial-branch=main")
    git(checkout, "remote", "add", "origin", origin.as_uri())
    git(checkout, "fetch", "--depth=1", "origin", source)
    git(checkout, "checkout", "--detach", "FETCH_HEAD")
    git(checkout, "config", "user.name", "Nightly regression")
    git(checkout, "config", "user.email", "nightly@example.invalid")
    assert git(checkout, "rev-parse", "--is-shallow-repository") == "true"
    assert not git(checkout, "for-each-ref", "refs/remotes/origin/main")
    monkeypatch.setattr(push_preflight, "REPO_ROOT", checkout)
    monkeypatch.setattr(push_preflight, "FHD_ROOT", checkout / "FHD")
    # This fixture isolates the real Git/changelog/baseline gates from the unrelated catalog.
    monkeypatch.setattr(push_preflight, "check_capability_center", lambda _: (True, "fixture"))
    steps = yaml.load(
        (release.FHD / ".github/workflows/para-nightly-release.yml").read_text(),
        Loader=yaml.BaseLoader,
    )["jobs"]["prepare-version"]["steps"]

    def candidate(version):
        source = git(checkout, "rev-parse", "HEAD")
        (checkout / "FHD/VERSION.md").write_text(f"**XCAGI 稳定产品版本**：`{version}`\n")
        with (checkout / "FHD/CHANGELOG.md").open("a") as stream:
            stream.write(f"- Candidate {version}.\n")
        env = {
            **os.environ,
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            "SOURCE": source,
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        }
        baseline = steps[-2]["run"].split(
            "python scripts/dev/ssot_cli.py check version product-lines\n", 1
        )[1]
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", baseline],
            cwd=checkout / "FHD",
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        git(checkout, "add", "-u")
        git(checkout, "commit", "-m", f"candidate {version}")
        git(checkout, "merge-base", "--is-ancestor", source, "HEAD")
        return source, json.loads((checkout / "FHD/metrics/line_baseline.json").read_text())

    return candidate, steps[-1], tmp_path, checkout


def test_proposal_preflight_works_in_exact_shallow_checkout_without_origin_main(
    nightly_checkout,
):
    candidate, proposal, _, _ = nightly_checkout
    source, _ = candidate("1.0.0.2")
    commands = re.findall(r"scripts/dev/push_preflight\.py ([^;)]+)", proposal["run"])
    assert len(commands) == 2  # Retry loop and final publication guard must use the same base.
    for command in commands:
        assert push_preflight.main(shlex.split(command.replace("$SOURCE", source))) == 0


def test_consecutive_baseline_increases_record_the_batch_reason_in_the_proposal(
    nightly_checkout,
):
    candidate, proposal, tmp_path, checkout = nightly_checkout
    rounds = []
    for version in ("1.0.0.2", "1.0.0.3"):
        source, baseline = candidate(version)
        ok, detail = push_preflight.check_net_deletion(source)
        assert ok, detail
        rounds.append((version, source, baseline))
    assert rounds[1][2]["lines"] > rounds[0][2]["lines"]
    assert rounds[1][2]["note"] != rounds[0][2]["note"]
    assert proposal["env"]["BASELINE_REASON"] == "${{ steps.version.outputs.baseline_reason }}"
    body_command = next(
        line
        for line in proposal["run"].splitlines()
        if '> "$RUNNER_TEMP/para-release-pr.md"' in line
    )
    for version, source, baseline in rounds:
        reason = baseline["note"]
        assert version in reason and source in reason
        assert f"baseline_reason={reason}\n" in (tmp_path / "output").read_text()
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", body_command],
            check=True,
            cwd=checkout,
            env={
                **os.environ,
                "SOURCE": source,
                "head": "d" * 40,
                "BASELINE_REASON": reason,
                "RUNNER_TEMP": str(tmp_path),
            },
        )
        assert reason in (tmp_path / "para-release-pr.md").read_text()
