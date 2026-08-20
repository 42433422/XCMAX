# mypy: disable-error-code="attr-defined"
"""EmbeddingService 补充单元测试，聚焦未覆盖分支。

覆盖目标：
- ``_resolve_mode`` 各环境变量组合（local/remote/hash/disabled 及 alias）
- ``_embed_hash`` 算法：空输入、中文/英文 token、归一化、确定性、维度缓存
- ``_get_local_model`` 加载失败后不重试（``_load_attempted``）
- ``_embed_local`` model.encode 抛 RECOVERABLE_ERRORS 时返回空
- ``_embed_remote`` 无 api_key、无 model、空 data、HTTP 错误
- ``dim()`` hash 模式、缓存命中、探测失败
- 单例线程安全 / ``get_default_embedding_service`` 可用分支
- ``embed`` 空输入、未知 mode 兜底
- ``EmbedderPort`` 协议适配
"""

from __future__ import annotations

import sys
import threading
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.llm import embedding_service as emb_mod
from app.infrastructure.llm.embedding_service import (
    _HASH_EMBED_DIM,
    EmbeddingService,
    get_default_embedding_service,
)
from app.utils.operational_errors import BOUNDARY_ERRORS


@pytest.fixture(autouse=True)
def _reset_embedding_singleton():
    """每个用例前后清理单例，避免 env 变化被缓存。"""
    EmbeddingService.reset_singleton_for_tests()
    yield
    EmbeddingService.reset_singleton_for_tests()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """清理 embedding/RAG/desktop 相关环境变量。"""
    for key in (
        "FHD_EMBEDDING_MODE",
        "FHD_EMBEDDING_LOCAL_MODEL",
        "FHD_EMBEDDING_REMOTE_URL",
        "FHD_EMBEDDING_REMOTE_API_KEY",
        "FHD_EMBEDDING_REMOTE_MODEL",
        "XCAGI_RAG_ENABLED",
        "XCAGI_DESKTOP_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# _resolve_mode
# ---------------------------------------------------------------------------


class TestResolveMode:
    """直接测试 ``_resolve_mode`` 的所有分支。"""

    def test_local_aliases(self, monkeypatch: pytest.MonkeyPatch):
        for alias in ("local", "sentence-transformers", "st"):
            monkeypatch.setenv("FHD_EMBEDDING_MODE", alias)
            assert emb_mod._resolve_mode() == "local"

    def test_remote_aliases(self, monkeypatch: pytest.MonkeyPatch):
        for alias in ("remote", "api", "openai"):
            monkeypatch.setenv("FHD_EMBEDDING_MODE", alias)
            assert emb_mod._resolve_mode() == "remote"

    def test_hash_aliases(self, monkeypatch: pytest.MonkeyPatch):
        for alias in ("hash", "local-hash", "deterministic"):
            monkeypatch.setenv("FHD_EMBEDDING_MODE", alias)
            assert emb_mod._resolve_mode() == "hash"

    def test_disabled_aliases(self, monkeypatch: pytest.MonkeyPatch):
        for alias in ("disabled", "off", "none"):
            monkeypatch.setenv("FHD_EMBEDDING_MODE", alias)
            assert emb_mod._resolve_mode() == "disabled"

    def test_unset_falls_back_to_rag_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """未设置 mode 且 XCAGI_RAG_ENABLED 显式关闭 → disabled。"""
        monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
        for val in ("0", "false", "no", "off"):
            monkeypatch.setenv("XCAGI_RAG_ENABLED", val)
            assert emb_mod._resolve_mode() == "disabled", val

    def test_unset_falls_back_to_rag_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """未设置 mode 且 XCAGI_RAG_ENABLED 显式开启 → hash。"""
        monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
        for val in ("1", "true", "yes", "on", "auto"):
            monkeypatch.setenv("XCAGI_RAG_ENABLED", val)
            assert emb_mod._resolve_mode() == "hash", val

    def test_unset_falls_back_to_desktop_mode(self, monkeypatch: pytest.MonkeyPatch):
        """未设置 mode 与 RAG，desktop mode → disabled。"""
        monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
        monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)
        monkeypatch.setattr("app.utils.deployment.is_desktop_mode", lambda: True)
        assert emb_mod._resolve_mode() == "disabled"

    def test_unset_falls_back_to_non_desktop_hash(self, monkeypatch: pytest.MonkeyPatch):
        """未设置 mode / RAG，非 desktop → hash（web omniscient 默认）。"""
        monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
        monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)
        monkeypatch.setattr("app.utils.deployment.is_desktop_mode", lambda: False)
        assert emb_mod._resolve_mode() == "hash"

    def test_unset_desktop_probe_import_error_falls_back_to_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """is_desktop_mode 抛异常时不应阻断，回退到 hash。"""
        monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
        monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)

        def _raise() -> bool:
            raise RuntimeError("probe failed")

        monkeypatch.setattr("app.utils.deployment.is_desktop_mode", _raise)
        assert emb_mod._resolve_mode() == "hash"

    def test_unset_mode_value_strips_whitespace_and_lowercases(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """带空白/大小写的值也能被识别。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "  LOCAL  ")
        assert emb_mod._resolve_mode() == "local"

    def test_unset_empty_string_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch):
        """空字符串视为未设置。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "")
        monkeypatch.setattr("app.utils.deployment.is_desktop_mode", lambda: False)
        assert emb_mod._resolve_mode() == "hash"


