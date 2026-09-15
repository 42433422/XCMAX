#!/usr/bin/env python3
"""连接件5（知识回流）：把闭环三件套沉淀为可检索案例，并回流消费。

记录：诊断（连接件2）+ 复现规格（连接件3）+ 客户侧重测回执（连接件4）
→ 一条结构化案例，落 test_reports/knowledge/cases.jsonl（append-only，
同 dedup_key 幂等替换——闭环重开重测后案例更新而非新增）。

检索：按故障签名（tool/code）规则匹配历史案例，供连接件2 诊断时直接给出
「历史同类案例与当时修复」，无 LLM、零延迟；未命中自然为空。

关闭：记录成功后复用工单状态机 record_transition 推进 verifying→closed
（非法迁移 fail-open 不阻塞）；可选 --close-issue 同步关闭 GitHub 工单。

用法：
    python scripts/dev/work_order_knowledge.py --record <dedup_key> [--close-issue 12]
    python scripts/dev/work_order_knowledge.py --search "tool:code"
    python scripts/dev/work_order_knowledge.py --list
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("work_order_knowledge")

_FHD_ROOT = Path(__file__).resolve().parents[2]


def _knowledge_path() -> Path:
    root = Path(
        os.environ.get("WORK_ORDER_KNOWLEDGE_DIR")
        or (_FHD_ROOT / "test_reports" / "knowledge")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / "cases.jsonl"


_KB_LOCK = threading.Lock()


def _diagnosis_path(dedup_key: str) -> Path:
    d = Path(
        os.environ.get("WORK_ORDER_DIAGNOSIS_DIR")
        or (_FHD_ROOT / "test_reports" / "diagnosis")
    )
    return d / f"diagnosis-{str(dedup_key)[:12]}.json"


def _repro_path(dedup_key: str) -> Path:
    d = Path(
        os.environ.get("WORK_ORDER_REPRO_DIR")
        or (_FHD_ROOT / "test_reports" / "repro")
    )
    return d / f"repro-{str(dedup_key)[:12]}.json"


def _retest_path(dedup_key: str) -> Path:
    d = Path(
        os.environ.get("WORK_ORDER_RETEST_DIR")
        or (_FHD_ROOT / "test_reports" / "retest")
    )
    return d / f"receipt-{str(dedup_key)[:12]}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def compose_case(dedup_key: str) -> dict[str, Any] | None:
    """组合三件套为一条知识案例；诊断缺失返回 None（无签名即无案例价值）。"""
    key = str(dedup_key or "")[:64]
    if not key:
        return None
    diagnosis = _read_json(_diagnosis_path(key))
    if not diagnosis:
        return None
    errors = diagnosis.get("errors") or []
    fixes = diagnosis.get("fixes") or []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    repro = _read_json(_repro_path(key)) or {}
    retest = _read_json(_retest_path(key)) or {}
    return {
        "dedup_key": key,
        "wo_id": str(diagnosis.get("wo_id") or ""),
        "recorded_at": datetime.now(UTC).isoformat(),
        "signature": {
            "tool": str(first_error.get("tool") or ""),
            "code": str(first_error.get("code") or ""),
            "file": str(first_error.get("file_path") or first_error.get("file") or ""),
            "line": first_error.get("line"),
        },
        "engine": str(diagnosis.get("engine") or ""),
        "fix_description": str(
            (fixes[0].get("description") if fixes and isinstance(fixes[0], dict) else "")
            or ""
        ),
        "repro": {
            "kind": str(repro.get("kind") or ""),
            "status": str(repro.get("status") or ""),
            "path": str(_repro_path(key)),
        },
        "retest": {
            "verdict": str(retest.get("verdict") or "pending"),
            "app_version": str(retest.get("app_version") or ""),
            "path": str(_retest_path(key)) if retest else "",
        },
        "diagnosis_path": str(_diagnosis_path(key)),
    }


def upsert_case(case: dict[str, Any]) -> int:
    """按 dedup_key 幂等写入案例文件，返回总案例数。"""
    path = _knowledge_path()
    with _KB_LOCK:
        cases: list[dict[str, Any]] = []
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8") or "[]")
                if isinstance(loaded, list):
                    cases = [c for c in loaded if isinstance(c, dict)]
            except json.JSONDecodeError:
                cases = []
        key = str(case.get("dedup_key") or "")
        cases = [c for c in cases if str(c.get("dedup_key") or "") != key]
        cases.append(case)
        path.write_text(
            json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return len(cases)


def load_cases() -> list[dict[str, Any]]:
    path = _knowledge_path()
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    return [c for c in loaded if isinstance(c, dict)] if isinstance(loaded, list) else []


def search_cases(tool: str = "", code: str = "") -> list[dict[str, Any]]:
    """按故障签名规则匹配历史案例（最新优先，最多 5 条）。"""
    tool, code = tool.strip(), code.strip()
    hits: list[dict[str, Any]] = []
    for case in reversed(load_cases()):
        sig = case.get("signature") or {}
        if tool and str(sig.get("tool") or "") != tool:
            continue
        if code and str(sig.get("code") or "") != code:
            continue
        if not tool and not code:
            continue
        hits.append(case)
        if len(hits) >= 5:
            break
    return hits


def close_work_order(wo_id: str) -> bool:
    """重测通过后推进状态机 verifying→closed；非法迁移/远端不可达 fail-open。"""
    try:
        from app.services.work_order_ssot import record_transition

        res = record_transition(
            wo_id,
            "closed",
            note="customer retest pass (connector-4); knowledge case recorded",
            source="customer_retest",
        )
        logger.info("work order transition: %s", res)
        return bool(res.get("ok"))
    except Exception:  # noqa: BLE001 - 状态机不可达不阻塞知识回流
        logger.debug("work order transition skipped", exc_info=True)
        return False


def close_github_issue(issue_number: int, case: dict[str, Any]) -> bool:
    """关闭工单 issue（对外观测载体）；失败不阻塞。"""
    body = (
        "## 客户问题闭环关闭（连接件5，自动）\n"
        f"- 客户侧重测: **pass**（版本 `{case.get('retest', {}).get('app_version') or 'unknown'}`）\n"
        f"- 故障签名: `[{case.get('signature', {}).get('tool')}:{case.get('signature', {}).get('code')}]`\n"
        f"- 知识案例: 已沉淀到本地案例库（`test_reports/knowledge/cases.jsonl`）\n"
        "- 后续同类故障诊断将自动引用本案例（连接件2 消费回流）。\n"
    )
    try:
        completed = subprocess.run(
            ["gh", "issue", "close", str(issue_number), "--comment", body],
            cwd=str(_FHD_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run(args: argparse.Namespace) -> int:
    if args.search is not None:
        tool, _, code = str(args.search).partition(":")
        for case in search_cases(tool, code):
            sig = case.get("signature") or {}
            print(
                f"{case.get('wo_id')} [{sig.get('tool')}:{sig.get('code')}] "
                f"{case.get('fix_description') or '(no fix description)'}"
            )
        return 0
    if args.list:
        for case in load_cases():
            print(case.get("wo_id"), case.get("dedup_key", "")[:12], case.get("recorded_at"))
        return 0
    key = str(args.record or "")
    case = compose_case(key)
    if case is None:
        logger.error("no diagnosis for %s; nothing to record", key[:12])
        return 1
    total = upsert_case(case)
    logger.info("knowledge case recorded: %s (total=%d)", case["wo_id"], total)
    if case["retest"]["verdict"] == "pass" and case["wo_id"]:
        close_work_order(case["wo_id"])
    if args.close_issue:
        ok = close_github_issue(int(args.close_issue), case)
        logger.info("issue close: %s", "done" if ok else "failed (non-blocking)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", default="", help="按 dedup_key 组合并写入知识案例")
    parser.add_argument("--search", default=None, help='按 "tool:code" 检索历史案例')
    parser.add_argument("--list", action="store_true", help="列出全部案例")
    parser.add_argument("--close-issue", default="", help="记录后关闭指定 GitHub issue")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
