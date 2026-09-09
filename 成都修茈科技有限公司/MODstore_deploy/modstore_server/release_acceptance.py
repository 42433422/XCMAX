"""发布验收判定：按版本聚合安装回执 → 双平台验收结论（fail-closed）。

规则（macOS 与 Windows 平级，任一端未通过真实运行验证都不能验收）：
- accepted：win 与 mac 两个平台都至少有一台设备最新状态为 installed，
  且该版本没有任何设备的最新状态停留在 failed / rolled_back / revoked
- rejected：任一设备最新状态为 failed / rolled_back / revoked
  （客户机安装或运行失败 → 回写重开原工单，不另起新单）
- pending：其余（双平台回执未齐 / 无任何回执）

「最新状态」按 installation_id 分组取 reported_at 最新一条。
判定是纯计算，不落库：回写幂等由 GitHub issue 侧的标签/状态保证。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Protocol

VERDICT_ACCEPTED = "accepted"
VERDICT_REJECTED = "rejected"
VERDICT_PENDING = "pending"

REQUIRED_PLATFORMS: tuple[str, ...] = ("win", "mac")
_FAILURE_STATUSES = frozenset({"failed", "rolled_back", "revoked"})

_PLATFORM_ALIASES = {
    "win32": "win",
    "windows": "win",
    "win": "win",
    "darwin": "mac",
    "macos": "mac",
    "mac": "mac",
    "osx": "mac",
}


class _ReceiptLike(Protocol):
    installation_id: str
    platform: str
    status: str
    error: str
    reported_at: datetime | None


def normalize_platform(raw: str) -> str:
    """Electron process.platform 等取值归一到 win/mac。"""
    return _PLATFORM_ALIASES.get(str(raw or "").strip().lower(), str(raw or "").strip().lower())


def _latest_by_installation(receipts: Iterable[_ReceiptLike]) -> dict[str, _ReceiptLike]:
    latest: dict[str, _ReceiptLike] = {}
    for row in receipts:
        key = str(row.installation_id or "").strip()
        if not key:
            continue
        current = latest.get(key)
        if current is None or (row.reported_at or datetime.min) >= (
            current.reported_at or datetime.min
        ):
            latest[key] = row
    return latest


def judge_release_acceptance(
    receipts: Iterable[_ReceiptLike],
    *,
    version: str,
    required_platforms: tuple[str, ...] = REQUIRED_PLATFORMS,
) -> dict[str, Any]:
    """聚合某版本全部回执并给出验收判定与证据摘要。"""
    latest = _latest_by_installation(receipts)

    per_platform: dict[str, dict[str, int]] = {}
    failures: list[dict[str, str]] = []
    for installation_id, row in latest.items():
        platform = normalize_platform(row.platform) or "unknown"
        status = str(row.status or "").strip()
        bucket = per_platform.setdefault(platform, {"devices": 0, "installed": 0, "failed": 0})
        bucket["devices"] += 1
        if status == "installed":
            bucket["installed"] += 1
        if status in _FAILURE_STATUSES:
            bucket["failed"] += 1
            failures.append(
                {
                    "installation_id": installation_id,
                    "platform": platform,
                    "status": status,
                    "error": str(row.error or "")[:300],
                }
            )

    if failures:
        verdict = VERDICT_REJECTED
    elif all(per_platform.get(p, {}).get("installed", 0) >= 1 for p in required_platforms):
        verdict = VERDICT_ACCEPTED
    else:
        verdict = VERDICT_PENDING

    missing = [p for p in required_platforms if per_platform.get(p, {}).get("installed", 0) < 1]
    return {
        "version": str(version or ""),
        "verdict": verdict,
        "reported_devices": len(latest),
        "per_platform": per_platform,
        "missing_platforms": missing,
        "failures": failures,
        "required_platforms": list(required_platforms),
    }


__all__ = [
    "REQUIRED_PLATFORMS",
    "VERDICT_ACCEPTED",
    "VERDICT_PENDING",
    "VERDICT_REJECTED",
    "judge_release_acceptance",
    "normalize_platform",
]
