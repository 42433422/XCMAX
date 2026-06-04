"""FHD/MODstore release gate placeholder (embedded copy; full suite in MODstore_deploy)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.release_gate


def test_modstore_package_importable() -> None:
    import modstore_server  # noqa: F401

    assert True
