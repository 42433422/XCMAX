from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_app import static_mounts


def test_admin_console_static_serves_history_fallback(monkeypatch, tmp_path: Path) -> None:
    dist = tmp_path / "templates" / "admin-vue-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><title>XCMAX 服务器后台</title><div id="app"></div>',
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('admin')", encoding="utf-8")
    monkeypatch.setattr(static_mounts, "get_base_dir", lambda: str(tmp_path))

    app = FastAPI()
    static_mounts.mount_admin_console_static(app)
    client = TestClient(app)

    login = client.get("/admin/login")
    asset = client.get("/admin/assets/app.js")

    assert login.status_code == 200
    assert "XCMAX 服务器后台" in login.text
    assert asset.status_code == 200
    assert "console.log('admin')" in asset.text
