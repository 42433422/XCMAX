"""Compat module path: debt19 renamed ports.py → protocols.py."""

from __future__ import annotations

from app.application.shipment_etl.protocols import (  # noqa: F401
    Payload,
    ShipmentApplication,
    DocumentPreview,
    TemplateIngest,
    OutputPath,
    InputPath,
    ExtractionHistory,
    TemplateCapture,
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
