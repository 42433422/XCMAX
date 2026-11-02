"""Only the installed record, never process authorization or normal startup, satisfies the probe."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.application import elt_login_authorization as authorization
from XCAGI import run_fastapi


@pytest.fixture
def record(monkeypatch, tmp_path):
    path = tmp_path / "config" / "elt_notice_publication.json"
    path.parent.mkdir()
    payload = {
        "notice_version": authorization.NOTICE_VERSION,
        "recipient_disclosure_version": authorization.RECIPIENT_DISCLOSURE_VERSION,
        "published_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(authorization, "_NOTICE_PUBLICATION_FILE", path)
    monkeypatch.delenv(authorization.NOTICE_PUBLICATION_ENV, raising=False)

    def forbid_startup(*_args):
        raise AssertionError("notice probe entered normal app/session startup")

    for name in (
        "_load_dotenv_if_present",
        "_apply_desktop_bootstrap",
        "_apply_no_console_child_defaults",
        "_bootstrap_stage",
    ):
        monkeypatch.setattr(run_fastapi, name, forbid_startup)
    monkeypatch.setattr(authorization, "_active_session", forbid_startup)
    return path, payload


def probe(path, expected=None):
    digest = expected if expected is not None else hashlib.sha256(path.read_bytes()).hexdigest()
    run_fastapi.main(["--verify-notice-publication-sha256", digest])
    return digest


def test_probe_reads_real_loader_and_exits_before_startup(record, monkeypatch, capsys):
    path, _ = record
    original = path.read_bytes()
    database = "postgresql://synthetic.invalid/never-used"
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    calls = []
    loader = authorization.notice_publication
    publication = loader()
    assert publication is not None

    def real_loader():
        calls.append(True)
        return loader()

    monkeypatch.setattr(authorization, "notice_publication", real_loader)
    digest = probe(path)
    assert calls == [True]
    assert capsys.readouterr().out.strip() == (
        f"[notice-publication-probe] OK sha256={digest} "
        f"runtime_record_sha256={publication['record_sha256']}"
    )
    assert path.read_bytes() == original and os.environ["DATABASE_URL"] == database


@pytest.mark.parametrize("override", ["", "{}"])
def test_probe_rejects_even_empty_environment_override(record, monkeypatch, override):
    path, _ = record
    monkeypatch.setenv(authorization.NOTICE_PUBLICATION_ENV, override)
    with pytest.raises(SystemExit) as error:
        probe(path)
    assert error.value.code == 1


@pytest.mark.parametrize("digest", ["", "a" * 63, "g" * 64, "0" * 64])
def test_invalid_or_mismatched_digest_exits_nonzero_without_normal_startup(record, digest, capsys):
    path, _ = record
    with pytest.raises(SystemExit) as error:
        probe(path, digest)
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "OK" not in captured.out and "[notice-publication-probe] failed:" in captured.err


@pytest.mark.parametrize("failure", ["missing", "json", "version", "extra", "future"])
def test_invalid_bundled_record_with_matching_hash_still_fails(record, failure):
    path, payload = record
    if failure == "missing":
        path.unlink()
    elif failure == "json":
        path.write_text("not-json", encoding="utf-8")
    else:
        if failure == "version":
            payload["notice_version"] = "old"
        elif failure == "extra":
            payload["enabled"] = True
        else:
            payload["published_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "0" * 64
    with pytest.raises(SystemExit) as error:
        probe(path, digest)
    assert error.value.code == 1


def test_changed_record_during_loader_read_fails(record, monkeypatch):
    path, _ = record
    loader = authorization.notice_publication

    def changed_loader():
        result = loader()
        path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(authorization, "notice_publication", changed_loader)
    with pytest.raises(SystemExit) as error:
        probe(path)
    assert error.value.code == 1


def test_probe_rejects_symlinked_record(record, monkeypatch):
    path, _ = record
    link = path.with_name("linked-record.json")
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink privilege is unavailable on this Windows executor")
    monkeypatch.setattr(authorization, "_NOTICE_PUBLICATION_FILE", link)
    with pytest.raises(SystemExit) as error:
        probe(path)
    assert error.value.code == 1
