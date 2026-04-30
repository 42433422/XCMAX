from __future__ import annotations

import os
import json

from app.desktop_runtime.paths import configure_desktop_environment, ensure_desktop_dirs
from app.desktop_runtime.model_downloader import load_manifest


def test_configure_desktop_environment_sets_local_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)

    data_dir = configure_desktop_environment(tmp_path)

    assert data_dir == tmp_path.resolve()
    assert os.environ["XCAGI_DESKTOP_MODE"] == "1"
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")
    assert os.environ["CACHE_REDIS_URL"] == ""
    assert os.environ["CELERY_BROKER_URL"] == "memory://"


def test_ensure_desktop_dirs_creates_expected_layout(tmp_path):
    dirs = ensure_desktop_dirs(tmp_path)

    assert dirs["data"].is_dir()
    assert dirs["uploads"].is_dir()
    assert dirs["logs"].is_dir()
    assert dirs["mods"].is_dir()
    assert dirs["models"].is_dir()


def test_model_manifest_loads_assets(tmp_path):
    manifest = tmp_path / "models.json"
    manifest.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "name": "demo",
                        "version": "1.0.0",
                        "url": "https://models.example/demo.bin",
                        "sha256": "0" * 64,
                        "size": 12,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assets = load_manifest(manifest)

    assert assets[0].name == "demo"
    assert assets[0].version == "1.0.0"
