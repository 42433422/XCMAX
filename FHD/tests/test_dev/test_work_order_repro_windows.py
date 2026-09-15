"""连接件3 Windows 增量测试：needs_scenario 规格 → 实机注入场景升级 + 安全闸。

覆盖：
- 确定性映射：备份/主库损坏、孤儿端口、双进程、迁移竞态、崩溃 → 对应注入场景
- 无匹配 → upgrade_spec 返回 None（不臆造场景）
- module_import 规格（Mac 已生成可执行用例）原样跳过，不覆盖
- 实机安全闸：数据根落在用户真实 %APPDATA%\\XCAGI → isolated=False，
  --execute 被 blocked_by_safety_gate 拒绝，绝不触碰客户机
- 升级后 scenario 为 dict（中继/知识回流按 dict 消费），command 参数正确
- run_injection 读取 receipt 判定 reproduced（mock 注入脚本，不真跑实机）
- run() 端到端：读 repro 规格 + 诊断文件，升级落盘，幂等（已升级规格跳过）
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_FHD_ROOT = Path(__file__).resolve().parents[2]


def _load_script(relpath: str, name: str) -> Any:
    path = _FHD_ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


win = _load_script("scripts/dev/work_order_repro_windows.py", "work_order_repro_windows")


def _diag(message: str, *, key: str = "d" * 24) -> dict[str, Any]:
    return {
        "dedup_key": key,
        "wo_id": "WO-" + key[:12],
        "errors": [{"message": message, "raw": message, "code": "", "tool": "unknown"}],
        "fixes": [],
    }


def _needs_scenario_spec(key: str = "d" * 24) -> dict[str, Any]:
    return {
        "dedup_key": key,
        "wo_id": "WO-" + key[:12],
        "kind": "none",
        "status": "needs_scenario",
        "scenario": None,
        "signature": {"tool": "unknown", "code": "", "message": "", "file": "", "line": 0},
    }


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("database is malformed", "corrupt-main"),
        ("backup file corrupt, restore failed", "corrupt-backup"),
        ("address already in use on 17500", "kill-orphan"),
        ("second instance already running", "dual-process"),
        ("migration race detected", "migration-mutex"),
        ("unexpected exit crash", "kill-all"),
    ],
)
def test_classify_scenario_rules(message: str, expected: str) -> None:
    scenario, matched = win.classify_scenario(_diag(message))
    assert scenario == expected
    assert matched


def test_classify_no_scenario() -> None:
    scenario, matched = win.classify_scenario(_diag("totally unrelated ui glitch"))
    assert scenario == ""
    assert matched == ""


def test_upgrade_spec_none_when_no_rule_match(tmp_path: Path) -> None:
    spec = _needs_scenario_spec()
    result = win.upgrade_spec(
        spec,
        _diag("unrelated"),
        install_root=str(tmp_path / "acc"),
        data_root=str(tmp_path / "iso"),
        evidence_dir=str(tmp_path / "ev"),
    )
    assert result is None


def test_upgrade_spec_skips_module_import(tmp_path: Path) -> None:
    spec = _needs_scenario_spec()
    spec.update(kind="module_import", status="generated", scenario={"module": "app.x"})
    result = win.upgrade_spec(
        spec,
        _diag("database is malformed"),
        install_root=str(tmp_path / "acc"),
        data_root=str(tmp_path / "iso"),
        evidence_dir=str(tmp_path / "ev"),
    )
    assert result is None  # Mac 已生成可执行用例，不覆盖


def test_upgrade_spec_produces_dict_scenario(tmp_path: Path) -> None:
    spec = _needs_scenario_spec()
    result = win.upgrade_spec(
        spec,
        _diag("database is malformed"),
        install_root=str(tmp_path / "acc"),
        data_root=str(tmp_path / "iso"),
        evidence_dir=str(tmp_path / "ev"),
    )
    assert result is not None
    assert result["kind"] == "windows_fault_injection"
    assert result["status"] == "generated"
    assert isinstance(result["scenario"], dict)  # 中继/知识回流按 dict 消费
    assert result["scenario"]["injection_scenario"] == "corrupt-main"
    assert result["isolated"] is True
    assert result["live_data_root_detected"] is False
    assert "-Scenario" in result["scenario"]["command"]
    assert "corrupt-main" in result["scenario"]["command"]
    assert "-CiMode" in result["scenario"]["command"]


def test_safety_gate_blocks_live_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    live = tmp_path / "XCAGI"
    live.mkdir()
    spec = _needs_scenario_spec()
    result = win.upgrade_spec(
        spec,
        _diag("backup corrupt"),
        install_root=str(tmp_path / "Programs"),
        data_root=str(live),
        evidence_dir=str(tmp_path / "ev"),
    )
    assert result is not None
    assert result["live_data_root_detected"] is True
    assert result["isolated"] is False
    evidence = win.run_injection(result, timeout_seconds=5)
    assert evidence["reproduced"] is False
    assert evidence.get("blocked_by_safety_gate") is True


def test_run_injection_reads_reproduced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _needs_scenario_spec()
    result = win.upgrade_spec(
        spec,
        _diag("database is malformed"),
        install_root=str(tmp_path / "acc"),
        data_root=str(tmp_path / "iso"),
        evidence_dir=str(tmp_path / "ev"),
    )
    assert result is not None
    receipt = {"summary": {"pass": 1, "fail": 0, "partial": 0, "skip": 0}}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(_cmd: list[str], **_kw: Any) -> _Proc:
        ev = Path(result["scenario"]["evidence_dir"])
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "fault-injection-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return _Proc()

    monkeypatch.setattr(win.subprocess, "run", _fake_run)
    evidence = win.run_injection(result, timeout_seconds=5)
    assert evidence["reproduced"] is True
    assert evidence["receipt"] == receipt


def test_run_upgrades_and_is_idempotent(tmp_path: Path) -> None:
    repro_dir = tmp_path / "repro"
    repro_dir.mkdir()
    diag_dir = tmp_path / "diagnosis"
    diag_dir.mkdir()
    key = "a" * 24
    key12 = key[:12]
    (repro_dir / f"repro-{key12}.json").write_text(
        json.dumps(_needs_scenario_spec(key)), encoding="utf-8"
    )
    (diag_dir / f"diagnosis-{key12}.json").write_text(
        json.dumps(_diag("unexpected exit crash", key=key)), encoding="utf-8"
    )
    args = SimpleNamespace(
        repro_dir=str(repro_dir),
        diagnosis_dir=str(diag_dir),
        install_root=str(tmp_path / "acc"),
        data_root=str(tmp_path / "iso"),
        max=20,
        timeout=900,
        execute=False,
    )
    assert win.run(args) == 0
    upgraded = json.loads((repro_dir / f"repro-{key12}.json").read_text(encoding="utf-8"))
    assert upgraded["kind"] == "windows_fault_injection"
    assert upgraded["scenario"]["injection_scenario"] == "kill-all"
    # 幂等：已升级规格（kind 非 none）再次运行跳过，保留内容
    (repro_dir / f"repro-{key12}.json").write_text("SENTINEL", encoding="utf-8")
    assert win.run(args) == 0
    assert (repro_dir / f"repro-{key12}.json").read_text(encoding="utf-8") == "SENTINEL"
