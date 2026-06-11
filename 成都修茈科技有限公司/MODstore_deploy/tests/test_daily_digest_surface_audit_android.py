"""P-App adb 截图（日更 digest）单元测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.release_gate


def test_filter_sample_pages_prefers_preview() -> None:
    from modstore_server.daily_digest_surface_audit_android import _filter_sample_pages

    pages = [
        {"id": "splash", "screenshot_b64": "abc", "name": "启动"},
        {"id": "home_hub", "preview": True, "screenshot_b64": "def", "name": "首页"},
    ]
    out = _filter_sample_pages(pages)
    assert len(out) == 1
    assert out[0]["id"] == "home_hub"


def test_page_to_digest_row_writes_png(tmp_path) -> None:
    import base64

    from modstore_server.daily_digest_surface_audit_android import _page_to_digest_row

    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    row = _page_to_digest_row(
        {
            "id": "home_hub",
            "name": "首页",
            "android_route": "home_hub",
            "screenshot_b64": png,
            "native": True,
            "status": 200,
        },
        idx=0,
        save_root=tmp_path,
    )
    assert row["lane"] == "P-App"
    assert row["android_capture"] is True
    assert row["screenshot_saved"]
    assert (tmp_path / "000_P-App_首页.png").is_file()
