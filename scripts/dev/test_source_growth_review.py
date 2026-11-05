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
        assert (
            'source_growth_review.py --base "$GROWTH_BASE" --head "$GROWTH_HEAD"'
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
