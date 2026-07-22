"""员工执行验证（10 项成熟度第 5 项「会验证」）。

做完必须拿证据说话：哪个测试过了、哪个文件真的改了、哪个接口 200、
哪个服务 active。不能只说"已完成"。

输入：employee_id + task + reasoning（cognition 输出）+ result（actions 输出）+ config
输出：
  {
    "checks": [
        {"name": "files_changed_exist", "ok": True, "evidence": "src/main.py 已存在 (1234B)"},
        {"name": "tests_reported", "ok": True, "evidence": "tests_passed=5 tests_failed=0"},
        {"name": "status_honest", "ok": True, "evidence": "status=success"},
        {"name": "summary_provided", "ok": True, "evidence": "完成 X 修复"},
    ],
    "ok_count": N,
    "total_count": M,
    "passed": bool,  # 全部通过
    "summary": "全部通过" or "X 项失败：..."
  }
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _try_parse_json_object(raw: Any) -> Dict[str, Any]:
    """Parse a final JSON object while tolerating model reasoning wrappers.

    Reasoning models such as MiniMax may prefix their actual answer with a
    ``<think>...</think>`` block.  We prefer the last object that carries the
    verification contract instead of interpreting arbitrary JSON mentioned in
    the reasoning trace as the result.
    """

    if not isinstance(raw, str) or not raw.strip():
        return {}
    raw = re.sub(r"<think\b[^>]*>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    # 1. 直接 json.loads
    try:
        v = json.loads(raw)
        if isinstance(v, dict):
            return v
    except (ValueError, TypeError):
        pass
    # 2. ```json ... ``` 块（贪婪）
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(1))
            if isinstance(v, dict):
                return v
        except (ValueError, TypeError):
            pass
    # 3. 剥 markdown 后整体
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
        try:
            v = json.loads(stripped)
            if isinstance(v, dict):
                return v
        except (ValueError, TypeError):
            pass
    # 4. 模型可能在正文前后附加自然语言；逐个 raw_decode，优先选择
    # 带 status + summary/report 的最后一个对象。
    decoder = json.JSONDecoder()
    candidates: List[tuple[int, int, Dict[str, Any]]] = []
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except (ValueError, TypeError):
            continue
        if not isinstance(value, dict):
            continue
        score = sum(
            (
                2 if str(value.get("status") or "").strip() else 0,
                2 if str(value.get("summary") or value.get("report") or "").strip() else 0,
                1 if value.get("evidence") is not None else 0,
            )
        )
        candidates.append((score, index, value))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1]))[2]
    return {}


def _try_parse_llm_output(reasoning: Dict[str, Any]) -> Dict[str, Any]:
    """从 reasoning["reasoning"] 字符串里解析 LLM 输出 JSON。"""

    if not isinstance(reasoning, dict):
        return {}
    return _try_parse_json_object(reasoning.get("reasoning") or "")


def _try_parse_handler_output(result: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the tool-using agent's final answer as verification evidence."""

    outputs = result.get("outputs") if isinstance(result, dict) else []
    if not isinstance(outputs, list):
        return {}
    # The agent handler is authoritative for tool-driven work and normally
    # runs before generic fallbacks. Iterate in reverse so the final handler
    # wins when multiple outputs carry structured contracts.
    for output in reversed(outputs):
        if not isinstance(output, dict):
            continue
        for key in ("output", "answer", "summary", "response"):
            raw = output.get(key)
            if isinstance(raw, dict):
                return raw
            parsed = _try_parse_json_object(raw)
            if parsed:
                return parsed
    return {}


