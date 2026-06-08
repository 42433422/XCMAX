"""测试 employee_pack 双身份产物：.xcemp 作为 Python zipapp 独立运行。

验证：
  1. _build_employee_pack_zip_with_source 生成的 zip 包含 __main__.py 与 standalone/
  2. python xxx.xcemp info   → 退出码 0，输出 id/name
  3. python xxx.xcemp validate → 退出码 0，输出 "validate: OK"
  4. python xxx.xcemp run    → 退出码 0，返回 JSON {"ok": true}
  5. 旧的平台入口（manifest.json / backend/）仍在 zip 中（向后兼容）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

from modstore_server.employee_pack_standalone_template import standalone_import_prefix

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _minimal_manifest(pack_id: str) -> dict:
    return {
        "id": pack_id,
        "name": "测试员工",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "scope": "global",
        "description": "独立 CLI 测试用最小员工包",
        "employee": {
            "id": pack_id,
            "label": "测试员工",
            "capabilities": [],
        },
        "actions": {
            "handlers": ["llm_md", "echo"],
        },
        "cognition": {
            "agent": {
                "system_prompt": (
                    "你是一名测试员工，负责验证 employee_pack 独立 CLI 功能是否正常工作。"
                    "接收任务后输出 Markdown 格式的验证报告，包含：员工 ID、任务摘要、执行结果。"
                    "遇到格式错误时输出具体原因，不编造数据。"
                ),
            }
        },
    }


def _build_xcemp(pack_id: str) -> bytes:
    """调 employee_pack_export._build_employee_pack_zip_with_source 生成 zip。"""
    # 需要在 MODstore_deploy 下才能 import
    modstore_root = Path(__file__).parent.parent
    if str(modstore_root) not in sys.path:
        sys.path.insert(0, str(modstore_root))

    from modstore_server.employee_pack_export import _build_employee_pack_zip_with_source

    manifest = _minimal_manifest(pack_id)
    return _build_employee_pack_zip_with_source(pack_id, manifest, source_py=None)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def xcemp_path(tmp_path_factory):
    """生成一个临时 .xcemp 文件，整个模块共用。"""
    pack_id = "test-standalone-employee"
    zip_bytes = _build_xcemp(pack_id)
    tmp = tmp_path_factory.mktemp("xcemp")
    p = tmp / f"{pack_id}.xcemp"
    p.write_bytes(zip_bytes)
    return p, pack_id


# ---------------------------------------------------------------------------
# zip 结构测试（不执行子进程）
# ---------------------------------------------------------------------------


class TestZipContents:
    def test_has_main_py(self, xcemp_path):
        path, pack_id = xcemp_path
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert "__main__.py" in names, "__main__.py 应在 zip 顶层"

    def test_has_manifest(self, xcemp_path):
        path, pack_id = xcemp_path
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert f"{pack_id}/manifest.json" in names

    def test_has_backend(self, xcemp_path):
        path, pack_id = xcemp_path
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert any(n.startswith(f"{pack_id}/backend/") for n in names), "backend/ 目录应存在"

    def test_has_standalone_cli(self, xcemp_path):
        path, pack_id = xcemp_path
        sp = standalone_import_prefix(pack_id)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert f"{sp}/standalone/cli.py" in names

    def test_has_standalone_runner(self, xcemp_path):
        path, pack_id = xcemp_path
        sp = standalone_import_prefix(pack_id)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert f"{sp}/standalone/runner.py" in names

    def test_has_standalone_handlers(self, xcemp_path):
        path, pack_id = xcemp_path
        sp = standalone_import_prefix(pack_id)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert f"{sp}/standalone/handlers/no_llm.py" in names
        assert f"{sp}/standalone/handlers/llm_md.py" in names

    def test_has_standalone_readme(self, xcemp_path):
        path, pack_id = xcemp_path
        sp = standalone_import_prefix(pack_id)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert f"{sp}/standalone/README.md" in names

    def test_manifest_json_valid(self, xcemp_path):
        path, pack_id = xcemp_path
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read(f"{pack_id}/manifest.json").decode("utf-8"))
        assert data["id"] == pack_id
        assert data["artifact"] == "employee_pack"


# ---------------------------------------------------------------------------
# zipapp CLI 执行测试（子进程）
# ---------------------------------------------------------------------------


def _run(xcemp_path_obj: Path, *args, timeout: int = 30):
    """子进程执行 `python xxx.xcemp <args>`，返回 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        [sys.executable, str(xcemp_path_obj), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ},
    )
    return result.returncode, result.stdout, result.stderr


