# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type, var-annotated"
"""Coverage-ratchet and generated-workflow drift scanners."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["modstore_server.telemetry_backlog_loop"]


def _scan_coverage_ratchet_gap() -> List[Dict[str, Any]]:
    """扫描覆盖率历史，检测棘轮回退。

    数据源：FHD/metrics/coverage-history.jsonl
    信号类型：coverage_ratchet_gap（覆盖率回退 > 1% 时触发）
    """
    signals = []
    try:
        import json
        from pathlib import Path

        repo_root = Path(_facade().__file__).resolve().parents[3]
        history_file = repo_root / "FHD" / "metrics" / "coverage-history.jsonl"
        if not history_file.is_file():
            return signals
        lines = history_file.read_text(encoding="utf-8").splitlines()
        records = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    records.append(rec)
            except json.JSONDecodeError:
                continue
            if len(records) >= 10:
                break
        if len(records) < 2:
            return signals

        def _valid_rec(rec: _facade().Dict[str, _facade().Any]) -> bool:
            return rec.get("backend_lines") is not None or rec.get("frontend_lines") is not None

        valid = [r for r in records if _valid_rec(r)]
        if len(valid) < 2:
            return signals
        latest = valid[0]
        prev = valid[1]
        latest_be = latest.get("backend_lines")
        prev_be = prev.get("backend_lines")
        if isinstance(latest_be, (int, float)) and isinstance(prev_be, (int, float)):
            delta = latest_be - prev_be
            if delta < -1.0:
                signals.append(
                    {
                        "type": "coverage_ratchet_gap",
                        "source": "coverage_history_backend",
                        "payload": {
                            "latest": latest_be,
                            "previous": prev_be,
                            "delta": round(delta, 2),
                            "dimension": "backend_lines",
                            "latest_commit": latest.get("commit", "unknown"),
                            "previous_commit": prev.get("commit", "unknown"),
                            "description": f"后端行覆盖率回退 {abs(delta):.2f}%（{prev_be:.2f}% → {latest_be:.2f}%）",
                        },
                    }
                )
        latest_fe = latest.get("frontend_lines")
        prev_fe = prev.get("frontend_lines")
        if isinstance(latest_fe, (int, float)) and isinstance(prev_fe, (int, float)):
            delta = latest_fe - prev_fe
            if delta < -1.0:
                signals.append(
                    {
                        "type": "coverage_ratchet_gap",
                        "source": "coverage_history_frontend",
                        "payload": {
                            "latest": latest_fe,
                            "previous": prev_fe,
                            "delta": round(delta, 2),
                            "dimension": "frontend_lines",
                            "latest_commit": latest.get("commit", "unknown"),
                            "previous_commit": prev.get("commit", "unknown"),
                            "description": f"前端行覆盖率回退 {abs(delta):.2f}%（{prev_fe:.2f}% → {latest_fe:.2f}%）",
                        },
                    }
                )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("coverage ratchet gap scan skipped")
    return signals


def _scan_workflow_drift() -> List[Dict[str, Any]]:
    """检测 GitHub Actions workflow 漂移（根仓 SSOT 与源文件不一致）。

    数据源：根仓 .github/workflows/fhd-*.yml 与 FHD/.github/workflows/*.yml
    信号类型：workflow_drift（源文件比生成文件新时触发）
    """
    signals = []
    try:
        from pathlib import Path

        repo_root = Path(_facade().__file__).resolve().parents[3]
        root_wf = repo_root / ".github" / "workflows"
        fhd_wf = repo_root / "FHD" / ".github" / "workflows"
        if not root_wf.is_dir() or not fhd_wf.is_dir():
            return signals
        drifted = []
        for gen_file in root_wf.glob("fhd-*.yml"):
            try:
                header = gen_file.read_text(encoding="utf-8").splitlines()[:3]
            except OSError:
                continue
            src_name = None
            for line in header:
                if "generated from" in line:
                    marker = "FHD/.github/workflows/"
                    idx = line.find(marker)
                    if idx >= 0:
                        rest = line[idx + len(marker) :]
                        end = rest.find(".yml")
                        if end >= 0:
                            src_name = rest[: end + len(".yml")]
                    break
            if not src_name:
                continue
            src_file = fhd_wf / src_name
            if not src_file.is_file():
                continue
            gen_mtime = gen_file.stat().st_mtime
            src_mtime = src_file.stat().st_mtime
            if src_mtime - gen_mtime > 60:
                drifted.append(
                    {
                        "generated": gen_file.name,
                        "source": src_name,
                        "source_mtime": src_mtime,
                        "generated_mtime": gen_mtime,
                    }
                )
        if drifted:
            drift_list = ", ".join((d["source"] for d in drifted[:5]))
            signals.append(
                {
                    "type": "workflow_drift",
                    "source": "workflow_sync_check",
                    "payload": {
                        "drifted_count": len(drifted),
                        "drifted_files": drift_list,
                        "description": f"检测到 {len(drifted)} 个 workflow 漂移（源文件更新但未同步到根仓）：{drift_list}",
                    },
                }
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("workflow drift scan skipped")
    return signals
