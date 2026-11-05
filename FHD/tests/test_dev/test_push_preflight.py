"""push_preflight 纯函数单测：与 CI changelog 门禁同口径、只认 Unreleased 节的新增行。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev import push_preflight as pf  # noqa: E402


def test_product_patterns_follow_ci_gate():
    patterns = pf.product_patterns(pf.GATE_WORKFLOW.read_text(encoding="utf-8"))
    assert "FHD/app/**" in patterns and "FHD/VERSION.md" in patterns


def test_unreleased_range_stops_at_next_release():
    text = "# 日志\n\n## Unreleased\n- 新条目\n\n## 1.0.0.4\n- 旧条目\n"
    assert pf.unreleased_range(text) == (3, 5)
    assert pf.unreleased_range("# 日志\n## 1.0.0.4\n") is None


def test_added_line_numbers_skip_blank_and_header():
    diff = "--- a/x\n+++ b/x\n@@ -3,0 +4,2 @@\n+- 新条目\n+\n@@ -9 +11 @@\n-旧\n+- 另一条\n"
    assert pf.added_line_numbers(diff) == [4, 11]
