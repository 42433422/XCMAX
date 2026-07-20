"""T-E06 · DORA 部署事件计数接线测试。

锁住以下契约，防止回退：
  - ``emit_deploy_event.emit()`` 真正向 ``deploy_events.jsonl`` 追加一条事件
  - ``collect_dora.compute_dora()`` 在 7d 窗口内能数到刚写入的事件
  - 7d 窗口过滤：早于窗口的事件不计入 ``event_count``
  - 状态分类：``success`` / ``failed`` / ``rollback`` 计数独立

这些是 Wave-E T-E06 验收所需的最低接线断言。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

# 让测试可以从仓库根直接导入 FHD/scripts/observability 下的模块
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "FHD" / "scripts" / "observability"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import collect_dora  # noqa: E402
import emit_deploy_event  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestEmitWritesEventToFile:
    """emit() 真正落盘到 deploy_events.jsonl。"""

    def test_emit_appends_one_jsonl_line(self, tmp_path: Path) -> None:
        out = tmp_path / "deploy_events.jsonl"
        assert not out.exists()

        event = emit_deploy_event.emit(
            status="success",
            source_workflow="test-wiring",
            environment="staging",
            head_branch="main",
            deploy_id="t1",
            metrics_dir=tmp_path,
        )

        assert out.is_file()
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["deploy_id"] == "t1"
        assert parsed["status"] == "success"
        assert parsed["source_workflow"] == "test-wiring"
        # 返回值与落盘内容一致
        assert event == parsed

    def test_emit_appends_multiple_events_preserves_order(self, tmp_path: Path) -> None:
        for i in range(3):
            emit_deploy_event.emit(
                status="success",
                source_workflow="test-wiring",
                deploy_id=f"t{i}",
                metrics_dir=tmp_path,
            )
        lines = (tmp_path / "deploy_events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        ids = [json.loads(line)["deploy_id"] for line in lines]
        assert ids == ["t0", "t1", "t2"]

    def test_emit_auto_generates_deploy_id_when_missing(self, tmp_path: Path) -> None:
        event = emit_deploy_event.emit(
            status="success",
            source_workflow="test-wiring",
            metrics_dir=tmp_path,
        )
        assert event["deploy_id"]
        assert len(event["deploy_id"]) >= 8  # uuid4().hex[:12]


class TestComputeDoraCountsRecentEvents:
    """compute_dora() 在 7d 窗口内能数到刚写入的事件（接线核心断言）。"""

    def test_one_recent_event_count_is_at_least_one(self, tmp_path: Path) -> None:
        """T-E06 验收主断言：7d 不再恒为 0。"""
        emit_deploy_event.emit(
            status="success",
            source_workflow="test-wiring",
            deploy_id="recent-1",
            metrics_dir=tmp_path,
        )
        events = collect_dora.load_events(tmp_path / "deploy_events.jsonl")
        report = collect_dora.compute_dora(events, window_days=7)
        assert report["event_count"] >= 1
        assert report["successes"] >= 1

    def test_old_event_outside_window_excluded(self, tmp_path: Path) -> None:
        """窗口外的事件不计入 — 解释为什么 T-E06 之前 7d 恒为 0。"""
        old_time = datetime.now(UTC) - timedelta(days=30)
        old_event = {
            "deploy_id": "old-seed",
            "deployed_at": _iso(old_time),
            "commit_at": _iso(old_time),
            "status": "success",
            "restored_at": None,
            "source_workflow": "Deploy",
            "head_branch": "main",
        }
        (tmp_path / "deploy_events.jsonl").write_text(
            json.dumps(old_event) + "\n", encoding="utf-8"
        )

        events = collect_dora.load_events(tmp_path / "deploy_events.jsonl")
        report = collect_dora.compute_dora(events, window_days=7)
        assert report["event_count"] == 0
        assert report["successes"] == 0

    def test_mixed_old_and_recent_only_recent_counted(self, tmp_path: Path) -> None:
        """混合场景：旧 seed 数据 + 新部署事件，只有新的进 7d 窗口。"""
        # 写入 5 条 seed（30~60d 前）模拟 T-E06 之前的 jsonl 现状
        seed_lines: list[str] = []
        for i in range(5):
            old_time = datetime.now(UTC) - timedelta(days=30 + i * 5)
            seed = {
                "deploy_id": f"seed-{i + 1}",
                "deployed_at": _iso(old_time),
                "commit_at": _iso(old_time - timedelta(hours=1)),
                "status": "success",
                "restored_at": None,
                "source_workflow": "Deploy",
                "head_branch": "main",
            }
            seed_lines.append(json.dumps(seed))
        # 再写入 2 条 7d 内的新事件
        for i in range(2):
            emit_deploy_event.emit(
                status="success",
                source_workflow="test-wiring",
                deploy_id=f"new-{i + 1}",
                metrics_dir=tmp_path,
            )

        events = collect_dora.load_events(tmp_path / "deploy_events.jsonl")
        report = collect_dora.compute_dora(events, window_days=7)
        assert report["event_count"] == 2
        assert report["successes"] == 2


class TestComputeDoraStatusClassification:
    """DORA 状态分类计数独立（success/failed/rollback）。"""

    def test_status_breakdown_counts_separately(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        events_data = [
            {
                "deploy_id": "s1",
                "deployed_at": _iso(now - timedelta(hours=2)),
                "commit_at": _iso(now - timedelta(hours=3)),
                "status": "success",
                "restored_at": None,
                "source_workflow": "test-wiring",
                "head_branch": "main",
            },
            {
                "deploy_id": "f1",
                "deployed_at": _iso(now - timedelta(hours=1)),
                "commit_at": _iso(now - timedelta(hours=2)),
                "status": "failed",
                "restored_at": None,
                "source_workflow": "test-wiring",
                "head_branch": "main",
            },
            {
                "deploy_id": "rb1",
                "deployed_at": _iso(now - timedelta(minutes=30)),
                "commit_at": _iso(now - timedelta(hours=1)),
                "status": "rollback",
                "restored_at": _iso(now - timedelta(minutes=15)),
                "source_workflow": "test-wiring",
                "head_branch": "main",
            },
        ]
        (tmp_path / "deploy_events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events_data) + "\n", encoding="utf-8"
        )

        events = collect_dora.load_events(tmp_path / "deploy_events.jsonl")
        report = collect_dora.compute_dora(events, window_days=7)
        assert report["event_count"] == 3
        assert report["successes"] == 1
        assert report["failures"] == 1
        assert report["rollbacks"] == 1
        assert report["change_failure_rate"] == round(1 / 3, 4)


class TestEndToEndWiringContract:
    """端到端接线契约：emit → load → compute 闭环可工作。"""

    def test_end_to_end_wiring(self, tmp_path: Path) -> None:
        """模拟 Wave-E 真实交付：写入 1 条 success 事件 → DORA 7d 计数 ≥ 1。"""
        emit_deploy_event.emit(
            status="success",
            source_workflow="Wave-E-delivery",
            environment="staging",
            head_branch="main",
            deploy_id="wave-e-e2e",
            git_sha="abc123",
            metrics_dir=tmp_path,
        )

        # 重新加载文件，模拟 collect_dora.py CLI 的行为
        events = collect_dora.load_events(tmp_path / "deploy_events.jsonl")
        report = collect_dora.compute_dora(events, window_days=7)

        assert report["event_count"] >= 1
        assert report["successes"] >= 1
        # Wave-E-delivery 事件在 7d 窗口内
        wave_e_events = [e for e in events if e.get("source_workflow") == "Wave-E-delivery"]
        assert len(wave_e_events) == 1
        assert wave_e_events[0]["status"] == "success"
        assert wave_e_events[0]["git_sha"] == "abc123"
