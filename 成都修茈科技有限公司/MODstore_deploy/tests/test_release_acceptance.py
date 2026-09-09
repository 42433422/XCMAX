"""release_acceptance 双平台验收判定测试。

覆盖：
- 平台名归一（win32/darwin → win/mac）
- accepted：双平台各有 installed 且无失败
- rejected：任一设备最新状态 failed / rolled_back / revoked
- pending：平台回执不齐 / 无回执
- 同一 installation_id 取最新状态（失败后重装成功 → 不计失败）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from modstore_server.release_acceptance import (
    judge_release_acceptance,
    normalize_platform,
)


@dataclass
class _Receipt:
    installation_id: str
    platform: str
    status: str
    error: str = ""
    reported_at: datetime | None = None


def _receipt(
    installation: str,
    platform: str,
    status: str,
    *,
    minutes_ago: int = 5,
    error: str = "",
) -> _Receipt:
    return _Receipt(
        installation_id=installation,
        platform=platform,
        status=status,
        error=error,
        reported_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


class TestNormalizePlatform:
    def test_aliases(self) -> None:
        assert normalize_platform("win32") == "win"
        assert normalize_platform("darwin") == "mac"
        assert normalize_platform("Windows") == "win"
        assert normalize_platform("macOS") == "mac"

    def test_unknown_passthrough(self) -> None:
        assert normalize_platform("linux") == "linux"
        assert normalize_platform("") == ""


class TestJudge:
    def test_no_receipts_pending(self) -> None:
        result = judge_release_acceptance([], version="1.0.0.2")
        assert result["verdict"] == "pending"
        assert result["reported_devices"] == 0

    def test_dual_platform_installed_accepted(self) -> None:
        rows = [
            _receipt("dev-win", "win32", "installed"),
            _receipt("dev-mac", "darwin", "installed"),
        ]
        result = judge_release_acceptance(rows, version="1.0.0.2")
        assert result["verdict"] == "accepted"
        assert result["per_platform"]["win"]["installed"] == 1
        assert result["per_platform"]["mac"]["installed"] == 1
        assert result["missing_platforms"] == []

    def test_single_platform_pending(self) -> None:
        """只有 Windows 回执健康、macOS 未回传 → 不平级不验收。"""
        rows = [_receipt("dev-win", "win32", "installed")]
        result = judge_release_acceptance(rows, version="1.0.0.2")
        assert result["verdict"] == "pending"
        assert result["missing_platforms"] == ["mac"]

    def test_any_failure_rejected(self) -> None:
        rows = [
            _receipt("dev-win", "win32", "installed"),
            _receipt("dev-mac", "darwin", "installed"),
            _receipt("dev-mac2", "darwin", "failed", error="launch crash"),
        ]
        result = judge_release_acceptance(rows, version="1.0.0.2")
        assert result["verdict"] == "rejected"
        assert result["failures"][0]["error"] == "launch crash"

    def test_rolled_back_rejected(self) -> None:
        rows = [
            _receipt("dev-win", "win32", "installed"),
            _receipt("dev-mac", "darwin", "installed"),
            _receipt("dev-win2", "win32", "rolled_back"),
        ]
        assert judge_release_acceptance(rows, version="1.0.0.2")["verdict"] == "rejected"

    def test_latest_status_wins(self) -> None:
        """同一设备先失败后安装成功：最新状态 installed → 不再计失败。"""
        rows = [
            _receipt("dev-win", "win32", "installed"),
            _receipt("dev-mac", "darwin", "installed"),
            _receipt("dev-mac", "darwin", "failed", minutes_ago=30, error="old crash"),
        ]
        result = judge_release_acceptance(rows, version="1.0.0.2")
        assert result["verdict"] == "accepted"
        assert result["failures"] == []

    def test_reinstall_failure_after_success_rejected(self) -> None:
        """同一设备先成功后失败（更新回滚）：最新状态 failed → rejected。"""
        rows = [
            _receipt("dev-win", "win32", "installed"),
            _receipt("dev-mac", "darwin", "installed"),
            _receipt("dev-win", "win32", "failed", minutes_ago=1, error="post-update crash"),
        ]
        result = judge_release_acceptance(rows, version="1.0.0.2")
        assert result["verdict"] == "rejected"


class TestAcceptanceEndpoint:
    def test_acceptance_endpoint_requires_admin_and_judges(self, client) -> None:
        from modstore_server.models import get_session_factory
        from modstore_server.update_installation_api import (
            UpdateInstallationReceiptBody,
            get_release_acceptance,
            record_update_installation_receipt,
        )

        sf = get_session_factory()
        with sf() as db:
            from modstore_server.models import User

            suffix = uuid.uuid4().hex[:12]
            admin = User(
                username=f"accept_admin_{suffix}",
                email=f"accept_admin_{suffix}@pytest.local",
                password_hash="x",
                is_admin=True,
            )
            plain = User(
                username=f"accept_user_{suffix}",
                email=f"accept_user_{suffix}@pytest.local",
                password_hash="x",
                is_admin=False,
            )
            db.add_all([admin, plain])
            db.commit()
            db.refresh(admin)
            db.refresh(plain)

            version = f"9.9.{uuid.uuid4().int % 9000 + 1000}"
            for platform in ("win32", "darwin"):
                body = UpdateInstallationReceiptBody(
                    installation_id=str(uuid.uuid4()),
                    idempotency_key=f"accept-{uuid.uuid4().hex}",
                    platform=platform,
                    target_version=version,
                    installed_version=version,
                    installed_build_sha="b" * 40,
                    status="installed",
                    reported_at=datetime.now(UTC) - timedelta(minutes=1),
                )
                record_update_installation_receipt(body, db, plain)

            verdict = get_release_acceptance(version=version, channel="stable", db=db, user=admin)
            assert verdict["verdict"] == "accepted"
            assert verdict["version"] == version

            import pytest
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as excinfo:
                get_release_acceptance(version=version, channel="stable", db=db, user=plain)
            assert excinfo.value.status_code == 403
