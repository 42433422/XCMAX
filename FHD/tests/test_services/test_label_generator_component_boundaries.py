"""Generated label programs must work with real images and untrusted text values."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from PIL import Image, ImageFont

from app.services.skills.label_template_generator import analysis as image_analysis
from app.services.skills.label_template_generator import label_template_generator as generator
from app.services.skills.label_template_generator import ocr as image_ocr
from app.services.skills.label_template_generator.ports import Grid, ImageAnalysisPorts, OCRPorts


@pytest.fixture
def reference_image(tmp_path: Path) -> Path:
    path = tmp_path / "reference.png"
    with Image.new("RGB", (800, 600), "white") as image:
        image.save(path)
    return path


def _load_class(code: str) -> type:
    namespace: dict[str, Any] = {"__name__": "generated_label_fixture"}
    exec(compile(code, "<generated-label>", "exec"), namespace)
    return cast(type, namespace["FixtureLabel"])


def _code(reference_image: Path, *, fields: bool = False) -> str:
    ocr = (
        {
            "success": True,
            "fields": [
                {
                    "field_key": "product_name",
                    "label": "Name",
                    "value": "sample",
                    "type": "dynamic",
                }
            ],
        }
        if fields
        else None
    )
    return generator.generate_template_code(str(reference_image), "FixtureLabel", ocr)


@pytest.mark.parametrize("text", ['Value "quoted"', "first line\nsecond line", "C:\\new\\table"])
def test_field_text_round_trips_through_generated_python(reference_image, text):
    fields = [
        {"field_key": text, "label": text, "value": text, "type": "dynamic"},
    ]
    code = generator.generate_template_code(
        str(reference_image), "FixtureLabel", {"success": True, "fields": fields}
    )

    generated = _load_class(code)()

    assert generated.fields[text] == {
        "label": text,
        "default_value": text,
        "type": "dynamic",
        "editable": False,
    }


def test_reference_filename_cannot_break_generated_python(tmp_path):
    source = tmp_path / 'reference-"""-quoted.png'
    with Image.new("RGB", (200, 200), "white") as image:
        image.save(source)

    generated = _load_class(_code(source))()

    assert (generated.width, generated.height) == (200, 200)


@pytest.mark.parametrize("class_name", ["class", "invalid-name", "Label:\n    pass\n"])
def test_invalid_class_name_does_not_publish_a_python_file(reference_image, tmp_path, class_name):
    destination = tmp_path / "generated.py"

    result = generator.LabelTemplateGeneratorSkill().execute(
        str(reference_image), class_name=class_name, output_file=str(destination), enable_ocr=False
    )

    assert result["success"] is False
    assert result.get("message")
    assert not destination.exists()


@pytest.mark.parametrize("fields", [False, True])
def test_generated_label_handles_real_output_errors(reference_image, tmp_path, monkeypatch, fields):
    label_class = _load_class(_code(reference_image, fields=fields))
    monkeypatch.setattr(label_class, "_get_font", lambda self, size: ImageFont.load_default())
    output = tmp_path / "blocked-output"
    output.write_text("owned by an existing file")
    label = label_class(output_dir=str(output))

    assert label.generate_label({"product_name": "sample"}, "ORDER", 1) is None
    assert output.read_text() == "owned by an existing file"


@pytest.mark.parametrize("fields", [False, True])
def test_generated_filename_stays_inside_the_output_directory(
    reference_image, tmp_path, monkeypatch, fields
):
    label_class = _load_class(_code(reference_image, fields=fields))
    monkeypatch.setattr(label_class, "_get_font", lambda self, size: ImageFont.load_default())
    output = tmp_path / "labels"
    outside = tmp_path / "outside"
    outside.mkdir()
    label = label_class(output_dir=str(output))

    filename = label.generate_label({"product_name": "sample"}, "../outside/escape", 1)

    assert filename is not None
    assert not list(outside.iterdir())
    assert Path(filename).name == filename
    with Image.open(output / filename) as image:
        assert image.size == (800, 600)


