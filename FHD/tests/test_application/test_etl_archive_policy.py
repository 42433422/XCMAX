from datetime import UTC, datetime, timedelta

import pytest

from app.application.etl.archive_policy import ArchivePolicy, ArchivePolicyError


@pytest.mark.parametrize(
    "days,quota,rule",
    [
        (0, 100, "manual"),
        (1, 100, "manual"),
        (None, 0, "manual"),
        (1, 100, ""),
        (True, 100, "expire"),
        (1, True, "expire"),
    ],
)
def test_archive_policy_requires_explicit_valid_choices(days, quota, rule):
    with pytest.raises(ArchivePolicyError):
        ArchivePolicy(days, quota, rule)


def test_archive_admission_checks_quota_and_records_expiry():
    policy = ArchivePolicy(30, 100, "expire")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert policy.admission(size_bytes=20, used_bytes=80, now=now) == now + timedelta(days=30)
    with pytest.raises(ArchivePolicyError, match="配额"):
        policy.admission(size_bytes=21, used_bytes=80, now=now)
    with pytest.raises(ArchivePolicyError, match="时区"):
        policy.admission(size_bytes=1, used_bytes=0, now=now.replace(tzinfo=None))


def test_manual_retention_never_expires_automatically():
    policy = ArchivePolicy(None, 100, "manual")
    assert (
        policy.admission(size_bytes=1, used_bytes=0, now=datetime(2026, 1, 1, tzinfo=UTC)) is None
    )
