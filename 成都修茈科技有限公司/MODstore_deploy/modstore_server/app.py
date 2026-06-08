"""Application entry — delegates to :mod:`modstore_server.api.app_factory`."""

from __future__ import annotations

import httpx  # noqa: F401  # tests: ``@patch("modstore_server.app.httpx.Client")``

from modman.repo_config import load_config, save_config
from modman.store import project_root
from modstore_server.api.app_factory import create_app, load_default_config
from modstore_server.api.auth_deps import require_user as _require_user
from modstore_server.infrastructure import library_paths

app = create_app(load_default_config())


def _lib():
    """Legacy alias used by ``mod_sync_catalog_api`` and tests."""

    return library_paths.lib()


def _cfg():
    """Legacy alias used by ``mod_sync_catalog_api``."""

    return library_paths.cfg()
