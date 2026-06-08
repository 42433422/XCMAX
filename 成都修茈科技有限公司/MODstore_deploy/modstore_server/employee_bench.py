"""员工上架前的基准测试：LLM 生成 1-5 级任务 → 执行 → 量化打分 → 五维审核 →（可选）员工包质询。

公开接口
--------
generate_bench_tasks(brief, panel_summary, db, user_id, provider, model, *, use_platform_dispatch, strict)
    -> List[{level, tasks:[{id, task_desc}]}]

run_and_score_bench(employee_id, task_list, db, user, *, bench_llm_override, per_dimension_ids)
    -> {tasks_result, level_scores, overall_score, audit, passed, reviewer_selection, ...}
    可选环境变量 ``MODSTORE_PACK_PEER_REVIEW_EMPLOYEE``：五维之后在 ``audit.pack_peer_review`` 中附加 LLM 质询分。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modstore_server.models import User

logger = logging.getLogger(__name__)

# ── 权重：越低难度级别权重越高 ──────────────────────────────────────────
_LEVEL_WEIGHTS = {1: 3.0, 2: 2.5, 3: 2.0, 4: 1.5, 5: 1.0}

# ── 效率因子基准（tokens，超过则 efficiency < 1）─────────────────────────
_EFFICIENT_TOKEN_THRESHOLD = 500

# ── 通过标准 ─────────────────────────────────────────────────────────────
_PASS_OVERALL_SCORE = 60.0
_PASS_AUDIT_SCORE = True  # audit.summary.pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 生成测试任务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TASK_GEN_SYSTEM = """\
你是一位严格的 AI 员工考官。根据员工功能描述，为该员工设计一套分级测试任务（共 5 级，每级 3 个任务）。

任务难度递增：
- 1 级：极简验证，单步操作，无歧义输入
- 2 级：基础功能，正常业务场景
- 3 级：中等复杂度，含边界条件
- 4 级：多步骤、需要判断的场景
- 5 级：压力/异常/综合场景

