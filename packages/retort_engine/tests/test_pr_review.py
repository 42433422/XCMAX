from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.pr_review import parse_unified_diff, review_diff


SAMPLE_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def handler():
+    api_key = "live-secret"
+    # TODO: replace with real absorption action
     return True
"""


def test_review_diff_returns_line_comments_and_groups() -> None:
    result = review_diff(SAMPLE_DIFF)
    severities = {comment["severity"] for comment in result["comments"]}

    assert result["status"] == "reviewed"
    assert result["summary"]["ready_for_employee_tasking"] is True
    assert {"high", "medium"}.issubset(severities)
    assert result["task_groups"]
    assert validate_contract("pr_review_result", result)["valid"] is True


def test_parse_unified_diff_keeps_new_line_numbers() -> None:
    files = parse_unified_diff(SAMPLE_DIFF)
    added = [change for change in files[0]["hunks"][0]["changes"] if change["type"] == "add"]

    assert files[0]["path"] == "app.py"
    assert [change["line"] for change in added] == [2, 3]


def test_review_diff_cli_outputs_contract(tmp_path: Path) -> None:
    diff_file = tmp_path / "change.diff"
    diff_file.write_text(SAMPLE_DIFF, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "review-diff", "--diff-file", str(diff_file), "--json"],
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)

    assert payload["summary"]["comment_count"] >= 2
    assert validate_contract("pr_review_result", payload)["valid"] is True
