"""escalate_to_human.py 单元测试。

覆盖：
- escalate() 调用 post_to_approval_ledger 参数正确（action / source / payload）
- post_to_approval_ledger 返回 None（fail-open）不阻断主流程
- 调用顺序：subprocess.run(comment) → subprocess.run(label) → append_event → post_to_approval_ledger
- subprocess.run 被调用 2 次（comment + label），命令字符串含 issue_number / needs-human
- append_event 被调用且 event_type=escalated_to_human
- GITHUB_REPO 缺失 → RuntimeError
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 把 FHD/scripts/dev 和 FHD/scripts/ci 加入 sys.path
FHD_ROOT = Path(__file__).resolve().parents[2]
DEV_SCRIPTS = FHD_ROOT / "scripts" / "dev"
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
for _p in (DEV_SCRIPTS, CI_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import escalate_to_human as esc  # noqa: E402


# =====================================================================
# fixtures
# =====================================================================


@pytest.fixture
def env_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入必要的 env。"""
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")


@pytest.fixture
def proposal() -> dict:
    return {
        "triggered_by": "ai_issue_implement",
        "summary": "fix bug X",
        "files": ["app/foo.py"],
    }


@pytest.fixture
def failure_reasons() -> list[str]:
    return ["retry 1 failed", "retry 2 failed", "retry 3 failed"]


# =====================================================================
# post_to_approval_ledger 调用
# =====================================================================


class TestLedgerCall:
    def test_ledger_called_with_correct_args(
        self,
        env_ok: None,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        with patch.object(