# ---------------------------------------------------------------------------
# _embed_hash
# ---------------------------------------------------------------------------


class TestEmbedHash:
    """``_embed_hash`` 算法细节测试。"""

    def test_hash_dim_is_constant(self):
        svc = EmbeddingService(mode="hash")
        vec = svc._embed_hash("hello")
        assert len(vec) == _HASH_EMBED_DIM

    def test_hash_deterministic_for_same_input(self):
        svc = EmbeddingService(mode="hash")
        a = svc._embed_hash("hello world")
        b = svc._embed_hash("hello world")
        assert a == b

    def test_hash_different_for_different_input(self):
        svc = EmbeddingService(mode="hash")
        a = svc._embed_hash("hello world")
        b = svc._embed_hash("goodbye world")
        assert a != b

    def test_hash_normalized_to_unit_length(self):
        """输出向量 L2 范数应约为 1.0。"""
        import math

        svc = EmbeddingService(mode="hash")
        vec = svc._embed_hash("some random text for embedding")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-9

    def test_hash_empty_string_uses_placeholder_token(self):
        """空字符串应使用 ``_empty_`` 占位 token，不抛异常。"""
        svc = EmbeddingService(mode="hash")
        vec = svc._embed_hash("")
        assert len(vec) == _HASH_EMBED_DIM
        # 占位 token 也会产生非零向量
        assert any(v != 0.0 for v in vec)

    def test_hash_none_input_uses_placeholder_token(self):
        """None 输入应被 ``str(text or "")`` 转为空串并使用占位 token。"""
        svc = EmbeddingService(mode="hash")
        vec = svc._embed_hash(None)  # type: ignore[arg-type]
        assert len(vec) == _HASH_EMBED_DIM
        assert any(v != 0.0 for v in vec)

    def test_hash_chinese_tokens(self):
        """中文字符应被识别为 token。"""
        svc = EmbeddingService(mode="hash")
        vec_zh = svc._embed_hash("你好世界")
        vec_en = svc._embed_hash("hello world")
        assert vec_zh != vec_en

    def test_hash_caches_dim(self):
        """``_embed_hash`` 调用后应缓存 dim。"""
        svc = EmbeddingService(mode="hash")
        assert svc._dim_cache is None
        svc._embed_hash("hello")
        assert svc._dim_cache == _HASH_EMBED_DIM

    def test_hash_case_insensitive(self):
        """文本应被转为小写后再 tokenize。"""
        svc = EmbeddingService(mode="hash")
        a = svc._embed_hash("Hello World")
        b = svc._embed_hash("hello world")
        assert a == b


