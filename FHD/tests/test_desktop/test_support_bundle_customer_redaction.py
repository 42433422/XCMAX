"""Customer logs are redacted before they are stored in a support bundle."""

from __future__ import annotations

import io
import zipfile

from app.desktop_runtime import support_bundle


def test_customer_logs_in_zip_do_not_contain_secrets(tmp_path, monkeypatch):
    dirs = {
        "root": tmp_path,
        "data": tmp_path / "data",
        "mods": tmp_path / "mods",
        "models": tmp_path / "models",
        "backups": tmp_path / "backups",
        "logs": tmp_path / "logs",
    }
    dirs["logs"].mkdir()
    dirs["backups"].mkdir()
    monkeypatch.setattr(support_bundle, "is_desktop_mode", lambda: True)
    monkeypatch.setattr(support_bundle, "ensure_desktop_dirs", lambda *_args, **_kwargs: dirs)
    monkeypatch.setattr(support_bundle, "export_config", lambda *_args, **_kwargs: {})
    secret_log = "\n".join(
        [
            "api_key=sk-live-customer-secret",
            "Authorization: Bearer customer-bearer-token",
            "password=customer-password-secret",
            "postgresql://demo:customer-db-password@db.internal:5432/app",
            "aws_key=AKIAIOSFODNN7EXAMPLE",
            '{"client_secret":"customer-json-secret","access_token":"customer-access-token"}',
        ]
    ).encode()

    blob = support_bundle.build_support_bundle_zip(
        customer_logs=[("client.log", secret_log)]
    )
    archive = zipfile.ZipFile(io.BytesIO(blob))
    packed = "\n".join(
        archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()
    )
    for secret in (
        "sk-live-customer-secret",
        "customer-bearer-token",
        "customer-password-secret",
        "customer-db-password",
        "AKIAIOSFODNN7EXAMPLE",
        "customer-json-secret",
        "customer-access-token",
    ):
        assert secret not in packed
    readme = archive.read("README.txt").decode()
    assert "customer-logs/client.log" in archive.namelist()
    assert "已脱敏" in readme
    assert "postgresql://" not in packed
