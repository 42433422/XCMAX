#!/usr/bin/env python3
"""网页爬虫 CLI：Bing 浏览器填框搜索；可选 Tavily 兜底。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

MODSTORE_ROOT = Path(__file__).resolve().parents[1]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

from modstore_server.research_tools import (  # noqa: E402
    _web_results_for_llm,
    format_web_results_combined,
    web_crawl_per_engine_limit,
    web_search_crawl_parallel,
    web_search_result_titles,
    web_search_with_fallback,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bing 浏览器填框爬虫（整句搜索，标题原样输出）")
    p.add_argument("query", help="搜索关键词")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--companies-only", action="store_true")
    p.add_argument(
        "--crawler-only",
        action="store_true",
        help="仅 Bing 爬虫（等同 MODSTORE_WEB_SEARCH_USE_TAVILY=0）",
    )
    p.add_argument("--no-tavily", action="store_true", help="禁用 Tavily 兜底，失败则 DDG/SearXNG")
    p.add_argument("--headed", action="store_true", help="Edge 可见窗口（过验证码）")
    return p


async def _run(args: argparse.Namespace) -> Dict[str, Any]:
    q = args.query.strip()
    if args.headed:
        os.environ["MODSTORE_BING_EDGE_HEADLESS"] = "0"
    os.environ.setdefault("MODSTORE_WEB_CRAWL_ENGINES", "bing")
    if args.crawler_only or args.no_tavily:
        os.environ["MODSTORE_WEB_SEARCH_USE_TAVILY"] = "0"
    if args.crawler_only:
        results, via, crawl_errors = await web_search_crawl_parallel(q, max_results=args.max)
        err = "; ".join(crawl_errors)[:220] if crawl_errors and not results else None
    else:
        results, via, err = await web_search_with_fallback(q, max_results=args.max)
    if results:
        results = await _web_results_for_llm(results, max_results=args.max)
    companies = web_search_result_titles(results, limit=args.max) if results else []
    return {
        "query": q,
        "via": via,
        "per_engine": web_crawl_per_engine_limit(),
        "results": results,
        "companies": companies,
        "summary": format_web_results_combined(results) if results else "",
        "error": err,
    }


def main() -> int:
    args = _build_parser().parse_args()
    args.max = max(1, min(args.max, 50))
    payload = asyncio.run(_run(args))
    if args.companies_only:
        print(json.dumps(payload["companies"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("error") and not payload.get("results"):
        return 1
    if not payload.get("results") and not payload.get("companies"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
