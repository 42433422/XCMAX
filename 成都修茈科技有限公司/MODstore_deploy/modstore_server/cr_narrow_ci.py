"""窄 CI 验证：CR 自动审批前在受影响路径跑语法检查 + pytest 子集 + 可选 ruff。"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


def _narrow_ci_enabled() -> bool:
    return os.environ.get("MODSTORE_CR_NARROW_CI_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _pytest_timeout_sec() -> float:
    try:
        return max(10.0, float(os.environ.get("MODSTORE_CR_NARROW_CI_PYTEST_TIMEOUT", "120")))
    except ValueError:
        return 120.0


def _repo_root() -> Path:
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        return Path(repo_root())
    except Exception:
        return Path(os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()


def _modstore_tests_root(root: Path) -> Path:
    """定位 MODstore_deploy/tests（仓库根可能是 XCMAX 或 MODstore_deploy 自身）。"""
    candidates = [
        root / "tests",
        root / "MODstore_deploy" / "tests",
        root / "成都修茈科技有限公司" / "MODstore_deploy" / "tests",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return root / "tests"


def infer_related_test_files(rel_path: str, *, root: Optional[Path] = None) -> List[str]:
    """根据变更文件推断可跑的窄 pytest 目标。"""
    rp = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rp:
        return []
    root = root or _repo_root()
    tests_dir = _modstore_tests_root(root)
    if not tests_dir.is_dir():
        return []

    stem = Path(rp).stem
    module_hint = stem.replace("-", "_")
    patterns = [
        f"test_{module_hint}.py",
        f"test_{module_hint}_*.py",
        f"test_*{module_hint}*.py",
    ]
    found: List[str] = []
    for pat in patterns:
        for p in sorted(tests_dir.glob(pat)):
            if p.is_file():
                rel = str(p.relative_to(tests_dir.parent))
                if rel not in found:
                    found.append(rel)
    if found:
        return found[:6]

    # 按目录映射：modstore_server/foo/bar.py → tests/test_*_extra.py 或跑目录 smoke
    if rp.startswith("modstore_server/"):
        smoke = tests_dir / "test_orchestration_modules_smoke_extra.py"
        if smoke.is_file():
            return [str(smoke.relative_to(tests_dir.parent))]
    return []


def _run_py_compile(content: str, rel_path: str) -> Dict[str, Any]:
    suffix = Path(rel_path).suffix or ".py"
    if suffix not in (".py",):
        return {"ok": True, "skipped": True, "reason": "non_python_file"}

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content or "")
            tmp_path = tmp.name
        proc = subprocess.run(
            ["python3", "-m", "py_compile", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok = proc.returncode == 0
        return {
            "ok": ok,
            "step": "py_compile",
            "stderr": (proc.stderr or "")[:500],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "step": "py_compile", "error": str(exc)}
    finally:
        try:
            os.unlink(tmp_path)  # type: ignore[possibly-undefined]
        except Exception:
            pass


def _run_ruff_check(rel_path: str, *, root: Path) -> Dict[str, Any]:
    if os.environ.get("MODSTORE_CR_NARROW_CI_RUFF", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return {"ok": True, "skipped": True, "reason": "ruff disabled"}

    full = root / rel_path.replace("\\", "/").lstrip("/")
    if not full.is_file():
        return {"ok": True, "skipped": True, "reason": "file not on disk yet"}

    try:
        proc = subprocess.run(
            ["ruff", "check", str(full)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(root),
        )
        if proc.returncode == 127:
            return {"ok": True, "skipped": True, "reason": "ruff not installed"}
        return {
            "ok": proc.returncode == 0,
            "step": "ruff",
            "stdout": (proc.stdout or "")[:800],
            "stderr": (proc.stderr or "")[:800],
        }
    except FileNotFoundError:
        return {"ok": True, "skipped": True, "reason": "ruff not installed"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "step": "ruff", "error": str(exc)}


def _run_pytest_subset(test_files: Sequence[str], *, root: Path) -> Dict[str, Any]:
    if not test_files:
        return {"ok": True, "skipped": True, "reason": "no related tests"}

    existing = [f for f in test_files if (root / f.replace("\\", "/")).is_file()]
    if not existing:
        return {"ok": True, "skipped": True, "reason": "related tests not present on disk"}

    args = ["python3", "-m", "pytest", "-q", "--tb=short", *list(existing)]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_pytest_timeout_sec(),
            cwd=str(root),
        )
        return {
            "ok": proc.returncode == 0,
            "step": "pytest",
            "command": " ".join(args),
            "stdout": (proc.stdout or "")[-1200:],
            "stderr": (proc.stderr or "")[-1200:],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "step": "pytest", "error": "pytest timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "step": "pytest", "error": str(exc)}


def run_narrow_ci_validation(
    rel_path: str,
    content: str,
    *,
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """对 CR 变更跑窄验证链；全部通过才返回 ok=True。"""
    if not _narrow_ci_enabled():
        return {"ok": True, "skipped": True, "reason": "MODSTORE_CR_NARROW_CI_ENABLED=0"}

    root = Path(project_root).resolve() if project_root else _repo_root()
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    steps: List[Dict[str, Any]] = []

    compile_out = _run_py_compile(content, rel)
    steps.append(compile_out)
    if not compile_out.get("ok"):
        return {
            "ok": False,
            "rel_path": rel,
            "steps": steps,
            "failed_step": "py_compile",
        }

    ruff_out = _run_ruff_check(rel, root=root)
    steps.append(ruff_out)
    if not ruff_out.get("ok") and not ruff_out.get("skipped"):
        return {
            "ok": False,
            "rel_path": rel,
            "steps": steps,
            "failed_step": "ruff",
        }

    test_files = infer_related_test_files(rel, root=root)
    pytest_out = _run_pytest_subset(test_files, root=root)
    steps.append({**pytest_out, "test_files": test_files})
    if not pytest_out.get("ok") and not pytest_out.get("skipped"):
        return {
            "ok": False,
            "rel_path": rel,
            "steps": steps,
            "failed_step": "pytest",
        }

    return {
        "ok": True,
        "rel_path": rel,
        "steps": steps,
        "test_files": test_files,
    }


def record_cr_validation_failure_for_evolution(
    *,
    change_request_id: int,
    source_employee_id: str,
    rel_path: str,
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    """窄 CI 失败时写入 evolution-engine 建议单，供 prompt 进化消费。"""
    try:
        from modstore_server.employee_autonomy_service import create_employee_suggestion

        failed = str(validation.get("failed_step") or "unknown")
        return create_employee_suggestion(
            source_employee_id="evolution-engine",
            summary=f"CR#{change_request_id} 窄 CI 未通过（{failed}）",
            detail=(
                f"员工 {source_employee_id} 产出的 CR 在自动审批前未通过窄验证。\n"
                f"path={rel_path}\n"
                f"failed_step={failed}\n"
                f"steps={validation.get('steps')}"
            )[:20_000],
            payload={
                "kind": "cr_narrow_ci_failure",
                "change_request_id": int(change_request_id),
                "employee_id": source_employee_id,
                "rel_path": rel_path,
                "validation": validation,
            },
            target_employee_ids=[source_employee_id],
            kind="cr_narrow_ci_failure",
            risk_level="low",
            emit_event=True,
            auto_dispatch=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "record_cr_validation_failure_for_evolution failed cr=%s", change_request_id
        )
        return {"ok": False, "error": str(exc)}


__all__ = [
    "infer_related_test_files",
    "record_cr_validation_failure_for_evolution",
    "run_narrow_ci_validation",
]