def _extract_changed_files(llm_out: Dict[str, Any], result: Dict[str, Any]) -> List[str]:
    """从 LLM 输出和 handler output 里抽 files_changed。"""
    files: List[str] = []
    # 1. LLM 输出顶层
    for key in ("files_changed", "changed_files", "file_path"):
        v = llm_out.get(key)
        if isinstance(v, list):
            files.extend(str(x) for x in v if str(x).strip())
        elif isinstance(v, str) and v.strip():
            files.append(v.strip())
    # 2. handler output 字段（llm_md/echo handler 把 LLM 输出原样放在 output 字段）
    outputs = result.get("outputs") if isinstance(result, dict) else []
    if isinstance(outputs, list):
        for out in outputs:
            if not isinstance(out, dict):
                continue
            out_field = out.get("output")
            if isinstance(out_field, str) and out_field.strip().startswith("{"):
                try:
                    parsed = json.loads(out_field)
                    if isinstance(parsed, dict):
                        for key in ("files_changed", "changed_files"):
                            v = parsed.get(key)
                            if isinstance(v, list):
                                files.extend(str(x) for x in v if str(x).strip())
                except (ValueError, TypeError):
                    pass
    # 去重保序
    seen: set[str] = set()
    out_files: List[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out_files.append(f)
    return out_files


def _check_files_changed_exist(
    files: List[str],
    project_root: Optional[Path],
) -> Dict[str, Any]:
    """检查 LLM 声称改的文件是否真的存在。"""
    if not files:
        return {
            "name": "files_changed_exist",
            "ok": True,
            "evidence": "未声明改动文件（只读任务）",
            "skipped": True,
        }
    if not project_root:
        return {
            "name": "files_changed_exist",
            "ok": False,
            "evidence": f"声明改了 {len(files)} 个文件，但未提供 project_root 无法验证",
        }
    existing: List[str] = []
    missing: List[str] = []
    for f in files[:10]:  # 最多检查 10 个，避免大列表
        # 优先按相对路径检查
        p = Path(f)
        if not p.is_absolute():
            p = Path(project_root) / f
        if p.exists():
            try:
                size = p.stat().st_size
                existing.append(f"{f} ({size}B)")
            except OSError:
                existing.append(f)
        else:
            missing.append(f)
    if missing:
        return {
            "name": "files_changed_exist",
            "ok": False,
            "evidence": f"声明改了但找不到：{', '.join(missing[:5])}（共 {len(missing)} 个缺失）",
        }
    return {
        "name": "files_changed_exist",
        "ok": True,
        "evidence": f"声明改的 {len(existing)} 个文件都存在：{', '.join(existing[:3])}{'...' if len(existing) > 3 else ''}",
    }


def _check_tests_reported(llm_out: Dict[str, Any], task: str) -> Dict[str, Any]:
    """如果 task 涉及测试，检查 LLM 是否报告了测试结果。"""
    task_lower = str(task or "").lower()
    # "验收可测试" describes the quality of an acceptance criterion; it does
    # not claim that this execution ran a test suite.  Require an explicit test
    # execution noun/verb so planning and intent-analysis receipts are not
    # rejected by a substring match.
    chinese_test_execution = any(
        phrase in task_lower
        for phrase in (
            "执行测试",
            "运行测试",
            "跑测试",
            "测试用例",
            "单元测试",
            "集成测试",
            "回归测试",
            "测试通过",
            "测试失败",
            "测试结果",
            "单测",
        )
    )
    english_test_execution = bool(
        re.search(r"\b(?:test|tests|testing|qa|tdd|coverage)\b", task_lower)
    )
    involves_tests = chinese_test_execution or english_test_execution
    if not involves_tests:
        return {
            "name": "tests_reported",
            "ok": True,
            "evidence": "任务不涉及测试，跳过",
            "skipped": True,
        }
    # 检查 LLM 输出里是否有 tests_passed / tests_failed / coverage_pct 字段
    tests_passed = llm_out.get("tests_passed")
    tests_failed = llm_out.get("tests_failed")
    coverage = llm_out.get("coverage_pct") or llm_out.get("coverage")
    if tests_passed is None and tests_failed is None and coverage is None:
        return {
            "name": "tests_reported",
            "ok": False,
            "evidence": "任务涉及测试，但 LLM 输出未提供 tests_passed/tests_failed/coverage 字段",
        }
    parts: List[str] = []
    if tests_passed is not None:
        parts.append(f"tests_passed={tests_passed}")
    if tests_failed is not None:
        parts.append(f"tests_failed={tests_failed}")
    if coverage is not None:
        parts.append(f"coverage={coverage}%")
    return {
        "name": "tests_reported",
        "ok": True,
        "evidence": " ".join(parts) or "未提供详细数字",
    }


def _check_status_honest(llm_out: Dict[str, Any]) -> Dict[str, Any]:
    """检查 LLM 输出的 status 是否诚实（不是 unknown/pending）。"""
    status = str(llm_out.get("status") or "").strip().lower()
    if not status:
        return {
            "name": "status_honest",
            "ok": False,
            "evidence": "LLM 输出未提供 status 字段",
        }
    bad_statuses = {"unknown", "pending", "tbd", "?"}
    if status in bad_statuses:
        return {
            "name": "status_honest",
            "ok": False,
            "evidence": f"status={status}（不诚实状态）",
        }
    return {
        "name": "status_honest",
        "ok": True,
        "evidence": f"status={status}",
    }


def _check_summary_provided(llm_out: Dict[str, Any]) -> Dict[str, Any]:
    """检查 LLM 是否提供了 summary（不是空话）。"""
    summary = str(llm_out.get("summary") or llm_out.get("report") or "").strip()
    if not summary:
        return {
            "name": "summary_provided",
            "ok": False,
            "evidence": "LLM 输出未提供 summary/report 字段",
        }
    if len(summary) < 10:
        return {
            "name": "summary_provided",
            "ok": False,
            "evidence": f"summary 过短（{len(summary)} 字）：{summary[:80]}",
        }
    return {
        "name": "summary_provided",
        "ok": True,
        "evidence": f"summary 长度 {len(summary)} 字：{summary[:80]}{'...' if len(summary) > 80 else ''}",
    }


def _check_handler_outputs_nonempty(result: Dict[str, Any]) -> Dict[str, Any]:
    """检查 handler 是否真的产生了 output（不是空跑）。"""
    outputs = result.get("outputs") if isinstance(result, dict) else []
    if not isinstance(outputs, list) or not outputs:
        return {
            "name": "handler_outputs_nonempty",
            "ok": False,
            "evidence": "未执行任何 handler",
        }
    nonempty = 0
    empty = 0
    for o in outputs:
        if not isinstance(o, dict):
            continue
        # Handler families expose their real result under different keys:
        # llm_md/echo -> output, agent -> summary, some direct handlers ->
        # answer/response.  Treating agent summaries as empty made every
        # read-only agent burn-in unverifiable even after a real tool call.
        out_str = str(
            o.get("output") or o.get("answer") or o.get("summary") or o.get("response") or ""
        ).strip()
        if out_str:
            nonempty += 1
        else:
            empty += 1
    if nonempty == 0:
        return {
            "name": "handler_outputs_nonempty",
            "ok": False,
            "evidence": f"{len(outputs)} 个 handler 全部空 output",
        }
    return {
        "name": "handler_outputs_nonempty",
        "ok": True,
        "evidence": f"{nonempty}/{len(outputs)} 个 handler 有 output（{empty} 个空）",
    }


def run_verification(
    *,
    employee_id: str,
    task: str,
    reasoning: Dict[str, Any],
    result: Dict[str, Any],
    config: Dict[str, Any],
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """程序化验证员工执行结果。

    返回 checks 列表 + ok_count/total_count/passed/summary。
    """
    llm_out = _try_parse_llm_output(reasoning if isinstance(reasoning, dict) else {})
    handler_out = _try_parse_handler_output(result if isinstance(result, dict) else {})
    if handler_out:
        # Keep explicit cognition fields, but fill its missing contract from
        # the actual tool-using handler's final answer.
        llm_out = {**handler_out, **llm_out}
    files = _extract_changed_files(llm_out, result if isinstance(result, dict) else {})

    checks: List[Dict[str, Any]] = [
        _check_files_changed_exist(files, project_root),
        _check_tests_reported(llm_out, task),
        _check_status_honest(llm_out),
        _check_summary_provided(llm_out),
        _check_handler_outputs_nonempty(result if isinstance(result, dict) else {}),
    ]

    # 过滤掉 skipped 的（不算 total）
    real_checks = [c for c in checks if not c.get("skipped")]
    ok_count = sum(1 for c in real_checks if c.get("ok"))
    total_count = len(real_checks)
    failed = [c for c in real_checks if not c.get("ok")]

    if not failed:
        summary_text = f"全部 {total_count} 项验证通过"
    else:
        summary_text = f"{len(failed)}/{total_count} 项失败：" + "; ".join(
            f"{c['name']}({c.get('evidence', '')[:50]})" for c in failed[:3]
        )

    return {
        "checks": checks,
        "ok_count": ok_count,
        "total_count": total_count,
        "passed": len(failed) == 0,
        "failed_count": len(failed),
        "summary": summary_text,
        "files_declared": files,
    }


__all__ = ["run_verification"]
