"""telemetry_backlog_loop 的 Phase 4 + P1 监控扫描函数单元测试。

覆盖 4 个扫描函数：
- _scan_auto_merge_metrics：自动合并成功率追踪
- _scan_security_scan_metrics：安全扫描指标采集
- _scan_coverage_ratchet_gap：覆盖率棘轮差距检测
- _scan_workflow_drift：工作流漂移检测

测试策略：
- _scan_auto_merge_metrics：monkeypatch _load_loop_memory 返回测试数据
- 其余 3 个函数：monkeypatch 模块 __file__ 属性，使其指向临时目录结构，
  从而让 Path(__file__).resolve().parents[3] 指向临时 XCMAX 根目录。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import modstore_server.telemetry_backlog_loop as tbl

# ---------------------------------------------------------------------------
# 辅助：创建临时 XCMAX 根目录结构，使 parents[3] 指向 tmp_root
# 模块文件路径：tmp_root/成都修茈科技有限公司/MODstore_deploy/modstore_server/telemetry_backlog_loop.py
# ---------------------------------------------------------------------------


def _setup_tmp_xcmas_root(tmp_path: Path) -> Path:
    """创建临时 XCMAX 根目录结构，返回应赋给 module.__file__ 的路径。"""
    tmp_root = tmp_path.resolve()
    mod_file = (
        tmp_root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "modstore_server"
        / "telemetry_backlog_loop.py"
    )
    mod_file.parent.mkdir(parents=True, exist_ok=True)
    mod_file.touch()
    return mod_file


@pytest.fixture
def redirected_module(tmp_path, monkeypatch):
    """将 telemetry_backlog_loop.__file__ 重定向到临时目录，使 parents[3] 指向 tmp_root。"""
    mod_file = _setup_tmp_xcmas_root(tmp_path)
    monkeypatch.setattr(tbl, "__file__", str(mod_file))
    return tmp_path.resolve()


# ---------------------------------------------------------------------------
# _scan_auto_merge_metrics
# ---------------------------------------------------------------------------


class TestScanAutoMergeMetrics:
    """自动合并成功率追踪扫描函数测试。"""

    def test_no_memory_returns_empty(self, monkeypatch):
        """_load_loop_memory 返回非 dict 时返回空列表。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: None,
        )
        assert tbl._scan_auto_merge_metrics() == []

    def test_empty_recent_runs_returns_empty(self, monkeypatch):
        """recent_runs 为空时返回空列表。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: {"recent_runs": []},
        )
        assert tbl._scan_auto_merge_metrics() == []

    def test_insufficient_samples_returns_empty(self, monkeypatch):
        """样本不足 3 条时返回空列表。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: {"recent_runs": [{"action": "auto_merge", "status": "completed"}]},
        )
        assert tbl._scan_auto_merge_metrics() == []

    def test_no_auto_merge_runs_returns_empty(self, monkeypatch):
        """无 auto_merge 动作时返回空列表。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: {
                "recent_runs": [
                    {"action": "manual_review", "status": "completed"},
                    {"action": "manual_review", "status": "completed"},
                    {"action": "manual_review", "status": "completed"},
                ]
            },
        )
        assert tbl._scan_auto_merge_metrics() == []

    def test_low_success_rate_triggers_signal(self, monkeypatch):
        """成功率 < 80% 触发 auto_merge_degradation 信号。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: {
                "recent_runs": [
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "auto_merge", "status": "failed"},
                    {"action": "auto_merge", "status": "failed"},
                    {"action": "auto_merge", "status": "failed"},
                    {"action": "auto_merge", "status": "failed"},
                ]
            },
        )
        signals = tbl._scan_auto_merge_metrics()
        assert len(signals) >= 1
        sig = signals[0]
        assert sig["type"] == "auto_merge_degradation"
        assert sig["payload"]["success_rate"] < 80.0

    def test_high_rollback_rate_triggers_signal(self, monkeypatch):
        """回滚率 > 20% 触发 auto_merge_degradation 信号。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: {
                "recent_runs": [
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "manual_review", "status": "rollback"},
                    {"action": "manual_review", "status": "rollback"},
                    {"action": "manual_review", "status": "rollback"},
                ]
            },
        )
        signals = tbl._scan_auto_merge_metrics()
        # 至少有一个回滚率信号
        rollback_sigs = [s for s in signals if "rollback_rate" in s["payload"]]
        assert len(rollback_sigs) >= 1
        assert rollback_sigs[0]["payload"]["rollback_rate"] > 20.0

    def test_healthy_metrics_no_signal(self, monkeypatch):
        """成功率高且无回滚时不触发信号。"""
        monkeypatch.setattr(
            "modstore_server.self_maintenance_loop_runner._load_loop_memory",
            lambda: {
                "recent_runs": [
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "auto_merge", "status": "completed"},
                    {"action": "auto_merge", "status": "completed"},
                ]
            },
        )
        assert tbl._scan_auto_merge_metrics() == []


# ---------------------------------------------------------------------------
# _scan_security_scan_metrics
# ---------------------------------------------------------------------------


class TestScanSecurityScanMetrics:
    """安全扫描指标采集扫描函数测试。"""

    def test_no_metrics_dir_returns_empty(self, redirected_module):
        """FHD/metrics/ 目录不存在时返回空列表。"""
        assert tbl._scan_security_scan_metrics() == []

    def test_empty_metrics_dir_returns_empty(self, redirected_module):
        """FHD/metrics/ 目录为空时返回空列表。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        assert tbl._scan_security_scan_metrics() == []

    def test_gitleaks_findings_triggers_signal(self, redirected_module):
        """gitleaks 发现泄漏时触发 security_scan_alert 信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        sarif = {"runs": [{"results": [{"ruleId": "aws-access-token"}, {"ruleId": "private-key"}]}]}
        (metrics_dir / "gitleaks-2026-06-20.json").write_text(json.dumps(sarif))
        signals = tbl._scan_security_scan_metrics()
        assert len(signals) == 1
        assert signals[0]["type"] == "security_scan_alert"
        assert signals[0]["source"] == "gitleaks_scan"
        assert signals[0]["payload"]["findings"] == 2

    def test_codeql_high_alerts_triggers_signal(self, redirected_module):
        """CodeQL 发现 error 级别告警时触发 security_scan_alert 信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        sarif = {
            "runs": [
                {
                    "results": [
                        {"level": "error", "ruleId": "py/sql-injection"},
                        {"level": "warning", "ruleId": "py/unused-import"},
                    ]
                }
            ]
        }
        (metrics_dir / "codeql-2026-06-20.sarif").write_text(json.dumps(sarif))
        signals = tbl._scan_security_scan_metrics()
        assert len(signals) == 1
        assert signals[0]["source"] == "codeql_scan"
        assert signals[0]["payload"]["high_alerts"] == 1
        assert signals[0]["payload"]["total_alerts"] == 2

    def test_trivy_critical_vulns_triggers_signal(self, redirected_module):
        """Trivy 发现 CRITICAL/HIGH 漏洞时触发 security_scan_alert 信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        trivy = {
            "Results": [
                {
                    "Vulnerabilities": [
                        {"Severity": "CRITICAL"},
                        {"Severity": "HIGH"},
                        {"Severity": "MEDIUM"},
                    ]
                }
            ]
        }
        (metrics_dir / "trivy-2026-06-20.json").write_text(json.dumps(trivy))
        signals = tbl._scan_security_scan_metrics()
        assert len(signals) == 1
        assert signals[0]["source"] == "trivy_scan"
        assert signals[0]["payload"]["critical_high_vulns"] == 2

    def test_old_files_ignored(self, redirected_module):
        """超过 7 天的扫描结果文件被忽略。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        sarif = {"runs": [{"results": [{"ruleId": "test"}]}]}
        old_file = metrics_dir / "gitleaks-2020-01-01.json"
        old_file.write_text(json.dumps(sarif))
        # 设置 mtime 为 30 天前
        old_time = time.time() - 30 * 86400
        os.utime(old_file, (old_time, old_time))
        assert tbl._scan_security_scan_metrics() == []

    def test_no_findings_no_signal(self, redirected_module):
        """扫描结果无发现时不触发信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        sarif = {"runs": [{"results": []}]}
        (metrics_dir / "gitleaks-2026-06-20.json").write_text(json.dumps(sarif))
        assert tbl._scan_security_scan_metrics() == []


# ---------------------------------------------------------------------------
# _scan_coverage_ratchet_gap
# ---------------------------------------------------------------------------


class TestScanCoverageRatchetGap:
    """覆盖率棘轮差距检测扫描函数测试。"""

    def test_no_history_file_returns_empty(self, redirected_module):
        """coverage-history.jsonl 不存在时返回空列表。"""
        assert tbl._scan_coverage_ratchet_gap() == []

    def test_insufficient_records_returns_empty(self, redirected_module):
        """有效记录不足 2 条时返回空列表。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "coverage-history.jsonl").write_text(
            json.dumps({"backend_lines": 80.0, "commit": "abc"}) + "\n"
        )
        assert tbl._scan_coverage_ratchet_gap() == []

    def test_backend_regression_triggers_signal(self, redirected_module):
        """后端覆盖率回退 > 1% 触发 coverage_ratchet_gap 信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        # 最新记录在前（文件按行追加，但函数读取时 reversed，所以最新在最后）
        lines = [
            json.dumps({"backend_lines": 85.0, "commit": "old", "ts": "2026-06-01"}),
            json.dumps({"backend_lines": 80.0, "commit": "new", "ts": "2026-06-20"}),
        ]
        (metrics_dir / "coverage-history.jsonl").write_text("\n".join(lines) + "\n")
        signals = tbl._scan_coverage_ratchet_gap()
        assert len(signals) == 1
        sig = signals[0]
        assert sig["type"] == "coverage_ratchet_gap"
        assert sig["source"] == "coverage_history_backend"
        assert sig["payload"]["delta"] == -5.0
        assert sig["payload"]["latest"] == 80.0
        assert sig["payload"]["previous"] == 85.0

    def test_frontend_regression_triggers_signal(self, redirected_module):
        """前端覆盖率回退 > 1% 触发 coverage_ratchet_gap 信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        lines = [
            json.dumps({"frontend_lines": 30.0, "commit": "old"}),
            json.dumps({"frontend_lines": 25.0, "commit": "new"}),
        ]
        (metrics_dir / "coverage-history.jsonl").write_text("\n".join(lines) + "\n")
        signals = tbl._scan_coverage_ratchet_gap()
        assert len(signals) == 1
        assert signals[0]["source"] == "coverage_history_frontend"

    def test_small_regression_no_signal(self, redirected_module):
        """回退 <= 1% 不触发信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        lines = [
            json.dumps({"backend_lines": 80.5, "commit": "old"}),
            json.dumps({"backend_lines": 80.0, "commit": "new"}),
        ]
        (metrics_dir / "coverage-history.jsonl").write_text("\n".join(lines) + "\n")
        assert tbl._scan_coverage_ratchet_gap() == []

    def test_improvement_no_signal(self, redirected_module):
        """覆盖率提升不触发信号。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        lines = [
            json.dumps({"backend_lines": 80.0, "commit": "old"}),
            json.dumps({"backend_lines": 85.0, "commit": "new"}),
        ]
        (metrics_dir / "coverage-history.jsonl").write_text("\n".join(lines) + "\n")
        assert tbl._scan_coverage_ratchet_gap() == []

    def test_null_values_skipped(self, redirected_module):
        """null 值记录被跳过，查找有效记录。"""
        metrics_dir = redirected_module / "FHD" / "metrics"
        metrics_dir.mkdir(parents=True)
        lines = [
            json.dumps({"backend_lines": 85.0, "commit": "old"}),
            json.dumps({"backend_lines": None, "commit": "mid"}),  # 跳过
            json.dumps({"backend_lines": 80.0, "commit": "new"}),
        ]
        (metrics_dir / "coverage-history.jsonl").write_text("\n".join(lines) + "\n")
        signals = tbl._scan_coverage_ratchet_gap()
        assert len(signals) == 1
        assert signals[0]["payload"]["previous"] == 85.0
        assert signals[0]["payload"]["latest"] == 80.0


