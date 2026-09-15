#!/usr/bin/env python3
"""连接件4（客户侧重测）：修复送达客户机后，对运行中的客户应用执行场景重测。

三查：GET /api/health?lite=1（健康+版本身份）、scenario.retest_url（修复前
404/5xx、修复后 <400）。回执落 test_reports/retest/receipt-<key12>.json，
--issue-comment 写回工单 issue；不替代既有 release-acceptance-closeout 闭环。
代理绕过：全部请求走 ProxyHandler({}) 直连（代理拦截 127.0.0.1 假阴性教训）。

用法：python scripts/dev/customer_retest.py --spec <repro spec> \
    --base-url http://127.0.0.1:8787 [--expect-version 1.0.0.4]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("customer_retest")

_FHD_ROOT = Path(__file__).resolve().parents[2]


def _repro_dir() -> Path:
    return Path(
        os.environ.get("WORK_ORDER_REPRO_DIR") or (_FHD_ROOT / "test_reports" / "repro")
    )


def _retest_dir() -> Path:
    return Path(
        os.environ.get("WORK_ORDER_RETEST_DIR") or (_FHD_ROOT / "test_reports" / "retest")
    )


# 直连客户端：绕过本机代理（历史教训：代理拦截 127.0.0.1 造成假阴性）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_get(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """GET 直连请求，永不抛出——返回 {ok, status, body_snippet, error}。"""
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            raw = resp.read(65536).decode("utf-8", errors="replace")
            return {"ok": True, "status": int(resp.status), "body": raw}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": int(exc.code), "body": "", "error": f"http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": 0, "body": "", "error": str(exc)[:200]}


def _check(base_url: str, name: str, url: str, *, ok_status_lt: int) -> dict[str, Any]:
    result = _http_get(url)
    status = int(result.get("status") or 0)
    ok = result.get("ok") is True and status < ok_status_lt
    body = result.get("body") or ""
    return {
        "name": name,
        "url": url,
        "ok": ok,
        "status": status,
        "error": result.get("error") or "",
        # body 供调用方解析（如 health JSON）；body_snippet 仅供回执展示
        "body": body,
        "body_snippet": body[:400],
    }


def retest(spec: dict[str, Any], base_url: str, *, expect_version: str = "") -> dict[str, Any]:
    """对运行中的客户应用执行重测检查，返回回执 dict（不落盘）。"""
    scenario = spec.get("scenario") if isinstance(spec.get("scenario"), dict) else {}
    checks: list[dict[str, Any]] = []
    base = base_url.rstrip("/")

    health = _check(base_url, "app_health", f"{base}/api/health?lite=1", ok_status_lt=400)
    app_version = ""
    if health["ok"]:
        try:
            payload = json.loads(health.get("body") or "{}")
            app_version = str(payload.get("version") or "")
        except json.JSONDecodeError:
            health["ok"] = False
            health["error"] = "health_payload_not_json"
    health.pop("body", None)  # 回执只留摘要，不落完整响应体
    health["app_version"] = app_version
    checks.append(health)

    if expect_version:
        checks.append(
            {
                "name": "app_version_expectation",
                "ok": app_version == expect_version,
                "expected": expect_version,
                "actual": app_version,
            }
        )

    retest_url = str(scenario.get("retest_url") or "")
    if retest_url:
        url = retest_url if retest_url.startswith("http") else f"{base}{retest_url}"
        checks.append(
            _check(base_url, "scenario_retest", url, ok_status_lt=400)
        )

    verdict = "pass" if checks and all(c["ok"] for c in checks) else "fail"
    return {
        "dedup_key": spec.get("dedup_key"),
        "wo_id": spec.get("wo_id"),
        "checked_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "app_version": app_version,
        "checks": checks,
        "verdict": verdict,
    }


def _comment_on_issue(issue_number: int, receipt: dict[str, Any]) -> bool:
    """把重测回执摘要写回工单 issue（对外观测载体）；失败不阻塞。"""
    lines = [
        "## 客户侧重测回执（连接件4，自动）",
        f"- 判定: **{receipt['verdict']}**",
        f"- 应用版本: `{receipt.get('app_version') or 'unknown'}`",
        f"- 时间: `{receipt['checked_at']}`",
    ]
    for check in receipt.get("checks", []):
        lines.append(f"- {'PASS' if check.get('ok') else 'FAIL'} {check.get('name')} ({check.get('status', '-')})")
    try:
        completed = subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", "\n".join(lines)],
            cwd=str(_FHD_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _record_knowledge(key12: str) -> None:
    """连接件5 生产侧：重测通过后把三件套沉淀为知识案例（fail-open）。"""
    path = Path(__file__).with_name("work_order_knowledge.py")
    if not path.is_file():
        return
    spec = importlib.util.spec_from_file_location("work_order_knowledge", path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("work_order_knowledge", module)
    spec.loader.exec_module(module)
    try:
        module.main(["--record", _spec_dedup_key(key12)])
    except Exception:  # noqa: BLE001 - 知识回流失败不阻塞重测回执
        logger.debug("knowledge record skipped", exc_info=True)


def _spec_dedup_key(key12: str) -> str:
    """从重测回执里取完整 dedup_key（知识案例按完整 key 幂等）。"""
    receipt_path = _retest_dir() / f"receipt-{key12}.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        return str(receipt.get("dedup_key") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def run(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec) if args.spec else _pick_latest_spec()
    if spec_path is None or not spec_path.is_file():
        logger.error("repro spec not found")
        return 1
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    receipt = retest(spec, args.base_url, expect_version=args.expect_version)
    retest_dir = _retest_dir()
    retest_dir.mkdir(parents=True, exist_ok=True)
    key12 = str(spec.get("dedup_key") or "")[:12]
    out = retest_dir / f"receipt-{key12}.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("retest receipt: %s verdict=%s", out, receipt["verdict"])
    if receipt["verdict"] == "pass":
        _record_knowledge(key12)
    if args.issue_comment:
        ok = _comment_on_issue(int(args.issue_comment), receipt)
        logger.info("issue comment: %s", "posted" if ok else "failed (non-blocking)")
    return 0 if receipt["verdict"] == "pass" else 2


def _pick_latest_spec() -> Path | None:
    specs = sorted(_repro_dir().glob("repro-*.json"))
    return specs[-1] if specs else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default="", help="复现规格路径（缺省取最新一份）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--expect-version", default="", help="校验客户机应用版本（更新到位证据）")
    parser.add_argument("--issue-comment", default="", help="把回执摘要评论到工单 issue")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
