"""One-off: score a .xcemp with six-dimension report."""

from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

from modstore_server.employee_six_dimension import compute_six_dimension_report
from modstore_server.workbench_api import _employee_handlers_contract_ok


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/score_xcemp_once.py <path.xcemp>", file=sys.stderr)
        return 2
    xcemp = Path(sys.argv[1]).resolve()
    if not xcemp.is_file():
        print(f"not found: {xcemp}", file=sys.stderr)
        return 1

    tmpdir = Path(tempfile.mkdtemp(prefix="xcemp_score_"))
    try:
        with zipfile.ZipFile(xcemp) as z:
            z.extractall(tmpdir)
        # find pack root (first dir with manifest.json)
        pack = None
        for mf in tmpdir.rglob("manifest.json"):
            pack = mf.parent
            break
        if not pack:
            print("no manifest.json in zip", file=sys.stderr)
            return 1

        mf = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        handlers = (mf.get("employee_config_v2") or {}).get("actions", {}).get("handlers") or []
        vendor_convert = pack / "backend" / "vendor" / "word_full_extract" / "convert.py"
        checks = [
            {"id": "manifest", "ok": True, "message": "manifest 可读"},
            {
                "id": "employee_pack_consistency",
                "ok": mf.get("artifact") == "employee_pack",
            },
            {
                "id": "python_compile",
                "ok": _py_compile_all(pack),
            },
            {
                "id": "word_extract_runtime",
                "ok": vendor_convert.is_file() and handlers == ["direct_python"],
                "message": "需 backend/vendor/.../convert.py 且 handlers 仅 direct_python",
            },
        ]
        mod_sandbox = {
            "ok": all(c.get("ok") for c in checks),
            "checks": checks,
        }
        h_ok, h_msg = _employee_handlers_contract_ok(pack)

        report = compute_six_dimension_report(
            pack_dir=pack,
            pipeline_label="word_full_extract",
            routing_brief="全量提取 Word docx，direct_python，输出 document_full.json 和 document_full.txt",
            structured_requirement={"suggested_handlers": ["direct_python"]},
            mod_sandbox=mod_sandbox,
            workflow_sandbox={"ok": True, "skipped": True},
            catalog_registered=False,
            standalone_smoke_ok=False,
            employee_target="pack_only",
        )

        print("=== 包体概况 ===")
        print(f"路径: {xcemp}")
        print(f"pack_id: {mf.get('id')}")
        print(f"name: {mf.get('name')}")
        print(f"handlers: {handlers}")
        print(f"文件数: {len(list(pack.rglob('*')))}")
        for p in sorted(pack.rglob("*")):
            if p.is_file():
                print(f"  - {p.relative_to(pack).as_posix()}")
        print(f"rule_spec.json: {'有' if (pack / 'rule_spec.json').is_file() else '无'}")
        print(f"vendor convert: {'有' if vendor_convert.is_file() else '无'}")
        print(f"handlers 契约检查: {h_ok} — {h_msg[:200] if h_msg else ''}")
        print()
        print("=== 六维评分 ===")
        print(
            f"综合 {report['overall_score']} 分 · {report['overall_grade']}级 "
            f"({report['overall_grade_label']})"
        )
        print(
            f"通过: {report['passed']} · 关键门禁: {'未过' if report['critical_failed'] else '通过'}"
        )
        print()
        for key, d in report["dimensions"].items():
            reasons = "；".join(d.get("reasons") or []) or "—"
            print(f"· {d['label']}: {d['grade']}级 / {d['score']}分 — {reasons}")
        print()
        if report["failed_dimensions"]:
            print("未达单维底线:", ", ".join(report["failed_dimensions"]))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


def _py_compile_all(pack: Path) -> bool:
    import py_compile

    try:
        for py in pack.rglob("*.py"):
            py_compile.compile(str(py), doraise=True)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
