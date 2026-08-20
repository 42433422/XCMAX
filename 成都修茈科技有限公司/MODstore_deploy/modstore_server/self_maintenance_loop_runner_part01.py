"""Para TLS configuration extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _para_tls_verify():
    """Build a verified TLS context for Para; optionally trust an operator CA bundle."""
    ca_bundle = str(_facade().os.environ.get("MODSTORE_PARA_CA_BUNDLE") or "").strip()
    if ca_bundle:
        ca_path = _facade().Path(ca_bundle).expanduser()
        if not ca_path.is_file():
            raise FileNotFoundError(f"MODSTORE_PARA_CA_BUNDLE does not exist: {ca_path}")
        return _facade().ssl.create_default_context(cafile=str(ca_path))
    return _facade().ssl.create_default_context()
