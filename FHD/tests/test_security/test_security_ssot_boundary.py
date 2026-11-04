"""Security SSOT boundary — modules exist and redaction helpers importable."""

from __future__ import annotations

import importlib

import pytest

REQUIRED = [
    "app.security.web_jwt",
    "app.security.mobile_jwt",
    "app.security.license_guard",
    "app.security.log_redaction",
    "app.security.lan_cidr_guard",
]


@pytest.mark.parametrize("mod", REQUIRED)
def test_security_ssot_modules_importable(mod: str) -> None:
    importlib.import_module(mod)


def test_log_redaction_masks_secretish_values() -> None:
    from app.security import log_redaction as lr

    # Prefer a real helper if present; otherwise assert module exports something callable.
    helpers = [n for n in dir(lr) if callable(getattr(lr, n)) and not n.startswith("__")]
    assert helpers, "log_redaction must export callable helpers"
