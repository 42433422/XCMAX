from __future__ import annotations

from retort_engine.pr_review import parse_unified_diff
from retort_engine.static_analysis_gate import scan_static_analysis_findings


def test_static_analysis_gate_detects_high_risk_added_lines() -> None:
    diff = """diff --git a/app/run.py b/app/run.py
--- a/app/run.py
+++ b/app/run.py
@@ -0,0 +1,4 @@
+eval(user_input)
+subprocess.run(command, shell=True)
+yaml.load(payload)
+requests.get(url, verify=False)
"""

    report = scan_static_analysis_findings(parse_unified_diff(diff))

    assert report["status"] == "blocked"
    assert report["summary"]["high_count"] == 4
    assert {finding["rule_id"] for finding in report["findings"]} == {
        "python-eval-exec",
        "subprocess-shell-true",
        "unsafe-yaml-load",
        "tls-verify-disabled",
    }


def test_static_analysis_gate_allows_safe_yaml_loader() -> None:
    diff = """diff --git a/app/config.py b/app/config.py
--- a/app/config.py
+++ b/app/config.py
@@ -0,0 +1 @@
+yaml.load(payload, Loader=yaml.SafeLoader)
"""

    report = scan_static_analysis_findings(parse_unified_diff(diff))

    assert report["status"] == "clean"
    assert report["findings"] == []
