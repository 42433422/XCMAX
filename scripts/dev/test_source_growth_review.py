"""Real Git fixtures for bounded, traceable source-growth review requests."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.dev import source_growth_review as gate

SOURCE = "FHD/app/service.py"


def run(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def save(root):
    run(root, "add", ".")
    run(root, "commit", "-qm", "synthetic fixture")
    return run(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    run(tmp_path, "init", "-q")
    run(tmp_path, "config", "user.name", "Fixture")
    run(tmp_path, "config", "user.email", "fixture@example.invalid")
    write(tmp_path, "README.md", "synthetic fixture\n")
    save(tmp_path)
    return tmp_path


def request(measured):
    return {
        **measured,
        "reason": "Add validation for the existing public operation.",
        "boundary": "The operation owns the transaction and its failure cleanup.",
        "validation": "Targeted operation tests cover success and rollback.",
        "follow_up": "@maintainer will assess boundary extraction before the next feature.",
        "review_owner": "@maintainer",
    }


@pytest.mark.parametrize(
    "before,after,trigger",
    [
        (0, 801, True),
        (800, 801, True),
        (801, 802, True),
        (800, 800, False),
        (901, 901, False),
        (901, 900, False),
    ],
)
def test_real_git_growth_boundaries(repo, before, after, trigger):
    if before:
        write(repo, SOURCE, "value = 1\n" * before)
        save(repo)
    base = run(repo, "rev-parse", "HEAD")
    write(repo, SOURCE, "value = 2\n" * after)
    head = save(repo)
    _, _, changes = gate.growth(repo, base, head)
    assert bool(changes) is trigger
    if trigger:
        assert changes[SOURCE]["before_lines"] == before
        assert changes[SOURCE]["after_lines"] == after
        assert gate.evaluate(changes, {})
        assert not gate.evaluate(changes, {SOURCE: request(changes[SOURCE])})


@pytest.mark.parametrize(
    "path",
    [
        "FHD/app/tests/test_big.py",
        "FHD/frontend/src/large.test.ts",
        "FHD/frontend/src/generated/large.ts",
        "docs/large.py",
    ],
)
def test_excluded_paths(repo, path):
    base = run(repo, "rev-parse", "HEAD")
    write(repo, path, "# fixture\n" * 900)
    assert not gate.growth(repo, base, save(repo))[2]


@pytest.mark.parametrize("old", [SOURCE, "FHD/app/tests/test_big.py"])
def test_pure_rename_and_move_into_production(repo, old):
    write(repo, old, "# fixture\n" * 900)
    base = save(repo)
    new = "FHD/app/renamed.py"
    (repo / old).rename(repo / new)
    changes = gate.growth(repo, base, save(repo))[2]
    assert bool(changes) is (old != SOURCE)


def test_renamed_growth_is_not_exempt(repo):
    write(repo, SOURCE, "# fixture\n" * 900)
    base = save(repo)
    new = "FHD/app/renamed.py"
    (repo / SOURCE).rename(repo / new)
    write(repo, new, "# fixture\n" * 901)
    changes = gate.growth(repo, base, save(repo))[2]
    assert changes[new]["base_file"] == SOURCE
    assert changes[new]["before_lines"] == 900


@pytest.mark.parametrize(
    "key,value",
    [
        ("head_blob", "stale"),
        ("base_blob", "stale"),
        ("base_file", "elsewhere.py"),
        ("before_lines", True),
        ("after_lines", 999),
        ("reason", "TODO"),
        ("boundary", ""),
        ("validation", None),
        ("follow_up", "N/A"),
        ("review_owner", "approved"),
    ],
)
def test_bad_or_stale_requests(key, value):
    measured = {
        "base_file": SOURCE,
        "base_blob": "a" * 40,
        "head_blob": "b" * 40,
        "before_lines": 900,
        "after_lines": 901,
    }
    entry = request(measured)
    entry[key] = value
    assert gate.evaluate({SOURCE: measured}, {SOURCE: entry})


def test_unrelated_old_request_does_not_block():
    assert not gate.evaluate({}, {SOURCE: {"head_blob": "old"}})


def test_baseline_refresh_and_dirty_request_do_not_bypass(repo):
    write(repo, SOURCE, "# fixture\n" * 900)
    base = save(repo)
    write(repo, SOURCE, "# fixture\n" * 901)
    write(repo, "config/source_governance_baseline.json", '{"oversized_files": {}}')
    write(repo, gate.REVIEW_PATH, '{"schema_version": 1, "reviews": {}}')
    head = save(repo)
    changes = gate.growth(repo, base, head)[2]
    write(
        repo,
        gate.REVIEW_PATH,
        json.dumps(
            {"schema_version": 1, "reviews": {SOURCE: request(changes[SOURCE])}}
        ),
    )
    assert gate.main(["--repo-root", str(repo), "--base", base, "--head", head]) == 1
    assert not gate.evaluate(changes, gate.load_reviews(repo, save(repo)))


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        '{"schema_version":1,"reviews":{},"reviews":{}}',
        '{"schema_version":1,"reviews":[]}',
    ],
)
def test_bad_catalog_fails_closed(repo, payload):
    write(repo, gate.REVIEW_PATH, payload)
    head = save(repo)
    with pytest.raises(ValueError):
        gate.load_reviews(repo, head)


def test_missing_history_fails_closed(repo):
    assert gate.main(["--repo-root", str(repo), "--base", "missing-ref"]) == 2


def test_merge_base_ignores_unrelated_target_changes(repo):
    write(repo, SOURCE, "# fixture\n" * 901)
    common = save(repo)
    run(repo, "checkout", "-qb", "target")
    write(repo, SOURCE, "# fixture\n" * 900)
    target = save(repo)
    run(repo, "checkout", "-qb", "feature", common)
    write(repo, "README.md", "unrelated change\n")
    head = save(repo)
    assert not gate.growth(repo, target, head)[2]


@pytest.fixture
def pr_merge(repo):
    write(repo, SOURCE, "# fixture\n" * 800)
    event_base = save(repo)
    write(repo, SOURCE, "# fixture\n" * 801)
    base = save(repo)
    run(repo, "checkout", "-qb", "feature")
    write(repo, SOURCE, "# fixture\n" * 802)
    head = save(repo)
    changes = gate.growth(repo, base, head)[2]
    write(
        repo,
        gate.REVIEW_PATH,
        json.dumps(
            {"schema_version": 1, "reviews": {SOURCE: request(changes[SOURCE])}}
        ),
    )
    head = save(repo)
    run(repo, "checkout", "--detach", base)
    run(repo, "merge", "--no-ff", "--no-edit", head)
    return {
        "base": base,
        "head": head,
        "source": run(repo, "rev-parse", "HEAD"),
        "event_base": event_base,
    }


def pr_args(repo, identities):
    return [
        "--repo-root",
        str(repo),
        "--base",
        identities["event_base"],
        "--head",
        identities["head"],
        "--pr-merge-sha",
        identities["source"],
    ]


def test_pr_merge_uses_tested_parent_despite_stale_event_and_moving_target(
    repo, pr_merge, capsys
):
    args = pr_args(repo, pr_merge)
    # Reproduce the original gate's stale-base failure with the valid committed catalog.
    assert gate.main(args[:-2]) == 1
    capsys.readouterr()
    run(repo, "checkout", "-qb", "advanced-target", pr_merge["base"])
    write(repo, SOURCE, "# fixture\n" * 803)
    advanced = save(repo)
    run(repo, "update-ref", "refs/remotes/origin/main", advanced)
    run(repo, "checkout", "--detach", pr_merge["source"])
    assert gate.main(args) == 0
    report, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert report["base"] == pr_merge["base"]
    assert report["head"] == pr_merge["head"]
    assert report["event_base"] == pr_merge["event_base"]
    assert report["tested_merge_sha"] == pr_merge["source"]
    assert report["growth"][SOURCE]["before_lines"] == 801
    assert report["growth"][SOURCE]["after_lines"] == 802
    assert report["errors"] == []


@pytest.mark.parametrize(
    "case",
    [
        "checkout",
        "head",
        "single-parent",
        "octopus",
        "shallow",
        "missing-source",
        "missing-head",
        "empty",
        "mutable",
    ],
)
def test_pr_merge_identity_or_history_mismatch_fails_closed(
    repo, pr_merge, case, capsys
):
    if case == "checkout":
        run(repo, "checkout", "--detach", pr_merge["base"])
    elif case == "head":
        pr_merge["head"] = pr_merge["base"]
    elif case == "single-parent":
        pr_merge["source"] = pr_merge["head"]
        run(repo, "checkout", "--detach", pr_merge["source"])
    elif case == "octopus":
        tree = run(repo, "rev-parse", "HEAD^{tree}")
        pr_merge["source"] = run(
            repo,
            "commit-tree",
            tree,
            "-p",
            pr_merge["base"],
            "-p",
            pr_merge["head"],
            "-p",
            pr_merge["event_base"],
            "-m",
            "synthetic octopus",
        )
        run(repo, "checkout", "--detach", pr_merge["source"])
    elif case == "shallow":
        write(repo, ".git/shallow", pr_merge["source"] + "\n")
    elif case.startswith("missing-"):
        pr_merge[case.removeprefix("missing-")] = "0" * 40
    else:
        pr_merge["source"] = "" if case == "empty" else "HEAD"
    assert gate.main(pr_args(repo, pr_merge)) == 2
    assert "Cannot verify comparison" in capsys.readouterr().out


def test_pr_merge_does_not_accept_stale_head_review(repo, pr_merge, capsys):
    run(repo, "checkout", "--detach", pr_merge["head"])
    write(repo, SOURCE, "# fixture\n" * 803)
    pr_merge["head"] = save(repo)
    run(repo, "checkout", "--detach", pr_merge["base"])
    run(repo, "merge", "--no-ff", "--no-edit", pr_merge["head"])
    pr_merge["source"] = run(repo, "rev-parse", "HEAD")
    assert gate.main(pr_args(repo, pr_merge)) == 1
    output = capsys.readouterr().out
    assert "head_blob must match this exact change" in output
    assert "after_lines must match this exact change" in output


def test_required_workflow_uses_pr_identities_and_full_history():
    root = Path(__file__).resolve().parents[2]
    for path in ["FHD/.github/workflows/ci-cd.yml", ".github/workflows/fhd-ci-cd.yml"]:
        # Inspect the entire job, not only the next top-level property.
        text = (
            (root / path)
            .read_text()
            .split("  arch-fitness:\n", 1)[1]
            .split("\n  build:", 1)[0]
        )
        assert "fetch-depth: 0" in text
        assert "filter: blob:none" in text
        assert "github.event.pull_request.base.sha" in text
        assert "github.event.pull_request.head.sha" in text
        assert "GROWTH_SOURCE: ${{ github.sha }}" in text
        assert (
            'source_growth_review.py --base "$GROWTH_BASE" --head "$GROWTH_HEAD" --pr-merge-sha "$GROWTH_SOURCE"'
            in text
        )
        assert "if: github.event_name == 'pull_request'" in text


@pytest.mark.parametrize("field", ["base_file", "base_blob"])
def test_new_source_requires_explicit_null_identity(field):
    measured = {
        "base_file": None,
        "base_blob": None,
        "head_blob": "b" * 40,
        "before_lines": 0,
        "after_lines": 801,
    }
    entry = request(measured)
    del entry[field]
    assert gate.evaluate({SOURCE: measured}, {SOURCE: entry})


def test_missing_catalog_with_real_growth_fails_closed(repo):
    base = run(repo, "rev-parse", "HEAD")
    write(repo, SOURCE, "# fixture\n" * 801)
    head = save(repo)
    assert gate.main(["--repo-root", str(repo), "--base", base, "--head", head]) == 2
