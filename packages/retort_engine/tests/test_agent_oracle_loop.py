from pathlib import Path

from retort_engine.agent_oracle_loop import run_agent_oracle_loop


def test_agent_oracle_loop_completes_on_heldout_fail_to_pass() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_agent_oracle_loop(root, run_id="unit-agent-oracle")
    assert result["status"] == "ready"
    assert result["summary"]["completed"] is True
    assert result["summary"]["oracle_all_resolved"] is True
    assert result["summary"]["process_group_runner"] is True
    assert result["loop"]["status"] == "complete"
