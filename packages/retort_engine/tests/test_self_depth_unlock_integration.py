from pathlib import Path
from unittest.mock import patch

import pytest
from retort_engine.absorption import RetortAbsorptionRunner
from retort_engine.core import absorb
from retort_engine.models import ExternalProjectRef
from retort_engine.self_bootstrap import (
    build_self_depth_report,
    external_improvement_gate,
    package_root,
)


@pytest.mark.keep_self_depth_gate
def test_real_package_self_depth_can_unlock_other_modules() -> None:
    root = package_root()
    report = build_self_depth_report(root)
    assert report["summary"]["behavior_layer_passed_count"] == 4
    assert report["comparative_benchmark"]["passed"] is True
    # Unlock requires recorded sources + landing; the checked-in package should satisfy after phase6.
    if report["external_improvement_allowed"]:
        assert (
            external_improvement_gate(root, root / "other-module-placeholder")["status"]
            == "allowed"
        )
        assert report["status"] == "strongest_depth_verified"
    else:
        assert report["summary"]["missing"]


@pytest.mark.keep_self_depth_gate
def test_apply_and_core_absorb_share_self_depth_gate(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    blocked = {"status": "blocked", "missing": ["behavior:x"], "reason": "locked"}
    with patch("retort_engine.core.external_improvement_gate", return_value=blocked):
        core_result = absorb(
            {"own_project": str(other), "github_url": "https://github.com/example/x"}
        )
    assert core_result["status"] == "blocked_by_self_depth_gate"

    with patch(
        "retort_engine.absorption.external_improvement_gate", return_value=blocked
    ):
        runner = RetortAbsorptionRunner()
        result = runner.run(
            own_project=str(other),
            external_ref=ExternalProjectRef(
                source="https://github.com/example/x",
                source_type="path",
                local_path=str(other),
            ),
        )
    assert result.status == "blocked_by_self_depth_gate"
