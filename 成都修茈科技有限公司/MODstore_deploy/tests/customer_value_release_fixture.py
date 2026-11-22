"""An explicit published desktop identity; never infer publication from server SHA."""

import json
from pathlib import Path


def published_catalog(tmp_path, monkeypatch, sha="a" * 40):
    source = Path(__file__).resolve().parents[3] / "FHD/config/download_release.json"
    catalog = json.loads(source.read_text())
    artifact = {
        "product": "xcagi",
        "sku": "enterprise",
        "platform": "macos",
        "arch": "arm64",
        "channel": "stable-ota",
        "source_sha": sha,
        "build_run_id": "123",
        "artifact_sha256": "b" * 64,
        "state": "published",
        "signature": "signed",
        "notarization": "accepted",
        "evidence": {
            "acceptance": "acceptance.json",
            "authorization": "approval.json",
            "publication": "readback.json",
        },
    }
    catalog["release_history"] = [
        {
            "version": "1.0.0.1",
            "kind": "release",
            "publication_state": "published",
            "deliveries": [artifact],
        }
    ]
    path = tmp_path / "download-release.json"
    path.write_text(json.dumps(catalog))
    monkeypatch.setenv("MODSTORE_DOWNLOAD_RELEASE_JSON", str(path))
    return catalog, path, artifact
