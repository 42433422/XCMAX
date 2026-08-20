from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from PIL import Image

from app.infrastructure.skills.label_template_generator import barcode_generator


def test_barcode_type_validation_and_descriptions() -> None:
    assert barcode_generator.BarcodeGenerator("EAN13").barcode_type == "ean13"
    assert barcode_generator.BarcodeGenerator("unknown").barcode_type == "code128"
    assert "ean13" in barcode_generator.BarcodeGenerator.get_supported_types()
    assert "国际商品" in barcode_generator.BarcodeGenerator.get_type_description("EAN13")
    assert "未知类型" in barcode_generator.BarcodeGenerator.get_type_description("custom")


def test_clean_barcode_data_for_numeric_and_alphanumeric_types() -> None:
    generator = barcode_generator.BarcodeGenerator()
    assert generator._clean_barcode_data("", "code128") == ""
    assert generator._clean_barcode_data(" A-b 12 ", "code128") == "Ab12"
    assert generator._clean_barcode_data("12-ab", "itf") == "12"
    assert generator._clean_barcode_data("123", "ean13") == "123000000000"
    assert generator._clean_barcode_data("12345678901234", "ean13") == "1234567890123"
    assert generator._clean_barcode_data("123456789012", "ean13") == "123456789012"
    assert generator._clean_barcode_data("12", "ean8") == "1200000"
    assert generator._clean_barcode_data("123456789", "ean8") == "12345678"
    assert generator._clean_barcode_data("12345678", "ean8") == "12345678"
    assert generator._clean_barcode_data("12", "upca") == "12000000000"
    assert generator._clean_barcode_data("1234567890123", "upca") == "123456789012"
    assert generator._clean_barcode_data("123456789012", "upca") == "123456789012"


def test_generate_success_invalid_input_and_recoverable_fallback() -> None:
    generator = barcode_generator.BarcodeGenerator("code128")
    barcode = MagicMock()
    barcode_class = MagicMock(return_value=barcode)
    image = MagicMock(spec=Image.Image)
    fake_barcode = ModuleType("barcode")
    fake_barcode.get_barcode = MagicMock(return_value=barcode_class)  # type: ignore[attr-defined]
    fake_writer = ModuleType("barcode.writer")
    fake_writer.ImageWriter = MagicMock  # type: ignore[attr-defined]
    with (
        patch.dict(
            sys.modules,
            {"barcode": fake_barcode, "barcode.writer": fake_writer},
        ),
        patch.object(barcode_generator.Image, "open", return_value=image),
    ):
        result = generator.generate(
            "ABC-123",
            {
                "width": 1,
                "height": 20,
                "quiet_zone": 2,
                "font_size": 8,
                "text_distance": 3,
                "show_text": False,
                "foreground": "111111",
                "background": "eeeeee",
                "compress": True,
            },
        )
    assert result is image
    barcode_class.assert_called_once()
    options = barcode.write.call_args.kwargs["options"]
    assert options["module_height"] == 20.0 and options["show_text"] is False

    with patch.dict(sys.modules, {"barcode": fake_barcode, "barcode.writer": fake_writer}):
        assert generator.generate("") is None

    fallback = Image.new("RGB", (2, 2))
    with (
        patch.dict(sys.modules, {"barcode": fake_barcode, "barcode.writer": fake_writer}),
        patch.object(generator, "_generate_fallback_barcode", return_value=fallback) as make,
    ):
        fake_barcode.get_barcode.side_effect = RuntimeError("broken")  # type: ignore[attr-defined]
        assert generator.generate("ABC") is fallback
    make.assert_called_once_with("ABC", {})


def test_fallback_image_defaults_and_text_options() -> None:
    generator = barcode_generator.BarcodeGenerator()
    default = generator._generate_fallback_barcode("same")
    with_text = generator._generate_fallback_barcode("same", {"height": 20})
    without_text = generator._generate_fallback_barcode("same", {"height": 20, "show_text": False})
    assert default.size == (400, 70)
    assert with_text.size == without_text.size == (400, 40)


def test_save_and_convenience_functions(tmp_path) -> None:
    generator = barcode_generator.BarcodeGenerator()
    image = MagicMock(spec=Image.Image)
    destination = tmp_path / "barcode.png"
    with patch.object(generator, "generate", return_value=image):
        assert generator.save(str(destination), "ABC") is True
    image.save.assert_called_once_with(str(destination))

    with patch.object(generator, "generate", return_value=None):
        assert generator.save(str(destination), "") is False
    with patch.object(generator, "generate", side_effect=RuntimeError("broken")):
        assert generator.save(str(destination), "ABC") is False

    sentinel = Image.new("RGB", (1, 1))
    with patch.object(barcode_generator.BarcodeGenerator, "generate", return_value=sentinel):
        assert barcode_generator.generate_barcode("ABC", "code39") is sentinel
    with patch.object(barcode_generator.BarcodeGenerator, "save", return_value=True):
        assert barcode_generator.save_barcode(str(destination), "ABC", "code39") is True
