# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


async def tool_query_cursor_usage(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询 Cursor 编辑器的使用统计（自动采集，含精确 token 用量）。

    数据源（按精确度从高到低）：
    1. cursor-usage CLI → 调 Cursor Dashboard 内部 API，返回精确的
       inputTokens/outputTokens/cacheReadTokens/totalCents（按 model 分组）
    2. macOS Keychain cursor-access-token → api2.cursor.sh/auth/usage
       获取免费配额（gpt-4）的请求次数
    3. 本地 ~/.cursor/ai-tracking/ai-code-tracking.db（SQLite）
       获取 AI 代码生成次数和 commit 代码比例

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 当前账单月）
    - detail_limit: 返回最近 N 条明细事件（默认 10，0 = 不返回明细）
    """
    import csv
    import io
    import shutil
    import sqlite3
    import subprocess
    from datetime import UTC, datetime, timedelta

    days = int(str(params.get("days") if params.get("days") is not None else 30))
    detail_limit = int(
        str(params.get("detail_limit") if params.get("detail_limit") is not None else 10)
    )
    result_data: dict[str, _facade().Any] = {
        "sources": [],
        "cli_usage": None,
        "api_usage": None,
        "local_db": None,
        "cursor_summary": {},
    }
    cli_bin = shutil.which("cursor-usage") or str(
        _facade().Path.home() / "Library" / "Python" / "3.9" / "bin" / "cursor-usage"
    )
    if _facade().Path(cli_bin).is_file():
        result_data["sources"].append("cursor-usage-cli")
        try:
            cmd = [cli_bin, "--json"]
            if days > 0:
                cmd.extend(["--days", str(days)])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                raw = _facade().json.loads(proc.stdout)
                aggregations = raw.get("aggregations", [])
                total_input = 0
                total_output = 0
                total_cache_read = 0
                total_cache_write = 0
                total_cents = 0.0
                by_model = []
                for agg in aggregations:
                    inp = int(agg.get("inputTokens") or 0)
                    out = int(agg.get("outputTokens") or 0)
                    cr = int(agg.get("cacheReadTokens") or 0)
                    cw = int(agg.get("cacheWriteTokens") or 0)
                    cents = float(agg.get("totalCents") or 0)
                    total_input += inp
                    total_output += out
                    total_cache_read += cr
                    total_cache_write += cw
                    total_cents += cents
                    by_model.append(
                        {
                            "model": agg.get("modelIntent", "unknown"),
                            "input_tokens": inp,
                            "output_tokens": out,
                            "cache_read_tokens": cr,
                            "cache_write_tokens": cw,
                            "total_tokens": inp + out + cr + cw,
                            "cost_cents": round(cents, 2),
                            "cost_usd": round(cents / 100, 4),
                            "tier": agg.get("tier"),
                        }
                    )
                by_model.sort(key=lambda x: x["cost_cents"], reverse=True)
                result_data["cli_usage"] = {
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_cache_read_tokens": total_cache_read,
                    "total_cache_write_tokens": total_cache_write,
                    "total_tokens": total_input
                    + total_output
                    + total_cache_read
                    + total_cache_write,
                    "total_cost_cents": round(total_cents, 2),
                    "total_cost_usd": round(total_cents / 100, 2),
                    "by_model": by_model,
                    "model_count": len(by_model),
                    "days_filter": days if days > 0 else "current_billing_month",
                }
                if detail_limit > 0:
                    csv_cmd = [cli_bin]
                    if days > 0:
                        csv_cmd.extend(["--days", str(days)])
                    else:
                        csv_cmd.extend(["--month", datetime.now(UTC).strftime("%Y-%m")])
                    csv_cmd.extend(["--csv", "-"])
                    csv_proc = subprocess.run(csv_cmd, capture_output=True, text=True, timeout=60)
                    if csv_proc.returncode == 0 and csv_proc.stdout:
                        reader = csv.DictReader(io.StringIO(csv_proc.stdout))
                        events = list(reader)
                        events = events[-detail_limit:] if len(events) > detail_limit else events
                        result_data["cli_usage"]["recent_events"] = [
                            {
                                "datetime": e.get("datetime_local", ""),
                                "model": e.get("model", ""),
                                "input_tokens": int(e.get("input_tokens") or 0),
                                "output_tokens": int(e.get("output_tokens") or 0),
                                "cache_read_tokens": int(e.get("cache_read_tokens") or 0),
                                "value_cents": float(e.get("value_cents") or 0),
                                "kind": e.get("kind", ""),
                            }
                            for e in events
                        ]
                        result_data["cli_usage"]["total_events"] = len(
                            list(csv.DictReader(io.StringIO(csv_proc.stdout)))
                        )
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["cli_usage"] = {"error": str(exc)}
    api_token = ""
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "cursor-access-token",
                "-a",
                "cursor-user",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            api_token = proc.stdout.strip()
    except _facade().RECOVERABLE_ERRORS:
        pass
    if api_token:
        result_data["sources"].append("cursor-api:auth/usage")
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://api2.cursor.sh/auth/usage",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "User-Agent": "cursor/0.50.0",
                    "x-cursor-client-version": "0.50.0",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                api_data = resp.json()
                result_data["api_usage"] = {
                    "free_quota": api_data,
                    "start_of_month": api_data.get("startOfMonth", ""),
                    "note": "仅返回免费配额(gpt-4)；Pro 版用量由 cursor-usage CLI 提供",
                }
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["api_usage"] = {"error": str(exc)}
    db_path = _facade().Path.home() / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
    if db_path.is_file():
        result_data["sources"].append(f"local-db:{db_path.name}")
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            since_ts = 0
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)
                since_ts = int(since_dt.timestamp() * 1000)
            if since_ts > 0:
                cur.execute(
                    "SELECT model, COUNT(*) as count FROM ai_code_hashes WHERE timestamp >= ? GROUP BY model ORDER BY count DESC",
                    (since_ts,),
                )
            else:
                cur.execute(
                    "SELECT model, COUNT(*) as count FROM ai_code_hashes GROUP BY model ORDER BY count DESC"
                )
            model_counts = [
                {"model": r["model"] or "(unknown)", "count": r["count"]} for r in cur.fetchall()
            ]
            cur.execute("SELECT COUNT(*) FROM ai_code_hashes")
            total_hashes = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) as commits, SUM(linesAdded) as total_add, SUM(tabLinesAdded) as tab_add, SUM(composerLinesAdded) as comp_add, SUM(humanLinesAdded) as human_add FROM scored_commits"
            )
            row = cur.fetchone()
            commits_data = {
                "total_commits": row["commits"],
                "total_lines_added": row["total_add"] or 0,
                "tab_lines_added": row["tab_add"] or 0,
                "composer_lines_added": row["comp_add"] or 0,
                "human_lines_added": row["human_add"] or 0,
            }
            ai_lines = commits_data["tab_lines_added"] + commits_data["composer_lines_added"]
            total_lines = commits_data["total_lines_added"] or 1
            commits_data["ai_percentage"] = round(ai_lines / total_lines * 100, 1)
            conn.close()
            result_data["local_db"] = {
                "db_path": str(db_path),
                "total_ai_generations": total_hashes,
                "by_model": model_counts,
                "commits": commits_data,
                "days_filter": days if days > 0 else "all",
            }
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["local_db"] = {"error": str(exc)}
    cli = result_data.get("cli_usage") or {}
    total_tokens = cli.get("total_tokens", 0)
    total_cost = cli.get("total_cost_usd", 0)
    total_gen = 0
    if result_data.get("local_db") and "error" not in result_data["local_db"]:
        total_gen = result_data["local_db"].get("total_ai_generations", 0)
    result_data["cursor_summary"] = {
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "total_ai_generations": total_gen,
        "has_cli": bool(cli and "error" not in cli),
        "has_api_token": bool(api_token),
        "has_local_db": bool(
            result_data.get("local_db") and "error" not in result_data.get("local_db", {})
        ),
        "note": "cursor-usage CLI 提供精确 token 和费用（来自 Dashboard API）。本地 DB 提供 AI 生成次数和代码比例。",
    }
    return _facade()._ok(
        f"Cursor 使用统计：{total_tokens:,} tokens，${total_cost}，{total_gen} 次 AI 生成，{len(result_data['sources'])} 个数据源",
        **result_data,
    )
