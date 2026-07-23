# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_acceptance.py
"""演化闭环验收测试（Task 13）。

3 个场景：
1. test_acceptance_full_loop_triggers_pack_listed
   端到端：intent_benchmark 低于 0.80 → 信号采集 → LLM 提议 → 开 issue →
   构建 pack → 注册 catalog → ledger pack_listed → owner 用 audit CLI 查询
2. test_acceptance_needs_human_after_3_retries
   3 次 LLM 重试失败 → 调用 escalate_to_human.py CLI → ledger escalated_to_human
3. test_acceptance_high_risk_file_blocks_listing
   pack 含 .env 高风险文件 → evaluate_employee_pack 返回 high → 阻断上架
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# 把 FHD/scripts/dev/ 加入 sys.path，以便导入 escalate_to_human
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FHD_SCRIPTS_DEV = _REPO_ROOT / "FHD" / "scripts" / "dev"
if str(_FHD_SCRIPTS_DEV) not in sys.path:
    sys.path.insert(0, str(_FHD_SCRIPTS_DEV))

from modstore_server.auto_approve_policy import evaluate_employee_pack  # noqa: E402
from modstore_server.build_employee_pack import build_pack_from_commit  # noqa: E402
from modstore_server.employee_autonomy_service import propose_employee_pack  # noqa: E402
from modstore_server.evolution_ledger import append_event, list_events  # noqa: E402
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
        "proposal_id": "acceptance-test-uuid-001",
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


def _run_audit_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(_FHD_SCRIPTS_DEV / "audit_evolution.py"), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


# --------------------------------------------------------------------------- #
# 场景 1：端到端全闭环 → pack_listed + audit CLI 查询
# --------------------------------------------------------------------------- #


def test_acceptance_full_loop_triggers_pack_listed(tmp_path, monkeypatch):
    """端到端：信号采集 → LLM 提议 → 开 issue → 构建 pack → 注册 catalog → ledger
    → owner 用 audit_evolution.py CLI 能查到 pack_listed 事件。"""
    # ---- 1. 准备扫描报告 + 环境变量 ----
    reports_dir = tmp_path / "reports"
    _write_scan_reports(reports_dir)
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(reports_dir / "legacy_report.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(reports_dir / "intent_report.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(reports_dir / "slo_report.json"))

    # ---- 2. 采集信号：intent_benchmark 触发 ----
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
    assert proposal["proposal_id"] == "acceptance-test-uuid-001"
    assert proposal["triggered_by"] == "intent_benchmark"
    assert proposal["signal_score"] > 0

    # ---- 4. mock gh CLI 开 issue ----
    # 注意：必须用 with patch(...) 而非 monkeypatch.setattr，因为
    # gap_to_issue.subprocess IS the subprocess module，monkeypatch 会污染全局
    # subprocess.run，导致后续 _run_audit_cli 的子进程调用也被 mock。
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    fake_issue_url = "https://github.com/owner/repo/issues/42"
    with patch(
        "modstore_server.gap_to_issue.subprocess.run",
        return_value=MagicMock(returncode=0, stdout=fake_issue_url + "\n"),
    ):
        issue_url = open_issue_for_proposal(proposal)
    assert issue_url == fake_issue_url

    # ledger 写了 issue_opened 事件
    issue_events = list_events(event_type="issue_opened")
    assert len(issue_events) == 1
    assert issue_events[0]["issue_url"] == fake_issue_url

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
    deployed_source_dir = files_root / pack_id
    deployed_source_dir.mkdir()
    for source in pack_src_dir.iterdir():
        (deployed_source_dir / source.name).write_bytes(source.read_bytes())
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    # ---- 7. mock git diff / read_pack_file / evaluate_employee_pack ----
    diff_files = [
        f"成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files/{pack_id}/{f.name}"
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
    assert catalog_data["packages"][0]["id"] == "intent-clerk"

    # ledger 末尾是 pack_built 事件，final_status == pack_listed
    all_events = list_events()
    assert len(all_events) >= 2  # 至少 issue_opened + pack_built
    last_event = all_events[-1]
    assert last_event["event_type"] == "pack_built"
    assert last_event["pack_id"] == pack_id
    assert last_event["final_status"] == "pack_listed"

    # ---- 9. owner 用 audit_evolution.py CLI 查询 pack_listed 事件 ----
    cli_env = os.environ.copy()
    cli_env["MODSTORE_EVOLUTION_LEDGER_PATH"] = os.environ.get("MODSTORE_EVOLUTION_LEDGER_PATH", "")
    cli_result = _run_audit_cli("--event", "pack_built", env=cli_env)
    assert cli_result.returncode == 0
    assert pack_id in cli_result.stdout
    assert "pack_listed" in cli_result.stdout


# --------------------------------------------------------------------------- #
# 场景 2：3 次重试失败 → escalate_to_human CLI → needs_human
# --------------------------------------------------------------------------- #


def test_acceptance_needs_human_after_3_retries(tmp_path, monkeypatch):
    """3 次 LLM 重试都失败 → 调用 escalate_to_human.py CLI →
    ledger 有 escalated_to_human 事件，final_status == needs_human。"""
    # ---- 1. 准备环境：隔离 ledger ----
    # conftest 的 _isolate_evolution_ledger 已经设置了 MODSTORE_EVOLUTION_LEDGER_PATH
    # 但本测试需要可控的 ledger 路径，所以重新设置
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    # ---- 2. 直接 append 3 次 implement_failed 事件到 ledger（模拟 3 次重试失败）----
    proposal = _valid_proposal()
    # escalate_to_human.py 从 proposal 中读 triggered_by，需补上
    proposal["triggered_by"] = "intent_benchmark"
    for i in range(3):
        append_event(
            {
                "event_type": "implement_failed",
                "triggered_by": "intent_benchmark",
                "proposal_id": proposal["proposal_id"],
                "retry_count": i + 1,
                "failure_reason": f"synthetic failure #{i + 1}",
                "final_status": "implement_failed",
            }
        )

    # 验证 3 次 implement_failed 已写入
    failed_events = list_events(event_type="implement_failed")
    assert len(failed_events) == 3

    # ---- 3. 调用 escalate_to_human.py CLI ----
    # CLI 参数：--issue-number <int> --proposal <path-to-json> --failure-reasons <json-list>
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
    failure_reasons = json.dumps(
        [
            "retry #1 failed: synthetic failure #1",
            "retry #2 failed: synthetic failure #2",
            "retry #3 failed: synthetic failure #3",
        ]
    )

    # mock escalate_to_human.subprocess.run 避免 gh CLI 真实调用
    # 通过设置环境变量传递 ledger 路径给子进程
    cli_env = os.environ.copy()
    cli_env["MODSTORE_EVOLUTION_LEDGER_PATH"] = str(ledger_path)
    cli_env["GITHUB_REPO"] = "owner/repo"

    # escalate_to_human.py 用 subprocess.run(shell=True) 调 gh，未安装/未认证时
    # 返回非零但 check=False 不抛错，ledger 仍会被写入。
    result = subprocess.run(
        [
            sys.executable,
            str(_FHD_SCRIPTS_DEV / "escalate_to_human.py"),
            "--issue-number",
            "42",
            "--proposal",
            str(proposal_path),
            "--failure-reasons",
            failure_reasons,
        ],
        capture_output=True,
        text=True,
        env=cli_env,
    )
    assert result.returncode == 0, (
        f"escalate_to_human.py CLI failed: rc={result.returncode}, " f"stderr={result.stderr}"
    )

    # ---- 4. 验证 ledger 有 escalated_to_human 事件，final_status == needs_human ----
    all_events = list_events()
    escalated_events = list_events(event_type="escalated_to_human")
    assert len(escalated_events) == 1
    evt = escalated_events[0]
    assert evt["final_status"] == "needs_human"
    assert evt["issue_number"] == 42
    assert evt["triggered_by"] == "intent_benchmark"
    # 末尾事件是 escalated_to_human
    assert all_events[-1]["event_type"] == "escalated_to_human"
    assert all_events[-1]["final_status"] == "needs_human"


# --------------------------------------------------------------------------- #
# 场景 3：高风险文件（.env）阻断上架
# --------------------------------------------------------------------------- #


def test_acceptance_high_risk_file_blocks_listing(tmp_path, monkeypatch):
    """pack 含 .env 高风险文件 → evaluate_employee_pack 返回 high → 阻断上架。"""
    # ---- 1. 准备 pack 目录，包含 manifest.json 和 evil.env ----
    pack_id = "evil-pack@1.0.0"
    pack_dir = tmp_path / "files" / pack_id
    pack_dir.mkdir(parents=True)
    manifest = {
        "name": "evil-pack",
        "version": "1.0.0",
        "department": "engineering",
        "prompt_template": "You are...",
        "skills": ["some-skill"],
        "tools": ["read_file"],
        "acceptance_criteria": ["criterion-1"],
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack_dir / "evil.env").write_text("SECRET_KEY=leaked", encoding="utf-8")

    # ---- 2. 设置 MODSTORE_CATALOG_FILES_ROOT ----
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))

    # ---- 3. 调用 evaluate_employee_pack(pack_id) ----
    risk_level, reason = evaluate_employee_pack(pack_id)

    # ---- 4. 验证返回 ("high", reason 含 evil.env 或 high-risk) ----
    assert risk_level == "high"
    reason_lower = reason.lower()
    assert (
        "evil.env" in reason_lower or "high-risk" in reason_lower
    ), f"reason should mention evil.env or high-risk, got: {reason}"
