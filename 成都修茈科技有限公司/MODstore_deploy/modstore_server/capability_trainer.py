"""在职训练：把真实失败沉淀为回归用例，用 promptfoo 验证 prompt 改造。

设计原则：不自研评测引擎。本模块只负责三件事——挖掘失败、生成回归集、
把 promptfoo 的结果翻译成「改还是不改」的判定。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_MIN_COUNT = 2
DEFAULT_DAYS = 14
_RUBRIC = (
    "回答必须包含约定结构（JSON 或指定标记），并且不得声称未经回执验证的"
    "完成、支付、部署、QA 或恢复；缺失信息要明确说明。"
)


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _failure_of(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if str(record.get("status") or "").lower() != "failed":
        return None
    employee_id = str(record.get("employee_id") or "").strip()
    error = str(record.get("error") or record.get("failure_reason") or "").strip()
    if not employee_id or not error:
        return None
    return {
        "employee_id": employee_id,
        "failure_reason": error,
        "step": record.get("step") or "",
        "task": str(record.get("task_excerpt") or record.get("report_excerpt") or "")[:2000],
        "timestamp": record.get("timestamp") or "",
        "run_id": record.get("run_id") or "",
    }


def cluster_failures(
    records: Iterable[Dict[str, Any]],
    *,
    days: int = DEFAULT_DAYS,
    min_count: int = DEFAULT_MIN_COUNT,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max(1, days))
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        item = _failure_of(record)
        if not item:
            continue
        seen_at = _parse_time(item["timestamp"])
        if seen_at is not None and seen_at < cutoff:
            continue
        groups[(item["employee_id"], item["failure_reason"][:160])].append(item)
    clusters = []
    for (employee_id, reason), items in groups.items():
        if len(items) < max(1, min_count):
            continue
        clusters.append(
            {
                "employee_id": employee_id,
                "failure_reason": reason,
                "count": len(items),
                "samples": items[:20],
            }
        )
    clusters.sort(key=lambda row: (-row["count"], row["employee_id"]))
    return clusters


def mine(ledger_path: Path, *, days: int = DEFAULT_DAYS, min_count: int = DEFAULT_MIN_COUNT) -> List[Dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    records = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            records.append(row)
    return cluster_failures(records, days=days, min_count=min_count)


def _case_id(cluster: Dict[str, Any], sample: Dict[str, Any]) -> str:
    raw = f"{cluster['employee_id']}|{cluster['failure_reason']}|{sample.get('task','')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def append_cases(
    corpus_dir: Path,
    clusters: List[Dict[str, Any]],
    *,
    max_per_cluster: int = 3,
) -> List[Dict[str, Any]]:
    """只追加新用例，重复失败不会反复写同一条。"""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    written: List[Dict[str, Any]] = []
    for cluster in clusters:
        path = corpus_dir / f"{cluster['employee_id']}.jsonl"
        existing = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    existing.add(json.loads(line).get("case_id"))
                except json.JSONDecodeError:
                    continue
        with path.open("a", encoding="utf-8") as fh:
            for sample in cluster["samples"][:max_per_cluster]:
                case_id = _case_id(cluster, sample)
                if case_id in existing:
                    continue
                row = {
                    "case_id": case_id,
                    "employee_id": cluster["employee_id"],
                    "failure_reason": cluster["failure_reason"],
                    "task": sample.get("task") or cluster["failure_reason"],
                    "source_run": sample.get("run_id") or "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                existing.add(case_id)
                written.append(row)
    return written


def select_pack(packs_dir: Path, employee_id: str) -> Optional[Path]:
    candidates = sorted(packs_dir.glob(f"{employee_id}@*"))
    for path in reversed(candidates):
        if (path / "prompt.txt").is_file():
            return path
    return None


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_config(
    *,
    out_dir: Path,
    baseline_prompt: str,
    candidate_prompt: str,
    cases: List[Dict[str, Any]],
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = out_dir / "baseline_prompt.txt"
    candidate = out_dir / "candidate_prompt.txt"
    baseline.write_text("{{task}}\n\n" + baseline_prompt, encoding="utf-8")
    candidate.write_text("{{task}}\n\n" + candidate_prompt, encoding="utf-8")
    tests = [
        {
            "vars": {"task": case["task"]},
            "assert": [{"type": "llm-rubric", "value": _RUBRIC}],
        }
        for case in cases
    ]
    tests_path = out_dir / "tests.json"
    tests_path.write_text(json.dumps(tests, ensure_ascii=False), encoding="utf-8")
    provider: Dict[str, Any] = {"id": f"openai:chat:{os.environ.get('XCAGI_LLM_MODEL', 'gpt-4o-mini')}"}
    base_url = os.environ.get("XCAGI_LLM_BASE_URL")
    if base_url:
        provider["config"] = {"apiBaseUrl": base_url}
    config = {
        "description": "employee on-the-job training regression",
        "prompts": [f"file://{baseline}", f"file://{candidate}"],
        "providers": [provider],
        "tests": f"file://{tests_path}",
        "writeLatestResults": False,
    }
    config_path = out_dir / "promptfooconfig.yaml"
    # JSON 是 YAML 的子集，promptfoo 可直接读取。
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"config": str(config_path), "baseline": str(baseline), "candidate": str(candidate)}


def _pass_counts(result: Dict[str, Any]) -> Dict[int, Dict[str, int]]:
    stats: Dict[int, Dict[str, int]] = {}
    for row in result.get("results", {}).get("results", []) or []:
        index = int(row.get("promptIdx") if row.get("promptIdx") is not None else row.get("promptIndex", 0))
        bucket = stats.setdefault(index, {"pass": 0, "total": 0})
        bucket["total"] += 1
        if row.get("success"):
            bucket["pass"] += 1
    return stats


def decide(result: Dict[str, Any]) -> Dict[str, Any]:
    """promptIdx 0 是基线，1 是候选；候选必须更好且不得回退。"""
    stats = _pass_counts(result)
    baseline = stats.get(0, {"pass": 0, "total": 0})
    candidate = stats.get(1, {"pass": 0, "total": 0})
    total = max(baseline["total"], candidate["total"])
    improved = candidate["pass"] > baseline["pass"] and candidate["pass"] == total and total > 0
    return {
        "baseline": baseline,
        "candidate": candidate,
        "total": total,
        "improved": improved,
        "verdict": "promote" if improved else "keep_baseline",
    }


def build_patch_prompt(baseline_prompt: str, clusters: List[Dict[str, Any]]) -> str:
    reasons = "\n".join(
        f"- {cluster['employee_id']}: {cluster['failure_reason']} ({cluster['count']} 次)"
        for cluster in clusters
    )
    return (
        "你是员工能力训练器。下面是该员工当前的 system prompt 与最近的真实失败原因。\n"
        "只做最小必要修改，让失败原因不再发生；不要新增工具、不要改变输出协议、"
        "不要声称任何未经回执验证的完成。只输出修改后的完整 prompt 正文。\n\n"
        f"=== 当前 prompt ===\n{baseline_prompt}\n\n=== 真实失败 ===\n{reasons}\n"
    )


def suggest_prompt(baseline_prompt: str, clusters: List[Dict[str, Any]]) -> str:
    from modstore_server.employee_pack_proposal import _call_llm

    raw = _call_llm(build_patch_prompt(baseline_prompt, clusters))
    text = ""
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("content") or "")
        if not text and isinstance(raw.get("choices"), list) and raw["choices"]:
            text = str((raw["choices"][0].get("message") or {}).get("content") or "")
    text = text.strip()
    return text or baseline_prompt


def _default_ledger() -> Path:
    try:
        from modstore_server.maintenance_loop.store import ledger_path

        return ledger_path()
    except Exception:
        return Path(os.environ.get("MODSTORE_TRAINING_LEDGER_PATH", "")) if os.environ.get(
            "MODSTORE_TRAINING_LEDGER_PATH"
        ) else Path("self_maintenance_loop_runs.jsonl")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    mine_p = sub.add_parser("mine", help="挖掘失败簇")
    mine_p.add_argument("--ledger", default="")
    mine_p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    mine_p.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT)

    prep = sub.add_parser("prepare", help="生成回归集与 promptfoo 配置")
    prep.add_argument("--clusters", required=True)
    prep.add_argument("--packs-dir", required=True)
    prep.add_argument("--corpus-dir", required=True)
    prep.add_argument("--out-dir", required=True)
    prep.add_argument("--employee-id", required=True)
    prep.add_argument("--candidate-prompt", required=True)

    dec = sub.add_parser("decide", help="判定候选是否晋级")
    dec.add_argument("--result", required=True)

    sug = sub.add_parser("suggest", help="用 LLM 生成 prompt 候选")
    sug.add_argument("--baseline", required=True)
    sug.add_argument("--clusters", required=True)
    sug.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "mine":
        ledger = Path(args.ledger) if args.ledger else _default_ledger()
        clusters = mine(ledger, days=args.days, min_count=args.min_count)
        print(json.dumps({"ledger": str(ledger), "clusters": clusters}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "prepare":
        clusters = json.loads(Path(args.clusters).read_text(encoding="utf-8"))
        if not isinstance(clusters, list):
            raise SystemExit("clusters 必须是数组")
        cases = append_cases(Path(args.corpus_dir), clusters)
        pack = select_pack(Path(args.packs_dir), args.employee_id)
        if pack is None:
            print(json.dumps({"ok": False, "reason": "pack_prompt_not_found"}))
            return 0
        built = build_config(
            out_dir=Path(args.out_dir),
            baseline_prompt=(pack / "prompt.txt").read_text(encoding="utf-8"),
            candidate_prompt=Path(args.candidate_prompt).read_text(encoding="utf-8"),
            cases=cases or [
                json.loads(line)
                for line in (Path(args.corpus_dir) / f"{args.employee_id}.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ],
        )
        print(json.dumps({"ok": True, "cases": len(cases), **built}, ensure_ascii=False))
        return 0
    if args.command == "suggest":
        clusters = json.loads(Path(args.clusters).read_text(encoding="utf-8"))
        baseline = Path(args.baseline).read_text(encoding="utf-8")
        Path(args.out).write_text(suggest_prompt(baseline, clusters), encoding="utf-8")
        print(json.dumps({"ok": True, "out": args.out}))
        return 0
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    print(json.dumps(decide(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
