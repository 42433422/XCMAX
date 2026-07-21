"""管理端 IM notify client（fail-open）。"""

from __future__ import annotations

import scripts.ci._im_notify_client as im


def test_notify_skips_without_env(monkeypatch):
    monkeypatch.delenv("XCAGI_FHD_INTERNAL_URL", raising=False)
    monkeypatch.delenv("FHD_API_BASE_URL", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_CS_INTAKE_LINK_SECRET", raising=False)
    assert im.notify_boss_im("hello") is False


def test_notify_posts_when_configured(monkeypatch):
    monkeypatch.setenv("XCAGI_FHD_INTERNAL_URL", "http://example.test")
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "k")
    monkeypatch.setenv("XCAGI_AUTONOMY_IM_BOSS_USER_ID", "9")

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            assert url.endswith("/api/internal/im/employee-message")
            assert headers["X-Internal-Api-Key"] == "k"
            assert json["boss_user_id"] == 9
            assert "hello" in json["body"]
            return _Resp()

    monkeypatch.setattr(im, "httpx", type("H", (), {"Client": _Client}))
    assert im.notify_boss_im("hello world", source="test") is True
