# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_e2e.py
"""演化闭环端到端集成测试。

覆盖两个 E2E 场景：
1. 全链路（信号采集 → LLM 提议 → 开 issue → 构建 pack → 注册 catalog → ledger）
2. 重试 3 次失败 → final_status=needs_human（ledger 末尾 implement_failed）

依赖 mock：
- employee_autonomy_service._call_llm（LLM 提议）
- gap_to_issue.subprocess.run（gh CLI）
- build_employee_pack._get_commit_diff_files / _read_pack_file / evaluate_employee_pack
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# 把 FHD/scripts/dev/ 加入 sys.path，以便导入 retry_with_adjusted_prompt
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FHD_SCRIPTS_DEV = _REPO_ROOT / "FHD" / "scripts" / "dev"
if str(_FHD_SCRIPTS_DEV) not in sys.path:
    sys.path.insert(0, str(_FHD_SCRIPTS_DEV))

from retry_with_adjusted_prompt import run_with_retries  # noqa: E402

from modstore_server.build_employee_pack import build_pack_from_commit  # noqa: E402
from modstore_server.employee_autonomy_service import propose_employee_pack  # noqa: E402
from modstore_server.evolution_ledger import list_events  # noqa: E402
from modstore_server.evolution_signal_collector import aggregate_signals  # noqa: E402
from modstore_server.gap_to_issue import open_issue_for_proposal  # noqa: E402


def _write_scan_reports(reports_dir: Path) -> None:
    """伪造 3 个扫描类 workflow 的 JSON 报告：intent 触发，legacy/SLO 不触发。"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "legacy_report.json").write_text(
        json.dumps({"legacy_ratio": 0.10, "total_files": 100, "legacy_files": 10}),
        encoding="utf-8",
    )
    (reports_dir / "intent_report.json").write_text(
        json.dumps({"accuracy": 0.72, "test_cases": 200, "failures": 56}),
        encoding="utf-8",
    )
    (reports_dir / "slo_report.json").write_text(
        json.dumps({"availability": 0.992, "error_rate": 0.005}),
        encoding="utf-8",
    )


def _valid_proposal() -> dict:
    """构造一个能通过 validate_proposal 的合法提议。"""
    return {
        "proposal_id": "e2e-test-uuid-001",
        "department": "engineering",
        "employee_pack": {
            "name": "intent-failure-triage-clerk",
            "responsibility": "scan failed intent cases and cluster failure patterns",
            "prompt_template": "You are an intent failure triage clerk...",
            "skills": ["intent-benchmark", "failure-clustering"],
            "tools": ["read_file", "write_pr_comment"],
            "acceptance_criteria": ["recall >= 0.7 on test set"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


def test_e2e_full_loop_with_mock_llm(tmp_path, monkeypatch):
    """端到端：信号采集 → LLM 提议 → 开 issue → 构建 pack → 注册 catalog → ledger。"""
    # ---- 1. 准备扫描报告 + 环境变量 ----
    reports_dir = tmp_path / "reports"
    _write_scan_reports(reports_dir)
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(reports_dir / "legacy_report.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(reports_dir / "intent_report.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(reports_dir / "slo_report.json"))

    # ---- 2. 采集信号 ----
    signals = aggregate_signals()
    assert signals["signals_to_propose"] >= 1
    assert signals["intent_benchmark"]["below_threshold"] is True
    assert signals["intent_benchmark"]["signal_score"] > 0
    # legacy / slo 不触发
    assert signals["legacy_usage"]["signal_score"] == 0
    assert signals["slo_metrics"]["signal_score"] == 0

    # ---- 3. mock LLM 生成提议 ----
    with patch("modstore_server.employee_autonomy_service._call_llm") as mock_llm:
        mock_llm.return_value = _valid_proposal()
        proposal = propose_employee_pack(signals)
    assert proposal is not None
    assert proposal["proposal_id"] == "e2e-test-uuid-001"
    assert proposal["triggered_by"] == "intent_benchmark"
    assert proposal["signal_score"] > 0

    # ---- 4. mock gh CLI 开 issue ----
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    fake_issue_url = "https://github.com/owner/repo/issues/42"
    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout=fake_issue_url + "\n"))
    monkeypatch.setattr("modstore_server.gap_to_issue.subprocess.run", mock_run)

    issue_url = open_issue_for_proposal(proposal)
    assert issue_url == fake_issue_url

    # ledger 写了 issue_opened 事件
    issue_events = list_events(event_type="issue_opened")
    assert len(issue_events) == 1
    assert issue_events[0]["issue_url"] == fake_issue_url
    assert issue_events[0]["llm_proposal"]["proposal_id"] == "e2e-test-uuid-001"

    # ---- 5. 准备 pack 文件 ----
    pack_id = "intent-clerk@1.0.0"
    pack_src_dir = tmp_path / "pack_src" / pack_id
    pack_src_dir.mkdir(parents=True)
    manifest = {
        "name": "intent-clerk",
        "version": "1.0.0",
        "department": "engineering",
        "prompt_template": "You are an intent clerk...",
        "skills": ["intent-benchmark"],
        "tools": ["read_file"],
        "acceptance_criteria": ["recall >= 0.7"],
    }
    (pack_src_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack_src_dir / "prompt.txt").write_text("You are an intent clerk...", encoding="utf-8")

    # ---- 6. 配置 catalog 路径 ----
    catalog_path = tmp_path / "catalog_data" / "packages.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    # ---- 7. mock git diff / read_pack_file / evaluate_employee_pack ----
    diff_files = [
        f"成都修茈科技有限公司/MODstore_deploy/catalog_data/files/{pack_id}/{f.name}"
        for f in pack_src_dir.iterdir()
    ]

    def fake_read_pack_file(rel_path: str, _repo_root: Path) -> str:
        rel = rel_path.split(f"{pack_id}/", 1)[1]
        return (pack_src_dir / rel).read_text(encoding="utf-8")

    with (
        patch(
            "modstore_server.build_employee_pack._get_commit_diff_files",
            return_value=diff_files,
        ),
        patch(
            "modstore_server.build_employee_pack._read_pack_file",
            side_effect=fake_read_pack_file,
        ),
        patch(
            "modstore_server.build_employee_pack.evaluate_employee_pack",
            return_value=("low", "auto-approved"),
        ),
    ):
        result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)

    # ---- 8. 验证 build_pack_from_commit 结果 ----
    assert result["approved"] is True
    assert result["pack_id"] == pack_id
    assert result["risk_level"] == "low"

    # catalog_data/packages.json 注册了新 pack
    catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog_data["packages"]) == 1
    assert catalog_data["packages"][0]["id"] == pack_id

    # ledger 末尾是 pack_built 事件
    all_events = list_events()
    assert len(all_events) >= 2  # 至少有 issue_opened + pack_built
    last_event = all_events[-1]
    assert last_event["event_type"] == "pack_built"
    assert last_event["pack_id"] == pack_id
    assert last_event["final_status"] == "pack_listed"


