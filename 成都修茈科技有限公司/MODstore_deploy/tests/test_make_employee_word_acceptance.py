"""Phase A Word 锚点：黄金对比、LLM 来源门禁、路由一致性（不依赖在线 LLM）。"""

from pathlib import Path

import pytest

from modstore_server.catalog_quality import resolve_employee_pack_dir
from modstore_server.employee_golden_compare import (
    GOLDEN_PARITY_PASS_THRESHOLD,
    compare_with_golden,
    golden_pack_id_for_runtime,
)
from modstore_server.employee_pack_cleanup import is_experimental_pack_id
from modstore_server.employee_pipeline_routing import (
    pipeline_label_for_runtime_kind,
    resolve_employee_runtime_kind,
    validate_runtime_pipeline_consistency,
)
from modstore_server.vibecoding_convert_loop import is_llm_codegen_source


def test_golden_pack_mapping_word_extract():
    assert golden_pack_id_for_runtime("word_full_extract") == "word-full-read-employee"


def test_golden_compare_passes_on_reference_pack():
    golden_dir = resolve_employee_pack_dir("word-full-read-employee")
    if not golden_dir or not golden_dir.is_dir():
        pytest.skip("golden pack word-full-read-employee not in library")
    smoke = {"ok": True, "output_json_keys": ["paragraphs", "tables", "metadata", "plain_text"]}
    result = compare_with_golden(
        golden_dir,
        golden_pack_id="word-full-read-employee",
        runtime_kind="word_full_extract",
        domain_smoke=smoke,
    )
    assert result["parity_score"] >= GOLDEN_PARITY_PASS_THRESHOLD
    assert result["passed"] is True


def test_llm_codegen_source_rejects_builtin():
    assert is_llm_codegen_source({"source": "llm_codegen", "generated": True})
    assert is_llm_codegen_source({"source": "llm_codegen_repair", "generated": True})
    assert not is_llm_codegen_source({"source": "word_extract_builtin"})
    assert not is_llm_codegen_source({"source": "auto_fixed", "generated": True})


def test_runtime_pipeline_consistency_word():
    brief = "Word docx 全量提取 document_full.json runtime_kind: word_full_extract"
    rk = resolve_employee_runtime_kind(brief)
    assert rk == "word_full_extract"
    label = pipeline_label_for_runtime_kind(rk)
    ok, err = validate_runtime_pipeline_consistency(
        routing_brief=brief,
        pipeline_label=label,
        rule_spec={"runtime_kind": rk},
    )
    assert ok, err


def test_experimental_pack_id_detected():
    assert is_experimental_pack_id("word-full-read-employee-vibecode-train")
    assert is_experimental_pack_id("foo-llm-lab")
    assert not is_experimental_pack_id("word-full-read-employee")


def test_golden_compare_fails_without_convert(tmp_path: Path):
    pack = tmp_path / "empty-pack"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        '{"id":"empty-pack","artifact":"employee","employee_config_v2":{"actions":{"handlers":["direct_python"]}}}',
        encoding="utf-8",
    )
    (pack / "rule_spec.json").write_text('{"runtime_kind":"word_full_extract"}', encoding="utf-8")
    result = compare_with_golden(
        pack,
        golden_pack_id="word-full-read-employee",
        runtime_kind="word_full_extract",
        domain_smoke={"ok": False, "error": "no convert"},
    )
    assert not result["passed"]
    assert result["parity_score"] < GOLDEN_PARITY_PASS_THRESHOLD
