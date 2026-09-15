#!/usr/bin/env python3
"""连接件2（自动诊断编排）：工单证据包 → 结构化诊断 → 供中继写入 issue。

复用 scripts/ci/ai_self_heal.py 的七元契约件（Signal→Diagnosis→Action→Policy
→Adapter→RuntimeTruthSnapshot→AuditEntry），把「CI 日志自愈」同一套
提取/规则匹配/LLM 兜底接到客户工单上：

    python scripts/dev/work_order_diagnose.py --llm --force

- 输入：capability_proposal.jsonl 中带 evidence_ref（连接件1 产物）的提案
- 证据：support bundle ZIP（本地路径 + SHA256 校验；CI 无证据时自然 no-op）
- 输出：test_reports/diagnosis/diagnosis-<dedup_key[:12]>.json
  （不含用户原文/槽位值，遵守「用户原文留在本地」治理门禁；日志本身已脱敏）
- 中继：capability_proposal_to_issue 读取该 JSON 把「自动诊断」节写入 issue，
  经既有 fhd-ai-issue-implement 派发实现——本脚本不新建任何派发通道。

fail-open：单条提案失败不影响其余；LLM 不可用降级为规则匹配结果。
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import logging
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("work_order_diagnose")

_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from app.services.capability_proposal_recorder import (  # noqa: E402
    list_pending_proposals,
)
from app.services.work_order_ssot import derive_wo_id  # noqa: E402

_DIAGNOSIS_DIR = Path(
    os.environ.get("WORK_ORDER_DIAGNOSIS_DIR")
    or (_FHD_ROOT / "test_reports" / "diagnosis")
)


def _load_self_heal() -> Any:
    """复用 CI 自愈的提取/规则/LLM 件（与 tests 的 _load_script 同款约定）。"""
    path = _FHD_ROOT / "scripts" / "ci" / "ai_self_heal.py"
    spec = importlib.util.spec_from_file_location("ai_self_heal", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ai_self_heal", module)
    spec.loader.exec_module(module)
    return module


def _load_knowledge() -> Any:
    """连接件5 消费侧：加载知识回流检索件（案例库缺失/损坏时 fail-open）。"""
    path = _FHD_ROOT / "scripts" / "dev" / "work_order_knowledge.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("work_order_knowledge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("work_order_knowledge", module)
    spec.loader.exec_module(module)
    return module


def _attach_known_cases(record: dict[str, Any]) -> None:
    """把历史同类案例（同 tool:code 签名）附进诊断，知识回流消费入口。"""
    errors = record.get("errors") or []
    if not errors:
        return
    kb = _load_knowledge()
    if kb is None:
        return
    known: list[dict[str, Any]] = []
    seen: set[str] = set()
    for error in errors[:20]:
        if not isinstance(error, dict):
            continue
        tool, code = str(error.get("tool") or ""), str(error.get("code") or "")
        if not tool and not code:
            continue
        for case in kb.search_cases(tool, code):
            wo = str(case.get("wo_id") or "")
            if wo in seen:
                continue
            seen.add(wo)
            known.append(
                {
                    "wo_id": wo,
                    "signature": case.get("signature") or {},
                    "fix_description": str(case.get("fix_description") or ""),
                    "retest_verdict": str((case.get("retest") or {}).get("verdict") or ""),
                    "recorded_at": str(case.get("recorded_at") or ""),
                }
            )
            if len(known) >= 3:
                record["known_cases"] = known
                return
    if known:
        record["known_cases"] = known


def _verify_sha256(path: Path, expected: str) -> tuple[bool, str]:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return False, ""
    actual = digest.hexdigest()
    return (not expected) or actual == expected, actual


def _bundle_log_text(path: Path) -> str:
    """拼接 bundle 内脱敏日志文本（logs/*.log 与 updater 事件行）。"""
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if not name.startswith("logs/"):
                    continue
                try:
                    chunks.append(zf.read(name).decode("utf-8", errors="replace"))
                except (zipfile.BadZipFile, OSError):
                    continue
    except (zipfile.BadZipFile, OSError):
        return ""
    return "\n".join(c for c in chunks if c)


def diagnose_proposal(proposal: dict[str, Any], *, use_llm: bool) -> dict[str, Any] | None:
    """对带证据包引用的提案产出结构化诊断；无证据引用返回 None。"""
    ref = proposal.get("evidence_ref")
    if not isinstance(ref, dict) or not ref.get("path"):
        return None
    heal = _load_self_heal()
    bundle_path = Path(str(ref["path"]))
    record: dict[str, Any] = {
        "dedup_key": str(proposal.get("dedup_key") or ""),
        "wo_id": derive_wo_id(str(proposal.get("dedup_key") or "")),
        "ts": datetime.now(UTC).isoformat(),
        "evidence": {"path": str(ref["path"]), "sha256_expected": str(ref.get("sha256") or "")},
        "engine": "none",
        "errors": [],
        "fixes": [],
    }
    if not bundle_path.is_file():
        record["status"] = "evidence_missing"
        return record
    verified, actual = _verify_sha256(bundle_path, str(ref.get("sha256") or ""))
    record["evidence"]["sha256_verified"] = actual
    record["evidence"]["intact"] = verified
    text = _bundle_log_text(bundle_path)
    errors = heal.select_actionable_errors(heal.extract_errors(text))
    record["errors"] = [dataclasses.asdict(e) for e in errors[:20]]
    fixes: list[Any] = heal.match_rules(errors) if errors else []
    record["engine"] = "rule" if fixes else ("no_signature" if not errors else "rule_no_match")
    if not fixes and use_llm and errors:
        llm_fixes = heal.call_llm(errors)
        if llm_fixes:
            fixes = llm_fixes
            record["engine"] = "llm"
    record["fixes"] = [
        {
            "description": f.description,
            "needs_human": f.needs_human,
            "risk_level": f.risk_level,
            "tool": f.error.tool,
            "code": f.error.code,
            "file": f.error.file_path,
            "line": f.error.line,
        }
        for f in fixes[:20]
    ]
    if not errors:
        # 无错误签名时保留脱敏日志节选供人工/后续 LLM 判读
        record["excerpt"] = heal.select_incident_log_excerpt(text, max_chars=4000)
    _attach_known_cases(record)
    return record


def run(args: argparse.Namespace) -> int:
    pending = list_pending_proposals()
    candidates = [p for p in pending if isinstance(p.get("evidence_ref"), dict)]
    if not candidates:
        logger.info("no proposals with evidence_ref; nothing to diagnose")
        return 0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = 0
    for proposal in candidates[: max(0, int(args.max))]:
        key = str(proposal.get("dedup_key") or "")
        out_path = out_dir / f"diagnosis-{key[:12]}.json"
        if out_path.is_file() and not args.force:
            logger.info("skip existing diagnosis: %s", out_path)
            continue
        try:
            record = diagnose_proposal(proposal, use_llm=args.llm)
        except Exception as exc:  # noqa: BLE001 - fail-open：单条失败不断链
            logger.warning("diagnose failed for %s: %s", key[:12], exc)
            continue
        if record is None:
            continue
        out_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        produced += 1
        logger.info("diagnosis written: %s engine=%s", out_path, record.get("engine"))
    logger.info("diagnosis done: produced=%d", produced)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(_DIAGNOSIS_DIR))
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--llm", action="store_true", help="规则无匹配时调用 LLM 兜底")
    parser.add_argument("--force", action="store_true", help="重写已存在的诊断文件")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
