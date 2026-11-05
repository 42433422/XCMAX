#!/usr/bin/env python3
"""发布时回收 merged/released：把本次发布关闭的工单推进到验收窗口。

发布清单（download_release.json）携带 ``linked_issues``（本次发布合并的 PR 所
关闭的 GitHub issue，见 extract_release_linked_issues.py）+ 完整构建 SHA。本脚本
把这些 issue 关联的 Work Order 沿状态机真实推进：

  merged   ← 该 issue 的 PR 已合并且包含在本次发布范围（发布范围即合并证据）
  released ← 版本已发布（发布清单 + build_sha 为发布证据）

完成后工单处于 released，验收回执（closeout）在 verifying 窗口判 closed/reopened。

失败不阻断发布：单 issue 失败仅告警；市场不可达时跳过（发布照常，closeout 侧
仍可处理）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FHD_ROOT = Path(__file__).resolve().parents[2]

# 工单需要沿此推进的最新状态（released 之前）
_PRE_RELEASED = ("candidate", "routed", "in_dev", "merged")


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _http(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(token), method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")[:500]}
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("work-order api unreachable: %s", exc)
        return {"_error": "network", "_body": str(exc)}
    return json.loads(raw) if raw else {}


def _transition(
    market_base: str, token: str, wo_id: str, to_state: str, ref: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = _http(
        "POST",
        f"{market_base.rstrip('/')}/api/work-orders/transition",
        token,
        {"wo_id": wo_id, "to_state": to_state, "ref": ref, "source": "release_manifest"},
    )
    return result


def run(args: argparse.Namespace) -> int:
    config_path = Path(args.release_config)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("cannot read release config %s: %s", config_path, exc)
        return 1
    version = str(args.version or config.get("version_lock") or "").strip()
    build_sha = str(config.get("build_sha") or config.get("git_sha") or "").strip()
    linked = config.get("linked_issues")
    linked_issues = [int(n) for n in (linked if isinstance(linked, list) else []) if int(n) > 0]
    if not version:
        logger.error("no version resolved from --version or release config")
        return 1
    if not linked_issues:
        logger.info("version %s carries no linked_issues, nothing to progress", version)
        return 0

    base = str(args.market_base or "").rstrip("/")
    if not base:
        logger.error("--market-base required")
        return 1
    token = str(args.market_token or "")

    failures = 0
    progressed = 0
    ref: dict[str, Any] = {"release_version": version, "build_sha": build_sha}
    for number in linked_issues:
        view = _http("GET", f"{base}/api/work-orders/by-issue/{number}", token)
        if not isinstance(view, dict) or not view.get("wo_id"):
            logger.info("issue #%d has no work order (or unreachable); skip", number)
            continue
        wo_id = str(view["wo_id"])
        status = str(view.get("status") or "")
        if status in ("released", "verifying", "closed", "reopened"):
            logger.info("issue #%d wo=%s already %s", number, wo_id, status)
            continue
        if status not in _PRE_RELEASED:
            logger.warning("issue #%d wo=%s unexpected status %s", number, wo_id, status)
            continue
        if args.dry_run:
            logger.info(
                "[dry-run] would progress issue #%d wo=%s (%s) → released", number, wo_id, status
            )
            progressed += 1
            continue
        steps = [("merged", status)] if status in ("candidate", "routed", "in_dev") else []
        steps.append(("released", steps[-1][1] if steps else status))
        ok = True
        for to_state, _from in steps:
            call_ref = dict(ref)
            call_ref["issue_number"] = number
            result = _transition(base, token, wo_id, to_state, call_ref)
            if isinstance(result, dict) and not result.get("_error") and result.get("ok") is True:
                progressed += 1
                continue
            reason = str(
                result.get("reason") or result.get("_body") or result.get("_error") or "?"
            ).strip()
            logger.warning("issue #%d wo=%s → %s failed: %s", number, wo_id, to_state, reason)
            ok = False
            break
        if not ok:
            failures += 1

    logger.info("progressed %d transition(s), failures=%d", progressed, failures)
    # 失败不阻断发布：脚本以 0 退出，发布流程 continue-on-error
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-base", default=os.environ.get("XCAGI_MARKET_BASE_URL", ""))
    parser.add_argument("--market-token", default=os.environ.get("MARKET_ADMIN_TOKEN", ""))
    parser.add_argument("--release-config", default="config/download_release.json")
    parser.add_argument("--version", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mode = "dry-run" if args.dry_run else ("apply" if args.apply else "")
    if not mode:
        logger.error("specify --dry-run or --apply")
        raise SystemExit(2)
    if not args.market_base:
        logger.error("--market-base is required")
        raise SystemExit(2)
    if args.apply and not args.market_token:
        logger.error("--apply requires --market-token")
        raise SystemExit(2)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