# ---------------------------------------------------------------------------
# _scan_workflow_drift
# ---------------------------------------------------------------------------


class TestScanWorkflowDrift:
    """工作流漂移检测扫描函数测试。"""

    def test_no_workflow_dirs_returns_empty(self, redirected_module):
        """workflow 目录不存在时返回空列表。"""
        assert tbl._scan_workflow_drift() == []

    def test_no_drift_returns_empty(self, redirected_module):
        """源文件和生成文件 mtime 一致时返回空列表。"""
        root_wf = redirected_module / ".github" / "workflows"
        fhd_wf = redirected_module / "FHD" / ".github" / "workflows"
        root_wf.mkdir(parents=True)
        fhd_wf.mkdir(parents=True)

        gen_file = root_wf / "fhd-ci-cd.yml"
        src_file = fhd_wf / "ci-cd.yml"
        gen_content = "# CI SSOT: generated from FHD/.github/workflows/ci-cd.yml — DO NOT edit here.\nname: CI/CD\n"
        src_content = "name: CI/CD\n"
        gen_file.write_text(gen_content)
        src_file.write_text(src_content)
        # 同步 mtime（src 稍旧）
        now = time.time()
        os.utime(gen_file, (now, now))
        os.utime(src_file, (now - 10, now - 10))

        assert tbl._scan_workflow_drift() == []

    def test_drift_triggers_signal(self, redirected_module):
        """源文件比生成文件新超过 60 秒时触发 workflow_drift 信号。"""
        root_wf = redirected_module / ".github" / "workflows"
        fhd_wf = redirected_module / "FHD" / ".github" / "workflows"
        root_wf.mkdir(parents=True)
        fhd_wf.mkdir(parents=True)

        gen_file = root_wf / "fhd-ci-cd.yml"
        src_file = fhd_wf / "ci-cd.yml"
        gen_content = "# CI SSOT: generated from FHD/.github/workflows/ci-cd.yml — DO NOT edit here.\nname: CI/CD\n"
        src_content = "name: CI/CD\n"
        gen_file.write_text(gen_content)
        src_file.write_text(src_content)
        # 生成文件旧，源文件新（超过 60 秒）
        old_time = time.time() - 120
        new_time = time.time()
        os.utime(gen_file, (old_time, old_time))
        os.utime(src_file, (new_time, new_time))

        signals = tbl._scan_workflow_drift()
        assert len(signals) == 1
        sig = signals[0]
        assert sig["type"] == "workflow_drift"
        assert sig["payload"]["drifted_count"] == 1
        assert "ci-cd.yml" in sig["payload"]["drifted_files"]

    def test_no_ssot_header_skipped(self, redirected_module):
        """无 CI SSOT 头的文件被跳过。"""
        root_wf = redirected_module / ".github" / "workflows"
        fhd_wf = redirected_module / "FHD" / ".github" / "workflows"
        root_wf.mkdir(parents=True)
        fhd_wf.mkdir(parents=True)

        gen_file = root_wf / "fhd-custom.yml"
        src_file = fhd_wf / "custom.yml"
        # 无 CI SSOT 头
        gen_file.write_text("name: Custom\n")
        src_file.write_text("name: Custom\n")
        old_time = time.time() - 120
        new_time = time.time()
        os.utime(gen_file, (old_time, old_time))
        os.utime(src_file, (new_time, new_time))

        assert tbl._scan_workflow_drift() == []

    def test_source_file_missing_skipped(self, redirected_module):
        """源文件不存在时跳过该生成文件。"""
        root_wf = redirected_module / ".github" / "workflows"
        fhd_wf = redirected_module / "FHD" / ".github" / "workflows"
        root_wf.mkdir(parents=True)
        fhd_wf.mkdir(parents=True)

        gen_file = root_wf / "fhd-ci-cd.yml"
        gen_content = "# CI SSOT: generated from FHD/.github/workflows/ci-cd.yml — DO NOT edit here.\nname: CI/CD\n"
        gen_file.write_text(gen_content)
        # 不创建源文件 ci-cd.yml

        assert tbl._scan_workflow_drift() == []

    def test_multiple_drifts_aggregated(self, redirected_module):
        """多个漂移聚合成一个信号。"""
        root_wf = redirected_module / ".github" / "workflows"
        fhd_wf = redirected_module / "FHD" / ".github" / "workflows"
        root_wf.mkdir(parents=True)
        fhd_wf.mkdir(parents=True)

        old_time = time.time() - 120
        new_time = time.time()

        for src_name, gen_name in [
            ("ci-cd.yml", "fhd-ci-cd.yml"),
            ("deploy.yml", "fhd-deploy.yml"),
        ]:
            gen_file = root_wf / gen_name
            src_file = fhd_wf / src_name
            gen_file.write_text(
                f"# CI SSOT: generated from FHD/.github/workflows/{src_name} — DO NOT edit here.\nname: Test\n"
            )
            src_file.write_text("name: Test\n")
            os.utime(gen_file, (old_time, old_time))
            os.utime(src_file, (new_time, new_time))

        signals = tbl._scan_workflow_drift()
        assert len(signals) == 1
        assert signals[0]["payload"]["drifted_count"] == 2
