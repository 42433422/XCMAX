"""Typed inputs for image analysis, OCR, template generation and skill execution."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TextIO

from PIL import Image

Payload = dict[str, Any]


class AnalyzeImage(Protocol):
    def __call__(self, image_path: str, verbose: bool = False) -> Payload: ...


class ExtractText(Protocol):
    def __call__(self, image_path: str, use_regions: bool = True) -> Payload: ...


class PairFields(Protocol):
    def __call__(
        self,
        text_blocks: list[Payload],
        horizontal_lines: list[int],
        vertical_lines: list[int],
        merged_horizontal: list[Payload] | None = None,
    ) -> list[Payload]: ...


class OCRService(Protocol):
    def recognize_text_blocks(self, image: Image.Image) -> list[Payload]: ...

    def get_active_ocr_backend(self) -> str: ...


class GenerateCode(Protocol):
    def __call__(
        self,
        image_path: str,
        class_name: str = "LabelTemplateGenerator",
        ocr_result: Payload | None = None,
        verbose: bool = False,
    ) -> str: ...


class OpenWriter(Protocol):
    def __call__(
        self, file: str, mode: str, *, encoding: str
    ) -> AbstractContextManager[TextIO]: ...


@dataclass(frozen=True)
class ImageAnalysisPorts:
    open_image: Callable[[str], Image.Image]
    colors: Callable[[Image.Image], Payload]
    sections: Callable[[int, int], list[Payload]]
    font_sizes: Callable[[int, int], dict[str, int]]
    logger: logging.Logger


@dataclass(frozen=True)
class Grid:
    horizontal: list[int]
    vertical: list[int]
    cells: list[Payload]
    merged: list[Payload]


@dataclass(frozen=True)
class OCRPorts:
    open_image: Callable[[str], Image.Image]
    load_grid_detector: Callable[[], Callable[[Image.Image], Grid]]
    service: Callable[[], OCRService]
    pair: PairFields
    fallback: Callable[[str], list[Payload]]
    logger: logging.Logger


@dataclass(frozen=True)
class CodePorts:
    analyze: AnalyzeImage
    with_fields: Callable[[str, str, int, int, Payload, list[Payload]], str]
    basic: Callable[[str, str, int, int, Payload], str]


@dataclass(frozen=True)
class SkillPorts:
    analyze: AnalyzeImage
    extract: ExtractText
    generate: GenerateCode
    open_writer: OpenWriter
    logger: logging.Logger


@dataclass(frozen=True)
class TemplateDescription:
    source: str
    class_name: str
    width: int
    height: int
    colors: Payload
    fields: list[Payload] | None
    created_at: datetime
