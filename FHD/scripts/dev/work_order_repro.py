#!/usr/bin/env python3
"""连接件3（自动复现）：结构化诊断 → 可执行复现用例 → 红/绿证据。

从连接件2 的诊断文件（错误签名）生成最小复现场景：

- kind=module_import：目标文件存在于仓库 → 生成「模块可导入」pytest
  （故障期导入失败=RED 复现，修复后 GREEN），直接用仓库 venv 执行
- 其余签名：产出场景规格 status=needs_scenario，供实现 agent 在修复 PR 里
  补充可执行步骤（不造假自动复现）

产物（test_reports/repro/）：
- repro-<dedup_key[:12]>.json   场景规格（经中继嵌入 issue，供实现与重测复用）
- test_repro_<key12>.py         生成的可执行复现用例（kind=module_import 时）
- evidence-<key12>.json         --run 执行后的红/绿证据（复现=RED）

fail-open：无诊断文件/无法生成时只写规格，不阻塞主线。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("work_order_repro")

_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

_DIAGNOSIS_DIR = Path(
    os.environ.get("WORK_ORDER_DIAGNOSIS_DIR") or (_FHD_ROOT / "test_reports" / "diagnosis")
)
_REPRO_DIR = Path(
    os.environ.get("WORK_ORDER_REPRO_DIR") or (_FHD_ROOT / "test_reports" / "repro")
)

_PYTEST_TEMPLATE = '''"""AUTO-GENERATED 复现用例（连接件3 自动复现）— WO {wo_id}

来源：工单证据包诊断（签名 {tool}:{code}）。勿手改；由 work_order_repro 生成。
故障期 `{module}` 导入失败（RED=复现）；修复后本用例 GREEN。
"""

from __future__ import annotations

import importlib

import pytest

MODULE = {module!r}


def test_repro_module_importable() -> None:
    try:
        importlib.import_module(MODULE)
    except Exception as exc:  # noqa: BLE001 - 复现语义：导入失败即故障未修复
        pytest.fail(f"repro: {{MODULE}} import failed: {{exc}}")
'''


def _file_to_module(file_path: str) -> str:
    rel = file_path.removesuffix(".py").replace("/", ".").replace("\\", ".")
    return rel


def _top_error(diagnosis: dict[str, Any]) -> dict[str, Any] | None:
    errors = [e for e in (diagnosis.get("errors") or []) if isinstance(e, dict)]
    return errors[0] if errors else None


def generate_repro(diagnosis: dict[str, Any]) -> dict[str, Any] | None:
    """从单条诊断生成复现规格（及可执行用例）；无法生成时返回 None。"""
    key = str(diagnosis.get("dedup_key") or "")
    if not key:
        return None
    key12 = key[:12]
    error = _top_error(diagnosis)
    spec: dict[str, Any] = {
        "dedup_key": key,
        "wo_id": diagnosis.get("wo_id") or "",
        "generated_at": datetime.now(UTC).isoformat(),
        "signature": {
            "tool": (error or {}).get("tool", ""),
            "code": (error or {}).get("code", ""),
            "message": (error or {}).get("message", ""),
            "file": (error or {}).get("file_path", ""),
            "line": (error or {}).get("line", 0),
        },
        "kind": "none",
        "status": "needs_scenario",
        "scenario": None,
    }
    if error and str(error.get("file_path") or "").endswith(".py"):
        candidate = _FHD_ROOT / str(error["file_path"])
        if candidate.is_file():
            module = _file_to_module(str(error["file_path"]))
            spec.update(
                kind="module_import",
                status="generated",
                scenario={"module": module, "assertion": "importable"},
            )
            _REPRO_DIR.mkdir(parents=True, exist_ok=True)
            test_path = _REPRO_DIR / f"test_repro_{key12}.py"
            test_path.write_text(
                _PYTEST_TEMPLATE.format(
                    wo_id=spec["wo_id"],
                    tool=spec["signature"]["tool"],
                    code=spec["signature"]["code"],
                    module=module,
                ),
                encoding="utf-8",
            )
            spec["scenario"]["test_path"] = str(test_path)
    return spec


def run_repro(spec: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    """执行生成的复现用例，返回红/绿证据（复现=RED=exit≠0）。"""
    evidence: dict[str, Any] = {
        "dedup_key": spec.get("dedup_key"),
        "wo_id": spec.get("wo_id"),
        "ran_at": datetime.now(UTC).isoformat(),
        "kind": spec.get("kind"),
        "reproduced": False,
        "exit_code": None,
        "log_tail": "",
    }
    scenario = spec.get("scenario") or {}
    test_path = scenario.get("test_path")
    if spec.get("kind") != "module_import" or not test_path or not Path(test_path).is_file():
        evidence["skipped"] = "no_executable_scenario"
        return evidence
    command = [sys.executable, "-m", "pytest", str(test_path), "-x", "-q", "--no-header"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(_FHD_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        evidence["exit_code"] = completed.returncode
        evidence["reproduced"] = completed.returncode != 0
        evidence["log_tail"] = (completed.stdout + completed.stderr)[-2000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        evidence["error"] = str(exc)[:300]
    return evidence


def run(args: argparse.Namespace) -> int:
    _REPRO_DIR.mkdir(parents=True, exist_ok=True)
    diag_files = sorted(Path(args.diagnosis_dir).glob("diagnosis-*.json"))
    if not diag_files:
        logger.info("no diagnosis files; nothing to reproduce")
        return 0
    produced = 0
    for diag_path in diag_files[: max(0, int(args.max))]:
        try:
            diagnosis = json.loads(diag_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(diagnosis, dict):
            continue
        key12 = str(diagnosis.get("dedup_key") or "")[:12]
        if not key12:
            continue
        spec_path = _REPRO_DIR / f"repro-{key12}.json"
        if spec_path.is_file() and not args.force:
            logger.info("skip existing repro spec: %s", spec_path)
            continue
        spec = generate_repro(diagnosis)
        if spec is None:
            continue
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        produced += 1
        logger.info("repro spec written: %s kind=%s", spec_path, spec["kind"])
        if args.run and spec["status"] == "generated":
            evidence = run_repro(spec)
            evidence_path = _REPRO_DIR / f"evidence-{key12}.json"
            evidence_path.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(
                "repro run: reproduced=%s exit=%s -> %s",
                evidence.get("reproduced"),
                evidence.get("exit_code"),
                evidence_path,
            )
    logger.info("repro done: produced=%d", produced)
    return 0


def main(argv: list[str] | None = None) -> int:
    global _REPRO_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis-dir", default=str(_DIAGNOSIS_DIR))
    parser.add_argument("--out-dir", default=str(_REPRO_DIR))
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--run", action="store_true", help="生成后立即执行复现用例留证")
    parser.add_argument("--force", action="store_true", help="重写已存在的复现规格")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _REPRO_DIR = Path(args.out_dir)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
