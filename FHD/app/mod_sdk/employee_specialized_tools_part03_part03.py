# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


async def tool_query_codex_usage(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询 OpenAI Codex CLI 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.codex/archived_sessions/*.jsonl — 逐会话的精确 token 用量
       （input/cached/output/reasoning/total tokens + rate_limits）
    2. ~/.codex/goals_1.sqlite 的 thread_goals 表 — 按会话的 tokens_used 和状态
    3. ~/.codex/config.toml — 当前 model 配置

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 全部）
    """
    import glob
    import sqlite3
    from datetime import UTC, datetime, timedelta

    days = int(str(params.get("days") if params.get("days") is not None else 30))
    codex_dir = _facade().Path.home() / ".codex"
    result_data: dict[str, _facade().Any] = {
        "sources": [],
        "sessions": None,
        "goals_db": None,
        "config": None,
        "codex_summary": {},
    }
    sessions_dir = codex_dir / "archived_sessions"
    jsonl_files = sorted(glob.glob(str(sessions_dir / "*.jsonl"))) if sessions_dir.is_dir() else []
    if jsonl_files:
        result_data["sources"].append(f"archived-sessions:{len(jsonl_files)}-files")
        try:
            since_dt = None
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)
            sessions_list = []
            total_input = 0
            total_cached = 0
            total_output = 0
            total_reasoning = 0
            total_tokens = 0
            for fpath in jsonl_files:
                session_model = "unknown"
                session_cwd = ""
                session_ts = ""
                last_usage = None
                rate_limit_used = None
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = _facade().json.loads(line)
                        except _facade().json.JSONDecodeError:
                            continue
                        evt_type = evt.get("type", "")
                        payload = evt.get("payload", {})
                        if evt_type == "session_meta":
                            session_model = payload.get("model", session_model)
                            session_cwd = payload.get("cwd", "")
                            session_ts = payload.get("timestamp", "")
                        if evt_type == "event_msg" and payload.get("type") == "token_count":
                            info = payload.get("info", {})
                            last_usage = info.get("total_token_usage", {})
                            rl = payload.get("rate_limits", {})
                            primary = rl.get("primary", {})
                            rate_limit_used = primary.get("used_percent")
                if last_usage:
                    inp = int(last_usage.get("input_tokens") or 0)
                    cached = int(last_usage.get("cached_input_tokens") or 0)
                    out = int(last_usage.get("output_tokens") or 0)
                    reasoning = int(last_usage.get("reasoning_output_tokens") or 0)
                    tot = int(last_usage.get("total_tokens") or 0)
                    if since_dt and session_ts:
                        try:
                            evt_dt = datetime.fromisoformat(session_ts.replace("Z", "+00:00"))
                            if evt_dt < since_dt:
                                continue
                        except (ValueError, TypeError):
                            pass
                    total_input += inp
                    total_cached += cached
                    total_output += out
                    total_reasoning += reasoning
                    total_tokens += tot
                    sessions_list.append(
                        {
                            "file": _facade().Path(fpath).name,
                            "model": session_model,
                            "cwd": session_cwd,
                            "timestamp": session_ts,
                            "input_tokens": inp,
                            "cached_input_tokens": cached,
                            "output_tokens": out,
                            "reasoning_output_tokens": reasoning,
                            "total_tokens": tot,
                            "rate_limit_used_percent": rate_limit_used,
                        }
                    )
            sessions_list.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
            result_data["sessions"] = {
                "total_sessions": len(sessions_list),
                "total_input_tokens": total_input,
                "total_cached_input_tokens": total_cached,
                "total_output_tokens": total_output,
                "total_reasoning_output_tokens": total_reasoning,
                "total_tokens": total_tokens,
                "by_session": sessions_list[:20],
                "days_filter": days if days > 0 else "all",
            }
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["sessions"] = {"error": str(exc)}
    goals_db = codex_dir / "goals_1.sqlite"
    if goals_db.is_file():
        result_data["sources"].append("goals-sqlite")
        try:
            conn = sqlite3.connect(str(goals_db))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT thread_id, objective, status, token_budget, tokens_used, time_used_seconds, created_at_ms FROM thread_goals ORDER BY created_at_ms DESC"
            )
            goals_list = []
            total_goal_tokens = 0
            total_goal_time = 0
            for r in cur.fetchall():
                tokens = r["tokens_used"] or 0
                total_goal_tokens += tokens
                total_goal_time += r["time_used_seconds"] or 0
                goals_list.append(
                    {
                        "thread_id": r["thread_id"],
                        "objective": (r["objective"] or "")[:80],
                        "status": r["status"],
                        "token_budget": r["token_budget"],
                        "tokens_used": tokens,
                        "time_used_seconds": r["time_used_seconds"] or 0,
                        "created_at": datetime.fromtimestamp(
                            (r["created_at_ms"] or 0) / 1000
                        ).strftime("%Y-%m-%d %H:%M"),
                    }
                )
            conn.close()
            result_data["goals_db"] = {
                "total_threads": len(goals_list),
                "total_tokens_used": total_goal_tokens,
                "total_time_seconds": total_goal_time,
                "by_status": {
                    s: sum(1 for g in goals_list if g["status"] == s)
                    for s in {g["status"] for g in goals_list}
                },
                "threads": goals_list,
            }
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["goals_db"] = {"error": str(exc)}
    config_file = codex_dir / "config.toml"
    if config_file.is_file():
        result_data["sources"].append("config-toml")
        try:
            config_text = config_file.read_text(encoding="utf-8")
            model = ""
            reasoning_effort = ""
            for line in config_text.splitlines():
                line = line.strip()
                if line.startswith("model") and "=" in line:
                    model = line.split("=", 1)[1].strip().strip('"')
                if line.startswith("model_reasoning_effort") and "=" in line:
                    reasoning_effort = line.split("=", 1)[1].strip().strip('"')
            result_data["config"] = {"model": model, "reasoning_effort": reasoning_effort}
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["config"] = {"error": str(exc)}
    sess = result_data.get("sessions") or {}
    goals = result_data.get("goals_db") or {}
    total_tok = sess.get("total_tokens", 0) or goals.get("total_tokens_used", 0)
    result_data["codex_summary"] = {
        "total_tokens": total_tok,
        "total_sessions": sess.get("total_sessions", 0),
        "total_threads": goals.get("total_threads", 0),
        "total_time_seconds": goals.get("total_time_seconds", 0),
        "model": (result_data.get("config") or {}).get("model", "unknown"),
        "note": "Codex CLI 本地数据。archived_sessions 含精确 token（input/cached/output/reasoning），goals_db 含按会话的 token 和状态。",
    }
    return _facade()._ok(
        f"Codex 使用统计：{total_tok:,} tokens，{sess.get('total_sessions', 0)} 个会话，{len(result_data['sources'])} 个数据源",
        **result_data,
    )
