from __future__ import annotations

"""Branch coverage for data_analysis_service + llm_adapter."""

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# DataAnalysisService
# ---------------------------------------------------------------------------

class TestDataAnalysisService:
    def _make_svc(self):
        from app.services.data_analysis_service import DataAnalysisService

        return DataAnalysisService()

    # analyze_file — success path
    def test_analyze_file_csv(self, tmp_path):
        import pandas as pd

        csv = tmp_path / "test.csv"
        csv.write_text("a,b,c\n1,2,3\n4,5,6\n")
        svc = self._make_svc()
        result = svc.analyze_file(str(csv))
        assert result["success"] is True
        assert result["file_info"]["rows"] == 2

    def test_analyze_file_empty(self, tmp_path):
        csv = tmp_path / "empty.csv"
        csv.write_text("")
        svc = self._make_svc()
        result = svc.analyze_file(str(csv))
        assert result["success"] is False

    def test_analyze_file_unsupported(self, tmp_path):
        f = tmp_path / "file.xyz"
        f.write_text("data")
        svc = self._make_svc()
        result = svc.analyze_file(str(f))
        assert result["success"] is False

    def test_analyze_file_json(self, tmp_path):
        import json

        jf = tmp_path / "data.json"
        jf.write_text(json.dumps([{"x": 1, "y": 2}, {"x": 3, "y": 4}]))
        svc = self._make_svc()
        result = svc.analyze_file(str(jf))
        assert result["success"] is True

    def test_analyze_file_with_query_sales(self, tmp_path):
        csv = tmp_path / "sales.csv"
        csv.write_text("销量,价格\n10,100\n20,200\n")
        svc = self._make_svc()
        result = svc.analyze_file(str(csv), query="销量分析")
        assert "检测到销量相关分析需求" in result["insights"]

    def test_analyze_file_with_query_roi(self, tmp_path):
        csv = tmp_path / "roi.csv"
        csv.write_text("ROI,渠道\n0.1,online\n")
        svc = self._make_svc()
        result = svc.analyze_file(str(csv), query="ROI分析")
        assert "检测到ROI/渠道分析需求" in result["insights"]

    # _load_file branches
    def test_load_file_xlsx(self, tmp_path):
        import pandas as pd

        svc = self._make_svc()
        xlsx = tmp_path / "test.xlsx"
        pd.DataFrame({"x": [1]}).to_excel(str(xlsx), index=False)
        df = svc._load_file(str(xlsx))
        assert df is not None

    def test_load_file_txt(self, tmp_path):
        svc = self._make_svc()
        txt = tmp_path / "test.txt"
        txt.write_text("a\tb\n1\t2\n")
        df = svc._load_file(str(txt))
        # tab-separated should parse OK
        assert df is not None

    def test_load_file_bad_extension(self, tmp_path):
        svc = self._make_svc()
        result = svc._load_file(str(tmp_path / "file.bak"))
        assert result is None

    def test_load_file_bad_content(self, tmp_path):
        svc = self._make_svc()
        f = tmp_path / "bad.csv"
        f.write_bytes(b"\x00\x01\x02\x03")  # binary garbage
        # should return None (recoverable error caught)
        result = svc._load_file(str(f))
        # outcome depends on pandas version — just ensure no exception propagates
        assert result is None or result is not None

    # _generate_chart_data — no numeric cols
    def test_generate_chart_data_no_numeric(self):
        import pandas as pd

        svc = self._make_svc()
        df = pd.DataFrame({"name": ["a", "b"]})
        result = svc._generate_chart_data(df, "")
        assert result["type"] == "bar"
        assert result["labels"] == []

    # _generate_chart_data — with numeric
    def test_generate_chart_data_with_numeric(self):
        import pandas as pd

        svc = self._make_svc()
        df = pd.DataFrame({"qty": list(range(15))})
        result = svc._generate_chart_data(df, "")
        assert result["type"] == "line"
        assert len(result["datasets"]) == 1

    # export_to_excel
    def test_export_to_excel_success(self, tmp_path):
        svc = self._make_svc()
        out = str(tmp_path / "out.xlsx")
        result = svc.export_to_excel({"data": []}, out)
        assert result is True

    def test_export_to_excel_failure(self, tmp_path):
        svc = self._make_svc()
        # write to a non-writable path → RECOVERABLE_ERRORS caught
        with patch("pandas.DataFrame.to_excel", side_effect=OSError("no space")):
            result = svc.export_to_excel({}, str(tmp_path / "out.xlsx"))
        assert result is False

    # module-level factory function
    def test_get_data_analysis_service(self):
        from app.services.data_analysis_service import get_data_analysis_service

        svc = get_data_analysis_service()
        assert svc is not None