输出**仅**一个合法 JSON 数组（无注释、无 markdown 围栏）：
[
  {
    "level": 1,
    "tasks": [
      {"id": "1-1", "task_desc": "具体任务指令，30字以内"},
      {"id": "1-2", "task_desc": "..."},
      {"id": "1-3", "task_desc": "..."}
    ]
  },
  ... (level 2 to 5)
]
"""


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I | re.S)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _parse_task_list(content: str) -> List[Dict[str, Any]]:
    raw = _strip_fence(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("["), raw.rfind("]")
        if i < 0 or j <= i:
            return []
        try:
            data = json.loads(raw[i : j + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        lv = int(item.get("level") or 0)
        if lv < 1 or lv > 5:
            continue
        tasks = [
            {
                "id": str(t.get("id") or f"{lv}-{i+1}"),
                "task_desc": str(t.get("task_desc") or "").strip()[:120],
            }
            for i, t in enumerate((item.get("tasks") or [])[:3])
            if isinstance(t, dict) and str(t.get("task_desc") or "").strip()
        ]
        if tasks:
            out.append({"level": lv, "tasks": tasks})
    return out


def _fallback_tasks(brief: str) -> List[Dict[str, Any]]:
    """LLM 失败时生成最小占位任务集。"""
    short = (brief or "执行默认任务")[:40]
    return [
        {
            "level": lv,
            "tasks": [
                {"id": f"{lv}-{t}", "task_desc": f"[Lv{lv}] {short}（测试 {t}）"}
                for t in range(1, 4)
            ],
        }
        for lv in range(1, 6)
    ]


async def generate_bench_tasks(
    brief: str,
    panel_summary: str,
    *,
    db: Session,
    user_id: int,
    provider: Optional[str],
    model: Optional[str],
    use_platform_dispatch: bool = False,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """调 LLM 一次生成 1-5 级共 15 条测试任务。

    use_platform_dispatch=True 时使用平台密钥（不读用户 BYOK）。
    strict=True 时 LLM 失败会抛出 RuntimeError，而不是静默退回到占位任务。
    """
    from modstore_server.services.llm import (
        chat_dispatch_via_platform_only,
        chat_dispatch_via_session,
    )

    if not provider or not model:
        msg = "generate_bench_tasks: 无 provider/model，无法生成测试任务"
        if strict:
            raise RuntimeError(msg)
        logger.warning("%s，使用占位任务", msg)
        return _fallback_tasks(brief)

    user_msg = (
        f"员工功能描述（brief）：\n{(brief or '').strip()}\n\n"
        f"功能摘要（panel_summary）：\n{(panel_summary or '（无）').strip()}"
    )
    messages = [
        {"role": "system", "content": _TASK_GEN_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    try:
        # 思考型模型会占用 reasoning_content + content；2048 易导致 JSON 落在空 content。
        _mt = 6000 if use_platform_dispatch else 2000
        if use_platform_dispatch:
            result = await chat_dispatch_via_platform_only(
                provider, model, messages, max_tokens=_mt
            )
        else:
            result = await chat_dispatch_via_session(
                db, user_id, provider, model, messages, max_tokens=_mt
            )
    except Exception as exc:  # noqa: BLE001
        msg = f"generate_bench_tasks LLM call failed: {exc}"
        if strict:
            raise RuntimeError(msg) from exc
        logger.warning(msg)
        return _fallback_tasks(brief)

    if not result.get("ok"):
        msg = f"generate_bench_tasks LLM error: {result.get('error')}"
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)
        return _fallback_tasks(brief)

    tasks = _parse_task_list(str(result.get("content") or ""))
    if not tasks:
        msg = "generate_bench_tasks: LLM 响应解析失败，未获得有效任务列表"
        if strict:
            raise RuntimeError(msg)
        logger.warning("%s，使用占位任务", msg)
        return _fallback_tasks(brief)

    # 补齐缺失的 level
    seen = {t["level"] for t in tasks}
    for lv in range(1, 6):
        if lv not in seen:
            tasks.append(
                {
                    "level": lv,
                    "tasks": [{"id": f"{lv}-1", "task_desc": f"[Lv{lv}] {brief[:40]}（补位）"}],
                }
            )
    tasks.sort(key=lambda x: x["level"])
    return tasks


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 执行 + 量化打分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_RUBRIC_SYSTEM = """\
你是 AI 员工基准测试的量化评分裁判。根据每条任务的「任务描述」与「执行输出摘要」，\
给出 0–100 的符合度分数（integer 或 float）。
规则：
- 只根据摘要判断是否回应了任务；若摘要显示报错、空输出或与任务无关，给低分（0–35）。
- 执行标记 execution_ok=false 时，分数通常不超过 40，除非摘要显示仍有有效部分。
输出**仅**一个合法 JSON 数组（无 markdown 围栏），每个元素：
{"task_id": "<与输入一致>", "score": <0-100>, "note": "<一句中文理由>"}
必须覆盖输入中的每一个 task_id，不得遗漏。"""


def _derive_bench_execution_ok(raw: Dict[str, Any]) -> bool:
    """从 execute_employee_task 返回体推导是否执行成功（顶层无 ok 字段）。"""
    if not isinstance(raw, dict):
        return False
    if str(raw.get("cognition_error") or "").strip():
        return False
    if raw.get("ok") is False:
        return False
    err_top = raw.get("error")
    if err_top and not raw.get("result"):
        return False
    inner = raw.get("result")
    if not isinstance(inner, dict):
        return True
    for out in inner.get("outputs") or []:
        if not isinstance(out, dict):
            continue
        if out.get("error"):
            return False
        if out.get("ok") is False:
            return False
    return True


def _extract_output_preview(raw: Dict[str, Any], limit: int = 500) -> str:
    """抽取员工输出摘要供裁判模型评分。"""
    if not isinstance(raw, dict):
        return ""
    head = str(raw.get("reasoning_excerpt") or "").strip()
    parts: List[str] = []
    if head:
        parts.append(head[:limit])
    inner = raw.get("result")
    if isinstance(inner, dict):
        chunks: List[str] = []
        for out in (inner.get("outputs") or [])[:8]:
            if not isinstance(out, dict):
                continue
            text = (
                out.get("output")
                or out.get("reasoning")
                or out.get("summary")
                or out.get("text_preview")
                or out.get("response")
            )
            if text:
                chunks.append(str(text).strip()[:limit])
            elif out.get("error"):
                chunks.append(f"error:{str(out.get('error'))[:200]}")
        if chunks:
            parts.extend(chunks)
    if parts:
        return "\n".join(parts)[: limit * 5]
    if raw.get("error"):
        return f"error:{str(raw.get('error'))[:limit]}"
    return ""


def _parse_rubric_scores(content: str) -> Dict[str, float]:
    """解析裁判模型返回的 JSON 数组。"""
    raw = _strip_fence(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("["), raw.rfind("]")
        if i < 0 or j <= i:
            return {}
        try:
            data = json.loads(raw[i : j + 1])
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, list):
        return {}
    out: Dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("task_id") or "").strip()
        sc = row.get("score")
        if not tid or sc is None:
            continue
        try:
            val = float(sc)
        except (TypeError, ValueError):
            continue
        out[tid] = float(max(0.0, min(100.0, val)))
    return out


def _align_rubric_keys(raw_scores: Dict[str, float], expected_ids: set[str]) -> Dict[str, float]:
    """裁判返回的 task_id 可能与请求略有差异，对齐到真实 task_id。"""
    if not raw_scores or not expected_ids:
        return {}
    # 精确匹配优先
    out: Dict[str, float] = {}
    lower_map = {k.strip().lower(): v for k, v in raw_scores.items()}
    for tid in expected_ids:
        if tid in raw_scores:
            out[tid] = raw_scores[tid]
            continue
        lk = tid.strip().lower()
        if lk in lower_map:
            out[tid] = lower_map[lk]
    return out


async def _llm_rubric_scores_platform(
    provider: str,
    model: str,
    items: List[Dict[str, Any]],
) -> Tuple[Dict[str, float], Optional[str]]:
    """调用平台密钥裁判模型为每条任务打分（不经 require_llm_credit / 钱包）。"""
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    if not items:
        return {}, None
    out: Dict[str, float] = {}
    chunk_size = 10
    last_err: Optional[str] = None
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        payload = json.dumps(chunk, ensure_ascii=False)
        result = await chat_dispatch_via_platform_only(
            provider,
            model,
            [
                {"role": "system", "content": _RUBRIC_SYSTEM},
                {"role": "user", "content": payload},
            ],
            max_tokens=6000,
        )
        if not result.get("ok"):
            last_err = str(result.get("error") or "rubric upstream error")
            logger.warning("bench rubric LLM failed: %s", last_err)
            continue
        part = _parse_rubric_scores(str(result.get("content") or ""))
        out.update(part)
    return out, last_err


def _level_scores_from_entries(tasks_result: List[Dict[str, Any]]) -> Dict[int, float]:
    buckets: Dict[int, List[float]] = defaultdict(list)
    for e in tasks_result:
        lv = int(e.get("level") or 0)
        if 1 <= lv <= 5:
            buckets[lv].append(float(e.get("score") or 0.0))
    out: Dict[int, float] = {}
    for lv in range(1, 6):
        vals = buckets.get(lv) or []
        out[lv] = round(sum(vals) / len(vals), 1) if vals else 0.0
    return out


def _efficiency_factor(cost_tokens: int) -> float:
    """token 消耗越少效率因子越高（最大 1.0）。"""
    if cost_tokens <= 0:
        return 1.0
    factor = _EFFICIENT_TOKEN_THRESHOLD / max(cost_tokens, _EFFICIENT_TOKEN_THRESHOLD)
    return min(1.0, factor)


def _run_single_task(
    employee_id: str,
    task_desc: str,
    user_id: int,
    bench_llm_override: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    """同步执行单条任务，记录 ok / cost_tokens / duration_ms。"""
    from modstore_server.services.employee import get_default_employee_client

    client = get_default_employee_client()
    t0 = time.perf_counter()
    try:
        res = client.execute_task(
            employee_id=employee_id,
            task=task_desc,
            input_data={},
            user_id=user_id,
            bench_llm_override=bench_llm_override,
        )
        if isinstance(res, dict):
            ok = _derive_bench_execution_ok(res)
            cost_tokens = int(
                res.get("llm_tokens") or res.get("cost_tokens") or res.get("tokens_used") or 0
            )
        else:
            ok = bool(res)
            cost_tokens = 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "bench task failed employee=%s task=%r: %s", employee_id, task_desc[:40], exc
        )
        ok = False
        cost_tokens = 0
        res = {"error": str(exc)}
    duration_ms = (time.perf_counter() - t0) * 1000
    raw_dict = res if isinstance(res, dict) else {}
    return {
        "ok": ok,
        "cost_tokens": cost_tokens,
        "duration_ms": round(duration_ms, 1),
        "raw": raw_dict,
        "output_preview": _extract_output_preview(raw_dict),
    }


def _score_level(level_results: List[Dict[str, Any]]) -> float:
    """对某一级的多条任务结果计算平均得分（0-100）。"""
    if not level_results:
        return 0.0
    scores = [
        100.0 * (1.0 if r["ok"] else 0.0) * _efficiency_factor(r["cost_tokens"])
        for r in level_results
    ]
    return sum(scores) / len(scores)


def _weighted_overall(level_scores: Dict[int, float]) -> float:
    total_w = sum(_LEVEL_WEIGHTS[lv] for lv in range(1, 6))
    weighted = sum(_LEVEL_WEIGHTS.get(lv, 1.0) * level_scores.get(lv, 0.0) for lv in range(1, 6))
    return weighted / total_w if total_w else 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 五维审核
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 支持的五个维度键（与 package_sandbox_audit 返回结构一致）
AUDIT_DIMENSIONS = (
    "manifest_compliance",
    "declaration_completeness",
    "api_testability_static",
    "security_and_size",
    "metadata_quality",
)

_DIM_LABELS_ZH: Dict[str, str] = {
    "manifest_compliance": "清单 / manifest 结构与 artifact 合规",
    "declaration_completeness": "声明完整度（workflow_employees、字段齐全）",
    "api_testability_static": "API / 路由静态可测性",
    "security_and_size": "包体大小与安全扫描",
    "metadata_quality": "元数据质量（名称、描述、行业等）",
}

_MAX_REVIEWER_CANDIDATES = 48

_MACHINE_SCORE_LINE = re.compile(r"^MACHINE_SCORE\s*=\s*(\d{1,3})\s*$", re.MULTILINE)


def _parse_machine_score_from_text(text: str) -> Optional[int]:
    """从质询员 Markdown 末行解析 ``MACHINE_SCORE=0..100``。"""
    if not (text or "").strip():
        return None
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    for ln in reversed(lines[-8:]):
        m = re.match(r"^MACHINE_SCORE\s*=\s*(\d{1,3})\s*$", ln, flags=re.I)
        if m:
            v = int(m.group(1))
            return max(0, min(100, v))
    m2 = _MACHINE_SCORE_LINE.search(text)
    if m2:
        v = int(m2.group(1))
        return max(0, min(100, v))
    return None


def _peer_review_gate_enabled() -> bool:
    return (os.environ.get("MODSTORE_BENCH_PEER_REVIEW_GATE", "0") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _peer_review_min_score() -> float:
    raw = (os.environ.get("MODSTORE_BENCH_PEER_REVIEW_MIN_SCORE", "55") or "").strip()
    try:
        return float(raw)
    except ValueError:
        return 55.0


async def _run_pack_peer_review_optional(
    subject_employee_id: str,
    *,
    db: Session,
    user: User,
    bench_llm_override: Optional[Tuple[str, str]],
) -> Optional[Dict[str, Any]]:
    """若设置 ``MODSTORE_PACK_PEER_REVIEW_EMPLOYEE``，对被测包 manifest 片段跑一轮 LLM 质询并量化。

    质询员工（如 ``employee-pack-quality-interviewer``）须在输出**最后一行**写 ``MACHINE_SCORE=整数``。
    """
    reviewer = (os.environ.get("MODSTORE_PACK_PEER_REVIEW_EMPLOYEE") or "").strip()
    if not reviewer:
        return None
    if not bench_llm_override:
        return {
            "skipped": True,
            "reason": "no_platform_bench_llm",
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }

    from modstore_server.employee_executor import execute_employee_task
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )

    materialize_employee_pack_if_missing(subject_employee_id)
    mf_path = modstore_library_path() / subject_employee_id / "manifest.json"
    if not mf_path.is_file():
        return {
            "ok": False,
            "error": "subject manifest not found",
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }
    try:
        manifest = json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": f"manifest read failed: {exc}",
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }

    excerpt = json.dumps(manifest, ensure_ascii=False, indent=2)
    max_chars = int(
        (os.environ.get("MODSTORE_PACK_PEER_REVIEW_MAX_MANIFEST_CHARS", "14000") or "14000").strip()
        or "14000"
    )
    max_chars = max(2000, min(100_000, max_chars))
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n…[truncated for peer review]…"

    task = (
        "对以下候选员工包（manifest JSON）执行质询面试：按你的系统提示输出 Markdown 各节；"
        "全文最后一行且仅此一行必须严格为 MACHINE_SCORE=整数（0–100），表示上架准备度量化分，该行前后不要反引号或多余文字。"
    )
    payload: Dict[str, Any] = {
        "manifest_excerpt": excerpt,
        "target_role": str(manifest.get("name") or subject_employee_id)[:200],
        "handler": "llm_md",
    }

    import asyncio

    def _run() -> Dict[str, Any]:
        return execute_employee_task(
            reviewer,
            task,
            payload,
            user.id,
            bench_llm_override=bench_llm_override,
        )

    try:
        exec_out = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pack peer review execute failed subject=%s reviewer=%s: %s",
            subject_employee_id,
            reviewer,
            exc,
        )
        return {
            "ok": False,
            "error": str(exc)[:500],
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }

    text = ""
    res_block = exec_out.get("result") if isinstance(exec_out.get("result"), dict) else {}
    for block in res_block.get("outputs") or []:
        if isinstance(block, dict) and block.get("handler") == "llm_md":
            text = str(block.get("output") or "")
            break
    if not text.strip():
        text = str((exec_out.get("reasoning_excerpt") or ""))[:8000]

    score = _parse_machine_score_from_text(text)
    min_sc = _peer_review_min_score()
    parsed_ok = score is not None
    pass_peer = parsed_ok and float(score) >= min_sc

    return {
        "ok": True,
        "reviewer_employee_id": reviewer,
        "subject_employee_id": subject_employee_id,
        "parsed_score": score,
        "min_score": min_sc,
        "pass_peer": pass_peer,
        "output_preview": text[:4000],
        "missing_machine_score": not parsed_ok,
    }


def _read_employee_brief(employee_id: str) -> Tuple[str, str]:
    """从本地库读取被测员工 brief + panel_summary。"""
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )

    eid = (employee_id or "").strip()
    if not eid:
        return "", ""
    materialize_employee_pack_if_missing(eid)
    mf_path = modstore_library_path() / eid / "manifest.json"
    if not mf_path.is_file():
        return "", ""
    try:
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    brief = (
        str(mf.get("description") or "") or str((mf.get("identity") or {}).get("description") or "")
    )[:800]
    rows = mf.get("workflow_employees") or []
    panel_summary = ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
    return brief, panel_summary


def _collect_reviewer_candidate_ids(subject_id: str) -> List[str]:
    """评审池：环境变量 CSV + 可选 catalog 全部 employee_pack（去重、排除被测 id）。"""
    import os

    subject_id = (subject_id or "").strip()
    raw = (os.environ.get("MODSTORE_BENCH_REVIEWER_POOL") or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    flag = (os.environ.get("MODSTORE_BENCH_REVIEWER_POOL_FROM_CATALOG") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        try:
            from modstore_server import catalog_store

            rows, _ = catalog_store.list_packages(
                artifact="employee_pack", q=None, limit=400, offset=0
            )
            for r in rows or []:
                pid = str(r.get("id") or "").strip()
                if pid:
                    ids.append(pid)
        except Exception as ex:  # noqa: BLE001
            logger.warning("reviewer pool: catalog scan failed: %s", ex)

    seen: set[str] = set()
    out: List[str] = []
    for x in ids:
        if not x or x == subject_id or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out[:_MAX_REVIEWER_CANDIDATES]


def _snapshot_reviewer_candidate(emp_id: str) -> Optional[Dict[str, str]]:
    """读取候选评审包的 id / 名称 / 简介（用于 LLM 路由）。"""
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )

    eid = (emp_id or "").strip()
    if not eid:
        return None
    materialize_employee_pack_if_missing(eid)
    mf_path = modstore_library_path() / eid / "manifest.json"
    if not mf_path.is_file():
        return None
    try:
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ident = mf.get("identity") if isinstance(mf.get("identity"), dict) else {}
    name = str(mf.get("name") or ident.get("name") or eid).strip()[:120]
    desc = str(mf.get("description") or ident.get("description") or "").strip()[:400]
    return {"id": eid, "name": name, "description": desc}


def _dimensions_still_open(
    env_defaults: Dict[str, str],
    explicit: Dict[str, str],
) -> List[str]:
    """尚未被环境变量或 API 显式指定的维度 → 才可自动分配。"""
    holes: List[str] = []
    for dim in AUDIT_DIMENSIONS:
        if str(explicit.get(dim) or "").strip():
            continue
        if str(env_defaults.get(dim) or "").strip():
            continue
        holes.append(dim)
    return holes


async def _llm_assign_reviewers_to_dimensions(
    subject_id: str,
    brief: str,
    panel_summary: str,
    candidates: List[Dict[str, str]],
    provider: str,
    model: str,
    holes: List[str],
) -> Tuple[Dict[str, str], Optional[str]]:
    """调用平台 LLM，为「空缺维度」从候选包中选评审参考包 id。"""
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    if not holes or not candidates:
        return {}, None

    allowed = {c["id"] for c in candidates if c.get("id")}
    dim_lines = "\n".join(f"- {d}: {_DIM_LABELS_ZH.get(d, d)}" for d in AUDIT_DIMENSIONS)

    system = f"""你是员工包「五维沙盒审核」的评审路由编排器。
