"""_finalize_session_done must not clobber error-terminal sessions."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_finalize_skips_when_session_already_error():
    from modstore_server import workbench_api as wa

    sid = "pytest-finalize-guard-1"
    wa.WORKBENCH_SESSIONS[sid] = {
        "id": sid,
        "status": "error",
        "error": "mod_sandbox failed",
        "steps": [
            {"id": "mod_sandbox", "status": "error", "message": "gap"},
            {"id": "complete", "status": "pending", "message": None},
        ],
    }
    await wa._finalize_session_done(sid, {"artifact": "should_not_apply"})
    sess = wa.WORKBENCH_SESSIONS[sid]
    assert sess["status"] == "error"
    assert sess["steps"][1]["status"] == "pending"
    assert "artifact" not in sess or sess.get("artifact") != {"artifact": "should_not_apply"}
    del wa.WORKBENCH_SESSIONS[sid]
