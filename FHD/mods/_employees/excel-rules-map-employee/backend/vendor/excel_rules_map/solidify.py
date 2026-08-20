"""固化循环：LLM 把「业务转换规则」写成 Python 脚本，金样对账通过后固化。

窄接口契约（用户拍板方案 A）：LLM 只生成 **records 生产者**——

    def produce_records(source_workbook: dict, rules: dict) -> list[dict]

「哪里写、怎么写」仍由 compile/写入员/质检员的白盒管道负责；LLM 代码面积
最小化，且每一轮产出都被金样反读 records（``golden.extract_records_from_workbook``）
确定性对账。循环：生成 → 静态安全检查 → 沙箱执行 → 结构校验 → 金样 diff →
通过则固化（脚本 + sha256 + 迭代证据），不通过把 diff/异常喂回 LLM 重写。

固化后每月运行零 LLM：固化脚本 + compile + write + QC 全确定性。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.mod_sdk.errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

from .golden import diff_records

CallLLM = Callable[..., Awaitable[Dict[str, Any]]]

DEFAULT_MAX_ITERATIONS = 4
_MAX_SOURCE_ROWS = 30
_MAX_EXPECTED_SAMPLES = 20

# 与宿主 run_sandboxed_python 同源的黑名单：固化脚本只允许纯计算。
_FORBIDDEN_RE = re.compile(
    r"\b(import\s+subprocess|import\s+socket|import\s+requests|import\s+urllib"
    r"|__import__|eval\s*\(|exec\s*\(|os\.system|shutil\.|open\s*\()"
)

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


class SolidifyError(ValueError):
    """固化输入不满足前置条件（fail-fast）。"""


def _extract_code(content: str) -> str:
    text = str(content or "").strip()
    m = _CODE_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    if "def produce_records" in text:
        return text
    return ""


def _static_check(code: str) -> str:
    if not code:
        return "LLM 输出中未找到 Python 代码（需要 ```python 代码块，含 def produce_records）"
    if "def produce_records" not in code:
        return "脚本缺少 def produce_records(source_workbook, rules) 定义"
    m = _FORBIDDEN_RE.search(code)
    if m:
        return f"脚本包含禁止的操作：{m.group(0)!r}（只允许标准库纯计算）"
    return ""


def _load_and_run(
    code: str,
    source_workbook: Dict[str, Any],
    rules: Dict[str, Any],
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    namespace: Dict[str, Any] = {"__name__": "solidified_transform"}
    try:
        exec(compile(code, "<solidified_transform>", "exec"), namespace)  # noqa: S102
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return None, f"脚本加载失败：{type(exc).__name__}: {exc}"
    fn = namespace.get("produce_records")
    if not callable(fn):
        return None, "脚本执行后未得到可调用的 produce_records"
    try:
        records = fn(source_workbook, rules)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return None, f"produce_records 执行异常：{type(exc).__name__}: {exc}"
    if not isinstance(records, list):
        return None, f"produce_records 必须返回 list，得到 {type(records).__name__}"
    return records, ""


def _validate_records_shape(records: List[Any], rules: Dict[str, Any]) -> str:
    bands = set((rules.get("bands") or {}).keys())
    calendar = (rules.get("template_map") or {}).get("calendar") or {}
    day_count = int(calendar.get("day_count") or 0)
    for i, r in enumerate(records[:2000]):
        if not isinstance(r, dict):
            return f"records[{i}] 必须是对象"
        if not str(r.get("key") or "").strip():
            return f"records[{i}] 缺少 key"
        if r.get("cells") is not None:
            continue
        try:
            day = int(r.get("day"))
        except (TypeError, ValueError):
            return f"records[{i}] day 非整数：{r.get('day')!r}"
        if day_count and (day < 1 or day > day_count):
            return f"records[{i}] day 越界：{day}（1..{day_count}）"
        band = str(r.get("band") or "").strip()
        if bands and band not in bands:
            return f"records[{i}] band 未定义：{band!r}（可用 {sorted(bands)}）"
        entries = r.get("entries")
        if not isinstance(entries, list) or not entries:
            return f"records[{i}] entries 缺失或为空"
    return ""


def _source_digest(source_workbook: Dict[str, Any]) -> Dict[str, Any]:
    """源表摘要（LLM 输入）：sheet 名 + 表头 + 前 N 行展平数据。"""
    out: List[Dict[str, Any]] = []
    for sheet in (source_workbook.get("sheets") or [])[:3]:
        out.append(
            {
                "name": sheet.get("name"),
                "header_row": sheet.get("header_row"),
                "columns": (sheet.get("columns") or [])[:40],
                "rows_preview": (sheet.get("rows") or [])[:_MAX_SOURCE_ROWS],
                "row_count": sheet.get("row_count"),
            }
        )
    return {"sheets": out, "source": source_workbook.get("source")}


def _rules_digest(rules: Dict[str, Any]) -> Dict[str, Any]:
    tm = rules.get("template_map") or {}
    return {
        "bands": rules.get("bands"),
        "calendar": tm.get("calendar"),
        "block_keys_sample": [b.get("key") for b in (tm.get("blocks") or []) if b.get("key")][:15],
        "policy": rules.get("policy"),
    }


def build_solidify_prompt(
    source_workbook: Dict[str, Any],
    rules: Dict[str, Any],
    expected_records: List[Dict[str, Any]],
    business_context: str,
    feedback: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    system = (
        "你是数据转换工程师。写一个纯计算的 Python 脚本，定义：\n"
        "def produce_records(source_workbook: dict, rules: dict) -> list[dict]\n"
        'records 契约：[{"key": str, "day": int, "band": str, '
        '"entries": [{"symbol": str, "value": float|None}]}]；'
        "band 必须取自 rules['bands'] 的键；day 在 rules['template_map']['calendar']['day_count'] 内；"
        "key 必须与模板块键一致。\n"
        "source_workbook 是读取员的 workbook.json（sheets[].columns/rows 为展平数据行）。\n"
        "只允许标准库纯计算（re/datetime/math/collections 等）；禁止文件、网络、子进程、eval/exec。\n"
        "只输出一个 ```python 代码块，不要解释文字。"
    )
    payload: Dict[str, Any] = {
        "源表摘要": _source_digest(source_workbook),
        "规则摘要": _rules_digest(rules),
        "金样期望records样例": expected_records[:_MAX_EXPECTED_SAMPLES],
        "业务规则说明": business_context or "（未提供，请从金样样例归纳规律）",
    }
    if feedback:
        payload["上一轮失败反馈"] = feedback
        payload["要求"] = (
            "修正脚本使金样对账全绿：missing 槽要补齐，mismatched 槽要与期望一致，extra 槽要去掉。"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


async def solidify_transform(
    source_workbook: Dict[str, Any],
    rules: Dict[str, Any],
    expected_records: List[Dict[str, Any]],
    call_llm: CallLLM,
    *,
    business_context: str = "",
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> Dict[str, Any]:
    """返回 {ok, script, script_sha256, records, diff, iterations: [..]}。"""
    if not expected_records:
        raise SolidifyError(
            "金样期望 records 为空：请提供金样输出（经读取员转 JSON）或期望 records。"
        )
    iterations: List[Dict[str, Any]] = []
    feedback: Optional[Dict[str, Any]] = None
    script = ""
    records: Optional[List[Dict[str, Any]]] = None
    diff: Optional[Dict[str, Any]] = None

    for attempt in range(1, max_iterations + 1):
        t0 = time.perf_counter()
        it: Dict[str, Any] = {"attempt": attempt}
        try:
            resp = await call_llm(
                build_solidify_prompt(
                    source_workbook, rules, expected_records, business_context, feedback
                ),
                max_tokens=4000,
                temperature=0.1,
            )
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            it["error"] = f"LLM 调用异常：{exc}"
            iterations.append(it)
            feedback = {"error": it["error"]}
            continue
        if not resp or not resp.get("ok"):
            it["error"] = f"LLM 不可用：{(resp or {}).get('error') or 'no response'}"
            iterations.append(it)
            feedback = {"error": it["error"]}
            continue

        script = _extract_code(str(resp.get("content") or ""))
        it["script_sha256"] = hashlib.sha256(script.encode("utf-8")).hexdigest() if script else ""

        why = _static_check(script)
        if why:
            it["error"] = f"静态检查未通过：{why}"
            iterations.append(it)
            feedback = {"error": it["error"]}
            continue

        records, why = _load_and_run(script, source_workbook, rules)
        if why:
            it["error"] = why
            iterations.append(it)
            feedback = {"error": why}
            continue

        why = _validate_records_shape(records, rules)
        if why:
            it["error"] = f"records 契约校验失败：{why}"
            iterations.append(it)
            feedback = {"error": it["error"], "records_preview": records[:5]}
            continue

        diff = diff_records(records, expected_records)
        it["diff_stats"] = diff["stats"]
        it["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        iterations.append(it)
        if diff["ok"]:
            return {
                "ok": True,
                "script": script,
                "script_sha256": it["script_sha256"],
                "records": records,
                "diff": diff,
                "iterations": iterations,
            }
        feedback = {"金样对账未通过": diff["stats"], "差异样本": diff["samples"]}

    return {
        "ok": False,
        "script": script,
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest() if script else "",
        "records": records,
        "diff": diff,
        "iterations": iterations,
    }
