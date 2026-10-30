"""Run nightly aggregation against transport stubs, including downstream failures."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("failure", ["none", "dispatch", "watch", "source", "event"])
def test_nightly_requires_matching_downstream_success(tmp_path, failure):
    runs = [
        {
            "databaseId": 7,
            "createdAt": "2099-01-01T00:00:00Z",
            "headSha": ("b" if failure == "source" else "a") * 40,
            "event": "push" if failure == "event" else "workflow_dispatch",
        }
    ]
    gh = tmp_path / "gh"
    gh.write_text("""#!/bin/bash
case "$1 $2" in
  "workflow run") [ "$FAILURE" != dispatch ] ;;
  "run list") printf '%s' "$RUNS" ;;
  "run watch") [ "$3" = 7 ] && [ "$FAILURE" != watch ] ;;
  "run view") echo failure ;;
  *) exit 3 ;;
esac
""")
    gh.chmod(0o700)
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/bash\nexit 0\n")
    sleep.chmod(0o700)
    result = subprocess.run(
        ["bash", str(ROOT / "FHD/scripts/ci/aggregate_nightly_results.sh")],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "GH_TOKEN": "test-token",
            "REF": "main",
            "RELEASE_SHA": "a" * 40,
            "GITHUB_REPOSITORY": "example/test",
            "FAILURE": failure,
            "RUNS": json.dumps(runs),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is (failure == "none"), result.stderr
    assert ("aggregate PASS" in result.stdout) is (failure == "none")


def test_nightly_workflow_calls_the_aggregate_script():
    for path in (
        "FHD/.github/workflows/nightly-full.yml",
        ".github/workflows/fhd-nightly-full.yml",
    ):
        workflow = yaml.safe_load((ROOT / path).read_text())
        job = workflow["jobs"]["dispatch-nightly"]
        assert any("aggregate_nightly_results.sh" in s.get("run", "") for s in job["steps"])
