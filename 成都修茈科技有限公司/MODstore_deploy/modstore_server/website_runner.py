"""企业官网（成都修茈科技有限公司 / xiu-ci.com）端侧 runner。

消费 unified_autonomy_orchestrator.py 写入的 IncidentEvent(scope=website)：
  1. 读 IncidentEvent → 校验 scope=website → 决策 action（redeploy / escalate）
  2. redeploy action：调 GitHub API `POST /repos/.../actions/workflows/corp-site-deploy.yml/dispatches`
  3. escalate action：创建 GitHub Issue with labels ["needs-human", "autonomy", "website"]
  4. 写 JSONL audit log + 自增 IncidentEvent.dispatched_count

七元契约沿用桌面端：
  Signal(IncidentEvent) → Diagnosis(decide_action) →
  Action(workflow_dispatch / create issue) →
  Policy(r3 永不 auto-merge；security/ci.failed 必升级人工) →
  Adapter(httpx → GitHub API) →
  RuntimeTruthSnapshot(JSONL audit) →
  AuditEntry(GitHub Actions run / Issue URL)。

CLI：
  python -m modstore_server.website_runner <event_id>

部署位置：modstore_server/website_runner.py（与 unified_autonomy_orchestrator.py 同级）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modstore_server.website_runner_models import ActionResult, DispatchReport

try:
    import httpx
except ImportError:  # pragma: no cover - 测试环境可能未装 httpx
    httpx = None  # type: ignore[assignment]


GITHUB_API = "https://api.github.com"

# 官网部署 workflow 文件名（与 .github/workflows/corp-site-deploy.yml 一致）
CORP_SITE_DEPLOY_WORKFLOW_FILE = "corp-site-deploy.yml"

# event_type → action 映射
ACTION_REDEPLOY_EVENTS = {
    "corp_site_down",
    "website_down",
    "health_down",
    "on_health_down",
    "website.partial_down",
}
ACTION_ESCALATE_EVENTS = {
    "security.alert",
    "ci.failed",
    "on_quality_fail",
    "incident.unknown",
}


# =====================================================================
# GitHub API 适配
# =====================================================================


def _gh_headers(token: str | None = None) -> dict[str, str]:
    """GitHub API 标准请求头。"""
    token = token or os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _resolve_repo(token: str | None = None) -> str:
    """从 GITHUB_REPOSITORY env 解析 owner/repo（如 42433422/XCMAX）。"""
    return os.environ.get("GITHUB_REPOSITORY", "").strip()


def action_redeploy_via_workflow_dispatch(
    *,
    workflow_file: str = CORP_SITE_DEPLOY_WORKFLOW_FILE,
    ref: str = "main",
    inputs: dict[str, Any] | None = None,
    repo: str | None = None,
    token: str | None = None,
    client: Any = None,
    timeout: float = 15.0,
) -> ActionResult:
    """触发 corp-site-deploy.yml 重跑（GitHub workflow_dispatch）。

    Returns ActionResult（detail 含 dispatch_url 便于追溯）。
    """
    started = datetime.now(timezone.utc)
    repo = repo or _resolve_repo(token)
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo:
        return ActionResult(
            action="redeploy",
            ok=False,
            detail="GITHUB_REPOSITORY env missing",
        )
    if not token:
        return ActionResult(
            action="redeploy",
            ok=False,
            detail="GITHUB_TOKEN env missing",
        )
    if httpx is None and client is None:
        return ActionResult(
            action="redeploy",
            ok=False,
            detail="httpx unavailable",
        )

    url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    body: dict[str, Any] = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    close_after = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        close_after = True
    try:
        resp = client.post(url, headers=_gh_headers(token), json=body)
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        if resp.status_code in (200, 204):
            return ActionResult(
                action="redeploy",
                ok=True,
                detail=f"workflow_dispatch accepted: {url}",
                response_excerpt=f"status={resp.status_code}",
                duration_ms=duration,
            )
        return ActionResult(
            action="redeploy",
            ok=False,
            detail=f"non-2xx status={resp.status_code}",
            response_excerpt=resp.text[:500],
            duration_ms=duration,
        )
    except Exception as exc:  # noqa: BLE001 - fail-soft 转 ActionResult
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        return ActionResult(
            action="redeploy",
            ok=False,
            detail=f"http error: {exc!r}",
            duration_ms=duration,
        )
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - pragma: no cover
                pass


def action_escalate_to_human(
    *,
    title: str,
    body: str,
    labels: list[str] | None = None,
    repo: str | None = None,
    token: str | None = None,
    client: Any = None,
    timeout: float = 15.0,
) -> ActionResult:
    """创建 GitHub Issue 升级到人工（labels 默认 needs-human/autonomy/website）。"""
    started = datetime.now(timezone.utc)
    repo = repo or _resolve_repo(token)
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo:
        return ActionResult(
            action="escalate",
            ok=False,
            detail="GITHUB_REPOSITORY env missing",
        )
    if not token:
        return ActionResult(
            action="escalate",
            ok=False,
            detail="GITHUB_TOKEN env missing",
        )
    if httpx is None and client is None:
        return ActionResult(
            action="escalate",
            ok=False,
            detail="httpx unavailable",
        )

    labels = labels if labels is not None else ["needs-human", "autonomy", "website"]
    url = f"{GITHUB_API}/repos/{repo}/issues"
    payload = {"title": title, "body": body, "labels": labels}
    close_after = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        close_after = True
    try:
        resp = client.post(url, headers=_gh_headers(token), json=payload)
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        if resp.status_code in (200, 201):
            try:
                data = resp.json()
                issue_number = data.get("number")
                issue_url = data.get("html_url")
                return ActionResult(
                    action="escalate",
                    ok=True,
                    detail=f"issue #{issue_number} created",
                    response_excerpt=f"issue_url={issue_url}",
                    duration_ms=duration,
                )
            except Exception as exc:  # noqa: BLE001 - 解析失败但 2xx，记为 partial
                return ActionResult(
                    action="escalate",
                    ok=True,
                    detail=f"issue created but json parse failed: {exc!r}",
                    response_excerpt=resp.text[:300],
                    duration_ms=duration,
                )
        return ActionResult(
            action="escalate",
            ok=False,
            detail=f"non-2xx status={resp.status_code}",
            response_excerpt=resp.text[:500],
            duration_ms=duration,
        )
    except Exception as exc:  # noqa: BLE001 - fail-soft 转 ActionResult
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        return ActionResult(
            action="escalate",
            ok=False,
            detail=f"http error: {exc!r}",
            duration_ms=duration,
        )
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - pragma: no cover
                pass


# =====================================================================
# 决策核心
# =====================================================================


def decide_action(event_type: str) -> str:
    """event_type → action 映射。

    - ACTION_REDEPLOY_EVENTS: 重跑 corp-site-deploy.yml
    - ACTION_ESCALATE_EVENTS: 升级到人工（创建 GitHub Issue）
    - 其他：默认 escalate（fail-safe：未知事件升级人工）
    """
    if event_type in ACTION_REDEPLOY_EVENTS:
        return "redeploy"
    if event_type in ACTION_ESCALATE_EVENTS:
        return "escalate"
    # 未知 event_type 默认升级人工（fail-safe：未知事件让人决定）
    return "escalate"


# =====================================================================
# 主入口
# =====================================================================


def _write_audit(report: DispatchReport, audit_dir: Path) -> Path | None:
    """把 DispatchReport 追加写到 JSONL audit。"""
    if not audit_dir.exists():
        try:
            audit_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[website-runner] audit dir mkdir failed: {exc!r}", file=sys.stderr)
            return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    audit_file = audit_dir / f"website_dispatch_{ts}.jsonl"
    try:
        with audit_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[website-runner] audit write failed: {exc!r}", file=sys.stderr)
        return None
    return audit_file


def dispatch_incident(event_id: int) -> DispatchReport:
    """主入口：读 IncidentEvent → 校验 scope=website → 决策 → 执行 → 写 audit + 自增计数。

    失败模式（fail-soft，不抛异常）：
    - incident_not_found → 返回 ok=False report
    - scope 不匹配 → 返回 action=skip, ok=True report（不应被 website_runner 处理）
    - GitHub API 调用失败 → 返回 ok=False report，但 audit 已写
    """
    from modstore_server.models import IncidentEvent, get_session_factory

    started = datetime.now(timezone.utc)
    sf = get_session_factory()
    with sf() as session:
        ev = session.query(IncidentEvent).filter(IncidentEvent.id == int(event_id)).first()
        if not ev:
            return DispatchReport(
                event_id=int(event_id),
                event_type="",
                scope="",
                action="skip",
                ok=False,
                reason="incident_not_found",
                started_at=started.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        try:
            payload = json.loads(ev.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        # _unified_orchestration payload 已由 orchestrator 注入；取其 scope
        orch = payload.get("_unified_orchestration") or {}
        scope = orch.get("scope") or payload.get("scope") or "global"
        scope = str(scope).strip().lower()

        event_type = str(ev.event_type or "").strip()
        report = DispatchReport(
            event_id=int(event_id),
            event_type=event_type,
            scope=scope,
            action="skip",
            ok=False,
            dispatched_count_before=int(ev.dispatched_count or 0),
            started_at=started.isoformat(),
        )

        # scope 不匹配 → skip（不应被 website_runner 处理）
        if scope != "website":
            report.action = "skip"
            report.ok = True
            report.reason = f"scope mismatch: expected=website, actual={scope!r}"
            report.finished_at = datetime.now(timezone.utc).isoformat()
            return report

        # 决策 + 执行
        action = decide_action(event_type)
        report.action = action

        if action == "redeploy":
            inputs = {
                "event_id": str(event_id),
                "event_type": event_type,
                "triggered_by": "website_runner",
            }
            result = action_redeploy_via_workflow_dispatch(inputs=inputs)
            report.results.append(result)
            report.ok = result.ok
            if not result.ok:
                # redeploy 失败 → fallback 升级人工
                fallback = action_escalate_to_human(
                    title=f"[autonomy] corp-site redeploy failed for event #{event_id}",
                    body=json.dumps(
                        {
                            "event_id": event_id,
                            "event_type": event_type,
                            "payload_excerpt": {
                                k: v for k, v in payload.items() if k != "_unified_orchestration"
                            },
                            "redeploy_result": (
                                result.to_dict() if hasattr(result, "to_dict") else asdict(result)
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )[:4000],
                )
                report.results.append(fallback)
                # escalate 失败时 ok=False；成功时 ok=True（已升级人工）
                report.ok = fallback.ok
        elif action == "escalate":
            # 提取失败的 surface 列表（如果有，来自 corp_site_health_probe payload）
            failed_surfaces = payload.get("failed_surfaces", [])
            base_url = payload.get("base_url", "")
            body_lines = [
                f"## Autonomy Escalation: {event_type}",
                "",
                f"- **event_id**: {event_id}",
                f"- **scope**: {scope}",
                f"- **base_url**: {base_url}",
                f"- **failed_surfaces**: {len(failed_surfaces)}",
            ]
            if failed_surfaces:
                body_lines.append("")
                body_lines.append("### Failed Surfaces")
                for s in failed_surfaces[:10]:
                    body_lines.append(
                        f"- {s.get('name', '?')} @ {s.get('url', '?')} "
                        f"(status={s.get('status')}, error={s.get('error', '')[:200]!r})"
                    )
            body_lines.append("")
            body_lines.append("### Payload Excerpt")
            body_lines.append("```json")
            body_lines.append(
                json.dumps(
                    {k: v for k, v in payload.items() if k != "_unified_orchestration"},
                    ensure_ascii=False,
                    indent=2,
                )[:3000]
            )
            body_lines.append("```")
            result = action_escalate_to_human(
                title=f"[autonomy] website incident: {event_type} (event #{event_id})",
                body="\n".join(body_lines),
            )
            report.results.append(result)
            report.ok = result.ok
        else:
            # 不应到达（decide_action 只返回 redeploy/escalate）
            report.ok = False
            report.reason = f"unknown action: {action!r}"

        # 自增 dispatched_count
        ev.dispatched_count = int(ev.dispatched_count or 0) + 1
        report.dispatched_count_after = ev.dispatched_count
        session.commit()

        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report


def _audit_dir_from_env() -> Path:
    """audit dir 解析优先级：env WEBSITE_RUNNER_AUDIT_DIR > /opt/fhd-full/autonomy > /tmp/website_runner_audit"""
    return Path(os.environ.get("WEBSITE_RUNNER_AUDIT_DIR") or "/opt/fhd-full/autonomy")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="企业官网端侧 runner")
    parser.add_argument("event_id", type=int, help="IncidentEvent.id")
    parser.add_argument(
        "--audit-dir",
        default=None,
        help="JSONL audit 目录（默认 env WEBSITE_RUNNER_AUDIT_DIR 或 /opt/fhd-full/autonomy）",
    )
    args = parser.parse_args(argv)

    report = dispatch_incident(args.event_id)
    audit_dir = Path(args.audit_dir) if args.audit_dir else _audit_dir_from_env()
    audit_file = _write_audit(report, audit_dir)

    print(
        f"[website-runner] event_id={report.event_id} "
        f"scope={report.scope} action={report.action} ok={report.ok} "
        f"reason={report.reason!r}"
    )
    for r in report.results:
        print(f"[website-runner]   {r.action} ok={r.ok} detail={r.detail!r}")

    if audit_file:
        print(f"[website-runner] audit: {audit_file}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