def test_generated_barcode_is_pasted_into_its_owned_image(reference_image, tmp_path, monkeypatch):
    class Barcode:
        def __init__(self, value, writer):
            self.value = value

        def write(self, buffer, options):
            with Image.new("RGB", (360, 40), "black") as image:
                image.save(buffer, format="PNG")

    barcode = ModuleType("barcode")
    for name in ("Code128", "EAN13", "Code39"):
        setattr(barcode, name, Barcode)
    writer = ModuleType("barcode.writer")
    monkeypatch.setattr(writer, "ImageWriter", object, raising=False)
    monkeypatch.setitem(sys.modules, "barcode", barcode)
    monkeypatch.setitem(sys.modules, "barcode.writer", writer)
    label_class = _load_class(_code(reference_image, fields=True))
    monkeypatch.setattr(label_class, "_get_font", lambda self, size: ImageFont.load_default())
    output = tmp_path / "labels"
    label = label_class(output_dir=str(output))

    filename = label.generate_label({"product_name": "sample", "barcode_data": "ABC123"}, "ORDER")

    assert filename is not None
    with Image.open(output / filename) as image:
        assert image.getpixel((400, 120)) == (0, 0, 0)


@pytest.mark.parametrize("size", [(1, 1), (5, 12), (20, 20)])
def test_small_images_keep_their_actual_background_color(tmp_path, size):
    source = tmp_path / "small.png"
    with Image.new("RGB", size, "#123456") as image:
        image.save(source)

    analysis = generator.analyze_image(str(source))

    assert analysis["success"] is True
    assert analysis["colors"]["background"] == "#123456"
    assert analysis["colors"]["is_consistent_background"] is True


def test_cli_publishes_importable_generator(reference_image, tmp_path):
    output = tmp_path / "generated.py"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            generator.__name__,
            "--image",
            str(reference_image),
            "--output",
            str(output),
            "--name",
            "FixtureLabel",
            "--no-ocr",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "代码已保存到" in completed.stdout
    generated = _load_class(output.read_text(encoding="utf-8"))()
    assert (generated.width, generated.height) == (800, 600)


def test_capability_modules_import_without_facade_or_optional_ocr_engines():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, sys; "
            "prefix = 'app.services.skills.label_template_generator.'; "
            "[importlib.import_module(prefix + part) for part in "
            "('ports', 'analysis', 'fields', 'grid', 'adapters', 'ocr', 'codegen', 'skill')]; "
            "assert prefix + 'label_template_generator' not in sys.modules; "
            "assert 'cv2' not in sys.modules; assert 'paddleocr' not in sys.modules",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout


@pytest.mark.parametrize("fail", [False, True])
def test_analysis_closes_its_image_after_success_or_callback_error(reference_image, fail):
    image = Image.open(reference_image)

    def colors(source):
        if fail:
            raise ValueError("injected palette failure")
        return generator._analyze_colors(source)

    ports = ImageAnalysisPorts(
        lambda path: image,
        colors,
        generator._estimate_sections,
        generator._estimate_font_sizes,
        logging.getLogger(__name__),
    )

    result = image_analysis.analyze_image(ports, str(reference_image))

    assert result["success"] is not fail
    with pytest.raises(ValueError, match="closed image"):
        image.getpixel((0, 0))


@pytest.mark.parametrize("fail", [False, True])
def test_ocr_closes_its_image_after_success_or_detector_error(reference_image, fail):
    image = Image.open(reference_image)

    def detect(source):
        if fail:
            raise ValueError("injected grid failure")
        return Grid([], [], [], [])

    class Service:
        def recognize_text_blocks(self, source):
            return [{"text": "Name sample", "confidence": 1.0}]

        def get_active_ocr_backend(self):
            return "fixture"

    ports = OCRPorts(
        lambda path: image,
        lambda: detect,
        Service,
        lambda blocks, horizontal, vertical, merged=None: [],
        lambda text: [{"label": "Name", "value": "sample"}],
        logging.getLogger(__name__),
    )

    result = image_ocr.extract_text_with_ocr(ports, str(reference_image))

    assert result["success"] is not fail
    with pytest.raises(ValueError, match="closed image"):
        image.getpixel((0, 0))
