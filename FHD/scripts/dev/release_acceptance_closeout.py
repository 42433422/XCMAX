#!/usr/bin/env python3
"""验收闭环回写：市场端安装回执判定 → GitHub 工单验收/重开。

主线最后一环：CI 通过 ≠ 客户能用。发布上线后，macOS 与 Windows
客户机的安装/运行回执在市场端聚合判定（release_acceptance），
本脚本把判定结果回写到发布 manifest 携带的原工单（linked_issues）：

- rejected（任一设备失败/回滚）→ 重开原 issue + 失败证据评论 + acceptance-failed 标签
- accepted（双平台回执健康）→ 验收证据评论 + customer-accepted 标签
- pending（回执未齐）→ 不动作

幂等：以 issue 标签/状态为收据，重复执行不重复评论或重开。
失败重开的是原工单，不另起新单。

用法：
    python scripts/dev/release_acceptance_closeout.py \
        --repo "$GITHUB_REPOSITORY" --token "$GITHUB_TOKEN" \
        --market-base https://xiu-ci.com --market-token "$ADMIN_TOKEN" \
        --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# 通过 sys.path 注入让脚本能 import app.utils / app.services（与 to_issue 同款约定）
_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from app.utils.operational_errors import (  # noqa: E402  pylint: disable=wrong-import-position
    BOUNDARY_ERRORS,
)

logger = logging.getLogger(__name__)

LABEL_FAILED = "acceptance-failed"
LABEL_ACCEPTED = "customer-accepted"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _http(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(token), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")[:500]}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        # 网络超时/DNS/连接失败：返回结构化错误而非裸崩，调用方按失败处理
        return {"_error": "network_error", "_body": str(exc)[:500]}
    return json.loads(raw) if raw else {}


def _fetch_acceptance(
    market_base: str, market_token: str, version: str, channel: str, build_sha: str = ""
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"version": version, "channel": channel, "build_sha": build_sha})
    url = f"{market_base.rstrip('/')}/api/update-installations/receipts/acceptance?{query}"
    result = _http("GET", url, market_token)
    return result if isinstance(result, dict) else {}


def _ensure_label(repo: str, token: str, name: str, color: str, description: str) -> None:
    api = f"https://api.github.com/repos/{repo}/labels"
    result = _http("POST", api, token, {"name": name, "color": color, "description": description})
    if result.get("_error") not in (None, 422):  # 422 = already_exists
        logger.warning("ensure label %s failed: %s", name, result.get("_error"))


def _label_names(issue: dict[str, Any]) -> set[str]:
    return {
        str(label.get("name") or "")
        for label in issue.get("labels") or []
        if isinstance(label, dict)
    }


def _evidence_lines(acceptance: dict[str, Any]) -> list[str]:
    per_platform = acceptance.get("per_platform") or {}
    lines = []
    for platform in ("win", "mac"):
        stats = per_platform.get(platform) or {}
        lines.append(
            f"- {platform}: installed={int(stats.get('installed') or 0)} "
            f"failed={int(stats.get('failed') or 0)} devices={int(stats.get('devices') or 0)}"
        )
    return lines


def _reopen_issue(repo: str, token: str, issue: dict[str, Any], acceptance: dict) -> bool:
    number = int(issue["number"])
    labels = _label_names(issue)
    if str(issue.get("state")) == "open" and LABEL_FAILED in labels:
        logger.info("issue #%d already reopened for acceptance failure", number)
        return True
    api = f"https://api.github.com/repos/{repo}/issues/{number}"
    if str(issue.get("state")) != "open":
        reopened = _http("PATCH", api, token, {"state": "open"})
        if reopened.get("_error"):
            logger.error("reopen issue #%d failed: %s", number, reopened.get("_body"))
            return False
    failures = acceptance.get("failures") or []
    failure_lines = [
        f"  - 设备 `{f.get('installation_id')}` ({f.get('platform')}) "
        f"状态 {f.get('status')}: {str(f.get('error') or '')[:200]}"
        for f in failures[:5]
    ]
    body = (
        f"【验收失败 · 自动重开】版本 `{acceptance.get('version')}` 客户机安装/运行回执异常：\n"
        + "\n".join(_evidence_lines(acceptance))
        + "\n失败明细：\n"
        + ("\n".join(failure_lines) if failure_lines else "  - （无明细）")
        + "\n\n本工单已重开，修复后沿原主线重新发布验证，不另起新单。"
    )
    commented = _http("POST", f"{api}/comments", token, {"body": body})
    if commented.get("_error"):
        logger.error("comment issue #%d failed: %s", number, commented.get("_body"))
        return False
    labeled = _http("POST", f"{api}/labels", token, {"labels": [LABEL_FAILED]})
    if labeled.get("_error"):
        logger.error("label issue #%d failed: %s", number, labeled.get("_body"))
        return False
    logger.info("issue #%d reopened with acceptance evidence", number)
    return True


def _accept_issue(repo: str, token: str, issue: dict[str, Any], acceptance: dict) -> bool:
    number = int(issue["number"])
    labels = _label_names(issue)
    if LABEL_ACCEPTED in labels:
        logger.info("issue #%d already accepted", number)
        return True
    api = f"https://api.github.com/repos/{repo}/issues/{number}"
    body = (
        f"【验收通过】版本 `{acceptance.get('version')}` macOS 与 Windows "
        "客户机安装回执均健康：\n"
        + "\n".join(_evidence_lines(acceptance))
        + "\n\n工单验收关闭（回执驱动，非仅 CI 通过）。"
    )
    commented = _http("POST", f"{api}/comments", token, {"body": body})
    if commented.get("_error"):
        logger.error("comment issue #%d failed: %s", number, commented.get("_body"))
        return False
    labeled = _http("POST", f"{api}/labels", token, {"labels": [LABEL_ACCEPTED]})
    if labeled.get("_error"):
        logger.error("label issue #%d failed: %s", number, labeled.get("_body"))
        return False
    logger.info("issue #%d marked customer-accepted", number)
    return True


def _record_verdict_local(issue_number: int, version: str, verdict: str, acceptance: dict) -> None:
    """把验收判定落回本地工单事件流（best-effort；服务端运行时持久）。"""
    try:
        from app.services.work_order_ssot import record_acceptance_verdict

        record_acceptance_verdict(
            issue_number=issue_number,
            release_version=version,
            verdict=verdict,
            evidence={"per_platform": acceptance.get("per_platform") or {}},
        )
    except BOUNDARY_ERRORS:  # noqa: BLE001 - CI 运行器本地事件流为临时介质，不阻塞回写
        logger.debug("local work_order verdict skipped", exc_info=True)


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
        logger.info("version %s carries no linked_issues, nothing to close out", version)
        return 0

    acceptance = _fetch_acceptance(
        args.market_base, args.market_token, version, args.channel, build_sha
    )
    if acceptance.get("_error"):
        logger.error(
            "acceptance query failed: %s %s", acceptance.get("_error"), acceptance.get("_body")
        )
        return 1
    verdict = str(acceptance.get("verdict") or "pending")
    logger.info("version=%s verdict=%s linked_issues=%s", version, verdict, linked_issues)
    if verdict == "pending":
        return 0
    if verdict not in ("accepted", "rejected"):
        logger.error("unknown verdict: %s", verdict)
        return 1

    if args.dry_run:
        logger.info("[dry-run] would write back verdict=%s to issues %s", verdict, linked_issues)
        return 0

    _ensure_label(args.repo, args.token, LABEL_FAILED, "d73a4a", "客户机验收失败，工单已自动重开")
    _ensure_label(args.repo, args.token, LABEL_ACCEPTED, "0e8a16", "双平台客户机回执健康，验收通过")

    failures = 0
    for number in linked_issues:
        issue = _http(
            "GET", f"https://api.github.com/repos/{args.repo}/issues/{number}", args.token
        )
        if issue.get("_error"):
            logger.error("fetch issue #%d failed: %s", number, issue.get("_error"))
            failures += 1
            continue
        if "pull_request" in issue:
            continue
        ok = (
            _accept_issue(args.repo, args.token, issue, acceptance)
            if verdict == "accepted"
            else _reopen_issue(args.repo, args.token, issue, acceptance)
        )
        if ok:
            _record_verdict_local(number, version, verdict, acceptance)
        else:
            failures += 1
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--market-base", default=os.environ.get("XCAGI_MARKET_BASE_URL", ""))
    parser.add_argument("--market-token", default=os.environ.get("MARKET_ADMIN_TOKEN", ""))
    parser.add_argument("--release-config", default="config/download_release.json")
    parser.add_argument("--version", default="")
    parser.add_argument("--channel", default="stable", choices=("stable", "staging"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.dry_run and not args.apply:
        logger.error("specify --dry-run or --apply")
        raise SystemExit(2)
    if not args.repo or not args.market_base:
        logger.error("--repo and --market-base are required")
        raise SystemExit(2)
    if args.apply and (not args.token or not args.market_token):
        logger.error("--apply requires --token and --market-token")
        raise SystemExit(2)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
