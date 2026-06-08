"""只读黄金员工包对比 oracle（不向 LLM 提供黄金源码）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.catalog_quality import PUBLIC_TABULAR_PKG_IDS, resolve_employee_pack_dir

GOLDEN_PARITY_PASS_THRESHOLD = 85

# runtime_kind -> 黄金包 id（library 下只读）
RUNTIME_TO_GOLDEN_PACK: Dict[str, str] = {
    "word_full_extract": "word-full-read-employee",
    "word_generate": "word-generate-employee",
    "excel_full_read": "excel-full-read-employee",
    "excel_generate": "excel-generate-employee",
    "csv_full_read": "csv-full-read-employee",
    "csv_generate": "csv-generate-employee",
    "pdf_full_read": "pdf-full-read-employee",
    "pdf_generate": "pdf-generate-employee",
    "ppt_full_read": "ppt-full-read-employee",
    "ppt_generate": "ppt-generate-employee",
    "txt_full_read": "txt-full-read-employee",
    "txt_generate": "txt-generate-employee",
}

PROTECTED_GOLDEN_IDS = frozenset(PUBLIC_TABULAR_PKG_IDS)


def golden_pack_id_for_runtime(runtime_kind: str) -> Optional[str]:
    return RUNTIME_TO_GOLDEN_PACK.get((runtime_kind or "").strip()) or None


def resolve_golden_pack_dir(golden_pack_id: str) -> Optional[Path]:
    pid = str(golden_pack_id or "").strip()
    if not pid or pid not in PROTECTED_GOLDEN_IDS:
        return None
    return resolve_employee_pack_dir(pid)


def _read_manifest(pack_dir: Path) -> Dict[str, Any]:
    p = pack_dir / "manifest.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _manifest_contract_from_dir(pack_dir: Path) -> Dict[str, Any]:
    mf = _read_manifest(pack_dir)
    ec2 = mf.get("employee_config_v2") if isinstance(mf.get("employee_config_v2"), dict) else {}
    perception = ec2.get("perception") if isinstance(ec2.get("perception"), dict) else {}
    actions = ec2.get("actions") if isinstance(ec2.get("actions"), dict) else {}
    dp = actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
    rs: Dict[str, Any] = {}
    rule_p = pack_dir / "rule_spec.json"
    if rule_p.is_file():
        try:
            rs = json.loads(rule_p.read_text(encoding="utf-8"))
            if not isinstance(rs, dict):
                rs = {}
        except (json.JSONDecodeError, OSError):
            rs = {}
    return {
        "runtime_kind": str(rs.get("runtime_kind") or ""),
        "artifact": mf.get("artifact"),
        "handlers": list(actions.get("handlers") or []),
        "accepted_extensions": list(perception.get("accepted_extensions") or []),
        "default_output_relpath": str(dp.get("default_output_relpath") or ""),
    }


def _diff_contract(candidate: Dict[str, Any], golden: Dict[str, Any]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for key in ("runtime_kind", "artifact", "default_output_relpath"):
        cv, gv = str(candidate.get(key) or ""), str(golden.get(key) or "")
        if cv != gv:
            items.append({"field": key, "candidate": cv, "golden": gv})
    ch = candidate.get("handlers") or []
    gh = golden.get("handlers") or []
    if ch != gh:
        items.append({"field": "handlers", "candidate": str(ch), "golden": str(gh)})
    ce = set(candidate.get("accepted_extensions") or [])
    ge = set(golden.get("accepted_extensions") or [])
    if ce != ge:
        items.append(
            {
                "field": "accepted_extensions",
                "candidate": str(sorted(ce)),
                "golden": str(sorted(ge)),
            }
        )
    return items


def _static_convert_signals(pack_dir: Path) -> Dict[str, bool]:
    blob = ""
    has_convert = False
    for py_path in (pack_dir / "backend").rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
            blob += text.lower()
            if "def convert_file" in text and "vendor" in str(py_path).lower():
                has_convert = True
        except OSError:
            pass
    return {
        "has_convert_file": has_convert,
        "ooxml": any(t in blob for t in ("zipfile", "wordprocessingml", "document.xml")),
        "paragraphs": "paragraphs" in blob,
        "tables": "tables" in blob,
        "core_properties": "core_properties" in blob,
        "images": "images" in blob,
    }


def compare_with_golden(
    pack_dir: Path,
    *,
    golden_pack_id: Optional[str] = None,
    runtime_kind: str = "",
    domain_smoke: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """对比候选包与黄金包；返回 parity_score、diff_items、passed。"""
    pack_dir = Path(pack_dir)
    gid = golden_pack_id or golden_pack_id_for_runtime(runtime_kind)
    out: Dict[str, Any] = {
        "golden_pack_id": gid or "",
        "parity_score": 0.0,
        "diff_items": [],
        "passed": False,
        "dimensions": {},
    }
    if not gid:
        out["parity_score"] = 100.0
        out["passed"] = True
        out["note"] = "no golden mapping for runtime"
        return out

    golden_dir = resolve_golden_pack_dir(gid)
    if not golden_dir or not golden_dir.is_dir():
        out["note"] = f"golden pack not found: {gid}"
        return out

    cand_contract = _manifest_contract_from_dir(pack_dir)
    gold_contract = _manifest_contract_from_dir(golden_dir)
    contract_diffs = _diff_contract(cand_contract, gold_contract)
    out["dimensions"]["contract"] = {"diffs": contract_diffs}

    cand_static = _static_convert_signals(pack_dir)
    gold_static = _static_convert_signals(golden_dir)
    static_diffs: List[str] = []
    for key in cand_static:
        if cand_static[key] != gold_static.get(key):
            static_diffs.append(
                f"{key}: candidate={cand_static[key]} golden={gold_static.get(key)}"
            )
    out["dimensions"]["static"] = {"diffs": static_diffs}

    behavior_diffs: List[str] = []
    smoke = domain_smoke if isinstance(domain_smoke, dict) else {}
    if smoke.get("ok") is False:
        behavior_diffs.append(f"domain_smoke: {smoke.get('error') or 'failed'}")
    elif smoke.get("ok") is True:
        keys = smoke.get("output_json_keys")
        if isinstance(keys, list) and keys:
            for req in ("paragraphs", "tables", "metadata"):
                if req not in keys and runtime_kind == "word_full_extract":
                    behavior_diffs.append(f"smoke json missing key: {req}")

    score = 100.0
    score -= min(40.0, len(contract_diffs) * 12.0)
    score -= min(30.0, len(static_diffs) * 8.0)
    score -= min(30.0, len(behavior_diffs) * 15.0)
    if not cand_static.get("has_convert_file"):
        score -= 25.0
        static_diffs.append("missing convert_file in vendor")

    out["parity_score"] = max(0.0, round(score, 1))
    all_diffs: List[Dict[str, str]] = []
    for d in contract_diffs:
        all_diffs.append({"kind": "contract", **d})
    for msg in static_diffs:
        all_diffs.append({"kind": "static", "message": msg})
    for msg in behavior_diffs:
        all_diffs.append({"kind": "behavior", "message": msg})
    out["diff_items"] = all_diffs
    smoke_ok = smoke.get("ok") is not False if smoke else True
    out["passed"] = bool(
        smoke_ok
        and out["parity_score"] >= GOLDEN_PARITY_PASS_THRESHOLD
        and cand_static.get("has_convert_file")
    )
    return out
