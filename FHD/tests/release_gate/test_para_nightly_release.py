from datetime import UTC, datetime

import pytest
import yaml

from scripts.release import para_nightly_release as release

SOURCE = "a" * 40
REVIEWED = "b" * 40
MERGE = "c" * 40
CHECK_TIME = datetime(2026, 11, 20, 22, tzinfo=UTC)


def ready_fixtures():
    return {
        "git/ref/heads/main": {"object": {"sha": SOURCE}},
        "pulls/41": {
            "number": 41,
            "merged": True,
            "head": {"sha": REVIEWED},
            "base": {"ref": "main", "repo": {"full_name": release.REPOSITORY}},
            "merge_commit_sha": MERGE,
            "merged_at": "2026-11-20T18:15:00Z",
        },
        f"compare/{MERGE}...{SOURCE}": {"status": "ahead"},
    }


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
    assert workflow["jobs"]["build-private-candidates"]["needs"] == "prepare-version"
