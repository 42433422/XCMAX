"""Shared fixtures for tests/test_infrastructure/ — coverage ramp C3.3-b.

Provides:
* `mock_external_service` — context-manager that patches multiple external
  HTTP / Redis / LLM calls so the test sees a closed network.
* `disable_real_network` — monkeypatches ``httpx.AsyncClient.send`` to fail.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_external_service() -> Iterator[None]:
    """Disable outbound network calls across httpx, requests, urllib."""
    with (
        patch("httpx.AsyncClient.send", side_effect=ConnectionError("mocked")),
        patch("httpx.Client.send", side_effect=ConnectionError("mocked")),
        patch("urllib.request.urlopen", side_effect=ConnectionError("mocked")),
    ):
        yield


@pytest.fixture
def disable_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``httpx.AsyncClient.send`` to raise ``ConnectError``."""
    import httpx

    def _boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("disabled by test")

    monkeypatch.setattr(httpx.AsyncClient, "send", _boom)


@pytest.fixture(autouse=True)
def compat_db_writes_test_tenant_scope(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Legacy compat_db write unit tests run against a scoped mock tenant.

    Those tests mock table schemas narrowly to exercise SQL branch behavior. The
    production helper still fail-closes when real raw-SQL tables lack tenant_id;
    these branch tests get a deterministic test tenant instead of repeating the
    tenant column in every mocked column list.
    """
    compat_mock_files = {
        "test_compat_db_writes.py",
        "test_compat_db_writes_ext.py",
        "test_compat_db_writes_ext2.py",
        "test_compat_db_writes_cov.py",
        "test_coverage_ramp_phase3_p1_deep_backend.py",
        "test_coverage_ramp_phase6_p17_backend.py",
    }
    if request.node.fspath.basename not in compat_mock_files:
        yield
        return

    import app.infrastructure.persistence.compat_db.writes as writes

    def _append_scope(where_parts, bind, column_names, *, table_name):  # type: ignore[no-untyped-def]
        where_parts.append("tenant_id = :tenant_id")
        bind["tenant_id"] = 1

    def _require_scope(column_names, *, table_name):  # type: ignore[no-untyped-def]
        return 1

    monkeypatch.setattr(writes, "_append_tenant_scope_or_raise", _append_scope)
    monkeypatch.setattr(writes, "_require_tenant_id_or_raise", _require_scope)
    yield
