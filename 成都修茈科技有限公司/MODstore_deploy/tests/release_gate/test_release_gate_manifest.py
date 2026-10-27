"""MODstore release gate manifest (``pytest -m release_gate``)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.release_gate


def test_post_deploy_smoke_job_exports_scheduler_hooks(monkeypatch) -> None:
    from modstore_server.post_deploy_smoke_job import (
        cron_smoke_enabled,
        run_post_deploy_smoke_job,
    )

    monkeypatch.delenv("MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED", raising=False)
    assert cron_smoke_enabled() is False
    assert callable(run_post_deploy_smoke_job)
