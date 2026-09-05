import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from modstore_server import customer_issue_release_provenance as provenance


@pytest.fixture
def feed(monkeypatch, tmp_path):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        provenance,
        "UPDATE_PUBLIC_KEY",
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode(),
    )
    sha = "a" * 40
    body = json.dumps(
        {
            "buildSha": sha,
            "releaseId": "standard-" + sha,
            "productVersion": "1.0.0.1",
            "files": [
                {
                    "url": "standard.zip",
                    "size": 100,
                    "sha512": base64.b64encode(b"x" * 64).decode(),
                }
            ],
        }
    )
    text = body + "\nsignature: ed25519:" + base64.b64encode(key.sign(body.encode())).decode()
    provenance._CACHE.clear()
    monkeypatch.setattr(provenance, "_archive_path", lambda sha: tmp_path / (sha + ".yml"))
    monkeypatch.setattr(provenance, "_fetch_text", lambda url: text)
    return sha, text


def test_signed_release_requires_actual_main_ancestry(feed, monkeypatch):
    sha, _ = feed
    monkeypatch.setattr(
        provenance,
        "_fetch_json",
        lambda url: {
            "status": "behind",
            "merge_base_commit": {"sha": sha},
            "html_url": "https://github.com/verified",
        },
    )
    result = provenance.resolve_host_release(sha)
    assert result["git_sha"] == sha
    assert result["source_ref"] == "main"
    assert result["artifacts"][0]["sha512"]
    assert result["signed_metadata_sha256"]


def test_signed_customer_branch_is_not_a_main_release(feed, monkeypatch):
    sha, _ = feed
    monkeypatch.setattr(
        provenance,
        "_fetch_json",
        lambda url: {
            "status": "diverged",
            "merge_base_commit": {"sha": "b" * 40},
        },
    )
    assert provenance.resolve_host_release(sha) is None


def test_modified_feed_or_unknown_host_cannot_claim_provenance(feed, monkeypatch):
    sha, text = feed
    monkeypatch.setattr(
        provenance,
        "_fetch_text",
        lambda url: text.replace("standard.zip", "custom.zip"),
    )
    assert provenance.resolve_host_release(sha) is None
    assert provenance.resolve_host_release("../main") is None


def test_main_membership_alone_does_not_prove_a_published_host(feed, monkeypatch):
    _, text = feed
    monkeypatch.setattr(provenance, "_fetch_text", lambda url: text)
    assert provenance.resolve_host_release("b" * 40) is None


def test_signed_history_survives_feed_advance_but_never_trusts_modified_archive(feed, monkeypatch):
    sha, _ = feed
    monkeypatch.setattr(
        provenance,
        "_fetch_json",
        lambda _: {"status": "behind", "merge_base_commit": {"sha": sha}},
    )
    assert provenance.resolve_host_release(sha) is not None
    provenance._CACHE.clear()
    monkeypatch.setattr(provenance, "_fetch_text", lambda _: "newer release")
    assert provenance.resolve_host_release(sha) is not None
    provenance._CACHE.clear()
    path = provenance._archive_path(sha)
    path.write_text(path.read_text().replace("standard.zip", "modified.zip"))
    assert provenance.resolve_host_release(sha) is None
