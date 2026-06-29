"""员工人话汇报生成器（10 项成熟度要求第 10 项 — 会说人话）。

旧管道返回 JSON（result.reasoning 字符串是 LLM 输出 JSON），老板看不懂。
本模块把整个执行结果转成 Markdown 四段式汇报：
  1. 我做了什么 — task + 角色 + 耗时 + tokens
  2. 发现什么 — 输入类型 + 记忆 + LLM 推理摘要
  3. 修了什么 — handlers 执行了什么、改了哪些文件、路径检查通过没
  4. 还剩什么 — 失败的 handler、Phase-D 待回答的问题
  5. 你要不要确认 — 下一步建议 / 待老板回答的问题

挂载点：employee_executor.execute_employee_task 末尾，把 report 写到 result["human_report"]。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _safe_str(x: Any, max_len: int = 200) -> str:
    s = str(x or "").strip()
    if not s:
        return ""
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _try_parse_llm_json(reasoning_str: str) -> Dict[str, Any]:
    """尝试把 LLM 输出（JSON 字符串）解析成 dict；失败返回空 dict。"""
    s = (reasoning_str or "").strip()
    if not s:
        return {}
    # 直接 loads
    try:
        out = json.loads(s)
        if isinstance(out, dict):
            return out
    except (ValueError, TypeError):
        pass
    # ```json ... ``` 块
    import re

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        try:
            out = json.loads(m.group(1))
            if isinstance(out, dict):
                return out
        except (ValueError, TypeError):
            pass
    return {}


def _format_handlers_summary(result: Dict[str, Any]) -> str:
    """handler 执行情况一行话讲完。"""
    outputs = result.get("outputs") or []
    if not outputs:
        return "无 handler 执行"
    lines = []
    for o in outputs:
        if not isinstance(o, dict):
            continue
        name = _safe_str(o.get("handler"), 40) or "unknown"
        ok = o.get("ok")
        status = o.get("status") or o.get("status_code")
        err = _safe_str(o.get("error"), 80)
        if ok is True:
            line = f"  - {name}: ✅ 成功"
        elif ok is False:
            line = f"  - {name}: ❌ 失败"
            if err:
                line += f"（{err}）"
        elif status:
            line = f"  - {name}: status={status}"
            if err:
                line += f"（{err}）"
        else:
            line = f"  - {name}: 已执行"
        lines.append(line)
    return "\n".join(lines) if lines else "无 handler 执行"


def _format_changed_files(result: Dict[str, Any], path_guard: Optional[Dict[str, Any]]) -> str:
    """改动文件 + path_guard 检查结果。"""
    pg = path_guard or {}
    if not pg.get("checked"):
        return "未配置路径边界（workspace_policy.scope_globs），未做硬约束检查"
    all_files = pg.get("all_changed_files") or []
    if not all_files:
        return "本次未改动任何文件（只读任务或 handler 无文件输出）"
    violations = pg.get("violations") or []
    if violations:
        vlist = "\n".join(
            f"  - ❌ {v.get('path','')}（{v.get('reason','')}）"
            for v in violations[:5]
            if isinstance(v, dict)
        )
        return f"检测到 {len(all_files)} 个文件改动，其中 {len(violations)} 个越权：\n{vlist}"
    return f"检测到 {len(all_files)} 个文件改动，全部在 scope_globs 范围内 ✅"


def _format_phase_d(reasoning: Dict[str, Any]) -> str:
    """Phase-D 状态：员工有没有向老板提问、问的什么、答了没。"""
    if not isinstance(reasoning, dict):
        return ""
    triggered = reasoning.get("_phase_d_triggered")
    if not triggered:
        return ""
    q = _safe_str(reasoning.get("_phase_d_question"), 200)
    ans = reasoning.get("human_answer") or reasoning.get("_human_answer", {})
    if isinstance(ans, dict):
        ans_status = ans.get("status") or ""
        ans_text = _safe_str(ans.get("answer"), 100)
        if ans_status == "answered":
            return f"已问老板：「{q}」\n老板回复：{ans_text}"
        elif ans_status == "expired":
            return f"已问老板：「{q}」\n超时未答，员工已自行继续。"
        else:
            return f"已问老板：「{q}」\n等待回复中..."
    return f"已问老板：「{q}」"


def _format_handoff(result: Dict[str, Any]) -> str:
    """handoff 转交结果：转给谁、原因、协作线程 ID、是否被跳过。"""
    h = result.get("handoff") if isinstance(result, dict) else None
    if not isinstance(h, dict):
        return ""
    tgt = _safe_str(h.get("to"), 60)
    src = _safe_str(h.get("from"), 60)
    reason = _safe_str(h.get("reason"), 120)
    skipped = h.get("skipped")
    skip_reason = _safe_str(h.get("skip_reason"), 120)
    thread_id = h.get("thread_id") or 0
    msg_id = h.get("message_id") or 0

    if skipped:
        return (
            f"⚠️ 转交被跳过：{_safe_str(h.get('to'), 40) or '（空）'} — {skip_reason or '未知原因'}"
        )
    if not h.get("ok"):
        return f"❌ 转交失败：{skip_reason or '未知原因'}"

    lines = [f"✅ 已转交给 @{tgt}（协作线程 #{thread_id}，消息 #{msg_id}）"]
    if reason:
        lines.append(f"  - 原因：{reason}")
    return "\n".join(lines)


def _format_evolution(result: Dict[str, Any]) -> str:
    """evolution_signal 信号：失败次数是否达到阈值、是否需要 prompt 进化。"""
    e = result.get("evolution_signal") if isinstance(result, dict) else None
    if not isinstance(e, dict):
        return ""
    needed = e.get("needed")
    fail_count = e.get("fail_count", 0)
    min_failures = e.get("min_failures", 3)
    lookback = e.get("lookback_hours", 24)
    suggestion = _safe_str(e.get("suggestion"), 240)
    recent = e.get("recent_failures") or []
    if not isinstance(recent, list):
        recent = []

    if needed:
        lines = [f"⚠️ 学习信号：最近 {lookback}h 失败 {fail_count} 次（>= 阈值 {min_failures}），需要 prompt 进化"]
    else:
        lines = [f"学习信号：最近 {lookback}h 失败 {fail_count} 次（< 阈值 {min_failures}），暂不需要进化"]
    if suggestion:
        lines.append(f"  - {suggestion}")
    for f in recent[:3]:
        if not isinstance(f, dict):
            continue
        task_p = _safe_str(f.get("task"), 80)
        fkind = _safe_str(f.get("failure_kind"), 30)
        err_p = _safe_str(f.get("error_preview"), 80)
        line = f"  - 失败任务：{task_p}"
        if fkind:
            line += f" [{fkind}]"
        if err_p:
            line += f" — {err_p}"
        lines.append(line)
    return "\n".join(lines)


def _format_verification(result: Dict[str, Any]) -> str:
    """verification 检查结果：哪些验证项通过/失败，证据是什么。"""
    v = result.get("verification") if isinstance(result, dict) else None
    if not isinstance(v, dict):
        return ""
    checks = v.get("checks") or []
    if not checks:
        return ""
    ok_count = v.get("ok_count", 0)
    total_count = v.get("total_count", 0)
    failed_count = v.get("failed_count", 0)
    summary = _safe_str(v.get("summary"), 200)
    lines = [f"程序化验证（{ok_count}/{total_count} 通过，{failed_count} 失败）：{summary}"]
    for c in checks:
        if not isinstance(c, dict):
            continue
        name = _safe_str(c.get("name"), 40)
        ok = c.get("ok")
        skipped = c.get("skipped")
        evidence = _safe_str(c.get("evidence"), 100)
        if skipped:
            icon = "⏭️"
        elif ok:
            icon = "✅"
        else:
            icon = "❌"
        lines.append(f"  - {icon} {name}：{evidence}")
    return "\n".join(lines)


def build_human_report(
    *,
    employee_id: str,
    task: str,
    reasoning: Dict[str, Any],
    result: Dict[str, Any],
    duration_ms: float,
    llm_tokens: int,
    exec_status: str,
    perceived: Optional[Dict[str, Any]] = None,
    memory: Optional[Dict[str, Any]] = None,
    cognition_error: str = "",
) -> str:
    """生成 Markdown 四段式人话汇报。

    参数：
      employee_id: 员工 ID
      task: 原始任务
      reasoning: _cognition_real 返回的 dict（含 reasoning/memory/input/...）
      result: _actions_real 返回的 dict（含 outputs/path_guard/...）
      duration_ms / llm_tokens: 执行指标
      exec_status: success | handler_failed | blocked_by_risk_gate | blocked_by_path_guard
      perceived: _perception_real 输出（可选，用于「发现什么」）
      memory: _memory_real 输出（可选，用于「发现什么」）
      cognition_error: 认知层错误（如果有）

    返回：Markdown 字符串
    """
    # ── 1. 我做了什么 ──
    task_preview = _safe_str(task, 200)
    sec1 = [
        f"## 我做了什么",
        f"- 员工：`{employee_id}`",
        f"- 任务：{task_preview}" if task_preview else "- 任务：（空）",
        f"- 耗时：{duration_ms:.0f}ms，消耗 {llm_tokens} tokens",
        f"- 状态：{exec_status}",
    ]

    # ── 2. 发现什么 ──
    findings = []
    if isinstance(perceived, dict):
        ptype = _safe_str(perceived.get("type"), 30)
        findings.append(f"- 输入类型：{ptype or 'text'}")
        # 10 项成熟度第 3 项「会判断任务」— 显示任务分类
        ni = perceived.get("normalized_input") if isinstance(perceived.get("normalized_input"), dict) else None
        tc = ni.get("_task_classification") if isinstance(ni, dict) else None
        if isinstance(tc, dict):
            cat = _safe_str(tc.get("category"), 30)
            conf = tc.get("confidence", 0.0)
            tc_reason = _safe_str(tc.get("reason"), 120)
            should_ho = tc.get("should_handoff")
            icon = "🔁" if should_ho else "🏷️"
            findings.append(f"- {icon} 任务分类：{cat or 'unknown'}（置信度 {conf}）— {tc_reason}")
            if should_ho:
                findings.append("- ⚠️ 任务分类提示转交，可考虑 handoff_to")
    if isinstance(memory, dict):
        lt = memory.get("long_term") or {}
        if isinstance(lt, dict):
            if lt.get("error"):
                findings.append(f"- 长期记忆：报错（{_safe_str(lt.get('error'), 80)}）")
            else:
                memories = lt.get("memories") or []
                findings.append(f"- 长期记忆：检索到 {len(memories) if isinstance(memories, list) else 0} 条相关项")
        sess = memory.get("session") or {}
        if isinstance(sess, dict):
            recent = sess.get("recent_tasks") or []
            findings.append(f"- 短期记忆：最近 {len(recent) if isinstance(recent, list) else 0} 条任务记录")
    if cognition_error:
        findings.append(f"- ⚠️ 认知层报错：{_safe_str(cognition_error, 200)}")
    # LLM 推理摘要：解析 reasoning 字符串里的 summary/warnings 字段
    if isinstance(reasoning, dict):
        llm_str = reasoning.get("reasoning") or ""
        parsed = _try_parse_llm_json(llm_str)
        if parsed:
            if parsed.get("summary"):
                findings.append(f"- LLM 摘要：{_safe_str(parsed.get('summary'), 200)}")
            warns = parsed.get("warnings")
            if isinstance(warns, list) and warns:
                wlist = "; ".join(_safe_str(w, 80) for w in warns[:3])
                findings.append(f"- LLM 警告：{wlist}")
            elif isinstance(warns, str) and warns:
                findings.append(f"- LLM 警告：{_safe_str(warns, 200)}")
        else:
            # 非 JSON 输出，截前 200 字
            excerpt = _safe_str(llm_str, 200)
            if excerpt:
                findings.append(f"- LLM 输出：{excerpt}")

    sec2 = ["## 发现什么"] + (findings if findings else ["- （无明显发现）"])

    # ── 3. 修了什么 ──
    handlers_summary = _format_handlers_summary(result if isinstance(result, dict) else {})
    path_guard = result.get("path_guard") if isinstance(result, dict) else None
    files_summary = _format_changed_files(result if isinstance(result, dict) else {}, path_guard)
    verification_summary = _format_verification(result if isinstance(result, dict) else {})
    evolution_summary = _format_evolution(result if isinstance(result, dict) else {})
    handoff_summary = _format_handoff(result if isinstance(result, dict) else {})
    sec3 = [
        "## 修了什么",
        handlers_summary,
        "",
        f"路径边界检查：",
        files_summary,
    ]
    if verification_summary:
        sec3 += ["", f"程序化验证：", verification_summary]
    if evolution_summary:
        sec3 += ["", f"学习信号：", evolution_summary]
    if handoff_summary:
        sec3 += ["", f"任务转交：", handoff_summary]

    # ── 4. 还剩什么 ──
    remainders = []
    if exec_status == "handler_failed":
        outputs = result.get("outputs") or [] if isinstance(result, dict) else []
        failed = [
            o for o in outputs
            if isinstance(o, dict) and (o.get("ok") is False or o.get("error"))
        ]
        if failed:
            remainders.append(f"- {len(failed)} 个 handler 失败，详见上方「修了什么」")
    elif exec_status == "blocked_by_risk_gate":
        remainders.append("- ⚠️ 整体被风险门控拦截，未执行任何 handler")
    elif exec_status == "blocked_by_path_guard":
        remainders.append("- ⚠️ 改动文件越权，被路径边界拦截")
    # verification 失败项
    v = result.get("verification") if isinstance(result, dict) else None
    if isinstance(v, dict) and not v.get("passed"):
        failed_count = v.get("failed_count", 0)
        v_summary = _safe_str(v.get("summary"), 150)
        remainders.append(f"- ⚠️ 程序化验证有 {failed_count} 项失败：{v_summary}")
    # evolution_signal 需要进化
    evo = result.get("evolution_signal") if isinstance(result, dict) else None
    if isinstance(evo, dict) and evo.get("needed"):
        evo_fail = evo.get("fail_count", 0)
        remainders.append(
            f"- ⚠️ 学习信号触发：最近 {evo.get('lookback_hours', 24)}h 失败 {evo_fail} 次，"
            f"建议运行 prompt evolution（admin API: {evo.get('evolution_api','')}）"
        )
    # handoff 任务转交
    ho = result.get("handoff") if isinstance(result, dict) else None
    if isinstance(ho, dict):
        tgt = _safe_str(ho.get("to"), 40)
        if ho.get("skipped"):
            sr = _safe_str(ho.get("skip_reason"), 100)
            remainders.append(f"- ⚠️ 转交被跳过：{tgt or '（空）'} — {sr}")
        elif ho.get("ok"):
            tid = ho.get("thread_id") or 0
            mid = ho.get("message_id") or 0
            remainders.append(
                f"- ✅ 已 @{tgt} 转交任务（协作线程 #{tid}，消息 #{mid}），"
                "等对方判断是否接手"
            )
        else:
            remainders.append(f"- ❌ 转交 @{tgt} 失败：{_safe_str(ho.get('skip_reason'), 100)}")
    # Phase-D 待回答
    pd_text = _format_phase_d(reasoning if isinstance(reasoning, dict) else {})
    if pd_text:
        remainders.append(f"- Phase-D 主动沟通：\n  {pd_text.replace(chr(10), chr(10) + '  ')}")
    # CR 桥
    cr_ids = result.get("change_request_ids") if isinstance(result, dict) else None
    if isinstance(cr_ids, list) and cr_ids:
        remainders.append(f"- 已生成 {len(cr_ids)} 个 change request（ID: {cr_ids[:5]}）")

    if not remainders:
        remainders.append("- ✅ 全部 handler 成功执行，无遗留事项")

    sec4 = ["## 还剩什么"] + remainders

    # ── 5. 你要不要确认 ──
    confirmations = []
    pd = _format_phase_d(reasoning if isinstance(reasoning, dict) else {})
    if pd:
        confirmations.append("- ⚠️ 我问了老板一个问题（见上方），请确认或答复")
    if exec_status == "blocked_by_path_guard":
        confirmations.append("- ⚠️ 我尝试改了不属于自己范围的文件，请确认是否允许此次越权")
    if exec_status == "handler_failed":
        confirmations.append("- ⚠️ 部分操作失败，请老板判断是否需要换人 / 加资源 / 改任务")
    # evolution_signal 需要进化 → 请老板确认是否触发 prompt evolution
    evo = result.get("evolution_signal") if isinstance(result, dict) else None
    if isinstance(evo, dict) and evo.get("needed"):
        evo_fail = evo.get("fail_count", 0)
        confirmations.append(
            f"- ⚠️ 我最近失败 {evo_fail} 次了，要不要让我自改 prompt 试一次？"
            "（admin API 触发后我会跑影子 A/B，胜出才生效）"
        )
    # handoff → 请老板追进度
    ho = result.get("handoff") if isinstance(result, dict) else None
    if isinstance(ho, dict) and ho.get("ok"):
        tgt = _safe_str(ho.get("to"), 40)
        tid = ho.get("thread_id") or 0
        confirmations.append(
            f"- 我已经把任务 @{tgt} 转交了（协作线程 #{tid}），要不要追一下他的进度？"
        )
    if not confirmations:
        confirmations.append("- 如无异议，本次任务到此结束；如有补充请告诉我")

    sec5 = ["## 你要不要确认"] + confirmations

    return "\n".join(sec1 + [""] + sec2 + [""] + sec3 + [""] + sec4 + [""] + sec5)


__all__ = ["build_human_report"]