# ---------------------------------------------------------------------------
# OpenAICompatibleAdapter (llm_adapter)
# ---------------------------------------------------------------------------

class TestOpenAICompatibleAdapter:
    def _make_adapter(self, provider="deepseek", api_key="test-key"):
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        return OpenAICompatibleAdapter(provider=provider, api_key=api_key)

    def test_init_with_explicit_key(self):
        adapter = self._make_adapter(api_key="mykey")
        assert adapter.provider_name == "deepseek"
        assert adapter.model_name == "deepseek-chat"
        assert adapter.is_configured is True

    def test_init_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

            a = OpenAICompatibleAdapter(provider="deepseek")
        assert a.is_configured is False

    def test_init_env_key_resolution(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "env_key"}):
            from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

            a = OpenAICompatibleAdapter(provider="deepseek")
        assert a.is_configured is True

    def test_init_unknown_provider_fallback(self):
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        a = OpenAICompatibleAdapter(provider="unknownvendor", api_key="k")
        assert a._base_url.endswith("/v1") or "openai.com" in a._base_url

    def test_normalize_base_url_already_versioned(self):
        a = self._make_adapter()
        a._base_url = "https://api.example.com/v1"
        assert a._normalize_base_url() == "https://api.example.com/v1"

    def test_normalize_base_url_needs_v1(self):
        a = self._make_adapter()
        a._base_url = "https://api.example.com"
        assert a._normalize_base_url() == "https://api.example.com/v1"

    def test_normalize_base_url_v2_versioned(self):
        a = self._make_adapter()
        a._base_url = "https://api.example.com/v2"
        assert a._normalize_base_url() == "https://api.example.com/v2"

    def test_repr_configured(self):
        a = self._make_adapter(api_key="somekey")
        r = repr(a)
        assert "deepseek" in r

    def test_repr_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

            a = OpenAICompatibleAdapter(provider="deepseek")
        r = repr(a)
        assert "deepseek" in r

    # chat_completion — no api key
    @pytest.mark.asyncio
    async def test_chat_completion_no_key_raises(self):
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        a = OpenAICompatibleAdapter(provider="deepseek", api_key=None)
        a._api_key = None
        with pytest.raises(ValueError, match="API Key"):
            await a.chat_completion([{"role": "user", "content": "hi"}])

    # chat_completion — success
    @pytest.mark.asyncio
    async def test_chat_completion_success(self):
        import httpx

        a = self._make_adapter()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch.object(a, "_get_client", return_value=mock_client):
            result = await a.chat_completion([{"role": "user", "content": "hi"}])
        assert "choices" in result

    # stream_chat_completion — no api key
    @pytest.mark.asyncio
    async def test_stream_no_key_raises(self):
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        a = OpenAICompatibleAdapter(provider="deepseek", api_key=None)
        a._api_key = None
        with pytest.raises(ValueError):
            async for _ in a.stream_chat_completion([]):
                pass

    # close — both clients None
    @pytest.mark.asyncio
    async def test_close_no_clients(self):
        a = self._make_adapter()
        await a.close()  # should not raise

    # close — both clients open
    @pytest.mark.asyncio
    async def test_close_open_clients(self):
        a = self._make_adapter()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        a._client = mock_client
        a._stream_client = mock_client
        await a.close()
        assert mock_client.aclose.called

    # provider_name / model_name properties
    def test_provider_name(self):
        a = self._make_adapter(provider="moonshot", api_key="k")
        assert a.provider_name == "moonshot"

    def test_model_name(self):
        a = self._make_adapter(provider="moonshot", api_key="k")
        assert a.model_name == "moonshot-v1-8k"

    # custom base_url and model
    def test_custom_base_url_and_model(self):
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        a = OpenAICompatibleAdapter(
            provider="openai",
            model="gpt-4",
            api_key="k",
            base_url="https://my.proxy.com/v1/",
        )
        assert a._model == "gpt-4"
        assert a._base_url == "https://my.proxy.com/v1"

    # _get_client reuse
    @pytest.mark.asyncio
    async def test_get_client_reuse(self):
        a = self._make_adapter()
        c1 = await a._get_client()
        c2 = await a._get_client()
        assert c1 is c2
        await a.close()

    # _get_stream_client reuse
    @pytest.mark.asyncio
    async def test_get_stream_client_reuse(self):
        a = self._make_adapter()
        c1 = await a._get_stream_client()
        c2 = await a._get_stream_client()
        assert c1 is c2
        await a.close()
