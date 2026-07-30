"""联系页 / 工作台 · 公司名称本地库 + 联网匹配。

从 market_auth_api 拆出，避免 oversized 路由文件继续膨胀。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from modstore_server.contact_company_web_search import (
    contact_web_search_budget_sec,
    search_company_names_via_web,
)
from modstore_server.models import LandingContactSubmission, get_session_factory
from modstore_server.research_tools import (
    is_plausible_company_name,
    sanitize_contact_company_web_error,
)

logger = logging.getLogger(__name__)


def _normalize_company_key(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().casefold())


def _company_match_score(query: str, candidate: str) -> int:
    q = _normalize_company_key(query)
    c = _normalize_company_key(candidate)
    if not q or not c:
        return -1
    if q == c:
        return 100
    if c.startswith(q) or q.startswith(c):
        return 85
    if q in c or c in q:
        return 70
    return -1


def _iter_company_match_db_paths() -> list[Path]:
    paths: list[Path] = []
    raw = (os.environ.get("XCAGI_COMPANY_MATCH_DB_PATHS") or "").strip()
    if raw:
        for part in raw.split(","):
            p = Path(part.strip()).expanduser()
            if str(p):
                paths.append(p)
    repo = Path(os.environ.get("MODSTORE_REPO_ROOT", "/root/成都修茈科技有限公司")).expanduser()
    paths.extend(
        [
            repo / "data" / "mod_dbs" / "taiyangniao_pro.db",
            Path("/root/data/mod_dbs/taiyangniao_pro.db"),
            repo / "mods" / "taiyangniao-pro" / "mod_dbs" / "taiyangniao_pro.db",
            Path("/opt/fhd-full/data/mod_dbs/taiyangniao_pro.db"),
            Path("/opt/fhd-full/XCAGI/data/mod_dbs/taiyangniao_pro.db"),
        ]
    )
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _erp_company_names(query: str, limit: int) -> list[str]:
    import sqlite3

    pattern = f"%{query.strip()}%"
    names: list[str] = []
    for db_path in _iter_company_match_db_paths():
        if not db_path.is_file():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            cur = conn.execute(
                "SELECT DISTINCT customer_name FROM customers "
                "WHERE customer_name != '' AND customer_name LIKE ? COLLATE NOCASE "
                "ORDER BY LENGTH(customer_name) ASC LIMIT ?",
                (pattern, limit),
            )
            for row in cur:
                val = (row[0] or "").strip()
                if val and val not in names:
                    names.append(val)
                if len(names) >= limit:
                    break
            conn.close()
            if names:
                break
        except Exception:
            logger.debug("erp company match skipped for %s", db_path, exc_info=True)
    return names[:limit]


def _submission_company_rows(
    session, query: str, limit: int
) -> list[tuple[str, int, datetime | None]]:
    pattern = f"%{query.strip()}%"
    rows = (
        session.query(
            LandingContactSubmission.company,
            func.count(LandingContactSubmission.id).label("cnt"),
            func.max(LandingContactSubmission.created_at).label("last_at"),
        )
        .filter(
            LandingContactSubmission.company != "",
            LandingContactSubmission.company.ilike(pattern),
        )
        .group_by(LandingContactSubmission.company)
        .order_by(func.count(LandingContactSubmission.id).desc())
        .limit(limit)
        .all()
    )
    return [
        (str(name or "").strip(), int(cnt or 0), last_at)
        for name, cnt, last_at in rows
        if str(name or "").strip()
    ]


async def build_company_match_payload(query: str, limit: int, web: bool) -> dict:
    by_name: dict[str, dict] = {}
    typed_exact = is_plausible_company_name(query)
    sf = get_session_factory()
    try:
        with sf() as session:
            for name, cnt, last_at in _submission_company_rows(session, query, limit=40):
                by_name[name] = {
                    "name": name,
                    "exact": _normalize_company_key(name) == _normalize_company_key(query),
                    "has_history": True,
                    "submission_count": cnt,
                    "in_crm": False,
                    "source": "submission",
                    "last_submitted_at": last_at.isoformat() if last_at else None,
                    "_score": _company_match_score(query, name),
                }
    except (ProgrammingError, SQLAlchemyError) as exc:
        logger.warning("company match: landing_contact_submissions query skipped: %s", exc)

    for name in _erp_company_names(query, limit=20):
        score = _company_match_score(query, name)
        if score < 0:
            continue
        existing = by_name.get(name)
        if existing:
            existing["in_crm"] = True
            existing["source"] = "both"
            existing["_score"] = max(int(existing.get("_score") or 0), score)
        else:
            by_name[name] = {
                "name": name,
                "exact": _normalize_company_key(name) == _normalize_company_key(query),
                "has_history": False,
                "submission_count": 0,
                "in_crm": True,
                "source": "erp",
                "last_submitted_at": None,
                "_score": score,
            }

    web_used = False
    web_error: str | None = None
    web_via = ""
    incomplete_query = len(query) >= 2 and not typed_exact
    if web:
        try:
            web_names, web_error, web_via = await asyncio.wait_for(
                search_company_names_via_web(query, max_results=limit),
                timeout=contact_web_search_budget_sec() + 0.75,
            )
            if web_names:
                web_used = True
            for name in web_names:
                if not is_plausible_company_name(name):
                    continue
                score = _company_match_score(query, name)
                if score < 60:
                    score = 70
                existing = by_name.get(name)
                by_name[name] = {
                    "name": name,
                    "exact": _normalize_company_key(name) == _normalize_company_key(query),
                    "has_history": bool(existing and existing.get("has_history")),
                    "submission_count": int((existing or {}).get("submission_count") or 0),
                    "in_crm": bool(existing and existing.get("in_crm")),
                    "in_web": True,
                    "source": "web",
                    "last_submitted_at": (existing or {}).get("last_submitted_at"),
                    "_score": max(int((existing or {}).get("_score") or 0), score),
                }
        except asyncio.TimeoutError:
            logger.warning("company match web search timed out for q=%r", query)
            web_error = "联网检索超时"
        except Exception as exc:
            logger.warning("company match web search failed: %s", exc)
            web_error = "联网检索暂时不可用"
    web_error = sanitize_contact_company_web_error(web_error)

    ranked = sorted(
        by_name.values(),
        key=lambda item: (
            1 if item.get("source") == "web" else 0,
            int(item.get("_score") or 0),
            int(item.get("submission_count") or 0),
            len(item.get("name") or ""),
        ),
        reverse=True,
    )
    suggestions: list[dict] = []
    matched = None
    # 仅在联网真正命中时优先 web；超时/失败时仍用本地库作为 matched
    prefer_web = bool(web and web_used)
    for item in ranked:
        score = int(item.get("_score") or 0)
        payload = {k: v for k, v in item.items() if k != "_score"}
        if score < 60:
            continue
        is_web = payload.get("source") == "web"
        if prefer_web and not is_web:
            if len(suggestions) < limit:
                suggestions.append(payload)
            continue
        if matched is None and (not prefer_web or is_web):
            matched = payload
        if len(suggestions) < limit:
            suggestions.append(payload)

    if matched is None and suggestions:
        matched = suggestions[0]
    found = bool(matched or suggestions)
    return {
        "ok": True,
        "query": query,
        "found": found,
        "matched": matched,
        "suggestions": suggestions,
        "web_used": web_used,
        "web_error": web_error,
        "web_via": web_via or None,
        "query_incomplete": bool(incomplete_query and not found and not web_used),
    }
