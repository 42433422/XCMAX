import copy
import json
from types import SimpleNamespace

import pytest

from modstore_server.customer_value_release import desktop_publications, published_installation
from tests.customer_value_release_fixture import published_catalog


def receipt(**changes):
    return SimpleNamespace(
        **{
            "installed_version": "1.0.0.1",
            "target_version": "1.0.0.1",
            "installed_build_sha": "a" * 40,
            "target_build_sha": "a" * 40,
            "platform": "darwin",
            "channel": "stable",
            "status": "installed",
            **changes,
        }
    )


def test_published_desktop_survives_independent_server_release(tmp_path, monkeypatch):
    published_catalog(tmp_path, monkeypatch)
    for server_sha in ("b" * 40, "c" * 40, ""):
        monkeypatch.setenv("XCMAX_RELEASE_SHA", server_sha)
        assert published_installation(receipt(), desktop_publications())


@pytest.mark.parametrize("state", ["candidate", "accepted", "withdrawn"])
def test_nonpublished_catalog_artifact_does_not_qualify(tmp_path, monkeypatch, state):
    catalog, path, artifact = published_catalog(tmp_path, monkeypatch)
    artifact["state"] = state
    if state == "withdrawn":
        artifact["evidence"]["withdrawal"] = "withdrawal.json"
    path.write_text(json.dumps(catalog))
    monkeypatch.setenv("XCMAX_RELEASE_SHA", "a" * 40)
    assert not published_installation(receipt(), desktop_publications())


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform", "windows"),
        ("channel", "staging"),
        ("installed_version", "1.0.0.2"),
        ("target_version", "1.0.0.2"),
        ("installed_build_sha", "b" * 40),
        ("target_build_sha", "b" * 40),
        ("status", "failed"),
        ("installed_build_sha", "a" * 40 + "extra"),
    ],
)
def test_receipt_must_match_exact_desktop_identity(tmp_path, monkeypatch, field, value):
    published_catalog(tmp_path, monkeypatch)
    assert not published_installation(receipt(**{field: value}), desktop_publications())


def test_candidate_architecture_cannot_borrow_published_peer(tmp_path, monkeypatch):
    catalog, path, artifact = published_catalog(tmp_path, monkeypatch)
    peer = copy.deepcopy(artifact)
    peer.update(arch="x64", state="candidate", artifact_sha256="c" * 64)
    catalog["release_history"][0]["deliveries"].append(peer)
    path.write_text(json.dumps(catalog))
    assert not published_installation(receipt(), desktop_publications())


@pytest.mark.parametrize("evidence", ["acceptance", "authorization", "publication"])
def test_missing_publication_evidence_stays_unknown(tmp_path, monkeypatch, evidence):
    catalog, path, artifact = published_catalog(tmp_path, monkeypatch)
    artifact["evidence"].pop(evidence)
    path.write_text(json.dumps(catalog))
    observed = desktop_publications()
    assert observed["available"] is False
    assert not published_installation(receipt(), observed)


def test_missing_catalog_never_uses_server_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DOWNLOAD_RELEASE_JSON", str(tmp_path / "missing.json"))
    monkeypatch.setenv("XCMAX_RELEASE_SHA", "a" * 40)
    observed = desktop_publications()
    assert observed["available"] is False
    assert not published_installation(receipt(), observed)
