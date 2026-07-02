"""Desktop installer packaging policy checks."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_desktop_enterprise_installer_builds_full_frontend() -> None:
    scripts = REPO_ROOT / "scripts" / "package"
    ps_backend = (scripts / "build-backend.ps1").read_text(encoding="utf-8")
    ps_sync = (scripts / "sync-desktop-frontend.ps1").read_text(encoding="utf-8")
    sh_backend = (scripts / "build-backend.sh").read_text(encoding="utf-8")
    sh_windows = (scripts / "build-windows-installer.sh").read_text(encoding="utf-8")
    sh_thin = (scripts / "build-windows-electron-only.sh").read_text(encoding="utf-8")

    assert "personal = 'minimal'" in ps_backend
    assert "enterprise = 'full'" in ps_backend
    assert "personal   = 'minimal'" in ps_sync
    assert "enterprise = 'full'" in ps_sync

    for script in (sh_backend, sh_windows, sh_thin):
        assert (
            "VITE_XCAGI_PRODUCT_SKU=enterprise VITE_XCAGI_EDITION=full "
            "npm run build:full"
        ) in script
        assert "VITE_XCAGI_PRODUCT_SKU=enterprise npm run build" not in script
