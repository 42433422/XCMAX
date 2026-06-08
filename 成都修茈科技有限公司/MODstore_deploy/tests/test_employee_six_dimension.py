"""Tests for six-dimension employee pipeline scoring."""

from pathlib import Path

from modstore_server.employee_six_dimension import (
    SIX_DIMENSION_KEYS,
    compute_six_dimension_report,
    score_to_grade,
)


def test_six_dimensions_all_present_word_green(tmp_path: Path):
    pack = tmp_path / "word-full-extract-employee"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        '{"id":"word-full-extract-employee","artifact":"employee_pack",'
        '"employee":{"id":"word-full-extract-employee","label":"Word"},'
        '"employee_config_v2":{"actions":{"handlers":["direct_python"]}}}',
        encoding="utf-8",
    )
    (pack / "rule_spec.json").write_text(
        '{"runtime_kind":"word_full_extract"}',
        encoding="utf-8",
    )
    vendor = pack / "backend" / "vendor" / "word_full_extract"
    vendor.mkdir(parents=True)
    (vendor / "convert.py").write_text(
        "def convert_file(src, out, rule_spec):\n"
        "    return {'paragraphs':[],'tables':[],'images':[],'core_properties':{}}\n",
        encoding="utf-8",
    )

    report = compute_six_dimension_report(
        pack_dir=pack,
        pipeline_label="word_full_extract",
        routing_brief="全量提取 Word docx 输出 JSON 和 txt",
        structured_requirement={"suggested_handlers": ["direct_python"]},
        mod_sandbox={
            "ok": True,
            "checks": [
                {"id": "manifest", "ok": True},
                {"id": "python_compile", "ok": True},
                {"id": "employee_pack_consistency", "ok": True},
                {"id": "word_extract_runtime", "ok": True},
            ],
        },
        workflow_sandbox={"ok": True, "skipped": False},
        workflow_biz_ok=True,
        standalone_smoke_ok=True,
        catalog_registered=True,
        employee_target="pack_plus_workflow",
    )
    assert len(report["dimensions"]) == 6
    assert set(report["dimensions"].keys()) == set(SIX_DIMENSION_KEYS)
    assert report["overall_score"] >= 70
    assert report["passed"] is True
    assert report["critical_failed"] is False
    assert report.get("overall_grade") in ("S", "A", "B", "P")


def test_catalog_fail_low_executability(tmp_path: Path):
    pack = tmp_path / "emp"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        '{"id":"emp","artifact":"employee_pack","employee":{"id":"emp","label":"E"},'
        '"employee_config_v2":{"actions":{"handlers":["direct_python"]}}}',
        encoding="utf-8",
    )
    report = compute_six_dimension_report(
        pack_dir=pack,
        pipeline_label="asset",
        routing_brief="处理 Excel 考勤表",
        catalog_registered=False,
        standalone_smoke_ok=False,
        mod_sandbox={"ok": False, "checks": [{"id": "manifest", "ok": True}]},
    )
    assert report["dimensions"]["executability"]["score"] < 60
    assert report["critical_failed"] is True


def test_score_to_grade_tiers():
    assert score_to_grade(95)["code"] == "S"
    assert score_to_grade(88)["code"] == "A"
    assert score_to_grade(80)["code"] == "B"
    assert score_to_grade(72)["code"] == "P"
    assert score_to_grade(65)["code"] == "C"
    assert score_to_grade(55)["code"] == "D"
    assert score_to_grade(45)["code"] == "F"
    assert score_to_grade(30)["code"] == "G"
    assert score_to_grade(90, force_g=True)["code"] == "G"


