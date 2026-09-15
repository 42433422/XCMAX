# mypy: disable-error-code="no-any-return"
"""读取 capability_proposal.jsonl → 创建受控 GitHub 治理 issue。

CI 用法（在 capability-proposal-to-issue.yml workflow 中）:
    python scripts/dev/capability_proposal_to_issue.py \\
        --repo "$GITHUB_REPOSITORY" \\
        --token "$GITHUB_TOKEN" \\
        --max-issues 5 \\
        --apply

本地 dry-run:
    python scripts/dev/capability_proposal_to_issue.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 通过 sys.path 注入让脚本能 import app.services.capability_proposal_recorder
_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from app.services.capability_proposal_recorder import (  # noqa: E402  pylint: disable=wrong-import-position
    list_pending_proposals,
    mark_proposals_processed,
)
from app.services.work_order_ssot import (
    classify_track,  # noqa: E402  pylint: disable=wrong-import-position
    derive_wo_id,  # noqa: E402  pylint: disable=wrong-import-position
)
from app.utils.operational_errors import (  # noqa: E402  pylint: disable=wrong-import-position
    BOUNDARY_ERRORS,
)


def _derive_wo_id(source: str, dedup_key: str) -> str:
    """由去重键派生唯一工单 ID（source 仅归属，不参与散列，跨入口同单）。"""
    if not str(dedup_key or "").strip():
        return ""
    return derive_wo_id(str(dedup_key).strip())


def _build_acceptance_criteria(
    reason: str, intent_ctx: dict[str, Any], skill_ctx: dict[str, Any]
) -> str:
    """从提案上下文模板化生成可验证验收标准（无 LLM，可机器核对）。"""
    criteria = [
        "同类用户输入不再落入 capability_proposal 未命中队列（意图基准回归通过）",
        "新增能力按预期完成意图识别与槽位校验，全流程本地测试通过",
        "既有意图识别无回归（intent benchmark 棘轮不下降）",
        "发布后 macOS 与 Windows 客户机安装回执均为 installed，无未解决 failed/rolled_back",
    ]
    candidate_slots = skill_ctx.get("candidate_slots") or []
    if candidate_slots:
        criteria.insert(1, f"必需槽位 {', '.join(candidate_slots)} 缺失时正确追问")
    if not intent_ctx.get("classifier_fields_present"):
        criteria.append("意图分类器对该类输入产出稳定 primary_intent")
    _ = reason
    return "\n".join(f"- [ ] {item}" for item in criteria) + "\n\n"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_post(url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_gh_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}


def _gh_get(url: str, token: str) -> Any:
    req = urllib.request.Request(url, headers=_gh_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}


def _gh_api_find_existing(repo: str, title: str, token: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"q": f'repo:{repo} is:issue in:title "{title}"'})
    response = _gh_get(f"https://api.github.com/search/issues?{query}", token)
    if isinstance(response, dict) and response.get("_error"):
        return response
    items = response.get("items") if isinstance(response, dict) else []
    for item in items or []:
        if isinstance(item, dict) and item.get("title") == title:
            return {"html_url": item.get("html_url") or ""}
    return {}


def _gh_cli_create(repo: str, title: str, body: str, labels: list[str]) -> dict[str, Any]:
    """使用本机已认证 gh 创建 issue，供本地调度中继使用。"""
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"_error": "gh_cli_failed", "_body": str(exc)}
    if result.returncode != 0:
        return {"_error": result.returncode, "_body": result.stderr}
    return {"html_url": result.stdout.strip()}


def _gh_cli_find_existing(repo: str, title: str) -> dict[str, Any]:
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--search",
        f'"{title}" in:title',
        "--json",
        "title,url",
        "--limit",
        "10",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"_error": "gh_cli_failed", "_body": str(exc)}
    if result.returncode != 0:
        return {"_error": result.returncode, "_body": result.stderr}
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return {"_error": "gh_cli_invalid_json", "_body": result.stdout[:300]}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("title") == title:
            return {"html_url": row.get("url") or ""}
    return {}


def _is_actionable_skill_proposal(proposal: dict[str, Any]) -> bool:
    """仅接受新技能路由器产出的结构化提案，拒绝历史 ``intent_unknown`` 噪音。"""
    context = proposal.get("context")
    skill = context.get("skill_proposal") if isinstance(context, dict) else None
    return bool(
        proposal.get("reason") == "skill_proposal"
        and isinstance(skill, dict)
        and str(skill.get("proposed_skill_id") or "").strip()
        and str(skill.get("status") or "").strip() == "proposed"
    )


def _build_diagnosis_section(dedup_key: str) -> str:
    """连接件2：存在证据包诊断文件时，把结构化诊断写入 issue 正文。

    只输出错误签名与修复建议（工单外观载体），不含用户原文与日志原文；
    文件缺失/损坏时返回空串，绝不阻塞建单。
    """
    key = str(dedup_key or "")[:12]
    if not key:
        return ""
    diag_dir = Path(
        os.environ.get("WORK_ORDER_DIAGNOSIS_DIR") or (_FHD_ROOT / "test_reports" / "diagnosis")
    )
    path = diag_dir / f"diagnosis-{key}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(record, dict):
        return ""
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    lines = [
        "## 自动诊断（证据包驱动，连接件2）\n",
        f"- **诊断引擎**: `{record.get('engine') or 'none'}`",
        f"- **证据包完整**: `{evidence.get('intact')}`（SHA256 校验见诊断文件）",
        f"- **证据包状态**: `{record.get('status') or 'analyzed'}`",
    ]
    errors = record.get("errors") or []
    if errors:
        lines.append(f"- **错误签名（前 {len(errors[:10])} 条）**:")
        for e in errors[:10]:
            if isinstance(e, dict):
                lines.append(
                    f"  - `[{e.get('tool')}:{e.get('code')}]` "
                    f"`{e.get('file_path')}:{e.get('line')}` {e.get('message')}"
                )
    fixes = record.get("fixes") or []
    if fixes:
        lines.append(f"- **建议修复（前 {len(fixes[:10])} 条）**:")
        for f in fixes[:10]:
            if isinstance(f, dict):
                lines.append(
                    f"  - `[risk={f.get('risk_level')}]` {f.get('description')}"
                    f"（needs_human={f.get('needs_human')}）"
                )
    return "\n".join(lines) + "\n\n"


def _build_repro_section(dedup_key: str) -> str:
    """连接件3：存在复现规格时，把自动复现场景写入 issue 正文。

    供实现 agent 在修复 PR 中包含/更新可执行复现用例；文件缺失时返回空串。
    """
    key = str(dedup_key or "")[:12]
    if not key:
        return ""
    repro_dir = Path(
        os.environ.get("WORK_ORDER_REPRO_DIR") or (_FHD_ROOT / "test_reports" / "repro")
    )
    path = repro_dir / f"repro-{key}.json"
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(spec, dict):
        return ""
    signature = spec.get("signature") or {}
    scenario = spec.get("scenario") or {}
    lines = [
        "## 自动复现（连接件3）\n",
        f"- **复现场景**: `{spec.get('kind')}`（status: `{spec.get('status')}`）",
    ]
    if scenario:
        lines.append(f"- **目标**: `{json.dumps(scenario, ensure_ascii=False)}`")
    if signature:
        lines.append(
            f"- **故障签名**: `[{signature.get('tool')}:{signature.get('code')}]` "
            f"`{signature.get('file')}:{signature.get('line')}`"
        )
    if spec.get("status") == "needs_scenario":
        lines.append(
            "- **要求**: 修复 PR 必须附带可执行复现用例（先 RED 后 GREEN），并在 PR 描述留证。"
        )
    return "\n".join(lines) + "\n\n"


def _build_retest_section(dedup_key: str) -> str:
    """连接件4：存在客户侧重测回执时，把重测判定写入 issue 正文。

    回执由 scripts/dev/customer_retest.py 在客户机上产出（健康/版本/场景三查）；
    文件缺失时返回空串——发布验收回执仍由既有 release-acceptance-closeout 闭环承载。
    """
    key = str(dedup_key or "")[:12]
    if not key:
        return ""
    retest_dir = Path(
        os.environ.get("WORK_ORDER_RETEST_DIR") or (_FHD_ROOT / "test_reports" / "retest")
    )
    path = retest_dir / f"receipt-{key}.json"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(receipt, dict):
        return ""
    lines = [
        "## 客户侧重测（连接件4）\n",
        f"- **判定**: **{receipt.get('verdict')}**（应用版本 `{receipt.get('app_version') or 'unknown'}`）",
        f"- **基址**: `{receipt.get('base_url')}` · 时间 `{receipt.get('checked_at')}`",
    ]
    for check in receipt.get("checks") or []:
        if isinstance(check, dict):
            lines.append(
                f"- {'PASS' if check.get('ok') else 'FAIL'} `{check.get('name')}` "
                f"(status {check.get('status', '-')})"
            )
    return "\n".join(lines) + "\n\n"


def _build_issue_body(proposal: dict[str, Any]) -> str:
    reason = proposal.get("reason") or "intent_unknown"
    ts = proposal.get("ts") or ""
    ctx = proposal.get("context") or {}
    intent_ctx = ctx.get("intent_result") or {}
    skill_ctx = ctx.get("skill_proposal") or {}

    def safe_name(value: Any) -> str:
        text = str(value or "")
        return text if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", text) else ""

    slot_names = [
        name
        for name in (safe_name(value) for value in (intent_ctx.get("slot_names") or []))
        if name
    ]
    candidate_slots = [
        name
        for name in (safe_name(value) for value in (skill_ctx.get("candidate_slots") or []))
        if name
    ]
    safe_intent_ctx = {
        "classifier_fields_present": [
            key
            for key in ("primary_intent", "tool_key", "deepseek_intent")
            if intent_ctx.get(key) is not None
        ],
        "slot_names": slot_names,
    }
    rationale = str(skill_ctx.get("rationale") or "")
    safe_skill_ctx = {
        "candidate_slots": candidate_slots,
        "rationale": (
            rationale if rationale == "classifier_miss_or_low_confidence" else "unspecified"
        ),
        "status": "proposed",
    }
    dedup_key = str(proposal.get("dedup_key") or "")
    source = str(proposal.get("source") or "intent_confirmation_service")
    wo_id = _derive_wo_id(source, dedup_key)

    return (
        "## 来源：能力提案 (capability_proposal)\n\n"
        f"- **工单 ID (Work Order SSOT)**: `{wo_id}`\n"
        f"- **分流轨道（统一 Router）**: `{_classify_proposal_track(proposal)}`"
        "（ops_support 运维支持 / product_line 通用产品线 / industry_mod 行业 Mod / customer_custom 单客户定制）\n"
        f"- **未命中时间**: `{ts}`\n"
        f"- **未命中原因**: `{reason}`\n"
        f"- **来源**: `{proposal.get('source') or '-'}`\n\n"
        f"- **本地去重引用**: `{dedup_key}`\n\n"
        "## 结构化上下文（已移除用户原文和槽位值）\n\n```json\n"
        f"{json.dumps({'intent': safe_intent_ctx, 'skill': safe_skill_ctx}, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        f"{_build_diagnosis_section(dedup_key)}"
        f"{_build_repro_section(dedup_key)}"
        f"{_build_retest_section(dedup_key)}"
        "## 验收标准（进入 AI 开发前必须可验证）\n\n"
        f"{_build_acceptance_criteria(reason, safe_intent_ctx, safe_skill_ctx)}\n"
        "## 治理门禁\n\n"
        "1. 本 issue 只登记能力缺口，不直接触发任意代码生成。\n"
        "2. 用户原文与槽位值留在本地，不写入 GitHub。\n"
        "3. 先确认能力边界、风险、验收与回滚；满足受控实现策略后再进入实现队列。\n"
        "4. 实现、审核、合并、上架和部署收据必须分别留证。\n"
        "5. 仓库所有者确认后，单独评论 `确认实现` 或 `/approve-implementation`；"
        "系统将显式派发实现工作流，批准本身不能直接合并代码。\n"
        "6. CI 通过 ≠ 客户能用：发布后须 macOS 与 Windows 客户机安装回执双平台健康，"
        "方可验收关闭；任一平台失败自动重开本 issue，不另起新单。\n"
    )


def _build_issue_title(proposal: dict[str, Any]) -> str:
    dedup_key = str(proposal.get("dedup_key") or "unknown")[:12]
    return f"[capability-proposal] 新能力候选 {dedup_key}"


def _parse_issue_number(issue_url: str) -> int:
    """从 issue URL 解析编号（gh cli 创建只回 URL）。"""
    match = re.search(r"/issues/(\d+)", str(issue_url or ""))
    return int(match.group(1)) if match else 0


def _classify_proposal_track(proposal: dict[str, Any]) -> str:
    """统一 Router：按提案信号确定四类去向（确定性规则，见 work_order_ssot）。"""
    ctx = proposal.get("context") if isinstance(proposal.get("context"), dict) else {}
    return classify_track(
        source=str(proposal.get("source") or ""),
        reason=str(proposal.get("reason") or ""),
        context=ctx,
    )


def _link_work_order(
    proposal: dict[str, Any], issue_url: str, issue_number: int = 0, track: str = ""
) -> None:
    """主线接线：issue 创建/调和后把工单推进到 routed（候选期终点）。

    工单写入失败不阻塞 issue 流程 —— issue 本身是对外观测载体。
    """
    key = str(proposal.get("dedup_key") or "").strip()
    if not key:
        return
    source = str(proposal.get("source") or "intent_confirmation_service")
    number = int(issue_number or 0) or _parse_issue_number(issue_url)
    try:
        from app.services.work_order_ssot import link_issue, upsert_candidate

        upsert_candidate(
            source=source,
            dedup_key=key,
            reason=str(proposal.get("reason") or ""),
            context=proposal.get("context") if isinstance(proposal.get("context"), dict) else None,
        )
        link_issue(
            derive_wo_id(key),
            issue_number=number,
            issue_url=str(issue_url or ""),
            track=str(track or ""),
        )
    except BOUNDARY_ERRORS:  # noqa: BLE001 - CI/中继边界兜底，不影响 issue 流程
        logger.debug("work_order link skipped", exc_info=True)


def _mark_verified(
    keys: list[str],
    *,
    disposition: str,
    issue_urls: dict[str, str] | None = None,
) -> bool:
    if not keys:
        return True
    mark_proposals_processed(keys, disposition=disposition, issue_urls=issue_urls)
    pending_keys = {str(row.get("dedup_key") or "") for row in list_pending_proposals()}
    return not (set(keys) & pending_keys)


def _ensure_diagnoses(actionable: list[dict[str, Any]]) -> None:
    """连接件2（自动诊断编排）：建单前对带证据包引用的提案产出结构化诊断。

    复用 work_order_diagnose（其复用 ai_self_heal 提取/规则件）；fail-open：
    诊断模块缺失、无证据、单条失败都不阻塞建单。CI 兜底环境无证据包时自然 no-op。
    """
    if not any(isinstance(p.get("evidence_ref"), dict) for p in actionable):
        return
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "work_order_diagnose", Path(__file__).with_name("work_order_diagnose.py")
        )
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules["work_order_diagnose"] = module
        spec.loader.exec_module(module)
        module.main(
            [
                "--max",
                os.environ.get("WORK_ORDER_DIAGNOSIS_MAX", "20"),
                *(["--llm"] if os.environ.get("WORK_ORDER_DIAGNOSIS_LLM") == "1" else []),
            ]
        )
        # 连接件3：诊断产出后立即生成自动复现场景（嵌入 issue 供实现/重测复用）
        repro_spec = importlib.util.spec_from_file_location(
            "work_order_repro", Path(__file__).with_name("work_order_repro.py")
        )
        if repro_spec is not None and repro_spec.loader is not None:
            repro_module = importlib.util.module_from_spec(repro_spec)
            sys.modules["work_order_repro"] = repro_module
            repro_spec.loader.exec_module(repro_module)
            repro_module.main(["--max", os.environ.get("WORK_ORDER_DIAGNOSIS_MAX", "20")])
    except BOUNDARY_ERRORS:  # 插件隔离边界：动态加载执行诊断/复现链，失败不阻塞建单
        logger.debug("evidence diagnosis skipped", exc_info=True)


def run(args: argparse.Namespace) -> int:
    pending = list_pending_proposals()
    if not pending:
        logger.info("no pending capability_proposal")
        return 0

    ignored = [row for row in pending if not _is_actionable_skill_proposal(row)]
    actionable = [row for row in pending if _is_actionable_skill_proposal(row)]
    limited = actionable[: args.max_issues]
    logger.info("pending=%d processing=%d", len(pending), len(limited))

    if args.dry_run:
        logger.info("[dry-run] would ignore non-actionable=%d", len(ignored))
        for p in limited:
            logger.info(
                "[dry-run] would create issue: title=%s",
                _build_issue_title(p),
            )
        return 0

    if not args.repo:
        logger.error("--repo required for apply mode")
        return 1
    if not args.token and not args.gh_cli:
        logger.error("--token or --gh-cli required for apply mode")
        return 1

    # 连接件2：带证据包引用的提案先产出结构化诊断，供 issue 正文嵌入
    _ensure_diagnoses(actionable)

    ignored_keys = [str(row.get("dedup_key") or "") for row in ignored]
    if not _mark_verified(ignored_keys, disposition="ignored_non_skill_proposal"):
        logger.error("failed to persist ignored proposal receipts")
        return 1

    created_keys: list[str] = []
    reconciled_keys: list[str] = []
    issue_urls: dict[str, str] = {}
    created_count = 0
    base_labels = ["capability-proposal", "auto-generated", "needs-human"]
    for proposal in limited:
        # 统一 Router：四类去向轨道随 issue 标签对观察者可查
        track = _classify_proposal_track(proposal)
        labels = [*base_labels, f"track:{track}"]
        body = _build_issue_body(proposal)
        title = _build_issue_title(proposal)
        existing = (
            _gh_cli_find_existing(args.repo, title)
            if args.gh_cli
            else _gh_api_find_existing(args.repo, title, args.token)
        )
        if existing.get("_error"):
            logger.error("issue dedupe lookup failed: %s", existing.get("_error"))
            return 1
        if existing.get("html_url"):
            key = str(proposal.get("dedup_key") or "")
            reconciled_keys.append(key)
            issue_urls[key] = str(existing["html_url"])
            logger.info("existing issue reconciled: %s", existing["html_url"])
            continue
        if args.gh_cli:
            resp = _gh_cli_create(args.repo, title, body, labels)
        else:
            resp = _gh_post(
                f"https://api.github.com/repos/{args.repo}/issues",
                args.token,
                {"title": title, "body": body, "labels": labels},
            )
        if resp.get("_error"):
            logger.error(
                "create issue failed: status=%s body=%s",
                resp.get("_error"),
                (resp.get("_body") or "")[:300],
            )
            continue
        issue_url = resp.get("html_url") or ""
        issue_number = resp.get("number") or 0
        logger.info("issue created: #%s %s", issue_number, issue_url)
        key = str(proposal.get("dedup_key") or "")
        created_keys.append(key)
        issue_urls[key] = str(issue_url)
        _link_work_order(proposal, str(issue_url), int(issue_number or 0), track)
        created_count += 1

    if created_keys:
        if not _mark_verified(
            created_keys,
            disposition="issue_created",
            issue_urls=issue_urls,
        ):
            logger.error("issue created but processed receipt was not durable")
            return 1
    if reconciled_keys and not _mark_verified(
        reconciled_keys,
        disposition="issue_reconciled",
        issue_urls=issue_urls,
    ):
        logger.error("existing issue found but reconciliation receipt was not durable")
        return 1
    logger.info("done: created=%d/%d", created_count, len(limited))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="capability_proposal → GitHub issue")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--max-issues", type=int, default=5, help="单次最多创建 issue 数")
    parser.add_argument("--gh-cli", action="store_true", help="使用本机已认证 gh")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(args))


if __name__ == "__main__":
    main()