def test_e2e_retries_3_times_then_escalates(tmp_path, monkeypatch):
    """重试 3 次失败 → final_status=needs_human，ledger 末尾是 implement_failed。"""
    # ---- 准备信号环境（intent 触发）----
    reports_dir = tmp_path / "reports"
    _write_scan_reports(reports_dir)
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(reports_dir / "legacy_report.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(reports_dir / "intent_report.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(reports_dir / "slo_report.json"))

    signals = aggregate_signals()
    assert signals["signals_to_propose"] >= 1

    # ---- mock LLM 返回合法 proposal ----
    with patch("modstore_server.employee_autonomy_service._call_llm") as mock_llm:
        mock_llm.return_value = _valid_proposal()
        proposal = propose_employee_pack(signals)
    assert proposal is not None

    # ---- mock gh CLI 开 issue ----
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(
        "modstore_server.gap_to_issue.subprocess.run",
        MagicMock(
            return_value=MagicMock(returncode=0, stdout="https://github.com/owner/repo/issues/42\n")
        ),
    )
    issue_url = open_issue_for_proposal(proposal)
    assert "issues/42" in issue_url

    # ---- 调用 run_with_retries：action 总是返回失败结果 ----
    def always_fail_action(_prompt: str) -> dict:
        return {"ok": False, "error": "synthetic failure for e2e"}

    def always_fail_checker(result: dict):
        return (True, result.get("error") or "unknown")

    result = run_with_retries(
        base_prompt="base prompt for implement",
        action=always_fail_action,
        failure_checker=always_fail_checker,
        proposal=proposal,
    )

    # ---- 验证返回值 ----
    assert result["success"] is False
    assert result["attempts"] == 3
    assert result["final_status"] == "needs_human"

    # ---- ledger 末尾是 implement_failed，final_status=needs_human ----
    all_events = list_events()
    implement_failed_events = [e for e in all_events if e["event_type"] == "implement_failed"]
    # 3 次重试 + 1 次最终升级 = 4 个 implement_failed 事件
    assert len(implement_failed_events) == 4
    last_event = all_events[-1]
    assert last_event["event_type"] == "implement_failed"
    assert last_event["final_status"] == "needs_human"
    assert last_event["retry_count"] == 3
