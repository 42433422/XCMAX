"""Tests for TXT full-read and TXT generate employee runtimes."""

from __future__ import annotations

import json
from pathlib import Path

from modstore_server.txt_extract_runtime import (
    build_txt_generate_rule_spec,
    build_txt_read_rule_spec,
    is_txt_full_read,
    is_txt_generate,
    minimal_txt_fixture_bytes,
    render_txt_generate_convert_module,
    render_txt_read_convert_module,
    validate_txt_generate_backend,
    validate_txt_read_backend,
)
from modstore_server.word_extract_runtime import is_word_full_extract


def test_txt_full_read_routing_not_word():
    brief = "制作 TXT 全量读取员工包，上传 .txt 直接读取全部纯文本"
    assert is_txt_full_read(brief)
    assert not is_txt_generate(brief)
    assert not is_word_full_extract(brief)


def test_txt_generate_routing():
    brief = "制作 TXT 生成员工：上传 txt 读取输出 JSON 并写 generated_document.txt"
    assert is_txt_generate(brief)
    assert not is_txt_full_read(brief)
    assert not is_word_full_extract(brief)


def test_txt_read_convert_roundtrip(tmp_path: Path):
    src = tmp_path / "inputs" / "sample.txt"
    src.parent.mkdir(parents=True)
    content = "line one\nline two\n"
    src.write_text(content, encoding="utf-8")
    out = tmp_path / "outputs" / "document_full.txt"
    rule_spec = build_txt_read_rule_spec("txt read")
    mod_src = render_txt_read_convert_module()
    ns: dict = {}
    exec(mod_src, ns)  # noqa: S102
    result = ns["convert_file"](
        src,
        out,
        template_path=None,
        payload={},
        ctx={},
        rule_spec=rule_spec,
    )
    assert out.is_file()
    assert out.read_bytes() == src.read_bytes()
    meta = tmp_path / "outputs" / "document_meta.json"
    assert meta.is_file()
    meta_data = json.loads(meta.read_text(encoding="utf-8"))
    assert meta_data["line_count"] == 2
    assert result["char_count"] == len(meta_data["plain_text"])


def test_txt_generate_convert_roundtrip(tmp_path: Path):
    src = tmp_path / "inputs" / "note.txt"
    src.parent.mkdir(parents=True)
    src.write_bytes(minimal_txt_fixture_bytes())
    out = tmp_path / "outputs" / "document_parsed.json"
    rule_spec = build_txt_generate_rule_spec("txt generate json")
    mod_src = render_txt_generate_convert_module()
    ns: dict = {}
    exec(mod_src, ns)  # noqa: S102
    ns["convert_file"](src, out, template_path=None, payload={}, ctx={}, rule_spec=rule_spec)
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "lines" in data and "paragraphs" in data
    gen_txt = tmp_path / "outputs" / "generated_document.txt"
    assert gen_txt.is_file()
    assert "smoke" in gen_txt.read_text(encoding="utf-8")


def _make_pack(tmp_path: Path, *, pack_id: str, runtime_kind: str, convert_py: str) -> Path:
    from modstore_server.employee_asset_pipeline import _runtime_package_name

    pack = tmp_path / pack_id
    vendor = pack / "backend" / "vendor" / _runtime_package_name(pack_id, pack_id)
    vendor.mkdir(parents=True)
    (vendor / "convert.py").write_text(convert_py, encoding="utf-8")
    handlers = ["direct_python"] if runtime_kind == "txt_full_read" else ["direct_python", "agent"]
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "artifact": "employee_pack",
                "employee": {"id": pack_id, "label": pack_id},
                "employee_config_v2": {"actions": {"handlers": handlers}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pack / "rule_spec.json").write_text(
        json.dumps({"runtime_kind": runtime_kind}, ensure_ascii=False),
        encoding="utf-8",
    )
    return pack


def test_validate_txt_read_backend_ok(tmp_path: Path):
    pack = _make_pack(
        tmp_path,
        pack_id="txt-full-read-employee",
        runtime_kind="txt_full_read",
        convert_py=render_txt_read_convert_module(),
    )
    errs, _ = validate_txt_read_backend(pack)
    assert not errs


def test_validate_txt_generate_backend_ok(tmp_path: Path):
    pack = _make_pack(
        tmp_path,
        pack_id="txt-generate-employee",
        runtime_kind="txt_generate",
        convert_py=render_txt_generate_convert_module(),
    )
    errs, _ = validate_txt_generate_backend(pack)
    assert not errs
