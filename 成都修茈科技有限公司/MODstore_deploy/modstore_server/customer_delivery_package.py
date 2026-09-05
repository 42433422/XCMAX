"""Reuse the host's package trust implementation for customer delivery artifacts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast
from zipfile import BadZipFile


def verify_delivery_package(raw: bytes) -> dict[str, Any]:
    try:
        from app.infrastructure.mods.package_signing import verify_signed_package_bytes
    except ImportError:
        # The deployed monorepo contains the same host SDK used by the signing job.
        # Resolve only relative to trusted server source, never a customer path.
        fhd = Path(__file__).resolve().parents[3] / "FHD"
        if not (fhd / "app/infrastructure/mods/package_signing.py").is_file():
            raise RuntimeError("宿主签名校验组件不可用，不能交付未经验证的产物") from None
        if str(fhd) not in sys.path:
            sys.path.append(str(fhd))
        from app.infrastructure.mods.package_signing import verify_signed_package_bytes
    from app.infrastructure.mods.package import ModSignatureError

    try:
        return cast(dict[str, Any], verify_signed_package_bytes(raw))
    except (ModSignatureError, BadZipFile) as exc:
        raise ValueError(str(exc)) from exc
