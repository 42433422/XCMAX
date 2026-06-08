"""research_tools 配额与 duty_roster 编制."""

from __future__ import annotations

from datetime import date

import httpx
import pytest


def test_duty_roster_matrix_matches_aggregated_ids() -> None:
    """人数随 YUANGON_AREAS 增减而变，不测固定数字；只保证矩阵与聚合函数一致且无重复。"""
    from modstore_server import duty_roster as dr

    flat: list[str] = []
    for block in dr.YUANGON_AREAS.values():
        ids = block.get("ids") if isinstance(block.get("ids"), list) else []
        flat.extend(str(x) for x in ids if str(x).strip())
    assert flat, "YUANGON_AREAS 应至少包含一个编制 id"
    assert len(flat) == len(set(flat)), f"编制矩阵中存在重复 pkg_id: {flat}"
    assert dr.all_planned_employee_ids() == frozenset(flat)


def test_digest_bucket_cap_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DIGEST_RESEARCH_CAP", "2")
    from modstore_server import research_tools as rt

    rt._counters.clear()
    assert rt._today_allowed("bucket:daily_digest")[0] is True
    assert rt._today_allowed("bucket:daily_digest")[0] is True
    assert rt._today_allowed("bucket:daily_digest")[0] is False


def test_user_bucket_independent_of_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DIGEST_RESEARCH_CAP", "1")
    monkeypatch.setenv("MODSTORE_RESEARCH_DAILY_CAP", "5")
    from modstore_server import research_tools as rt

    rt._counters.clear()
    assert rt._today_allowed("bucket:daily_digest")[0] is True
    assert rt._today_allowed("bucket:daily_digest")[0] is False
    rt._counters["user:7"] = (date.today(), 0)
    assert rt._today_allowed("user:7")[0] is True


def test_workbench_research_reexports_build() -> None:
    from modstore_server.workbench_research import build_research_context

    assert callable(build_research_context)


def test_tavily_api_key_accepts_tvly_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_WEB_SEARCH_USE_TAVILY", "1")
    monkeypatch.delenv("MODSTORE_TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TVLY_API_KEY", "tvly-dev-test")
    from modstore_server import research_tools as rt

    assert rt.tavily_api_key() == "tvly-dev-test"


@pytest.mark.asyncio
async def test_ddg_fallback_retries_alternate_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server import research_tools as rt
    from modstore_server.infrastructure import http_clients

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            req = httpx.Request("GET", url)
            if url.startswith("https://duckduckgo.com/html/"):
                raise httpx.ConnectTimeout("primary blocked")
            if url.startswith("https://html.duckduckgo.com/html/"):
                html = """
                <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example</a>
                <div class="result__snippet">hello world</div>
                """
                return httpx.Response(200, request=req, text=html)
            return httpx.Response(200, request=req, text="")

    fake = _FakeClient()
    monkeypatch.setattr(http_clients, "get_external_client", lambda: fake)

    out = await rt.duckduckgo_html_search("hello", max_results=5)
    assert out and out[0]["url"] == "https://example.com"
    assert any("html.duckduckgo.com" in u for u in fake.calls)


def test_request_error_fragment_falls_back_to_exception_type() -> None:
    from modstore_server import research_tools as rt

    class _Quiet(Exception):
        def __str__(self) -> str:
            return ""

    assert rt._request_error_fragment(_Quiet()) == "_Quiet"


@pytest.mark.asyncio
async def test_web_search_free_tier_uses_searx_when_ddg_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modstore_server import research_tools as rt
    from modstore_server.infrastructure import http_clients

    monkeypatch.setenv("MODSTORE_SEARXNG_URL", "https://sx.test")

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            req = httpx.Request("GET", url)
            if "duckduckgo" in url:
                return httpx.Response(200, request=req, text="<html></html>")
            if "sx.test" in url:
                payload = {
                    "results": [
                        {"title": "Hi", "url": "https://example.org/x", "content": "snippet"},
                    ]
                }
                return httpx.Response(200, request=req, json=payload)
            return httpx.Response(404, request=req)

    fake = _FakeClient()
    monkeypatch.setattr(http_clients, "get_external_client", lambda: fake)

    results, err, via = await rt._web_search_free_tier("q", max_results=5)
    assert err is None
    assert via == "searxng"
    assert results and results[0]["url"] == "https://example.org/x"
    assert any("sx.test" in u for u in fake.calls)
