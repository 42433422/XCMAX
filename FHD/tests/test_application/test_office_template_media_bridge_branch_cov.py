"""office_template_media_bridge 分支覆盖测试。

覆盖 app/application/office_template_media_bridge.py 的全部公共函数与分支：
占位符/字段提取、PPTX/PDF 文本提取（zip 与库两种引擎及其回退）、OCR、
VLM 增强、pptx/pdf 模板 analyze 载荷构建。

策略：用 fake 模块替换 sys.modules 中的重依赖（pptx/pypdf/openpyxl/PIL 及
shipment_excel_etl_ocr/vlm_route/mod_employee_llm），避免真实文件/网络/LLM 调用，
保证快速且确定。
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.application import office_template_media_bridge as bridge

# ---------------------------------------------------------------------------
# 通用 fake 模块工厂
# ---------------------------------------------------------------------------


def _install_fake_module(monkeypatch, name: str, obj) -> None:
    monkeypatch.setitem(sys.modules, name, obj)


def _fake_pptx_module() -> MagicMock:
    mod = SimpleNamespace()
    mod.Presentation = MagicMock()
    return mod


def _fake_pypdf_module() -> SimpleNamespace:
    return SimpleNamespace(PdfReader=MagicMock())


def _fake_openpyxl_module() -> SimpleNamespace:
    return SimpleNamespace(load_workbook=MagicMock())


def _fake_pil_module() -> SimpleNamespace:
    return SimpleNamespace(Image=MagicMock())


def _fake_ocr_module(ocr_result=None, load_images=None) -> SimpleNamespace:
    mod = SimpleNamespace()
    mod.ocr_source_to_workbook = MagicMock(return_value=ocr_result)
    mod._load_image_arrays = MagicMock(return_value=load_images)
    return mod


def _fake_vlm_route_module() -> SimpleNamespace:
    return SimpleNamespace(resolve_vlm_route=MagicMock())


def _fake_mod_llm_module() -> SimpleNamespace:
    return SimpleNamespace(mod_employee_complete=AsyncMock())


# ---------------------------------------------------------------------------
# 占位符 / 字段纯函数
# ---------------------------------------------------------------------------


class TestPlaceholderAndFields:
    def test_extract_placeholder_tokens_all_patterns_and_dedup(self):
        text = "{{name}} {% if x %} ${price} [[note]] {{ name }} {{price}} plain"
        tokens = bridge.extract_placeholder_tokens(text)
        assert tokens == ["name", "price", "if x", "note"]

    def test_extract_placeholder_tokens_empty_and_none(self):
        assert bridge.extract_placeholder_tokens("") == []
        assert bridge.extract_placeholder_tokens(None) == []
        assert bridge.extract_placeholder_tokens("no placeholders here") == []

    def test_extract_placeholder_tokens_blank_group(self):
        # 空 token 被剔除
        assert bridge.extract_placeholder_tokens("{{  }} {{x}}") == ["x"]

    def test_fields_from_tokens(self):
        fs = bridge.fields_from_tokens(["a", "b"])
        assert fs == [
            {"label": "a", "value": "", "type": "dynamic"},
            {"label": "b", "value": "", "type": "dynamic"},
        ]

    def test_fields_from_text_lines_dedup_and_clean(self):
        fs = bridge.fields_from_text_lines("  Hello   World \nHello World\n\n  Item \n")
        assert fs == [
            {"label": "Hello World", "value": "", "type": "dynamic"},
            {"label": "Item", "value": "", "type": "dynamic"},
        ]

    def test_fields_from_text_lines_limit_and_empty(self):
        text = "\n".join(f"line {i}" for i in range(100))
        fs = bridge.fields_from_text_lines(text, limit=3)
        assert len(fs) == 3
        assert fs[0]["label"] == "line 0"
        assert bridge.fields_from_text_lines("") == []
        assert bridge.fields_from_text_lines(None) == []

    def test_fields_from_text_lines_label_truncated_80(self):
        long = "x" * 120
        fs = bridge.fields_from_text_lines(long)
        assert fs[0]["label"] == "x" * 80


# ---------------------------------------------------------------------------
# _collect_ooxml_text
# ---------------------------------------------------------------------------


class TestCollectOoxmlText:
    def test_collects_text_and_tail(self):
        xml = (
            '<?xml version="1.0"?><root><a:t>Hello</a:t></root>'
            '<?xml version="1.0"?>'
        )
        # 包含 t 与 tail
        xml2 = (
            '<root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:t>One</a:t>tail<a:p><a:t>Two</a:t></a:p></root>'
        )
        out = bridge._collect_ooxml_text(xml2.encode(), bridge._A_T)
        assert out == "OnetailTwo"

    def test_parse_error_returns_empty(self):
        assert bridge._collect_ooxml_text(b"<broken", bridge._A_T) == ""

    def test_no_matching_tag(self):
        out = bridge._collect_ooxml_text(b"<root><b>hi</b></root>", bridge._A_T)
        assert out == ""


# ---------------------------------------------------------------------------
# _extract_pptx_text_via_lib
# ---------------------------------------------------------------------------


class _RaisePara:
    @property
    def text(self):  # pragma: no cover - 触发 RECOVERABLE_ERRORS
        raise RuntimeError("boom")


class _RaiseFrame:
    @property
    def text(self):  # pragma: no cover - 触发 RECOVERABLE_ERRORS
        raise RuntimeError("boom")


class TestExtractPptxViaLib:
    def test_lib_success_with_notes(self, monkeypatch):
        fake = _fake_pptx_module()
        _install_fake_module(monkeypatch, "pptx", fake)
        prs = fake.Presentation.return_value

        slide = MagicMock()
        slide.shapes = [
            SimpleNamespace(has_text_frame=True, text_frame=SimpleNamespace(paragraphs=[SimpleNamespace(text="Title")])),
            SimpleNamespace(has_text_frame=False),
        ]
        slide.has_notes_slide = True
        slide.notes_slide.notes_text_frame = SimpleNamespace(text="  Notes  ")
        prs.slides = [slide]

        text, count = bridge._extract_pptx_text_via_lib("x.pptx")
        assert count == 1
        assert "[slide 1]" in text
        assert "Title" in text
        assert "Notes" in text

    def test_lib_recoverable_error_skips_para(self, monkeypatch):
        fake = _fake_pptx_module()
        _install_fake_module(monkeypatch, "pptx", fake)
        prs = fake.Presentation.return_value
        slide = MagicMock()
        slide.shapes = [
            SimpleNamespace(
                has_text_frame=True,
                text_frame=SimpleNamespace(paragraphs=[SimpleNamespace(text="ok"), _RaisePara()]),
            )
        ]
        slide.has_notes_slide = False
        prs.slides = [slide]

        text, count = bridge._extract_pptx_text_via_lib("x.pptx")
        assert count == 1
        assert "ok" in text
        assert "boom" not in text

    def test_lib_recoverable_error_skips_notes(self, monkeypatch):
        fake = _fake_pptx_module()
        _install_fake_module(monkeypatch, "pptx", fake)
        prs = fake.Presentation.return_value
        slide = MagicMock()
        slide.shapes = []
        slide.has_notes_slide = True
        slide.notes_slide.notes_text_frame = _RaiseFrame()
        prs.slides = [slide]

        text, count = bridge._extract_pptx_text_via_lib("x.pptx")
        assert count == 1
        assert text == "[slide 1]"


# ---------------------------------------------------------------------------
# _extract_pptx_text_via_zip
# ---------------------------------------------------------------------------


class _FakeZip:
    def __init__(self, names, reads):
        self._names = names
        self._reads = reads

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def namelist(self):
        return self._names

    def read(self, name):
        if name in self._reads:
            return self._reads[name]
        raise KeyError(name)


class TestExtractPptxViaZip:
    def test_zip_extracts_slides_and_notes(self, monkeypatch):
        names = [
            "ppt/slides/slide1.xml",
            "ppt/slides/slide10.xml",
            "ppt/notesSlides/notesSlide1.xml",
            "ppt/slides/slide2.xml",
            "other/data.txt",
        ]
        reads = {
            "ppt/slides/slide1.xml": b"s1",
            "ppt/slides/slide10.xml": b"s10",
            "ppt/notesSlides/notesSlide1.xml": b"n1",
            "ppt/slides/slide2.xml": b"s2",
        }
        monkeypatch.setattr(
            bridge.zipfile, "ZipFile", lambda path, mode: _FakeZip(names, reads)
        )
        monkeypatch.setattr(
            bridge,
            "_collect_ooxml_text",
            lambda xml, tag: xml.decode() if tag == bridge._A_T else "",
        )
        text, count = bridge._extract_pptx_text_via_zip("x.pptx")
        assert count == 3  # slide1, slide10, slide2
        assert "s1" in text and "s2" in text and "n1" in text

    def test_zip_skips_failed_parts(self, monkeypatch):
        names = ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml"]
        monkeypatch.setattr(
            bridge.zipfile, "ZipFile", lambda path, mode: _FakeZip(names, {})
        )
        called = []

        def _collect(xml, tag):
            called.append(xml)
            if xml == b"__missing__":
                raise KeyError("missing")
            return "ok"

        monkeypatch.setattr(bridge, "_collect_ooxml_text", _collect)
        # _FakeZip.read raises KeyError for any name -> caught
        text, count = bridge._extract_pptx_text_via_zip("x.pptx")
        assert count == 2
        assert text == ""


# ---------------------------------------------------------------------------
# extract_pptx_document_text
# ---------------------------------------------------------------------------


class TestExtractPptxDocumentText:
    def test_uses_lib_engine(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "_extract_pptx_text_via_lib", lambda fp: ("hello", 2)
        )
        meta = bridge.extract_pptx_document_text("x.pptx")
        assert meta["engine"] == "python-pptx"
        assert meta["text"] == "hello"
        assert meta["slide_count"] == 2
        assert meta["char_count"] == 5

    def test_fallback_to_zip_on_import_error(self, monkeypatch):
        def _boom(fp):
            raise ImportError("no pptx")

        monkeypatch.setattr(bridge, "_extract_pptx_text_via_lib", _boom)
        monkeypatch.setattr(
            bridge, "_extract_pptx_text_via_zip", lambda fp: ("ziptext", 3)
        )
        meta = bridge.extract_pptx_document_text("x.pptx")
        assert meta["engine"] == "zip_ooxml"
        assert meta["text"] == "ziptext"
        assert meta["slide_count"] == 3

    def test_fallback_to_zip_on_recoverable_error(self, monkeypatch):
        monkeypatch.setattr(
            bridge,
            "_extract_pptx_text_via_lib",
            lambda fp: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(
            bridge, "_extract_pptx_text_via_zip", lambda fp: ("ziptext", 1)
        )
        meta = bridge.extract_pptx_document_text("x.pptx")
        assert meta["engine"] == "zip_ooxml"
        assert meta["text"] == "ziptext"


# ---------------------------------------------------------------------------
# extract_pdf_document_text
# ---------------------------------------------------------------------------


class TestExtractPdfDocumentText:
    def _reader(self, pages_texts):
        pages = []
        for t in pages_texts:
            p = MagicMock()
            p.extract_text.return_value = t
            pages.append(p)
        reader = MagicMock()
        reader.pages = pages
        return reader

    def test_pdf_success(self, monkeypatch):
        fake = _fake_pypdf_module()
        _install_fake_module(monkeypatch, "pypdf", fake)
        fake.PdfReader.return_value = self._reader(["Page One", "Page Two"])
        meta = bridge.extract_pdf_document_text("x.pdf")
        assert meta["page_count"] == 2
        assert "[page 1]" in meta["text"]
        assert "[page 2]" in meta["text"]
        assert meta["engine"] == "pypdf"

    def test_pdf_skips_empty_and_error_pages(self, monkeypatch):
        fake = _fake_pypdf_module()
        _install_fake_module(monkeypatch, "pypdf", fake)
        p1 = MagicMock()
        p1.extract_text.return_value = "   "
        p2 = MagicMock()
        p2.extract_text.side_effect = RuntimeError("boom")
        reader = MagicMock()
        reader.pages = [p1, p2]
        fake.PdfReader.return_value = reader
        meta = bridge.extract_pdf_document_text("x.pdf")
        assert meta["text"] == ""
        assert meta["page_count"] == 2


# ---------------------------------------------------------------------------
# _ocr_pdf_plaintext
# ---------------------------------------------------------------------------


class TestOcrPdfPlaintext:
    def test_ocr_failure(self, monkeypatch):
        fake = _fake_ocr_module(ocr_result={"success": False, "message": "no text"})
        _install_fake_module(monkeypatch, "app.application.shipment_excel_etl_ocr", fake)
        out = bridge._ocr_pdf_plaintext("x.pdf")
        assert out["success"] is False
        assert out["engine"] == "ocr"
        assert "no text" in out["message"]

    def test_ocr_success_reads_workbook(self, monkeypatch):
        fake = _fake_ocr_module(
            ocr_result={
                "success": True,
                "workbook_path": "/tmp/out.xlsx",
                "message": "ok",
            }
        )
        _install_fake_module(monkeypatch, "app.application.shipment_excel_etl_ocr", fake)
        openpyxl = _fake_openpyxl_module()
        _install_fake_module(monkeypatch, "openpyxl", openpyxl)
        wb = MagicMock()
        ws = MagicMock()
        ws.iter_rows.return_value = [(None, "A", "B"), ("C", None, " D ")]
        wb.active = ws
        openpyxl.load_workbook.return_value = wb

        out = bridge._ocr_pdf_plaintext("x.pdf")
        assert out["success"] is True
        assert "A\tB" in out["text"]
        assert "C\tD" in out["text"]
        assert out["workbook_path"] == "/tmp/out.xlsx"

    def test_ocr_workbook_read_failure(self, monkeypatch):
        fake = _fake_ocr_module(
            ocr_result={"success": True, "workbook_path": "/tmp/out.xlsx"}
        )
        _install_fake_module(monkeypatch, "app.application.shipment_excel_etl_ocr", fake)

        def _boom(*a, **k):
            raise OSError("read fail")

        openpyxl = _fake_openpyxl_module()
        openpyxl.load_workbook = _boom
        _install_fake_module(monkeypatch, "openpyxl", openpyxl)
        out = bridge._ocr_pdf_plaintext("x.pdf")
        assert out["success"] is False
        assert "read fail" in out["message"]


# ---------------------------------------------------------------------------
# _vlm_enrich_enabled / _sync_vlm_describe_first_image
# ---------------------------------------------------------------------------


class TestVlmEnrichEnabled:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("on", True),
            (" 1 ", True),
            ("0", False),
            ("no", False),
            ("", False),
            ("off", False),
        ],
    )
    def test_vlm_enrich_enabled(self, monkeypatch, value, expected):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", value)
        assert bridge._vlm_enrich_enabled() is expected


class TestSyncVlmDescribe:
    def _install_route(self, monkeypatch, route):
        vlm = _fake_vlm_route_module()
        vlm.resolve_vlm_route.return_value = route
        _install_fake_module(monkeypatch, "app.infrastructure.llm.vlm_route", vlm)
        return vlm

    def _install_llm(self, monkeypatch, result):
        mod = _fake_mod_llm_module()
        mod.mod_employee_complete.return_value = result
        _install_fake_module(monkeypatch, "app.mod_sdk.mod_employee_llm", mod)
        return mod

    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.delenv("FHD_TEMPLATE_VLM_ENRICH", raising=False)
        assert bridge._sync_vlm_describe_first_image(b"data", hint="h") is None

    def test_no_image_bytes_returns_none(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        assert bridge._sync_vlm_describe_first_image(b"", hint="h") is None

    def test_route_not_ok(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        self._install_route(monkeypatch, {"ok": False, "message": "no route"})
        out = bridge._sync_vlm_describe_first_image(b"data", hint="h")
        assert out["vlm_ok"] is False
        assert out["message"] == "no route"

    def test_event_loop_busy_skips(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        self._install_route(monkeypatch, {"ok": True, "provider": "p", "model": "m"})
        loop = MagicMock()
        loop.is_running.return_value = True
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
        out = bridge._sync_vlm_describe_first_image(b"data", hint="h")
        assert out["vlm_ok"] is False
        assert out["message"] == "event_loop_busy_skip_vlm"

    def test_llm_failure(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        self._install_route(monkeypatch, {"ok": True, "provider": "p", "model": "m"})

        def _no_loop():
            raise RuntimeError("no loop")

        monkeypatch.setattr(asyncio, "get_running_loop", _no_loop)
        self._install_llm(
            monkeypatch, {"success": False, "error": "llm error"}
        )
        out = bridge._sync_vlm_describe_first_image(b"data", hint="h")
        assert out["vlm_ok"] is False
        assert "llm error" in out["message"]

    def test_llm_success(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        self._install_route(monkeypatch, {"ok": True, "provider": "px", "model": "mx"})
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError()))
        self._install_llm(monkeypatch, {"success": True, "content": " 描述文本  "})
        out = bridge._sync_vlm_describe_first_image(b"data", hint="h")
        assert out["vlm_ok"] is True
        assert out["description"] == "描述文本"
        assert out["route"] == {"provider": "px", "model": "mx"}

    def test_recoverable_error_skips(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        vlm = _fake_vlm_route_module()
        vlm.resolve_vlm_route.side_effect = OSError("boom")
        _install_fake_module(monkeypatch, "app.infrastructure.llm.vlm_route", vlm)
        out = bridge._sync_vlm_describe_first_image(b"data", hint="h")
        assert out["vlm_ok"] is False
        assert "boom" in out["message"]


# ---------------------------------------------------------------------------
# _maybe_pdf_page_image_bytes
# ---------------------------------------------------------------------------


class TestMaybePdfPageImageBytes:
    def test_no_images_returns_none(self, monkeypatch):
        fake = _fake_ocr_module(load_images=[])
        _install_fake_module(monkeypatch, "app.application.shipment_excel_etl_ocr", fake)
        assert bridge._maybe_pdf_page_image_bytes("x.pdf") is None

    def test_returns_png_bytes(self, monkeypatch):
        fake = _fake_ocr_module(load_images=[MagicMock()])
        _install_fake_module(monkeypatch, "app.application.shipment_excel_etl_ocr", fake)
        pil = _fake_pil_module()
        img = MagicMock()
        img.save = lambda buf, format: buf.write(b"PNGDATA")
        pil.Image.fromarray.return_value = img
        _install_fake_module(monkeypatch, "PIL", pil)
        out = bridge._maybe_pdf_page_image_bytes("x.pdf")
        assert out == b"PNGDATA"

    def test_recoverable_error_returns_none(self, monkeypatch):
        fake = _fake_ocr_module(load_images=[])
        fake._load_image_arrays.side_effect = OSError("boom")
        _install_fake_module(monkeypatch, "app.application.shipment_excel_etl_ocr", fake)
        assert bridge._maybe_pdf_page_image_bytes("x.pdf") is None


# ---------------------------------------------------------------------------
# build_pptx_template_analysis
# ---------------------------------------------------------------------------


class TestBuildPptxTemplateAnalysis:
    def test_success_with_tokens(self, monkeypatch):
        meta = {"text": "Hello {{name}} and ${price}", "engine": "python-pptx", "slide_count": 3}
        monkeypatch.setattr(bridge, "extract_pptx_document_text", lambda fp: meta)
        out = bridge.build_pptx_template_analysis(
            "dir/pres.pptx", template_name="模板A", original_filename="orig.pptx"
        )
        assert out["success"] is True
        assert out["template_name"] == "模板A"
        assert out["template_type"] == "pptx"
        assert out["preview_data"]["placeholders"] == ["name", "price"]
        assert out["preview_data"]["original_filename"] == "orig.pptx"
        assert out["preview_data"]["slide_count"] == 3

    def test_no_tokens_uses_text_lines(self, monkeypatch):
        meta = {"text": "第一行\n第二行", "engine": "zip_ooxml", "slide_count": 1}
        monkeypatch.setattr(bridge, "extract_pptx_document_text", lambda fp: meta)
        out = bridge.build_pptx_template_analysis("pres.pptx")
        assert out["success"] is True
        assert out["preview_data"]["placeholders"] == []
        assert out["preview_data"]["text_snippet"] == "第一行 第二行"
        assert out["preview_data"]["engine"] == "zip_ooxml"

    def test_no_fields_fails(self, monkeypatch):
        monkeypatch.setattr(bridge, "extract_pptx_document_text", lambda fp: {"text": "", "engine": "zip_ooxml"})
        out = bridge.build_pptx_template_analysis("pres.pptx")
        assert out["success"] is False
        assert "未能从 PPTX" in out["message"]

    def test_snippet_truncated_and_name_from_filename(self, monkeypatch):
        long_text = " ".join(["x" * 10] * 100) + " {{a}}"
        monkeypatch.setattr(
            bridge, "extract_pptx_document_text", lambda fp: {"text": long_text, "engine": "python-pptx"}
        )
        out = bridge.build_pptx_template_analysis("dir/my_pres.pptx")
        assert out["template_name"] == "my_pres"
        assert out["preview_data"]["text_snippet"].endswith("…")
        assert len(out["preview_data"]["text_snippet"]) == 401
        assert out["preview_data"]["original_filename"] == "my_pres.pptx"

    def test_original_filename_fallback_to_path_name(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "extract_pptx_document_text", lambda fp: {"text": "{{a}}", "engine": "python-pptx"}
        )
        out = bridge.build_pptx_template_analysis("dir/x.pptx", original_filename="")
        assert out["preview_data"]["original_filename"] == "x.pptx"


# ---------------------------------------------------------------------------
# build_pdf_template_analysis
# ---------------------------------------------------------------------------


class TestBuildPdfTemplateAnalysis:
    def test_extract_raises_recoverable(self, monkeypatch):
        monkeypatch.setattr(
            bridge,
            "extract_pdf_document_text",
            lambda fp: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        out = bridge.build_pdf_template_analysis("x.pdf")
        assert out["success"] is False
        assert "boom" in out["message"]

    def test_ocr_success_merges_text(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": "short", "engine": "pypdf", "page_count": 1}
        )
        monkeypatch.setattr(
            bridge,
            "_ocr_pdf_plaintext",
            lambda fp: {"success": True, "text": "OCR 文本 {{field}}", "workbook_path": "/w.xlsx", "char_count": 9},
        )
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: None)
        out = bridge.build_pdf_template_analysis("x.pdf")
        assert out["success"] is True
        assert out["preview_data"]["engine"] == "ocr"
        assert out["preview_data"]["ocr"]["workbook_path"] == "/w.xlsx"
        assert out["preview_data"]["placeholders"] == ["field"]

    def test_ocr_fail_warns_no_vlm(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": "short", "engine": "pypdf", "page_count": 1}
        )
        monkeypatch.setattr(
            bridge, "_ocr_pdf_plaintext", lambda fp: {"success": False, "message": "OCR 未产出文本"}
        )
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: None)
        out = bridge.build_pdf_template_analysis("x.pdf")
        assert out["success"] is True
        assert out["preview_data"]["engine"] == "pypdf"
        assert "OCR 未产出文本" in out["preview_data"]["warnings"]

    def test_vlm_enrich_merges_description(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": "long-enough-text", "engine": "pypdf", "page_count": 1}
        )
        monkeypatch.setattr(bridge, "_ocr_pdf_plaintext", lambda fp: {"success": False, "message": "x"})
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: b"PNG")
        monkeypatch.setattr(
            bridge,
            "_sync_vlm_describe_first_image",
            lambda img, hint: {"vlm_ok": True, "description": "VLM 描述 {{vlm_field}}"},
        )
        out = bridge.build_pdf_template_analysis("x.pdf")
        assert out["success"] is True
        assert "VLM 描述" in out["preview_data"]["text_snippet"]
        assert out["preview_data"]["vlm"]["vlm_ok"] is True
        assert out["preview_data"]["placeholders"] == ["vlm_field"]

    def test_vlm_no_image_bytes(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": "long-enough", "engine": "pypdf", "page_count": 1}
        )
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: None)
        out = bridge.build_pdf_template_analysis("x.pdf", template_name="t1")
        assert out["success"] is True
        assert out["template_name"] == "t1"
        assert "vlm" not in out["preview_data"]

    def test_no_fields_fails(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": "", "engine": "pypdf", "page_count": 1}
        )
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: None)
        monkeypatch.setattr(
            bridge, "_ocr_pdf_plaintext", lambda fp: {"success": False, "message": "OCR 未产出文本"}
        )
        out = bridge.build_pdf_template_analysis("x.pdf")
        assert out["success"] is False
        assert "未能从 PDF" in out["message"]
        assert "OCR 未产出文本" in out["warnings"]
        assert out["engine"] == "pypdf"

    def test_snippet_truncation_and_name(self, monkeypatch):
        long_text = " ".join(["y" * 10] * 100)
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": long_text, "engine": "pypdf", "page_count": 5}
        )
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: None)
        out = bridge.build_pdf_template_analysis("dir/report.pdf")
        assert out["success"] is True
        assert out["template_name"] == "report"
        assert out["preview_data"]["page_count"] == 5
        assert out["preview_data"]["text_snippet"].endswith("…")

    def test_vlm_sidecar_not_ok_keeps_text(self, monkeypatch):
        monkeypatch.setenv("FHD_TEMPLATE_VLM_ENRICH", "1")
        monkeypatch.setattr(
            bridge, "extract_pdf_document_text", lambda fp: {"text": "long-enough", "engine": "pypdf", "page_count": 1}
        )
        monkeypatch.setattr(bridge, "_maybe_pdf_page_image_bytes", lambda fp: b"PNG")
        monkeypatch.setattr(
            bridge,
            "_sync_vlm_describe_first_image",
            lambda img, hint: {"vlm_ok": False, "message": "fail"},
        )
        out = bridge.build_pdf_template_analysis("x.pdf")
        assert out["success"] is True
        assert out["preview_data"]["vlm"]["vlm_ok"] is False