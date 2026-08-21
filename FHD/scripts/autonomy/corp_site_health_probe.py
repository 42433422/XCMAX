#!/usr/bin/env python3
"""企业官网（成都修茈科技有限公司 / xiu-ci.com）健康探测脚本。

七元契约沿用 cvm_autonomy_watcher.py：
  Signal(schedule 每 10 分钟 / workflow_dispatch) →
  Diagnosis(6 surface 探测 + body_contains 断言) →
  Action(escalate → approval_ledger → IncidentEvent(scope=website)) →
  Policy(fail-open: ledger 写入失败不阻断探测) →
  Adapter(httpx GET) →
  RuntimeTruthSnapshot(JSONL audit) →
  AuditEntry(/opt/fhd-full/autonomy/corp_site_health_*.jsonl)。

退出码：
- 0：全部 surface 探测通过
- 1：至少一个 surface 失败（已写 audit + 已 escalate）
- 2：配置错误（base_url 缺失 / httpx 未安装 / audit-dir 不可写）

部署位置：CVM `/opt/fhd-full/scripts/autonomy/corp_site_health_probe.py`（与
cvm_autonomy_watcher.py 共享 fhd-full venv，单文件可独立运行）。
"""

from __future__ import annotations

import sys

# When this file is launched by absolute path, Python prepends its directory to
# sys.path. That directory also contains ``types.py``, which can shadow the
# standard-library ``types`` module during a clean interpreter startup. Remove
# only this script-directory entry before importing the standard library.
_SCRIPT_DIR = __file__.replace("\\", "/").rsplit("/", 1)[0]
if sys.path and sys.path[0].replace("\\", "/").rstrip("/") == _SCRIPT_DIR:
    sys.path.pop(0)

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The watcher executes this file by absolute path on CVM. In that mode Python
# places ``scripts/autonomy`` on sys.path, not the FHD deployment root, so the
# sibling ``app`` package is otherwise unavailable. Keep the probe genuinely
# standalone regardless of the caller's working directory.
FHD_ROOT = Path(__file__).resolve().parents[2]
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    import httpx
except ImportError:  # pragma: no cover - CVM venv 必装
    httpx = None  # type: ignore[assignment]


# =====================================================================
# 数据模型
# =====================================================================


@dataclass
class SurfaceSpec:
    """单个探测 surface 的规格定义。"""

    name: str
    path: str
    expected_status: int = 200
    body_contains: list[str] = field(default_factory=list)
    body_not_contains: list[str] = field(default_factory=list)
    timeout: float = 10.0


@dataclass
class ProbeResult:
    """单个 surface 探测结果。"""

    name: str
    url: str
    ok: bool
    status_code: int | None
    error: str = ""
    duration_ms: float = 0.0
    body_excerpt: str = ""
    failed_assertion: str = ""


@dataclass
class ProbeReport:
    """一次完整探测的报告。"""

    base_url: str
    started_at: str
    finished_at: str = ""
    results: list[ProbeResult] = field(default_factory=list)
    all_ok: bool = True
    failed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =====================================================================
# 默认 surface 清单
# =====================================================================


DEFAULT_SURFACES: list[SurfaceSpec] = [
    SurfaceSpec(
        name="homepage",
        path="/",
        body_contains=["成都修茈", "xiu-ci", "XCMAX"],
        body_not_contains=["404 Not Found", "500 Internal Server Error", "502 Bad Gateway"],
    ),
    SurfaceSpec(
        name="developer_portal",
        path="/developer.html",
        body_contains=["developer", "API", "开发者"],
        body_not_contains=["404 Not Found"],
    ),
    SurfaceSpec(
        name="partials_header",
        path="/partials/header.html",
        body_contains=["nav", "header", "成都修茈"],
        body_not_contains=["404 Not Found"],
    ),
    SurfaceSpec(
        name="partials_loader",
        path="/partials/loader.js",
        body_contains=["function", "load", "fetch"],
        body_not_contains=["404 Not Found"],
    ),
    SurfaceSpec(
        name="market_download",
        path="/market/download",
        body_contains=["download", "market", "MOD"],
        body_not_contains=["404 Not Found"],
    ),
    SurfaceSpec(
        name="market_index",
        path="/market/",
        body_contains=["market", "MOD", "插件"],
        body_not_contains=["404 Not Found"],
    ),
]


