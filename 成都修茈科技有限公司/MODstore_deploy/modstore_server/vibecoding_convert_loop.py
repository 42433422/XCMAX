"""Vibecoding：仅 LLM 生成/修复 convert，对比黄金包 + 领域冒烟。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.employee_asset_pipeline import (
    _validate_generated_convert_py,
    generate_runtime_convert_module,
    materialize_asset_employee_pack,
    repair_runtime_convert_module,
)
from modstore_server.employee_domain_smoke import run_pack_domain_smoke
from modstore_server.employee_golden_compare import (
    GOLDEN_PARITY_PASS_THRESHOLD,
    compare_with_golden,
    golden_pack_id_for_runtime,
)

MAX_CODEGEN_REPAIR_ROUNDS = 3
LLM_CODEGEN_SOURCES = frozenset({"llm_codegen", "llm_codegen_repair"})


def is_llm_codegen_source(meta: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(meta, dict):
        return False
    src = str(meta.get("source") or "")
    if src in LLM_CODEGEN_SOURCES:
        return True
    return bool(meta.get("generated")) and src not in (
        "word_extract_builtin",
        "word_extract_builtin_fallback",
        "word_generate_builtin",
        "excel_read_builtin",
        "csv_read_builtin",
        "auto_fixed",
    )


def write_codegen_trace(
    trace_root: Path,
    *,
    session_id: str,
    round_no: int,
    convert_py: str,
    meta: Dict[str, Any],
    smoke: Dict[str, Any],
    golden: Dict[str, Any],
) -> None:
    base = trace_root / str(session_id)
    base.mkdir(parents=True, exist_ok=True)
    (base / f"round_{round_no}_convert.py").write_text(convert_py or "", encoding="utf-8")
    (base / f"round_{round_no}_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (base / f"round_{round_no}_smoke.json").write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (base / f"round_{round_no}_golden.json").write_text(
        json.dumps(golden, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def run_vibecoding_codegen_loop(
    db: Any,
    user: Any,
    *,
    session_id: str,
    brief: str,
    rule_spec: Dict[str, Any],
    manifest: Dict[str, Any],
    asset_manifest: Dict[str, Any],
    provider: Optional[str],
    model: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
    trace_root: Optional[Path] = None,
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    返回 (convert_py, runtime_meta, domain_smoke, golden_comparison)。
    失败时 convert_py 为 None，runtime_meta 含 error。
    """
    runtime_kind = str(rule_spec.get("runtime_kind") or "")
    golden_id = golden_pack_id_for_runtime(runtime_kind)
    repair_history: List[Dict[str, Any]] = []
    trace_base = trace_root or Path("artifacts/llm_codegen_traces")

    convert_py, runtime_meta = await generate_runtime_convert_module(
        db,
        user,
        brief=brief,
        rule_spec=rule_spec,
        asset_manifest=asset_manifest,
        provider=provider,
        model=model,
        allow_builtin_codegen=False,
        payload=payload,
    )
    if not convert_py:
        return (
            None,
            {
                **runtime_meta,
                "error": runtime_meta.get("warning") or "LLM convert generation failed",
                "repair_history": repair_history,
            },
            {"ok": False, "error": "no convert"},
            {"passed": False, "parity_score": 0},
        )

    last_smoke: Dict[str, Any] = {}
    last_golden: Dict[str, Any] = {}

    for round_no in range(MAX_CODEGEN_REPAIR_ROUNDS + 1):
        ok_static, static_err = _validate_generated_convert_py(convert_py)
        pack_dir, _raw = materialize_asset_employee_pack(
            manifest=manifest,
            rule_spec=rule_spec,
            asset_manifest=asset_manifest,
            generated_convert_py=convert_py,
        )
        pid = str(manifest.get("id") or pack_dir.name)
        last_smoke = await run_pack_domain_smoke(pack_dir, pack_id=pid, runtime_kind=runtime_kind)
        last_golden = compare_with_golden(
            pack_dir,
            golden_pack_id=golden_id,
            runtime_kind=runtime_kind,
            domain_smoke=last_smoke,
        )
        runtime_meta = {
            **runtime_meta,
            "source": "llm_codegen_repair" if round_no else "llm_codegen",
            "generated": True,
            "round": round_no,
            "repair_history": repair_history,
        }
        write_codegen_trace(
            trace_base,
            session_id=session_id,
            round_no=round_no,
            convert_py=convert_py,
            meta=runtime_meta,
            smoke=last_smoke,
            golden=last_golden,
        )

        passed = (
            ok_static
            and last_smoke.get("ok") is not False
            and last_golden.get("passed") is True
            and is_llm_codegen_source(runtime_meta)
        )
        if passed:
            runtime_meta["domain_smoke"] = last_smoke
            runtime_meta["golden_comparison"] = last_golden
            return convert_py, runtime_meta, last_smoke, last_golden

        if round_no >= MAX_CODEGEN_REPAIR_ROUNDS:
            break

        failure = {
            "static_error": static_err if not ok_static else "",
            "domain_smoke": last_smoke,
            "golden_comparison": last_golden,
            "stage": "vibecoding_loop",
        }
        repaired, repair_meta = await repair_runtime_convert_module(
            db,
            user,
            brief=brief,
            rule_spec=rule_spec,
            previous_convert_py=convert_py,
            failure=failure,
            provider=provider,
            model=model,
            round_no=round_no + 1,
        )
        repair_history.append(repair_meta)
        if not repaired:
            break
        convert_py = repaired
        runtime_meta["source"] = "llm_codegen_repair"

    return (
        None,
        {
            **runtime_meta,
            "error": "vibecoding loop exhausted: static/smoke/golden not passed",
            "repair_history": repair_history,
            "domain_smoke": last_smoke,
            "golden_comparison": last_golden,
            "parity_threshold": GOLDEN_PARITY_PASS_THRESHOLD,
        },
        last_smoke,
        last_golden,
    )