# ---------------------------------------------------------------------------
# dim()
# ---------------------------------------------------------------------------


class TestDim:
    """``dim()`` 各分支测试。"""

    def test_dim_disabled_returns_zero(self):
        svc = EmbeddingService(mode="disabled")
        assert svc.dim() == 0

    def test_dim_hash_returns_constant(self):
        svc = EmbeddingService(mode="hash")
        assert svc.dim() == _HASH_EMBED_DIM
        # 缓存被设置
        assert svc._dim_cache == _HASH_EMBED_DIM

    def test_dim_hash_does_not_recompute_when_cached(self):
        svc = EmbeddingService(mode="hash")
        svc._dim_cache = 999  # 预设非默认值
        # hash 分支会强制覆盖为 _HASH_EMBED_DIM
        assert svc.dim() == _HASH_EMBED_DIM

    def test_dim_local_uses_cache_when_available(self, monkeypatch: pytest.MonkeyPatch):
        svc = EmbeddingService(mode="local")
        svc._dim_cache = 128
        # 不应触发任何 embed
        assert svc.dim() == 128

    def test_dim_local_probes_via_embed_one_on_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1, 0.2, 0.3, 0.4, 0.5]]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        assert svc.dim() == 5
        assert svc._dim_cache == 5

    def test_dim_local_probe_failure_returns_zero(self, monkeypatch: pytest.MonkeyPatch):
        """探测时 embed_one 返回空 → dim 返回 0。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        # 让 SentenceTransformer 加载失败 → embed 返回空
        fake_module = types.ModuleType("sentence_transformers")

        class _Raiser:
            def __getattr__(self, name: str) -> Any:
                raise ImportError("no st")

        monkeypatch.setitem(sys.modules, "sentence_transformers", _Raiser())
        svc = EmbeddingService(mode="local")
        assert svc.dim() == 0

    def test_dim_remote_probe_recoverable_error_returns_zero(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")
        with patch("requests.post", side_effect=ConnectionError("network down")):
            svc = EmbeddingService(mode="remote")
            assert svc.dim() == 0

    def test_dim_remote_probe_success_caches(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=fake_resp):
            svc = EmbeddingService(mode="remote")
            assert svc.dim() == 3
            assert svc._dim_cache == 3

    def test_dim_probe_recoverable_exception_returns_zero(self):
        """``embed_one`` 抛 RECOVERABLE_ERRORS 时 ``dim()`` 捕获并返回 0。

        注意：仅 local/remote 模式才会进入 dim() 的 try 分支（hash 直接返回常量）。
        """
        svc = EmbeddingService(mode="local")
        # 强制 embed_one 抛出可恢复异常（ValueError 属于 DATA_SHAPE）
        with patch.object(svc, "embed_one", side_effect=ValueError("probe error")):
            assert svc.dim() == 0
        # _dim_cache 未被设置
        assert svc._dim_cache is None


# ---------------------------------------------------------------------------
# embed / embed_one
# ---------------------------------------------------------------------------


class TestEmbedEdgeCases:
    def test_embed_empty_texts_returns_empty_in_any_mode(self):
        for mode in ("disabled", "local", "remote", "hash"):
            svc = EmbeddingService(mode=mode)  # type: ignore[arg-type]
            assert svc.embed([]) == []

    def test_embed_one_returns_empty_when_embed_returns_empty(self):
        svc = EmbeddingService(mode="disabled")
        assert svc.embed_one("hello") == []

    def test_embed_one_returns_first_vector_when_available(self):
        svc = EmbeddingService(mode="hash")
        vec = svc.embed_one("hello")
        assert len(vec) == _HASH_EMBED_DIM

    def test_embed_unknown_mode_returns_empty(self):
        svc = EmbeddingService(mode="disabled")  # type: ignore[arg-type]
        # 强制覆盖 mode 为非法值，触发 fallback return []
        svc._mode = "unknown"  # type: ignore[assignment]
        assert svc.embed(["x"]) == []

    def test_embed_hash_mode_returns_one_vector_per_text(self):
        svc = EmbeddingService(mode="hash")
        results = svc.embed(["a", "b", "c"])
        assert len(results) == 3
        for vec in results:
            assert len(vec) == _HASH_EMBED_DIM

    def test_embed_texts_delegates_to_embed(self):
        svc = EmbeddingService(mode="hash")
        assert svc.embed_texts(["a", "b"]) == svc.embed(["a", "b"])

    def test_embed_query_delegates_to_embed_one(self):
        svc = EmbeddingService(mode="hash")
        assert svc.embed_query("a") == svc.embed_one("a")


# ---------------------------------------------------------------------------
# _embed_local / _get_local_model
# ---------------------------------------------------------------------------


class TestEmbedLocal:
    def _install_fake_st(self, monkeypatch: pytest.MonkeyPatch, encode_return: Any) -> MagicMock:
        fake_model = MagicMock()
        fake_model.encode.return_value = encode_return
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
        return fake_model

    def test_local_encode_returns_numpy_like_rows(self, monkeypatch: pytest.MonkeyPatch):
        """encode 返回类 numpy 二维结构时，应正确转 list[float]。"""

        # 模拟每行是可迭代的对象（如 numpy.array）
        class _Row:
            def __init__(self, values: list[float]) -> None:
                self._values = values

            def __iter__(self):
                return iter(self._values)

        rows = [_Row([0.1, 0.2, 0.3]), _Row([0.4, 0.5, 0.6])]
        fake_model = self._install_fake_st(monkeypatch, rows)

        svc = EmbeddingService(mode="local")
        result = svc.embed(["a", "b"])
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        fake_model.encode.assert_called_once_with(["a", "b"])

    def test_local_caches_dim_after_first_embed(self, monkeypatch: pytest.MonkeyPatch):
        self._install_fake_st(monkeypatch, [[0.1, 0.2, 0.3]])
        svc = EmbeddingService(mode="local")
        assert svc._dim_cache is None
        svc.embed(["x"])
        assert svc._dim_cache == 3

    def test_local_does_not_overwrite_dim_cache_if_already_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        self._install_fake_st(monkeypatch, [[0.1, 0.2, 0.3]])
        svc = EmbeddingService(mode="local")
        svc._dim_cache = 999
        svc.embed(["x"])
        assert svc._dim_cache == 999

    def test_local_encode_recoverable_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        """encode 抛 RECOVERABLE_ERRORS 时返回空列表。"""
        fake_model = MagicMock()
        fake_model.encode.side_effect = RuntimeError("cuda OOM")
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        assert svc.embed(["x"]) == []

    def test_local_model_load_failure_marks_attempted_no_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """SentenceTransformer 构造失败后，``_load_attempted`` 应阻止重试。"""
        # 用计数器验证第二次调用不会触发 SentenceTransformer 构造
        import_call_count = {"n": 0}

        class _Raiser:
            def __getattr__(self, name: str) -> Any:
                import_call_count["n"] += 1
                raise ImportError("no st")

        fake_module = _Raiser()
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        # 第一次调用：尝试加载失败，返回 None
        assert svc._get_local_model() is None
        assert svc._load_attempted is True
        first_count = import_call_count["n"]
        # 第二次调用：应短路返回 None，不触发 __getattr__
        assert svc._get_local_model() is None
        assert import_call_count["n"] == first_count

    def test_local_model_loaded_returns_cached_instance(self, monkeypatch: pytest.MonkeyPatch):
        """模型加载成功后，再次调用 ``_get_local_model`` 返回缓存实例。"""
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1]]
        fake_module = types.ModuleType("sentence_transformers")
        st_ctor = MagicMock(return_value=fake_model)
        fake_module.SentenceTransformer = st_ctor
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        first = svc._get_local_model()
        second = svc._get_local_model()
        assert first is second is fake_model
        assert st_ctor.call_count == 1

    def test_local_uses_env_model_name(self, monkeypatch: pytest.MonkeyPatch):
        """``FHD_EMBEDDING_LOCAL_MODEL`` 环境变量应传递给构造器。"""
        monkeypatch.setenv("FHD_EMBEDDING_LOCAL_MODEL", "BAAI/bge-small-zh-v1.5")
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1]]
        fake_module = types.ModuleType("sentence_transformers")
        st_ctor = MagicMock(return_value=fake_model)
        fake_module.SentenceTransformer = st_ctor
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        svc.embed(["x"])
        st_ctor.assert_called_once_with("BAAI/bge-small-zh-v1.5")

    def test_local_default_model_name_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FHD_EMBEDDING_LOCAL_MODEL", raising=False)
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1]]
        fake_module = types.ModuleType("sentence_transformers")
        st_ctor = MagicMock(return_value=fake_model)
        fake_module.SentenceTransformer = st_ctor
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        svc.embed(["x"])
        st_ctor.assert_called_once_with("sentence-transformers/all-MiniLM-L6-v2")

    def test_local_thread_safe_lazy_load(self, monkeypatch: pytest.MonkeyPatch):
        """多线程并发触发 ``_get_local_model`` 应只加载一次。"""
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1]]
        fake_module = types.ModuleType("sentence_transformers")
        st_ctor = MagicMock(return_value=fake_model)
        fake_module.SentenceTransformer = st_ctor
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        results: list[Any] = []
        errors: list[BaseException] = []

        def _worker() -> None:
            try:
                results.append(svc._get_local_model())
            except BOUNDARY_ERRORS as e:  # thread boundary captures worker failures
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert all(r is fake_model for r in results)
        assert len(results) == 8
        assert st_ctor.call_count == 1

    def test_local_get_model_inner_lock_recheck(self, monkeypatch: pytest.MonkeyPatch):
        """覆盖 ``_get_local_model`` 锁内二次检查分支（line 201）。

        构造场景：进入外层检查时 ``_model is None``，但获取锁的过程中另一线程已设置
        ``_model``，此时锁内二次检查应直接返回缓存的模型，不再调用 SentenceTransformer。
        """
        fake_model = MagicMock()
        fake_module = types.ModuleType("sentence_transformers")
        st_ctor = MagicMock(return_value=fake_model)
        fake_module.SentenceTransformer = st_ctor
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService(mode="local")
        original_lock = svc._load_lock

        class _MockLock:
            """进入即设置 ``_model``，模拟另一线程已加载完毕。"""

            def __enter__(self):
                svc._model = fake_model
                return self

            def __exit__(self, *exc):
                return False

        svc._load_lock = _MockLock()  # type: ignore[assignment]
        # 外层检查时 _model 仍为 None
        assert svc._model is None
        result = svc._get_local_model()
        # 锁内二次检查命中，直接返回 fake_model，不调用 st_ctor
        assert result is fake_model
        assert st_ctor.call_count == 0
        # 恢复 lock 避免影响后续用例
        svc._load_lock = original_lock


# ---------------------------------------------------------------------------
# _embed_remote
# ---------------------------------------------------------------------------


class TestEmbedRemote:
    def test_remote_no_api_key_omits_authorization_header(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")
        # 不设置 FHD_EMBEDDING_REMOTE_API_KEY
        monkeypatch.delenv("FHD_EMBEDDING_REMOTE_API_KEY", raising=False)

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp) as mock_post:
            svc = EmbeddingService(mode="remote")
            result = svc.embed(["x"])

        assert result == [[0.1]]
        headers = mock_post.call_args.kwargs["headers"]
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_remote_no_model_omits_model_in_payload(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")
        monkeypatch.delenv("FHD_EMBEDDING_REMOTE_MODEL", raising=False)

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp) as mock_post:
            svc = EmbeddingService(mode="remote")
            svc.embed(["x"])

        payload = mock_post.call_args.kwargs["json"]
        assert "model" not in payload
        assert payload["input"] == ["x"]

    def test_remote_empty_data_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": []}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp):
            svc = EmbeddingService(mode="remote")
            assert svc.embed(["x"]) == []

    def test_remote_missing_index_field_defaults_to_zero(self, monkeypatch: pytest.MonkeyPatch):
        """OpenAI 兼容 API 中 item 缺 index 字段时按 0 排序。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "data": [
                {"embedding": [0.3, 0.4]},
                {"embedding": [0.1, 0.2]},
            ]
        }
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp):
            svc = EmbeddingService(mode="remote")
            result = svc.embed(["a", "b"])

        # 两个 item 都缺 index，按 0 排序，stable sort 保留原顺序
        assert result == [[0.3, 0.4], [0.1, 0.2]]

    def test_remote_caches_dim_after_first_call(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp):
            svc = EmbeddingService(mode="remote")
            assert svc._dim_cache is None
            svc.embed(["x"])
            assert svc._dim_cache == 4

    def test_remote_does_not_overwrite_dim_cache_if_already_set(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp):
            svc = EmbeddingService(mode="remote")
            svc._dim_cache = 999
            svc.embed(["x"])
            assert svc._dim_cache == 999

    def test_remote_timeout_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        with patch("requests.post", side_effect=TimeoutError("slow")):
            svc = EmbeddingService(mode="remote")
            assert svc.embed(["x"]) == []

    def test_remote_uses_30s_timeout(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp) as mock_post:
            svc = EmbeddingService(mode="remote")
            svc.embed(["x"])

        assert mock_post.call_args.kwargs["timeout"] == 30

    def test_remote_url_with_whitespace_is_stripped(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "  https://api.example.com/v1/embeddings  ")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [{"embedding": [0.1], "index": 0}]}
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp) as mock_post:
            svc = EmbeddingService(mode="remote")
            svc.embed(["x"])

        assert mock_post.call_args.args[0] == "https://api.example.com/v1/embeddings"


