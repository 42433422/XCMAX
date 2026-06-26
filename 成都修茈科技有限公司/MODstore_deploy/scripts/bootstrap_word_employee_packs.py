"""Bootstrap Word 全量读取 / Word 生成员工包到 library（内置 direct_python runtime）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORD_READ_BRIEF = """员工包 ID：word-full-read-employee
员工名称：Word全量读取员工
版本：1.0.0

全量提取 Word 文档（.docx）所有格式和信息：正文、标题层级、表格、加粗/列表、分章节、段落字体与段落格式。
输出 outputs/document_full.json（含 paragraphs/tables/outline/blocks/sections）、document_full.txt、images/。
handlers 必须为 direct_python，禁止 LLM 编造文档内容。"""

WORD_GEN_BRIEF = """员工包 ID：word-generate-employee
员工名称：Word生成员工
版本：1.0.0

根据 document_full.json（与 Word 全量读取同 schema）生成 Word 文档；可选 inputs/template.docx 作为样式模板。
输出 outputs/generated_document.docx。JSON 为中介。handlers 含 direct_python。"""


def _empty_asset_manifest() -> dict:
    return {
        "assets": [],
        "templates": [],
        "example_inputs": [],
        "expected_outputs": [],
        "rules": [],
    }


def _bootstrap_one(*, brief: str, extra_files: dict | None = None) -> Path:
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        build_rule_spec,
        materialize_asset_employee_pack,
    )
    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path

    asset_manifest = _empty_asset_manifest()
    if extra_files:
        session_assets = Path(tempfile.mkdtemp(prefix="word_emp_assets_"))
        inputs_dir = session_assets / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        for name, content in extra_files.items():
            p = inputs_dir / name
            if isinstance(content, bytes):
                p.write_bytes(content)
            elif isinstance(content, dict):
                p.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                p.write_text(str(content), encoding="utf-8")
            asset_manifest["assets"].append(
                {
                    "id": name,
                    "filename": name,
                    "kind": "example_input",
                    "suffix": Path(name).suffix.lower(),
                    "storage_path": str(p),
                }
            )

    rule_spec = build_rule_spec(brief, asset_manifest)
    manifest = _fallback_manifest(brief, rule_spec)
    manifest["id"] = rule_spec.get("runtime_kind", "").replace("_", "-")
    if "word-full-read" in brief or "word-full-read-employee" in brief:
        manifest["id"] = "word-full-read-employee"
    if "word-generate-employee" in brief:
        manifest["id"] = "word-generate-employee"
    manifest["version"] = "1.0.0"
    manifest["description"] = brief.split("\n")[0][:200]
    manifest["artifact"] = "employee_pack"

    pack_dir, raw_zip = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest=asset_manifest,
        generated_convert_py=None,
    )
    lib = modstore_library_path()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = Path(tmp.name)
    try:
        dest = import_zip(tmp_path, lib, replace=True)
    finally:
        tmp_path.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "ok": True,
                "pack_id": dest.name,
                "path": str(dest),
                "runtime_kind": rule_spec.get("runtime_kind"),
            },
            ensure_ascii=False,
        )
    )
    return dest


def main() -> int:
    from modstore_server.word_generate_runtime import minimal_document_full_json
    from modstore_server.word_extract_runtime import minimal_docx_bytes

    _bootstrap_one(brief=WORD_READ_BRIEF)
    _bootstrap_one(
        brief=WORD_GEN_BRIEF,
        extra_files={
            "document_full.json": minimal_document_full_json(),
            "template.docx": minimal_docx_bytes(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