# =====================================================================
# 探测核心
# =====================================================================


def probe_url(
    base_url: str,
    spec: SurfaceSpec,
    *,
    client: Any = None,
) -> ProbeResult:
    """探测单个 URL，返回 ProbeResult。"""
    url = base_url.rstrip("/") + spec.path
    result = ProbeResult(name=spec.name, url=url, ok=False, status_code=None)
    if httpx is None and client is None:
        result.error = "httpx unavailable"
        return result

    started = datetime.now(UTC)
    close_after = False
    if client is None:
        client = httpx.Client(timeout=spec.timeout, follow_redirects=True)
        close_after = True
    try:
        resp = client.get(url)
        result.status_code = resp.status_code
        body = resp.text
        result.body_excerpt = body[:200]
        if resp.status_code != spec.expected_status:
            result.error = f"status {resp.status_code} != expected {spec.expected_status}"
            result.failed_assertion = f"status_code:{resp.status_code}"
            return result
        if spec.body_contains:
            if not any(kw in body for kw in spec.body_contains):
                result.error = f"body_contains all missed: {spec.body_contains!r}"
                result.failed_assertion = "body_contains"
                return result
        for kw in spec.body_not_contains:
            if kw in body:
                result.error = f"body_not_contains hit: {kw!r}"
                result.failed_assertion = f"body_not_contains:{kw!r}"
                return result
        result.ok = True
        return result
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - 探测层覆盖所有异常转 ProbeResult
        result.error = f"http error: {exc!r}"
        return result
    finally:
        finished = datetime.now(UTC)
        result.duration_ms = (finished - started).total_seconds() * 1000.0
        if close_after:
            try:
                client.close()
            except RECOVERABLE_ERRORS:  # noqa: BLE001 - pragma: no cover
                pass


def run_probe(
    base_url: str,
    *,
    surfaces: list[SurfaceSpec] | None = None,
    client: Any = None,
) -> ProbeReport:
    """跑全量 surface 探测，返回 ProbeReport。"""
    surfaces = surfaces if surfaces is not None else DEFAULT_SURFACES
    report = ProbeReport(
        base_url=base_url,
        started_at=datetime.now(UTC).isoformat(),
    )
    close_client = client is None
    if client is None and httpx is not None:
        client = httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        for spec in surfaces:
            r = probe_url(base_url, spec, client=client)
            report.results.append(r)
            if not r.ok:
                report.all_ok = False
                report.failed_count += 1
    finally:
        if close_client and client is not None:
            try:
                client.close()
            except RECOVERABLE_ERRORS:  # noqa: BLE001 - pragma: no cover
                pass
    report.finished_at = datetime.now(UTC).isoformat()
    return report


# =====================================================================
# Audit + Escalate
# =====================================================================


def write_audit(report: ProbeReport, audit_dir: Path) -> Path | None:
    """把 ProbeReport 追加写到 JSONL audit。"""
    if not audit_dir.exists():
        try:
            audit_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[corp-probe] audit dir mkdir failed: {exc!r}", file=sys.stderr)
            return None
    ts = datetime.now(UTC).strftime("%Y%m%d")
    audit_file = audit_dir / f"corp_site_health_{ts}.jsonl"
    try:
        with audit_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[corp-probe] audit write failed: {exc!r}", file=sys.stderr)
        return None
    return audit_file


