"""Compat module path: debt19 renamed ports.py → protocols.py."""

from __future__ import annotations

from app.application.shipment_etl.protocols import (  # noqa: F401
    DocumentPreview,
    ExtractionHistory,
    InputPath,
    OutputPath,
    Payload,
    ShipmentApplication,
    TemplateCapture,
    TemplateIngest,
)

__all__ = [
    "Payload",
    "ShipmentApplication",
    "DocumentPreview",
    "TemplateIngest",
    "OutputPath",
    "InputPath",
    "ExtractionHistory",
    "TemplateCapture",
]