# ---------------------------------------------------------------------------
# 单例 / get_default_embedding_service
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_singleton_returns_same_instance(self):
        a = EmbeddingService.get_singleton()
        b = EmbeddingService.get_singleton()
        assert a is b

    def test_reset_singleton_creates_new_instance(self):
        a = EmbeddingService.get_singleton()
        EmbeddingService.reset_singleton_for_tests()
        b = EmbeddingService.get_singleton()
        assert a is not b

    def test_get_singleton_thread_safe(self):
        """并发获取单例应返回同一实例。"""
        results: list[EmbeddingService] = []
        errors: list[BaseException] = []

        def _worker() -> None:
            try:
                results.append(EmbeddingService.get_singleton())
            except BOUNDARY_ERRORS as e:  # thread boundary captures worker failures
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 16
        first = results[0]
        assert all(r is first for r in results)

    def test_get_default_embedding_service_returns_service_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "hash")
        svc = get_default_embedding_service()
        assert svc is not None
        assert svc.is_available() is True
        assert svc.mode == "hash"

    def test_get_default_embedding_service_returns_none_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "disabled")
        assert get_default_embedding_service() is None

    def test_construct_with_explicit_mode_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        svc = EmbeddingService(mode="hash")
        assert svc.mode == "hash"

    def test_construct_with_none_mode_uses_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        svc = EmbeddingService(mode=None)
        assert svc.mode == "remote"


# ---------------------------------------------------------------------------
# is_available / mode property
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_is_available_true_for_local(self):
        assert EmbeddingService(mode="local").is_available() is True

    def test_is_available_true_for_remote(self):
        assert EmbeddingService(mode="remote").is_available() is True

    def test_is_available_true_for_hash(self):
        assert EmbeddingService(mode="hash").is_available() is True

    def test_is_available_false_for_disabled(self):
        assert EmbeddingService(mode="disabled").is_available() is False

    def test_mode_property_returns_init_mode(self):
        for mode in ("local", "remote", "hash", "disabled"):
            assert EmbeddingService(mode=mode).mode == mode  # type: ignore[arg-type]