def _post_to_approval_ledger(
    action: str,
    payload: dict,
    *,
    source: str = "runtime",
) -> dict | None:
    """内联轻量 fail-open ledger 客户端（避免依赖 _approval_ledger_client 路径）。

    与 FHD/scripts/ci/_approval_ledger_client.py 行为一致：fail-open。
    """
    base_url = os.environ.get("FHD_API_BASE_URL", "").strip()
    if not base_url:
        print("[corp-probe] FHD_API_BASE_URL missing, skip ledger", file=sys.stderr)
        return None
    token = (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    if not token:
        print("[corp-probe] autonomy token missing, skip ledger", file=sys.stderr)
        return None
    if httpx is None:
        print("[corp-probe] httpx unavailable, skip ledger", file=sys.stderr)
        return None
    url = f"{base_url.rstrip('/')}/api/ops/autonomy/actions/ingest"
    headers = {"X-Autonomy-Token": token, "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "action": action,
        "payload": payload,
        "source": source,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=body)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - fail-open 覆盖网络/超时
        print(f"[corp-probe] ledger http error: {exc!r}", file=sys.stderr)
        return None
    if resp.status_code < 200 or resp.status_code >= 300:
        print(
            f"[corp-probe] ledger non-2xx status={resp.status_code} body={resp.text[:300]}",
            file=sys.stderr,
        )
        return None
    try:
        data = resp.json()
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - pragma: no cover
        print(f"[corp-probe] ledger json decode error: {exc!r}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        return None
    return data


def escalate(report: ProbeReport, *, dry_run: bool = False) -> dict | None:
    """失败时调用 approval ledger 写入待办（fail-open）。

    payload 结构与 IncidentEvent 表对齐：
      event_type=corp_site_down, scope=website, source=runtime
    后端 unified_autonomy_orchestrator.py 消费 scope=website → 触发
    website_runner.dispatch_incident（gap 4 实现）。
    """
    if report.all_ok:
        return None
    failed_surfaces = [
        {"name": r.name, "url": r.url, "error": r.error, "status": r.status_code}
        for r in report.results
        if not r.ok
    ]
    payload = {
        "event_type": "corp_site_down",
        "scope": "website",
        "source": "runtime",
        "base_url": report.base_url,
        "failed_surfaces": failed_surfaces,
        "failed_count": report.failed_count,
        "total_surfaces": len(report.results),
        "started_at": report.started_at,
        "finished_at": report.finished_at,
    }
    if dry_run:
        print(f"[corp-probe] dry-run escalate payload: {json.dumps(payload, ensure_ascii=False)}")
        return None
    return _post_to_approval_ledger(
        action="corp_site_down",
        payload=payload,
        source="runtime",
    )


# =====================================================================
# CLI
# =====================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="企业官网健康探测")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CORP_SITE_BASE_URL", "https://xiu-ci.com"),
        help="官网基准 URL（默认 env CORP_SITE_BASE_URL 或 https://xiu-ci.com）",
    )
    parser.add_argument(
        "--audit-dir",
        default="/opt/fhd-full/autonomy",
        help="JSONL audit 目录（默认 /opt/fhd-full/autonomy）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只采集 + 写 audit，不 escalate（不调 approval_ledger）",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.strip().rstrip("/")
    if not base_url:
        print("::error::[corp-probe] --base-url required (or CORP_SITE_BASE_URL env)")
        return 2
    if httpx is None:
        print("::error::[corp-probe] httpx not installed in current venv")
        return 2

    audit_dir = Path(args.audit_dir)
    print(f"[corp-probe] base_url={base_url} audit_dir={audit_dir} dry_run={args.dry_run}")

    report = run_probe(base_url)
    for r in report.results:
        status = "OK" if r.ok else "FAIL"
        print(
            f"[corp-probe] {status} {r.name} {r.url} "
            f"status={r.status_code} dur={r.duration_ms:.0f}ms "
            f"err={r.error!r}"
        )

    audit_file = write_audit(report, audit_dir)
    if audit_file:
        print(f"[corp-probe] audit written: {audit_file}")

    if report.all_ok:
        print(f"[corp-probe] PASS - all {len(report.results)} surfaces OK")
        return 0

    print(f"[corp-probe] FAIL - {report.failed_count}/{len(report.results)} surfaces failed")
    ledger_result = escalate(report, dry_run=args.dry_run)
    if ledger_result is not None:
        print(
            f"[corp-probe] ledger accepted: {json.dumps(ledger_result, ensure_ascii=False)[:300]}"
        )
    elif args.dry_run:
        print("[corp-probe] dry-run: ledger not called")
    else:
        print("[corp-probe] ledger write skipped (fail-open: env/config issue)")

    return 1


if __name__ == "__main__":
    sys.exit(main())
