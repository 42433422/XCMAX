"""从 mods/_employees 磁盘加载 employee_pack manifest 与 V2 配置。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.application.employee_runtime.config_v2_adapter import (
    needs_executor_translation,
    translate_v2_to_executor_config,
)
from app.utils.operational_errors import DATA_SHAPE, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DIRECT_PYTHON_RUNTIME_KINDS = frozenset(
    {
        "word_full_extract",
        "txt_full_read",
        "txt_generate",
        "pdf_full_read",
        "pdf_generate",
        "csv_full_read",
        "csv_generate",
        "generic_excel_transform",
        "contract_doc_review",
        "doc_template_transform",
        "ppt_full_read",
        "ppt_generate",
        "excel_full_read",
        "excel_generate",
    }
)

DIRECT_PYTHON_RUNTIME_MISSING_MSG = (
    "manifest 声明了 direct_python，但本地包缺少 rule_spec 与 backend/vendor/convert。"
    "请在工作台「做员工」流水线完成 generate 步后再安装；"
    "否则会覆盖为仅含 LLM 脚手架的空包。"
)
DIRECT_PYTHON_UNTRUSTED_MSG = (
    "员工包 Python 运行时未通过信任校验：用户可写目录中的代码必须来自真实签名安装，"
    "且运行前内容哈希必须与安装收据一致。"
)


def _employees_root() -> Path:
    from app.infrastructure.mods.employee_registry import get_employee_registry

    return Path(get_employee_registry()._root())


def _employee_roots() -> list[Path]:
    """Return writable employee packs first, then read-only bundled packs.

    Packaged desktop builds intentionally keep the marketplace install root in
    ``userData/mods`` while shipping a small, SKU-approved employee subset in
    ``_MEIPASS/mods/_employees``.  The writable root must win when a user has
    installed an override, but a missing user copy must not hide the bundled
    employee from the runtime.
    """

    roots = [_employees_root()]
    try:
        from app.mod_sdk.edition_policy import bundled_mods_dir

        bundled = bundled_mods_dir()
        if bundled is not None:
            candidate = Path(bundled) / "_employees"
            if candidate.is_dir() and all(candidate.resolve() != root.resolve() for root in roots):
                roots.append(candidate)
    except RECOVERABLE_ERRORS:
        logger.debug("resolve bundled employee root failed", exc_info=True)
    return roots


def candidate_pack_ids(pack_id: str) -> list[str]:
    raw = str(pack_id or "").strip()
    if not raw:
        return []
    candidates = [raw]
    for item in (raw.replace("_", "-"), raw.replace("-", "_"), f"{raw.replace('_', '-')}-employee"):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def resolve_pack_dir(pack_id: str) -> Path | None:
    for root in _employee_roots():
        for cid in candidate_pack_ids(pack_id):
            pdir = root / cid
            if (pdir / "manifest.json").is_file():
                return pdir
    return None


def normalize_manifest_legacy_deepseek_to_auto(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        return
    v2 = manifest.get("employee_config_v2")
    if not isinstance(v2, dict):
        return
    cog = v2.get("cognition")
    if not isinstance(cog, dict):
        return
    agent = cog.get("agent")
    if not isinstance(agent, dict):
        return
    model = agent.get("model")
    if not isinstance(model, dict):
        return
    if str(model.get("provider") or "").strip().lower() != "deepseek":
        return
    model["provider"] = "auto"
    model["model_name"] = "auto"


def load_employee_pack_from_disk(pack_id: str) -> dict[str, Any]:
    pdir = resolve_pack_dir(pack_id)
    if pdir is None:
        raise ValueError(f"员工包未安装：{pack_id}")
    manifest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest 无效：{pack_id}")
    normalize_manifest_legacy_deepseek_to_auto(manifest)
    resolved_id = str(manifest.get("id") or pdir.name).strip() or pdir.name
    return {
        "pack_id": resolved_id,
        "name": str(manifest.get("name") or resolved_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "manifest": manifest,
        "pack_dir": str(pdir.resolve()),
    }


def parse_employee_config_v2(manifest: dict[str, Any]) -> dict[str, Any]:
    v2 = manifest.get("employee_config_v2") if isinstance(manifest, dict) else None
    if isinstance(v2, dict):
        if needs_executor_translation(v2):
            return translate_v2_to_executor_config(v2)
        return v2
    employee = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    label = employee.get("label") if isinstance(employee, dict) else None
    return {
        "perception": {"type": "text"},
        "memory": {"type": "session"},
        "cognition": {
            "agent": {
                "system_prompt": (f"你是员工助手：{label or manifest.get('name') or 'assistant'}"),
                "model": {"provider": "auto", "model_name": "auto", "max_tokens": 4000},
            }
        },
        "actions": {"handlers": ["echo"]},
    }


def manifest_actions_handlers(manifest: dict[str, Any]) -> list[str]:
    cfg = parse_employee_config_v2(manifest)
    actions = cfg.get("actions") if isinstance(cfg.get("actions"), dict) else {}
    inner = actions.get("actions") if isinstance(actions.get("actions"), dict) else actions
    raw = (inner or {}).get("handlers") or actions.get("handlers") or []
    return [str(x).strip() for x in raw if str(x).strip()]


def pack_has_direct_python_runtime(pack_dir: Path | str) -> bool:
    pdir = Path(pack_dir)
    if not pdir.is_dir():
        return False
    rs = pdir / "rule_spec.json"
    if rs.is_file():
        try:
            data = json.loads(rs.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("runtime_kind") in DIRECT_PYTHON_RUNTIME_KINDS:
                return True
        except (OSError, json.JSONDecodeError):
            pass
    backend = pdir / "backend"
    if not backend.is_dir():
        return False
    for py_path in backend.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def convert_file" in text and "vendor" in py_path.as_posix().lower():
            return True
        if "def convert" in text and "_import_runtime" in text:
            return True
    emp_dir = backend / "employees"
    if emp_dir.is_dir():
        for py in emp_dir.glob("*.py"):
            if not py.name.startswith("_"):
                return True
    return False


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def verify_direct_python_pack_trust(pack_dir: Path | str) -> tuple[bool, str]:
    """Trust bundled/source packs, or verify signed-install receipt + current hash."""
    pdir = Path(pack_dir).resolve()
    source_root = Path(__file__).resolve().parents[3] / "mods" / "_employees"
    if _is_within(pdir, source_root):
        return True, "source_bundled"
    try:
        from app.mod_sdk.edition_policy import bundled_mods_dir

        bundled_root = bundled_mods_dir()
        if bundled_root is not None and _is_within(pdir, Path(bundled_root) / "_employees"):
            return True, "application_bundled"
    except RECOVERABLE_ERRORS:
        logger.debug("resolve bundled employee trust root failed", exc_info=True)

    receipt_path = pdir / ".xcagi-install-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("signature_verified") is not True:
            return False, "missing_verified_install_receipt"
        from app.infrastructure.mods.package import compute_directory_hash

        expected = str(receipt.get("content_sha256") or "")
        actual = compute_directory_hash(str(pdir))
        if not expected or actual != expected:
            return False, "installed_pack_content_hash_mismatch"
        return True, "signed_install_receipt"
    except (OSError, json.JSONDecodeError, ValueError):
        return False, "missing_or_invalid_install_receipt"


def direct_python_pack_trust_error(
    pack_dir: Path | str,
    *,
    verifier: Callable[[Path | str], tuple[bool, str]] = verify_direct_python_pack_trust,
) -> dict[str, Any] | None:
    """Return the structured executor error when a Python pack is untrusted."""
    trusted, trust_reason = verifier(pack_dir)
    if trusted:
        return None
    return {
        "handler": "direct_python",
        "ok": False,
        "error": DIRECT_PYTHON_UNTRUSTED_MSG,
        "error_code": "employee_python_pack_untrusted",
        "trust_reason": trust_reason,
    }


def build_employee_context(employee_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {"employee_id": employee_id, "input_data": input_data or {}}


def list_installed_pack_records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.employee_registry import get_employee_registry

        for row in get_employee_registry().list_packs():
            pack_id = str(row.get("pack_id") or row.get("id") or "").strip()
            if not pack_id:
                continue
            try:
                out.append(load_employee_pack_from_disk(pack_id))
            except DATA_SHAPE:
                logger.debug("skip broken employee pack %s", pack_id, exc_info=True)
    except RECOVERABLE_ERRORS:
        logger.debug("list_installed_pack_records failed", exc_info=True)
    return out


__all__ = [
    "DIRECT_PYTHON_RUNTIME_MISSING_MSG",
    "DIRECT_PYTHON_UNTRUSTED_MSG",
    "build_employee_context",
    "candidate_pack_ids",
    "direct_python_pack_trust_error",
    "list_installed_pack_records",
    "load_employee_pack_from_disk",
    "manifest_actions_handlers",
    "pack_has_direct_python_runtime",
    "parse_employee_config_v2",
    "resolve_pack_dir",
    "verify_direct_python_pack_trust",
]
