#!/usr/bin/env python3
"""验收闭环回写：市场端安装回执判定 → GitHub 工单验收/重开。

主线最后一环：CI 通过 ≠ 客户能用。发布上线后，macOS 与 Windows
客户机的安装/运行回执在市场端聚合判定（release_acceptance），
本脚本把判定结果回写到发布 manifest 携带的原工单（linked_issues）：

- rejected（任一设备失败/回滚）→ 重开原 issue + 失败证据评论 + acceptance-failed 标签
- accepted（双平台回执健康）→ 先持久化回执，再评论 + 标签 + 真正关闭 Issue
- pending（回执未齐）→ 不动作

幂等：以 issue 标签与实际开关状态为收据；持久化失败时禁止改变 GitHub 状态。
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
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LABEL_FAILED = "acceptance-failed"
LABEL_ACCEPTED = "customer-accepted"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _fetch_published_release(market_base: str) -> dict[str, Any]:
    """The published pointer carries linked_issues; the source catalog does not."""
    parsed = urllib.parse.urlsplit(market_base.rstrip("/"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return {"_error": "invalid_public_release_origin"}
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    req = urllib.request.Request(
        origin + "/download-release.json",
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            actual = urllib.parse.urlsplit(response.geturl())
            if (actual.scheme, actual.netloc) != (parsed.scheme, parsed.netloc):
                return {"_error": "public_release_redirected_to_another_origin"}
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return {"_error": "public_release_pointer_too_large"}
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {"_error": "invalid_public_release_pointer"}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"_error": "public_release_unavailable", "_body": str(exc)[:200]}



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
    if LABEL_ACCEPTED in labels and issue.get("state") == "closed":
        logger.info("issue #%d already accepted and closed", number)
        return True
    api = f"https://api.github.com/repos/{repo}/issues/{number}"
    body = (
        f"【验收通过】版本 `{acceptance.get('version')}` macOS 与 Windows "
        "客户机安装回执均健康：\n"
        + "\n".join(_evidence_lines(acceptance))
        + "\n\n工单验收关闭（回执驱动，非仅 CI 通过）。"
    )
    if LABEL_ACCEPTED not in labels:
        commented = _http("POST", f"{api}/comments", token, {"body": body})
        if commented.get("_error"):
            logger.error("comment issue #%d failed: %s", number, commented.get("_body"))
            return False
        labeled = _http("POST", f"{api}/labels", token, {"labels": [LABEL_ACCEPTED]})
        if labeled.get("_error"):
            logger.error("label issue #%d failed: %s", number, labeled.get("_body"))
            return False
    if issue.get("state") != "closed":
        closed = _http("PATCH", api, token, {"state": "closed", "state_reason": "completed"})
        if closed.get("_error") or closed.get("state") != "closed":
            logger.error("closing accepted issue #%d failed: %s", number, closed)
            return False
    logger.info("issue #%d marked customer-accepted and closed", number)
    return True


def _record_verdict_local(
    market_base: str,
    market_token: str,
    issue_number: int,
    version: str,
    verdict: str,
    acceptance: dict,
) -> bool:
    """Persist the verdict on the shared market host, never on an ephemeral CI runner."""
    payload = {
        "issue_number": int(issue_number),
        "release_version": version,
        "verdict": verdict,
        "evidence": {
            "build_sha": acceptance.get("build_sha") or acceptance.get("git_sha"),
            "per_platform": acceptance.get("per_platform") or {},
        },
    }
    result = _http(
        "POST", f"{market_base.rstrip('/')}/api/work-orders/acceptance",
        market_token, payload,
    )
    if not isinstance(result, dict) or result.get("ok") is not True:
        logger.error("market verdict persistence failed for issue #%s", issue_number)
        return False
    return True

def run(args: argparse.Namespace) -> int:
    # Scheduled runs MUST consume the already-published pointer.  The working
    # tree catalog is only release intent and intentionally lacks linked_issues.
    if args.release_config:
        try:
            config = json.loads(Path(args.release_config).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("cannot read release snapshot %s: %s", args.release_config, exc)
            return 1
    else:
        config = _fetch_published_release(args.market_base)
    if not isinstance(config, dict) or config.get("_error"):
        logger.error("published release lookup failed: %s", config)
        return 1

    version = str(config.get("download_version") or "").strip()
    build_sha = str(config.get("git_sha") or "").strip()
    issues = config.get("linked_issues")
    if (
        config.get("schema") != "xcagi.download_release.public/v1"
        or config.get("release_ready") is not True
        or not version
        or (args.version and args.version != version)
        or config.get("version_lock") != version
        or not _SHA.fullmatch(build_sha)
        or config.get("release_id") != f"xcagi-{version}-{build_sha}"
    ):
        logger.error("published release identity is missing, unready or inconsistent")
        return 1
    if (
        not isinstance(issues, list)
        or not issues
        or any(type(n) is not int or n <= 0 for n in issues)
        or len(issues) != len(set(issues))
    ):
        logger.error("published release %s carries no unique linked_issues", version)
        return 1

    acceptance = _fetch_acceptance(
        args.market_base, args.market_token, version, args.channel, build_sha
    )
    if not isinstance(acceptance, dict) or acceptance.get("_error"):
        logger.error("acceptance lookup failed: %s", acceptance)
        return 1
    if (
        acceptance.get("version") != version
        or str(acceptance.get("build_sha") or acceptance.get("git_sha") or "") != build_sha
    ):
        logger.error("acceptance receipt is not for this exact release")
        return 1
    verdict = str(acceptance.get("verdict") or "pending")
    logger.info("version=%s sha=%s verdict=%s linked_issues=%s",
                version, build_sha, verdict, issues)
    if verdict == "pending":
        return 0
    if verdict not in ("accepted", "rejected"):
        logger.error("unknown acceptance verdict: %s", verdict)
        return 1
    if verdict == "accepted":
        platforms = acceptance.get("per_platform")
        if not isinstance(platforms, dict):
            logger.error("accepted verdict missing per-platform evidence")
            return 1
        for platform in ("win", "mac"):
            row = platforms.get(platform)
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("installed"), int)
                or row["installed"] < 1
                or row.get("failed") != 0
            ):
                logger.error("accepted verdict has incomplete %s evidence", platform)
                return 1

    if args.dry_run:
        logger.info("[dry-run] would write back verdict=%s to issues %s", verdict, issues)
        return 0

    _ensure_label(args.repo, args.token, LABEL_FAILED, "d73a4a", "客户机验收失败，工单已自动重开")
    _ensure_label(args.repo, args.token, LABEL_ACCEPTED, "0e8a16", "双平台客户机回执健康，验收通过")

    failures = 0
    for number in issues:
        issue = _http(
            "GET", f"https://api.github.com/repos/{args.repo}/issues/{number}", args.token
        )
        if not isinstance(issue, dict) or issue.get("_error") or issue.get("number") != number:
            logger.error("fetch issue #%d failed or returned wrong identity", number)
            failures += 1
            continue
        if "pull_request" in issue:
            logger.error("linked work order #%d is a pull request, not an issue", number)
            failures += 1
            continue
        # CI runner disk is ephemeral. Never report an issue closed if the
        # authoritative customer acceptance record could not be persisted.
        if not _record_verdict_local(
            args.market_base, args.market_token, number, version, verdict, acceptance
        ):
            failures += 1
            continue
        ok = (
            _accept_issue(args.repo, args.token, issue, acceptance)
            if verdict == "accepted"
            else _reopen_issue(args.repo, args.token, issue, acceptance)
        )
        if not ok:
            failures += 1
    return 1 if failures else 0

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--market-base", default=os.environ.get("XCAGI_MARKET_BASE_URL", ""))
    parser.add_argument("--market-token", default=os.environ.get("MARKET_ADMIN_TOKEN", ""))
    parser.add_argument(
        "--release-config", default="",
        help="Explicit published pointer snapshot for offline testing; default fetches public pointer",
    )
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
    if args.apply and not args.token:
        logger.error("--apply requires --token")
        raise SystemExit(2)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
