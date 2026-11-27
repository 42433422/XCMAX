"""Authenticated uploaded-file fixture shared by native workbook and Word scenarios."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.db.models.elt import EltUpload
from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
from app.infrastructure.auth.agent_principal import require_agent_principal
from app.infrastructure.tenant_scope import tenant_scope
from evals.run_agent_eval import _authenticated_route_fixture
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def owned(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    client = SimpleNamespace(headers={})
    with _authenticated_route_fixture(client, role_name="admin"):
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        context = authenticated_runtime_context(
            {"attachment_upload_ids": ["owned-file"]}, principal
        )
        root = tmp_path / "elt" / "uploads" / principal.tenant_id / principal.user_id
        root.mkdir(parents=True)
        file = root / "owned-file.csv"
        raw = b"product,price\npaint,120\n"
        file.write_bytes(raw)
        from app.db.session import get_db

        with tenant_scope(int(principal.tenant_id)), get_db() as db:
            db.add(
                EltUpload(
                    id="owned-file",
                    tenant_id=int(principal.tenant_id),
                    owner_user_id=int(principal.user_id),
                    file_name="price.csv",
                    suffix=".csv",
                    storage_path=str(file),
                    size_bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        yield context, file