class TestStandaloneCLI:
    def test_info_exits_zero(self, xcemp_path):
        path, pack_id = xcemp_path
        rc, stdout, stderr = _run(path, "info")
        assert rc == 0, f"info 应退出码 0，stderr={stderr!r}"

    def test_info_shows_id(self, xcemp_path):
        path, pack_id = xcemp_path
        _, stdout, _ = _run(path, "info")
        assert pack_id in stdout, f"info 输出应包含 pack_id，got: {stdout!r}"

    def test_info_shows_name(self, xcemp_path):
        path, pack_id = xcemp_path
        _, stdout, _ = _run(path, "info")
        assert "测试员工" in stdout

    def test_validate_exits_zero(self, xcemp_path):
        path, pack_id = xcemp_path
        rc, stdout, stderr = _run(path, "validate")
        # 允许有 warning（system_prompt 长度等），但退出码应为 0
        assert rc == 0, f"validate 应退出码 0，stdout={stdout!r}，stderr={stderr!r}"

    def test_validate_ok_text(self, xcemp_path):
        path, pack_id = xcemp_path
        _, stdout, _ = _run(path, "validate")
        assert "OK" in stdout or "ok" in stdout.lower(), f"validate 输出应含 OK，got: {stdout!r}"

    def test_run_exits_zero(self, xcemp_path, tmp_path):
        path, pack_id = xcemp_path
        task_file = tmp_path / "task.json"
        task_file.write_text('{"task":"validate"}', encoding="utf-8")
        rc, stdout, stderr = _run(path, "run", "--input", str(task_file))
        assert rc == 0, f"run 应退出码 0，stderr={stderr!r}"

    def test_run_returns_json(self, xcemp_path, tmp_path):
        path, pack_id = xcemp_path
        task_file = tmp_path / "task.json"
        task_file.write_text('{"task":"validate"}', encoding="utf-8")
        _, stdout, _ = _run(path, "run", "--input", str(task_file))
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            pytest.fail(f"run 输出应为合法 JSON，got: {stdout!r}")
        assert "ok" in result, "返回 JSON 应包含 ok 字段"

    def test_run_no_input_also_works(self, xcemp_path):
        """不传 --input 时也应正常运行（使用默认空输入）。"""
        path, pack_id = xcemp_path
        rc, stdout, stderr = _run(path, "run")
        assert rc == 0, f"不传 --input 时 run 应退出码 0，stderr={stderr!r}"

    def test_no_llm_flag_without_key(self, xcemp_path, tmp_path, monkeypatch):
        """不设 LLM key 时加 --llm 应失败但不崩溃（返回 JSON error）。"""
        path, pack_id = xcemp_path
        task_file = tmp_path / "task.json"
        task_file.write_text('{"task":"test"}', encoding="utf-8")
        # 清除可能存在的 key
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_BASE_URL")
        }
        result = subprocess.run(
            [sys.executable, str(path), "run", "--input", str(task_file), "--llm"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        # 退出码非零（因为 LLM 失败），但输出应是合法 JSON
        try:
            data = json.loads(result.stdout)
            assert data.get("ok") is False, "无 key 时 --llm 路径应返回 ok=false"
        except json.JSONDecodeError:
            pytest.fail(f"--llm 无 key 时输出应为合法 JSON，got: {result.stdout!r}")
