# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.research_tools")


def _company_name_key(name: str) -> str:
    return _facade().re.sub("\\s+", "", (name or "").strip().casefold())


def _normalize_company_key(name: str) -> str:
    return _facade()._company_name_key(name)


def _query_matches_company_name(query: str, name: str) -> bool:
    q = (query or "").strip()
    n = _facade().re.sub("\\s+", "", (name or "").strip())
    if not q or not n:
        return False
    qk = _facade()._company_name_key(q)
    nk = _facade()._company_name_key(n)
    if qk in nk or nk in qk or q in n:
        return True
    m = _facade().re.match("^(.{2,4}?)(市)?(.+)$", qk)
    if m and (not m.group(2)) and m.group(3):
        alt = f"{m.group(1)}市{m.group(3)}"
        if alt in nk:
            return True
    return False


def sanitize_contact_company_web_error(raw: str | None) -> str | None:
    """联系页 API：不向访客暴露爬虫引擎名、TimeoutError 等内部信息。"""
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in ("无可用结果", "未从网页标题解析到公司全称"):
        return "联网核对暂不可用"
    low = text.lower()
    internal = (
        "timeout",
        "timeouterror",
        "connect",
        "connection",
        "ssl",
        "certificate",
        "duckduckgo",
        "bing",
        "tavily",
        "searxng",
        "playwright",
        "crawl",
        "httpx",
        "aiohttp",
        "refused",
        "reset",
        "dns",
        "proxy",
        "exception",
        "traceback",
    )
    if any((m in low for m in internal)):
        return "联网核对暂不可用"
    if len(text) > 48:
        return "联网核对暂不可用"
    return text


def is_plausible_company_name(name: str) -> bool:
    """联系页展示：须含公司后缀，且排除攻略/政府等标题误识别。"""
    n = _facade().re.sub("\\s+", "", (name or "").strip())
    if len(n) < 4 or len(n) > 80:
        return False
    if any((marker in n for marker in _facade()._BAD_COMPANY_NAME_MARKERS)):
        return False
    return any((suffix in n for suffix in _facade()._COMPANY_SUFFIXES))


def extract_company_names_from_text(
    text: str, query: str, *, limit: int = 10
) -> _facade().List[str]:
    """从网页文本启发式提取公司全称。"""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    seen: _facade().Set[str] = set()
    candidates: _facade().List[str] = []
    for m in _facade()._COMPANY_NAME_RE.finditer(_facade().unescape(text or "")):
        name = _facade().re.sub("\\s+", "", m.group(0).strip())
        if len(name) < 4 or len(name) > 80:
            continue
        nk = _facade()._company_name_key(name)
        if nk in seen:
            continue
        if not _facade()._query_matches_company_name(q, name):
            continue
        seen.add(nk)
        candidates.append(name)
    if not candidates:
        return []
    candidates.sort(
        key=lambda n: (
            1 if _facade()._normalize_company_key(q) == _facade()._normalize_company_key(n) else 0,
            1 if _facade()._query_matches_company_name(q, n) else 0,
            len(n),
        ),
        reverse=True,
    )
    return candidates[: max(1, limit)]


def _extract_companies_for_query(blob: str, query: str, *, limit: int) -> _facade().List[str]:
    names = _facade().extract_company_names_from_text(blob, query, limit=limit)
    if names:
        return names
    q = (query or "").strip()
    if q.startswith("深圳") and (not q.startswith("深圳市")):
        names = _facade().extract_company_names_from_text(blob, "深圳市" + q[2:], limit=limit)
        if names:
            return names
    skip = frozenset({"深圳", "北京", "上海", "包装", "工商", "公司", "有限公司"})
    for size in range(min(8, len(q)), 1, -1):
        for i in range(0, len(q) - size + 1):
            token = q[i : i + size]
            if token in skip:
                continue
            names = _facade().extract_company_names_from_text(blob, token, limit=limit)
            if names:
                return names
    return []


def contact_web_company_search_enabled() -> bool:
    raw = (_facade().os.environ.get("MODSTORE_CONTACT_WEB_COMPANY_SEARCH") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")
