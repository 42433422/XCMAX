"""Manifest reconcile after workflow-style edits."""

import json
from pathlib import Path

from modstore_server.employee_asset_pipeline import (
    materialize_asset_employee_pack,
    reconcile_employee_pack_manifest,
)
from modstore_server.word_extract_runtime import (
    build_word_extract_rule_spec,
    validate_word_extract_backend,
)


def test_reconcile_restores_direct_python_handlers_after_llm_handlers(tmp_path: Path):
    brief = "帮我做 Word 文档全量提取，输出 JSON 和 txt，图片到 outputs/images/"
    rule_spec = build_word_extract_rule_spec(brief)
    manifest = {
        "id": "word-full-extract-employee",
        "name": "Word 全量提取员",
        "version": "1.0.0",
        "employee_config_v2": {
            "actions": {"handlers": ["llm_md", "echo"]},
        },
        "workflow_bundles": [
            {
                "name": "（无回复）",
                "description": "若无疑问，将按此方案生成执行清单并制作员工包",
                "nodes": [],
            },
        ],
    }
    pack_dir, _ = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest={"assets": []},
        generated_convert_py=None,
    )
    # Simulate workflow attach overwriting handlers
    mf_path = pack_dir / "manifest.json"
    raw = json.loads(mf_path.read_text(encoding="utf-8"))
    v2 = raw.setdefault("employee_config_v2", {})
    actions = v2.setdefault("actions", {})
    actions["handlers"] = ["llm_md", "echo"]
    raw["actions"] = {"handlers": ["llm_md", "echo"]}
    mf_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reconcile_employee_pack_manifest(pack_dir, brief=brief)

    fixed = json.loads(mf_path.read_text(encoding="utf-8"))
    handlers = fixed.get("employee_config_v2", {}).get("actions", {}).get("handlers")
    assert handlers == ["direct_python"]
    bundle_name = fixed.get("workflow_bundles", [{}])[0].get("name")
    assert bundle_name != "（无回复）"
    errs, _ = validate_word_extract_backend(pack_dir)
    assert not errs