沙盒会对**评审参考包本身**跑静态五维打分；合成报告时，每个维度可以引用不同参考包在该维上的得分。

当前只需要为下列**尚未指定**的维度，各选一个**最合适**的候选包 id（必须从候选列表中选，禁止编造 id）。
尚未指定维度：{", ".join(holes)}

五维含义：
{dim_lines}

规则：
1. 输出**仅**一个 JSON 对象，不要 markdown。
2. 每个键必须是下列之一：{", ".join(AUDIT_DIMENSIONS)}
3. **只输出你需要填写的维度**（通常是 holes 中的维度）；每个值必须是候选中的 id 字符串。
4. 优先让五个维度覆盖不同候选（若候选不足再复用）。
5. 结合「被测员工」的领域与候选包的名称/简介做语义匹配。

示例：{{"manifest_compliance":"pkg-a","metadata_quality":"pkg-b"}}"""

    payload = {
        "subject_employee_id": subject_id,
        "subject_brief": (brief or "").strip(),
        "panel_summary": (panel_summary or "").strip(),
        "candidate_packages": candidates,
        "dimensions_to_fill": holes,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)

    result = await chat_dispatch_via_platform_only(
        provider,
        model,
        [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        max_tokens=2500,
    )
    if not result.get("ok"):
        return {}, str(result.get("error") or "LLM router failed")

    raw = _parse_router_json(str(result.get("content") or ""))
    out: Dict[str, str] = {}
    for dim in holes:
        v = str(raw.get(dim) or "").strip()
        if v in allowed:
            out[dim] = v
    return out, None


def _parse_router_json(text: str) -> Dict[str, Any]:
    raw = _strip_fence(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if i < 0 or j <= i:
            return {}
        try:
            data = json.loads(raw[i : j + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


async def resolve_auto_dimension_reviewers(
    subject_id: str,
    brief: str,
    panel_summary: str,
    bench_llm_override: Optional[Tuple[str, str]],
    *,
    explicit_per_dimension: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    """从评审池 + 平台 LLM 自动为「空缺维度」挑选评审参考包。无池 / 禁用 / 无空缺时跳过。"""
    import os

    meta: Dict[str, Any] = {"enabled": False}
    if (os.environ.get("MODSTORE_BENCH_REVIEWER_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        meta["skipped"] = "MODSTORE_BENCH_REVIEWER_DISABLE"
        return None, meta

    if not bench_llm_override:
        meta["skipped"] = "no_platform_bench_llm"
        return None, meta

    env_defaults = _load_audit_dimension_env_defaults()
    explicit = {
        k: v
        for k, v in (explicit_per_dimension or {}).items()
        if k in AUDIT_DIMENSIONS and str(v or "").strip()
    }
    holes = _dimensions_still_open(env_defaults, explicit)
    if not holes:
        meta["skipped"] = "all_dimensions_preassigned"
        meta["holes"] = []
        return None, meta

    cand_ids = _collect_reviewer_candidate_ids(subject_id)
    if not cand_ids:
        meta["skipped"] = "empty_reviewer_pool"
        meta["hint"] = (
            "设置 MODSTORE_BENCH_REVIEWER_POOL=id1,id2 或 MODSTORE_BENCH_REVIEWER_POOL_FROM_CATALOG=1"
        )
        return None, meta

    candidates: List[Dict[str, str]] = []
    for cid in cand_ids:
        snap = _snapshot_reviewer_candidate(cid)
        if snap:
            candidates.append(snap)
    meta["pool_raw"] = len(cand_ids)
    meta["candidates_loaded"] = len(candidates)
    if not candidates:
        meta["skipped"] = "no_candidate_manifests"
        return None, meta

    prov, mdl = bench_llm_override
    picked, err = await _llm_assign_reviewers_to_dimensions(
        subject_id, brief, panel_summary, candidates, prov, mdl, holes
    )
    meta["enabled"] = True
    meta["holes"] = holes
    meta["assignment"] = picked
    if err:
        meta["error"] = err
    if not picked:
        meta["skipped"] = "llm_router_empty"
        return None, meta
    return picked, meta


def _load_audit_dimension_env_defaults() -> Dict[str, str]:
    """从服务端环境变量读取五维专属包 ID 的静态默认映射。

    环境变量命名规则：``MODSTORE_AUDIT_DIM_<DIMENSION_UPPER>_EMPLOYEE``。
    例：``MODSTORE_AUDIT_DIM_MANIFEST_COMPLIANCE_EMPLOYEE=python-docstring-gen``
    """
    import os

    result: Dict[str, str] = {}
    for dim in AUDIT_DIMENSIONS:
        env_key = f"MODSTORE_AUDIT_DIM_{dim.upper()}_EMPLOYEE"
        val = (os.environ.get(env_key) or "").strip()
        if val:
            result[dim] = val
    return result


async def _audit_single_pack(employee_id: str) -> Dict[str, Any]:
    """对单个员工包构建 zip 并调沙盒审核，返回原始 audit 结果。"""
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )
    from modstore_server.package_sandbox_audit import run_package_audit_async

    materialize_employee_pack_if_missing(employee_id)
    pack_dir = modstore_library_path() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return {
            "ok": False,
            "error": f"员工包目录不存在: {employee_id}",
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }
    try:
        manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        zip_bytes = build_employee_pack_zip(employee_id, manifest)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"构建员工包失败: {exc}",
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }
    try:
        return await run_package_audit_async(zip_bytes, {"artifact": "employee_pack"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit failed employee=%s: %s", employee_id, exc)
        return {
            "ok": False,
            "error": str(exc),
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }


async def _run_five_dim_audit(
    employee_id: str,
    per_dimension_ids: Optional[Dict[str, str]] = None,
    auto_dimension_ids: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """五维合成审核：每个维度可独立指向不同员工包。

    合并优先级（后者覆盖前者）：
    1. 环境变量 ``MODSTORE_AUDIT_DIM_<DIM>_EMPLOYEE``
    2. ``auto_dimension_ids``（LLM 从评审池自动挑选，仅填补空缺）
    3. ``per_dimension_ids``（API / 人工显式指定）

    未配置的维度回退到主员工 employee_id 的静态审核得分。
    """
    env_defaults = _load_audit_dimension_env_defaults()
    effective_map: Dict[str, str] = {}
    effective_map.update(env_defaults)
    if auto_dimension_ids:
        for dim in AUDIT_DIMENSIONS:
            if str(effective_map.get(dim) or "").strip():
                continue
            v = str(auto_dimension_ids.get(dim) or "").strip()
            if v:
                effective_map[dim] = v
    if per_dimension_ids:
        effective_map.update(
            {k: v for k, v in per_dimension_ids.items() if k in AUDIT_DIMENSIONS and v}
        )

    # 找出所有需要单独审核的包（去重以避免重复 zip 构建）
    pack_ids_needed: set[str] = {employee_id}
    for dim in AUDIT_DIMENSIONS:
        eid = effective_map.get(dim, employee_id)
        pack_ids_needed.add(eid)

    # 并行构建所有需要的审核结果
    import asyncio

    raw_audits: Dict[str, Dict[str, Any]] = {}
    coros = {eid: _audit_single_pack(eid) for eid in pack_ids_needed}
    results = await asyncio.gather(*coros.values(), return_exceptions=True)
    for eid, res in zip(coros.keys(), results):
        if isinstance(res, Exception):
            raw_audits[eid] = {
                "ok": False,
                "error": str(res),
                "dimensions": {},
                "summary": {"average": 0, "pass": False},
            }
        else:
            raw_audits[eid] = res

    # 主员工审核（保留全量以保持 summary / functional_tests 等字段）
    primary_audit = raw_audits[employee_id]

    # 按维度合成 dimensions
    merged_dims: Dict[str, Any] = {}
    for dim in AUDIT_DIMENSIONS:
        target_eid = effective_map.get(dim, employee_id)
        target_audit = raw_audits.get(target_eid, primary_audit)
        dim_data = (target_audit.get("dimensions") or {}).get(dim)

        if dim_data is not None:
            entry = dict(dim_data)
            if target_eid != employee_id:
                entry["_source_employee"] = target_eid
        else:
            # 目标包无该维数据（包不存在或解压失败），回退到主员工
            fallback = (primary_audit.get("dimensions") or {}).get(dim)
            if fallback is not None:
                entry = dict(fallback)
                if target_eid != employee_id:
                    entry["reasons"] = list(entry.get("reasons") or []) + [
                        f"[分包 {target_eid} 审核失败，已回退到主员工]"
                    ]
                    entry["_source_employee"] = f"{target_eid}(fallback→{employee_id})"
            else:
                entry = {"score": 0, "reasons": ["审核数据缺失"]}
        merged_dims[dim] = entry

    # 重新计算 summary
    scores = [int(merged_dims[d].get("score") or 0) for d in AUDIT_DIMENSIONS]
    average = round(sum(scores) / len(scores), 1) if scores else 0.0
    manifest_ok = int(merged_dims.get("manifest_compliance", {}).get("score") or 0) >= 40
    orig_manifest_err = bool(
        primary_audit.get("summary", {}).get("pass") is False
        and not primary_audit.get("dimensions")
    )
    passed = average >= 60 and manifest_ok and not orig_manifest_err

    return {
        "ok": True,
        "dimensions": merged_dims,
        "functional_tests": primary_audit.get("functional_tests") or [],
        "summary": {
            "average": average,
            "pass": passed,
            "artifact": (primary_audit.get("summary") or {}).get("artifact", "employee_pack"),
            "composite": bool(effective_map),
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 公开入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def run_and_score_bench(
    employee_id: str,
    task_list: List[Dict[str, Any]],
    *,
    db: Session,
    user: User,
    bench_llm_override: Optional[Tuple[str, str]] = None,
    per_dimension_ids: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """执行全部测试任务、量化打分、五维审核，返回综合报告。

    bench_llm_override=(provider, model) 时，员工执行阶段的认知层使用该
    平台模型而非 manifest 中配置的模型（不读用户 BYOK）。

    per_dimension_ids={dim: employee_id} 时，各维度由指定员工包独立审核；
    未配置或员工包不存在的维度回退到 employee_id 主员工的静态审核结果。

    返回结构：
    {
        tasks_result: [{level, task_id, task_desc, ok, cost_tokens, duration_ms, score}],
        level_scores: {1: float, ..., 5: float},
        overall_score: float,
        audit: {...},          # run_package_audit_async 完整返回
        passed: bool,
    }
    """
    import asyncio

    tasks_result: List[Dict[str, Any]] = []
    level_results: Dict[int, List[Dict[str, Any]]] = {lv: [] for lv in range(1, 6)}

    for level_group in task_list:
        lv = int(level_group.get("level") or 0)
        if lv < 1 or lv > 5:
            continue
        for task in level_group.get("tasks") or []:
            task_id = str(task.get("id") or f"{lv}-?")
            task_desc = str(task.get("task_desc") or "").strip()
            if not task_desc:
                continue
            # 在线程中运行同步员工调用，不阻塞事件循环
            run_result = await asyncio.to_thread(
                _run_single_task, employee_id, task_desc, user.id, bench_llm_override
            )
            eff = _efficiency_factor(run_result["cost_tokens"])
            heuristic = 100.0 * (1.0 if run_result["ok"] else 0.0) * eff
            entry = {
                "level": lv,
                "task_id": task_id,
                "task_desc": task_desc,
                "ok": run_result["ok"],
                "cost_tokens": run_result["cost_tokens"],
                "duration_ms": run_result["duration_ms"],
                "heuristic_score": round(heuristic, 1),
                "score": round(heuristic, 1),
                "output_preview": run_result.get("output_preview") or "",
            }
            tasks_result.append(entry)
            level_results[lv].append(run_result)

    scoring_meta: Dict[str, Any] = {"method": "heuristic_ok_token_efficiency"}

    if bench_llm_override:
        prov, mdl = bench_llm_override
        rubric_items = [
            {
                "task_id": e["task_id"],
                "level": e["level"],
                "task_desc": e["task_desc"],
                "execution_ok": e["ok"],
                "output_excerpt": (e.get("output_preview") or "")[:1200],
            }
            for e in tasks_result
        ]
        rubric_raw, rubric_err = await _llm_rubric_scores_platform(prov, mdl, rubric_items)
        expected_ids = {e["task_id"] for e in tasks_result}
        rubric_map = _align_rubric_keys(rubric_raw, expected_ids)

        scoring_meta = {
            "method": "llm_rubric_platform",
            "provider": prov,
            "model": mdl,
            "rubric_raw_returned": len(rubric_raw),
            "rubric_aligned": len(rubric_map),
            "tasks_expected": len(expected_ids),
        }
        if rubric_err:
            scoring_meta["rubric_warning"] = rubric_err

        if rubric_map:
            missed = expected_ids - set(rubric_map.keys())
            if missed:
                scoring_meta["rubric_incomplete_task_ids"] = sorted(missed)

            for e in tasks_result:
                tid = e["task_id"]
                if tid in rubric_map:
                    e["score"] = round(rubric_map[tid], 1)
                    e["score_source"] = "llm_rubric"
                else:
                    e["score"] = round(min(float(e["heuristic_score"]), 35.0), 1)
                    e["score_source"] = "rubric_missing_penalty"

            vals = list(rubric_map.values())
            all_near_max = bool(vals) and all(float(v) >= 98.0 for v in vals)
            mostly_blank_out = sum(
                1 for e in tasks_result if len((e.get("output_preview") or "").strip()) < 15
            ) >= max(1, (len(tasks_result) + 1) // 2)
            if all_near_max and mostly_blank_out:
                scoring_meta["suspect_rubric_inflated"] = True
                for e in tasks_result:
                    if e.get("score_source") == "llm_rubric":
                        e["score"] = round(min(float(e["score"]), 55.0), 1)
                        e["score_note"] = "输出过短，抑制裁判虚高"
        else:
            scoring_meta["method"] = "heuristic_ok_token_efficiency"
            scoring_meta["rubric_failed"] = True
            for e in tasks_result:
                e["score"] = round(min(float(e["heuristic_score"]), 45.0), 1)
                e["score_source"] = "rubric_failed_capped"

        level_scores = _level_scores_from_entries(tasks_result)
        overall_score = round(_weighted_overall(level_scores), 1)
    else:
        level_scores = {
            lv: round(_score_level(results), 1) for lv, results in level_results.items()
        }
        overall_score = round(_weighted_overall(level_scores), 1)

    explicit_dims = {
        k: v
        for k, v in (per_dimension_ids or {}).items()
        if k in AUDIT_DIMENSIONS and str(v or "").strip()
    }
    auto_dims, reviewer_sel_meta = await resolve_auto_dimension_reviewers(
        employee_id,
        *_read_employee_brief(employee_id),
        bench_llm_override,
        explicit_per_dimension=explicit_dims,
    )

    audit = await _run_five_dim_audit(
        employee_id,
        explicit_dims or None,
        auto_dimension_ids=auto_dims,
    )
    audit_passed = bool(audit.get("summary", {}).get("pass", False))

    peer = await _run_pack_peer_review_optional(
        employee_id,
        db=db,
        user=user,
        bench_llm_override=bench_llm_override,
    )
    peer_blocks_pass = False
    if peer and not peer.get("skipped"):
        audit = dict(audit)
        audit["pack_peer_review"] = peer
        if _peer_review_gate_enabled() and not peer.get("skipped"):
            if not peer.get("ok"):
                peer_blocks_pass = True
            elif peer.get("missing_machine_score"):
                peer_blocks_pass = True
            elif not peer.get("pass_peer"):
                peer_blocks_pass = True

    passed = overall_score >= _PASS_OVERALL_SCORE and audit_passed and not peer_blocks_pass

    six_dimension: Optional[Dict[str, Any]] = None
    six_dimension_llm_meta: Optional[Dict[str, Any]] = None
    if bench_llm_override:
        try:
            from modstore_server.catalog_quality import pipeline_label_from_pack, run_pack_validate
            from modstore_server.employee_six_dimension import compute_six_dimension_report
            from modstore_server.employee_six_dimension_llm import (
                enrich_six_dimension_report_with_llm,
            )
            from modstore_server.mod_scaffold_runner import (
                materialize_employee_pack_if_missing,
                modstore_library_path,
            )

            materialize_employee_pack_if_missing(employee_id)
            pack_dir = modstore_library_path() / employee_id
            brief, _panel = _read_employee_brief(employee_id)
            if pack_dir.is_dir():
                pipeline_label = pipeline_label_from_pack(pack_dir, brief)
                val = await run_pack_validate(pack_dir=pack_dir, brief=brief)
                validate_errors = list(val.get("validate_errors") or [])
                baseline = compute_six_dimension_report(
                    pack_dir=pack_dir,
                    pipeline_label=pipeline_label,
                    routing_brief=brief,
                    validate_errors=validate_errors,
                    catalog_registered=False,
                    employee_target="pack_only",
                    standalone_smoke_ok=True,
                )
                bench_summary = {
                    "overall_score": overall_score,
                    "level_scores": level_scores,
                    "tasks_total": len(tasks_result),
                    "tasks_ok": sum(1 for e in tasks_result if e.get("ok")),
                    "sample_tasks": [
                        {
                            "level": e.get("level"),
                            "ok": e.get("ok"),
                            "score": e.get("score"),
                            "task_desc": (e.get("task_desc") or "")[:120],
                        }
                        for e in tasks_result[:6]
                    ],
                }
                six_dimension, six_dimension_llm_meta = await enrich_six_dimension_report_with_llm(
                    baseline,
                    pack_dir=pack_dir,
                    target_employee_id=employee_id,
                    pipeline_label=pipeline_label,
                    routing_brief=brief,
                    validate_errors=validate_errors,
                    bench_summary=bench_summary,
                    user_id=int(getattr(user, "id", 0) or 0),
                    bench_llm_override=bench_llm_override,
                    require_llm=True,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("bench six_dimension LLM failed for %s: %s", employee_id, exc)
            six_dimension_llm_meta = {"llm_error": str(exc)[:300]}

    out: Dict[str, Any] = {
        "tasks_result": tasks_result,
        "level_scores": level_scores,
        "overall_score": overall_score,
        "audit": audit,
        "passed": passed,
        "scoring": scoring_meta,
        "reviewer_selection": reviewer_sel_meta,
        "six_dimension": six_dimension,
        "six_dimension_llm_meta": six_dimension_llm_meta,
    }
    return out
