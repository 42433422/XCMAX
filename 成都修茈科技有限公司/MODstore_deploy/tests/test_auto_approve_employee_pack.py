# 成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_employee_pack.py
"""auto_approve_policy.evaluate_employee_pack 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

from modstore_server.auto_approve_policy import evaluate_employee_pack


def _setup_pack(tmp_path: Path, pack_id: str = "test-pack@1.0.0", files: list = None) -> Path:
    """创建测试 employee_pack 目录。"""
    pack_dir = tmp_path / "files" / pack_id
    pack_dir.mkdir(parents=True)
    default_files = files or [
        (
            "manifest.json",
            json.dumps({"name": "test-pack", "version": "1.0.0", "department": "engineering"}),
        ),
        ("prompt.txt", "You are..."),
        ("skills.json", "[]"),
    ]
    for name, content in default_files:
        target = pack_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return pack_dir


def test_evaluate_employee_pack_low_risk_approved(tmp_path, monkeypatch):
    _setup_pack(tmp_path)
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "low"
    assert "approved" in reason.lower() or "auto" in reason.lower()


def test_evaluate_employee_pack_rejects_env_file(tmp_path, monkeypatch):
    _setup_pack(
        tmp_path,
        files=[
            ("manifest.json", "{}"),
            ("evil.env", "SECRET=value"),
        ],
    )
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "high"
    assert "evil.env" in reason or "high-risk" in reason


def test_evaluate_employee_pack_rejects_workflow_file(tmp_path, monkeypatch):
    _setup_pack(
        tmp_path,
        files=[
            ("manifest.json", "{}"),
            (".github/workflows/evil.yml", "name: evil"),
        ],
    )
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "high"


def test_evaluate_employee_pack_rejects_more_than_5_files(tmp_path, monkeypatch):
    _setup_pack(tmp_path, files=[(f"f{i}.txt", "x") for i in range(7)])
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "high"
    assert "5" in reason or "files" in reason.lower()


def test_evaluate_employee_pack_handles_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("nonexistent@1.0.0")
    assert risk_level == "high"
    assert "not found" in reason.lower() or "missing" in reason.lower()
