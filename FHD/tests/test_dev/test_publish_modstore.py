from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from urllib.error import HTTPError

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "publish_modstore.py"
SPEC = importlib.util.spec_from_file_location("publish_modstore", SCRIPT)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def _package(path: Path) -> str:
    manifest = {
        "id": "receipt-verifier",
        "name": "Receipt Verifier",
        "version": "1.2.3",
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {"routes": "routes"},
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("backend/blueprints.py", "# route\n")
        archive.writestr("frontend/routes.js", "export default []\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Response:
    def __init__(self, value: dict | bytes, status: int = 200):
        self.status = status
        self._raw = value if isinstance(value, bytes) else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._raw


def test_publish_verifies_review_listing_and_download(tmp_path: Path) -> None:
    package = tmp_path / "receipt-verifier-1.2.3.xcmod"
    digest = _package(package)
    calls: list[tuple[str, str]] = []

    def opener(request, timeout=0):
        del timeout
        url = request.full_url
        calls.append((request.get_method(), url))
        if request.get_method() == "POST":
            assert request.headers["Authorization"] == "Bearer test-token"
            return _Response(
                {
                    "ok": True,
                    "idempotent": False,
                    "semantic_indexed": False,
                    "package": {"id": "receipt-verifier", "version": "1.2.3", "sha256": digest},
                    "review": {"summary": {"pass": True, "average": 96}},
                }
            )
        if url.endswith("/v1/packages/receipt-verifier/1.2.3"):
            return _Response({"id": "receipt-verifier", "version": "1.2.3", "sha256": digest})
        if "/api/market/catalog?" in url:
            return _Response(
                {
                    "items": [
                        {
                            "id": 42,
                            "pkg_id": "receipt-verifier",
                            "version": "1.2.3",
                            "compliance_status": "approved",
                        }
                    ],
                    "total": 1,
                }
            )
        if url.endswith("/v1/packages/receipt-verifier/1.2.3/download"):
            return _Response(package.read_bytes())
        raise AssertionError(url)

    receipt = publisher.publish_package(
        package,
        base_url="https://store.example",
        token="test-token",
        source_repository="owner/repo",
        source_sha="a" * 40,
        workflow_run_id="12345",
        opener=opener,
    )

    assert receipt["status"] == "published"
    assert receipt["sha256"] == digest
    assert receipt["semantic_indexed"] is False
    assert receipt["catalog_item_id"] == 42
    assert [method for method, _ in calls] == ["POST", "GET", "GET", "GET"]


def test_publish_fails_closed_when_public_listing_is_missing(tmp_path: Path) -> None:
    package = tmp_path / "receipt-verifier-1.2.3.xcmod"
    digest = _package(package)

    def opener(request, timeout=0):
        del timeout
        if request.get_method() == "POST":
            return _Response(
                {
                    "ok": True,
                    "package": {"sha256": digest},
                    "review": {"summary": {"pass": True}},
                }
            )
        if "/api/market/catalog?" in request.full_url:
            return _Response({"items": [], "total": 0})
        return _Response({"sha256": digest})

    with pytest.raises(publisher.PublishError, match="not uniquely visible"):
        publisher.publish_package(
            package,
            base_url="https://store.example",
            token="test-token",
            source_repository="owner/repo",
            source_sha="b" * 40,
            workflow_run_id="9",
            opener=opener,
        )


def test_http_error_does_not_echo_token(tmp_path: Path) -> None:
    package = tmp_path / "receipt-verifier-1.2.3.xcmod"
    _package(package)

    def opener(request, timeout=0):
        del request, timeout
        raise HTTPError("https://store.example/v1/packages", 403, "denied", {}, io.BytesIO(b"no"))

    with pytest.raises(publisher.PublishError) as exc:
        publisher.publish_package(
            package,
            base_url="https://store.example",
            token="super-secret-token",
            source_repository="owner/repo",
            source_sha="c" * 40,
            workflow_run_id="10",
            opener=opener,
        )
    assert "super-secret-token" not in str(exc.value)


def test_duty_roster_parser_finds_nested_ids(tmp_path: Path) -> None:
    roster = tmp_path / "duty.json"
    roster.write_text(
        json.dumps({"areas": {"ops": {"ids": ["internal-one"]}}, "ids": ["top-level"]}),
        encoding="utf-8",
    )
    assert publisher._duty_employee_ids(roster) == {"internal-one", "top-level"}
