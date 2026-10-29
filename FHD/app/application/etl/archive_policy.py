"""Fail-closed policy validation for future original-file archives.

This module does not persist files or change retention of existing uploads.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


class ArchivePolicyError(ValueError):
    """The archive policy or requested admission is incomplete or invalid."""


@dataclass(frozen=True)
class ArchivePolicy:
    retention_days: int | None
    quota_bytes: int
    deletion_rule: str

    def __post_init__(self) -> None:
        if self.deletion_rule == "manual":
            if self.retention_days is not None:
                raise ArchivePolicyError("手动删除的归档不能设置自动到期时间")
        elif type(self.retention_days) is not int or not 1 <= self.retention_days <= 36500:
            raise ArchivePolicyError("必须配置有效的归档保留天数")
        if type(self.quota_bytes) is not int or self.quota_bytes < 1:
            raise ArchivePolicyError("必须配置有效的归档配额")
        if self.deletion_rule not in {"manual", "expire"}:
            raise ArchivePolicyError("必须明确选择到期删除或人工删除")

    def admission(self, *, size_bytes: int, used_bytes: int, now: datetime) -> datetime | None:
        """Return the recorded expiry after checking a single admission.

        Quota reservation and concurrency must be enforced atomically by the
        eventual repository; this check alone does not reserve storage.
        """
        if type(size_bytes) is not int or size_bytes <= 0 or type(used_bytes) is not int or used_bytes < 0:
            raise ArchivePolicyError("文件大小或已用配额无效")
        if used_bytes + size_bytes > self.quota_bytes:
            raise ArchivePolicyError("归档配额不足")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ArchivePolicyError("归档时间必须包含时区")
        return now + timedelta(days=self.retention_days) if self.retention_days is not None else None
