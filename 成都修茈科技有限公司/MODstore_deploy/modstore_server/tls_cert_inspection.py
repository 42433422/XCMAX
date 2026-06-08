"""TLS 证书到期评估（运维 cert-expiry-check + 每日摘要巡检）。

使用宿主 ``openssl`` 读取 PEM 证书 ``notAfter``，计算剩余天数并按阈值分级。

环境变量（可选，整数天数）：
- ``CERT_EXPIRY_INFO_DAYS``（默认 60）：≤ 此值为 INFO（邮件展示；默认不入 incident）
- ``CERT_EXPIRY_WARN_DAYS``（默认 30）：≤ 此值为 WARNING（触发 ``security.alert``）
- ``CERT_EXPIRY_CRIT_DAYS``（默认 14）：≤ 此值为 CRITICAL（触发 ``security.alert``）

主机待扫描路径：
- ``MODSTORE_TLS_CERT_PATHS``：逗号或分号分隔的绝对路径或相对仓库根的路径。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Sequence

CertLevel = Literal["OK", "INFO", "WARNING", "CRITICAL"]


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def thresholds() -> tuple[int, int, int]:
    """返回 (info_days, warn_days, crit_days)，均已裁剪为非负且 crit <= warn <= info。"""
    info_d = max(0, _env_int("CERT_EXPIRY_INFO_DAYS", 60))
    warn_d = max(0, _env_int("CERT_EXPIRY_WARN_DAYS", 30))
    crit_d = max(0, _env_int("CERT_EXPIRY_CRIT_DAYS", 14))
    # 保证单调：crit 最紧，info 最宽
    crit_d = min(crit_d, warn_d, info_d)
    warn_d = min(warn_d, info_d)
    return info_d, warn_d, crit_d


def parse_openssl_not_after(line: str) -> datetime:
    """解析 ``openssl x509 -enddate`` 单行输出，返回 UTC aware datetime。"""
    s = (line or "").strip()
    prefix = "notAfter="
    if s.startswith(prefix):
        s = s[len(prefix) :].strip()
    # 例：May  8 12:00:00 2027 GMT（月份与日之间可能有多空格）
    parts = s.split()
    if len(parts) < 5:
        raise ValueError(f"unrecognized notAfter: {line!r}")
    mon, day, hms, year, tz = parts[0], parts[1], parts[2], parts[3], parts[4]
    fixed = f"{mon} {int(day, 10)} {hms} {year} {tz}"
    return datetime.strptime(fixed, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)


def openssl_cert_not_after(cert_path: Path) -> datetime:
    proc = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"openssl failed ({proc.returncode}): {out[:500]}")
    return parse_openssl_not_after(out)


def classify_days_remaining(days: int, *, info_d: int, warn_d: int, crit_d: int) -> CertLevel:
    if days > info_d:
        return "OK"
    if days > warn_d:
        return "INFO"
    if days > crit_d:
        return "WARNING"
    return "CRITICAL"


@dataclass(frozen=True)
class CertInspectionResult:
    path: str
    not_after_utc: datetime
    days_remaining: int
    level: CertLevel


def inspect_certificate_file(
    cert_path: Path, *, now: datetime | None = None
) -> CertInspectionResult:
    """评估单个证书文件。"""
    now = now or datetime.now(timezone.utc)
    na = openssl_cert_not_after(cert_path)
    # 按日历日差（与 KPI「提前 X 天」语义一致）
    delta = na.date() - now.astimezone(timezone.utc).date()
    days = int(delta.days)
    info_d, warn_d, crit_d = thresholds()
    level = classify_days_remaining(days, info_d=info_d, warn_d=warn_d, crit_d=crit_d)
    return CertInspectionResult(
        path=str(cert_path.resolve()),
        not_after_utc=na,
        days_remaining=days,
        level=level,
    )


def iter_tls_cert_paths_from_env() -> List[Path]:
    raw = (os.environ.get("MODSTORE_TLS_CERT_PATHS") or "").strip()
    if not raw:
        return []
    normalized = raw.replace(";", ",")
    chunks = [p.strip() for p in normalized.split(",") if p.strip()]
    out: List[Path] = []
    repo_root = _repo_root_optional()
    for c in chunks:
        if not c:
            continue
        p = Path(c)
        if not p.is_absolute() and repo_root is not None:
            p = repo_root / p
        out.append(p)
    return out


def _repo_root_optional() -> Path | None:
    env = os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root as rr

        return Path(rr())
    except Exception:
        return None


def scan_tls_certificates(paths: Sequence[Path | str] | None = None) -> List[CertInspectionResult]:
    """扫描路径列表；默认来自 ``MODSTORE_TLS_CERT_PATHS``。"""
    resolved: List[Path] = []
    if paths is None:
        resolved = iter_tls_cert_paths_from_env()
    else:
        for p in paths:
            resolved.append(Path(p))
    results: List[CertInspectionResult] = []
    now = datetime.now(timezone.utc)
    for p in resolved:
        if not p.is_file():
            continue
        try:
            results.append(inspect_certificate_file(p, now=now))
        except (OSError, RuntimeError, ValueError):
            continue
    return results


def format_cli_line(r: CertInspectionResult) -> str:
    na = r.not_after_utc.strftime("%Y-%m-%d %H:%M:%SZ")
    return f"level={r.level} days_remaining={r.days_remaining} " f"notAfter={na} path={r.path}"


def main(argv: List[str] | None = None) -> int:
    """CLI：``python -m modstore_server.tls_cert_inspection <cert.pem>``"""
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: tls_cert_inspection <path-to-pem-or-crt>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        return 2
    try:
        r = inspect_certificate_file(path)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_cli_line(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
