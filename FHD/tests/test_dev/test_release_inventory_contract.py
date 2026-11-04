from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/dev"))
from product_lines_status import _capability_builder, release_inventory_errors


def catalog():
    return json.loads((ROOT / "config/download_release.json").read_text())


def delivery():
    return {
        "product": "xcagi",
        "sku": "enterprise",
        "platform": "macos",
        "arch": "arm64",
        "channel": "stable-ota",
        "source_sha": "a" * 40,
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


def test_preserved_history_and_projection_are_one_catalog():
    data = catalog()
    assert not release_inventory_errors(data)
    versions = [row["version"] for row in data["release_history"]]
    assert len(versions) == len(set(versions))
    assert "1.0.0.4" in versions and "1.0.0.6" in versions
    fourth = next(row for row in data["release_history"] if row["version"] == "1.0.0.4")
    assert fourth["publication_state"] == "unknown"
    assert fourth["provenance"]["path"] == "FHD/CHANGELOG.md"
    source = json.loads(
        (ROOT.parent / "成都修茈科技有限公司/data/release-history.json").read_text()
    )
    builder = _capability_builder()
    assert source["release_history"] == builder.public_projection(data["release_history"], set())
    assert [row["version"] for row in source["release_history"]] == versions
    assert "太阳鸟" in json.dumps(data["release_history"], ensure_ascii=False)
    assert not any(
        marker in json.dumps(source, ensure_ascii=False).casefold()
        for marker in builder._PUBLIC_PRIVATE_MARKERS
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.pop("artifact_sha256"),
        lambda row: row.update(source_sha="short"),
        lambda row: row.update(state="ready"),
        lambda row: row["evidence"].pop("acceptance"),
        lambda row: row["evidence"].pop("authorization"),
        lambda row: row["evidence"].pop("publication"),
        lambda row: row.update(signature="unsigned"),
        lambda row: row.update(notarization="unknown"),
        lambda row: row.update(state="withdrawn"),
    ],
)
def test_artifact_publication_fails_closed_without_identity_and_evidence(mutation):
    data, record = catalog(), delivery()
    data["release_history"][0]["deliveries"] = [record]
    assert not release_inventory_errors(data)
    mutation(record)
    assert release_inventory_errors(data)


def test_aliases_and_duplicate_artifacts_do_not_create_extra_generations():
    data = catalog()
    data["release_history"][0]["aliases"] = [data["release_history"][1]["version"]]
    assert release_inventory_errors(data)
    data = catalog()
    data["release_history"][0]["deliveries"] = [delivery(), copy.deepcopy(delivery())]
    assert release_inventory_errors(data)
