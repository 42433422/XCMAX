"""CVM + 本机双端 health 日报。

Week 3 调度任务：把 ``https://xiu-ci.com/fhd-api/api/health`` (CVM)、
``http://127.0.0.1:8788/api/health`` (本机 API)、``http://127.0.0.1:8789/api/health``
(本机 scheduler) 三端探活写到同一张日报，每天 23:55 Asia/Shanghai 汇总过去 24h
可用率，门槛 ≥99% ok / 95-99% warn / <95% critical。

样本：``$MODSTORE_RUNTIME_DIR/system_status_health.jsonl``
日报：``$MODSTORE_RUNTIME_DIR/system_status_daily_report.json``
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

_OK_THRESHOLD = 0.99
_WARN_THRESHOLD = 0.95


def _runtime_dir() -> Path:
    raw = os.environ.get("MODSTORE_RUNTIME_DIR") or ""
    if raw:
        return Path(raw)
    return Path.home() / "Library" / "Application Support" / "XCMAX" / "modstore-daily" / "runtime"


def samples_path() -> Path:
    return _runtime_dir() / "system_status_health.jsonl"


def daily_report_path() -> Path:
    return _runtime_dir() / "system_status_daily_report.json"


def configured_endpoints() -> List[Tuple[str, str]]:
    """从 env 读取探活端点列表；未配置则返回默认三端。"""
    raw = os.environ.get("MODSTORE_SYSTEM_STATUS_ENDPOINTS") or ""
    endpoints: List[Tuple[str, str]] = []
    if raw.strip():
        for item in raw.split(","):
            item = item.strip()
            if not item or "|" not in item:
                continue
            name, url = item.split("|", 1)
            name = name.strip()
            url = url.strip()
            if name and url:
                endpoints.append((name, url))
    if not endpoints:
        endpoints = [
            ("cvm", "https://xiu-ci.com/fhd-api/api/health"),
            ("local_api", "http://127.0.0.1:8788/api/health"),
            ("local_scheduler", "http://127.0.0.1:8789/api/health"),
        ]
    return endpoints


def probe_endpoint(name: str, url: str, *, timeout: float = 5.0) -> Dict[str, Any]:
    """探活单个端点。"""
    started = time.monotonic()
    probed_at = datetime.now(timezone.utc).isoformat()
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.get(url)
        latency_ms = int((time.monotonic() - started) * 1000)
        body: Optional[Any] = None
        try:
            body = resp.json()
        except Exception:
            body = None
        ok = resp.status_code == 200
        return {
            "name": name,
            "url": url,
            "ok": ok,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "error": None if ok else f"HTTP {resp.status_code}",
            "body": body,
            "probed_at": probed_at,
        }
    except httpx.HTTPError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "name": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "error": f"connect_error: {exc.__class__.__name__}",
            "body": None,
            "probed_at": probed_at,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "name": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "error": f"unexpected: {exc.__class__.__name__}: {exc}",
            "body": None,
            "probed_at": probed_at,
        }


def append_sample(sample: Dict[str, Any]) -> Path:
    """追加一条样本到 jsonl，自动创建父目录。"""
    path = samples_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def sample_once() -> Dict[str, Any]:
    """对所有 configured_endpoints 各探活一次，落盘一条聚合样本。"""
    endpoints = configured_endpoints()
    results = [probe_endpoint(name, url) for name, url in endpoints]
    sample = {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": results,
        "total": len(results),
        "ok_count": sum(1 for r in results if r.get("ok")),
    }
    try:
        append_sample(sample)
    except Exception:
        pass
    return sample


def _read_samples(limit: int = 0) -> List[Dict[str, Any]]:
    path = samples_path()
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    if limit > 0:
        out = out[-limit:]
    return out


def compute_availability(samples: List[Dict[str, Any]], period_hours: int = 24) -> Dict[str, Any]:
    """计算每个 endpoint 在过去 ``period_hours`` 内的可用率。"""
    cutoff = datetime.now(timezone.utc).timestamp() - period_hours * 3600
    per_endpoint: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        try:
            sampled_at = datetime.fromisoformat(sample["sampled_at"]).timestamp()
        except Exception:
            continue
        if sampled_at < cutoff:
            continue
        for ep in sample.get("endpoints") or []:
            name = str(ep.get("name") or "unknown")
            bucket = per_endpoint.setdefault(
                name, {"total": 0, "ok": 0, "last_error": None, "last_latency_ms": None}
            )
            bucket["total"] += 1
            if ep.get("ok"):
                bucket["ok"] += 1
            else:
                bucket["last_error"] = ep.get("error")
            bucket["last_latency_ms"] = ep.get("latency_ms")

    for bucket in per_endpoint.values():
        total = bucket["total"]
        bucket["availability"] = (bucket["ok"] / total) if total else 0.0

    overall_total = sum(b["total"] for b in per_endpoint.values())
    overall_ok = sum(b["ok"] for b in per_endpoint.values())
    overall = (overall_ok / overall_total) if overall_total else 0.0
    return {
        "per_endpoint": per_endpoint,
        "overall": overall,
        "overall_total": overall_total,
        "overall_ok": overall_ok,
        "period_hours": period_hours,
    }


def _classify_health(availability: float) -> str:
    if availability >= _OK_THRESHOLD:
        return "ok"
    if availability >= _WARN_THRESHOLD:
        return "warn"
    return "critical"


def generate_daily_report(period_hours: int = 24) -> Dict[str, Any]:
    """聚合过去 24h 样本生成日报。"""
    samples = _read_samples()
    availability = compute_availability(samples, period_hours=period_hours)
    per_endpoint_health: Dict[str, Any] = {}
    for name, bucket in availability["per_endpoint"].items():
        per_endpoint_health[name] = {
            **bucket,
            "health": _classify_health(bucket["availability"]),
        }
    overall_availability = availability["overall"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_hours": period_hours,
        "overall_availability": overall_availability,
        "overall_health": _classify_health(overall_availability),
        "overall_total": availability["overall_total"],
        "overall_ok": availability["overall_ok"],
        "per_endpoint": per_endpoint_health,
        "sample_count": len(samples),
    }


def write_daily_report(report: Dict[str, Any]) -> Path:
    """原子写日报：先写 .tmp 再 rename。"""
    path = daily_report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, sort_keys=True, indent=2)
    tmp.replace(path)
    return path


def cleanup_old_samples(max_age_days: int = 7) -> int:
    """清理超过 ``max_age_days`` 的样本行，返回删除条数。"""
    path = samples_path()
    if not path.is_file():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    kept: List[str] = []
    removed = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            try:
                rec = json.loads(line_stripped)
                ts = datetime.fromisoformat(rec["sampled_at"]).timestamp()
            except Exception:
                removed += 1
                continue
            if ts < cutoff:
                removed += 1
                continue
            kept.append(line_stripped)
    with path.open("w", encoding="utf-8") as fh:
        for line in kept:
            fh.write(line + "\n")
    return removed


def system_status_sample_job() -> None:
    """cron 入口：每 30min 探活一次。失败不抛，单条 log。"""
    try:
        sample = sample_once()
        ok = sample.get("ok_count")
        total = sample.get("total")
        print(f"[system_status_sample] ok={ok}/{total}", flush=True)
    except Exception as exc:
        print(f"[system_status_sample] failed: {exc}", flush=True)


def system_status_daily_summary_job() -> None:
    """cron 入口：每天 23:55 Asia/Shanghai 生成日报 + 清理旧样本。"""
    try:
        report = generate_daily_report(period_hours=24)
        write_daily_report(report)
        cleanup_old_samples(max_age_days=7)
        print(
            f"[system_status_daily_summary] overall={report['overall_availability']:.4f} "
            f"health={report['overall_health']}",
            flush=True,
        )
    except Exception as exc:
        print(f"[system_status_daily_summary] failed: {exc}", flush=True)