def test_six_dimensions_txt_full_read_green(tmp_path: Path):
    pack = tmp_path / "txt-full-read-employee"
    pack.mkdir()
    from modstore_server.txt_extract_runtime import render_txt_read_convert_module

    vendor = pack / "backend" / "vendor" / "txt_full_read"
    vendor.mkdir(parents=True)
    (vendor / "convert.py").write_text(render_txt_read_convert_module(), encoding="utf-8")
    (pack / "manifest.json").write_text(
        '{"id":"txt-full-read-employee","artifact":"employee_pack",'
        '"employee":{"id":"txt-full-read-employee","label":"TXT Read"},'
        '"employee_config_v2":{"actions":{"handlers":["direct_python"]}}}',
        encoding="utf-8",
    )
    (pack / "rule_spec.json").write_text('{"runtime_kind":"txt_full_read"}', encoding="utf-8")

    report = compute_six_dimension_report(
        pack_dir=pack,
        pipeline_label="txt_full_read",
        routing_brief="TXT 全量读取 .txt 原样输出",
        structured_requirement={"suggested_handlers": ["direct_python"]},
        mod_sandbox={
            "ok": True,
            "checks": [
                {"id": "manifest", "ok": True},
                {"id": "python_compile", "ok": True},
                {"id": "employee_pack_consistency", "ok": True},
                {"id": "txt_read_runtime", "ok": True},
            ],
        },
        workflow_sandbox={"ok": True, "skipped": False},
        workflow_biz_ok=True,
        standalone_smoke_ok=True,
        catalog_registered=True,
        employee_target="pack_plus_workflow",
    )
    assert report["passed"] is True
    assert report["overall_score"] >= 70


def test_six_dimensions_txt_generate_green(tmp_path: Path):
    pack = tmp_path / "txt-generate-employee"
    pack.mkdir()
    from modstore_server.txt_extract_runtime import render_txt_generate_convert_module

    vendor = pack / "backend" / "vendor" / "txt_generate"
    vendor.mkdir(parents=True)
    (vendor / "convert.py").write_text(render_txt_generate_convert_module(), encoding="utf-8")
    (pack / "manifest.json").write_text(
        '{"id":"txt-generate-employee","artifact":"employee_pack",'
        '"employee":{"id":"txt-generate-employee","label":"TXT Gen"},'
        '"employee_config_v2":{"actions":{"handlers":["direct_python","agent"]}}}',
        encoding="utf-8",
    )
    (pack / "rule_spec.json").write_text(
        '{"runtime_kind":"txt_generate","optional_llm_polish":true}',
        encoding="utf-8",
    )

    report = compute_six_dimension_report(
        pack_dir=pack,
        pipeline_label="txt_generate",
        routing_brief="TXT 生成 JSON 并写 txt 可选润色",
        structured_requirement={"suggested_handlers": ["direct_python", "agent"]},
        mod_sandbox={
            "ok": True,
            "checks": [
                {"id": "manifest", "ok": True},
                {"id": "python_compile", "ok": True},
                {"id": "employee_pack_consistency", "ok": True},
                {"id": "txt_generate_runtime", "ok": True},
            ],
        },
        workflow_sandbox={"ok": True, "skipped": False},
        workflow_biz_ok=True,
        standalone_smoke_ok=True,
        catalog_registered=True,
        employee_target="pack_plus_workflow",
    )
    assert report["passed"] is True
    assert report["overall_score"] >= 70


def test_report_includes_overall_grade(tmp_path: Path):
    pack = tmp_path / "emp"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        '{"id":"emp","artifact":"employee_pack","employee":{"id":"emp","label":"E"},'
        '"employee_config_v2":{"actions":{"handlers":["direct_python"]}}}',
        encoding="utf-8",
    )
    report = compute_six_dimension_report(
        pack_dir=pack,
        pipeline_label="asset",
        routing_brief="测试",
        mod_sandbox={"ok": True, "checks": [{"id": "manifest", "ok": True}]},
        catalog_registered=True,
    )
    assert report.get("overall_grade") in ("S", "A", "B", "P", "C", "D", "F", "G")
    assert report.get("overall_grade_label")
    assert report["dimensions"]["pack_compliance"].get("grade")
