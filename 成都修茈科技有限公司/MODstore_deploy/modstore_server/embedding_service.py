"""OpenAI-compatible embedding client for knowledge-base vectors."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session


class EmbeddingConfigError(RuntimeError):
    pass


_PROVIDER_EMBEDDING_DEFAULTS: Dict[str, tuple[str, int]] = {
    "openai": ("text-embedding-3-small", 1536),
    "siliconflow": ("BAAI/bge-m3", 1024),
    "dashscope": ("text-embedding-v3", 1024),
    "zhipu": ("embedding-3", 2048),
    "together": ("BAAI/bge-large-en-v1.5", 1024),
    "ollama": ("nomic-embed-text", 768),
}
_EMBEDDING_PROVIDER_ORDER = ("openai", "siliconflow", "dashscope", "zhipu", "together", "ollama")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _provider_env_name(prefix: str, provider: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in provider.upper())
    return f"{prefix}_{safe}"


def _provider_embedding_configured(provider: str) -> bool:
    p = (provider or "").strip().lower()
    return bool(
        p in _PROVIDER_EMBEDDING_DEFAULTS
        or _env(_provider_env_name("MODSTORE_EMBEDDING_MODEL", p))
        or _env(_provider_env_name("MODSTORE_EMBEDDING_DIM", p))
    )


def _provider_embedding_model_dim(provider: str) -> tuple[str, int]:
    p = (provider or "").strip().lower()
    model = _env(_provider_env_name("MODSTORE_EMBEDDING_MODEL", p))
    dim_raw = _env(_provider_env_name("MODSTORE_EMBEDDING_DIM", p))
    default_model, default_dim = _PROVIDER_EMBEDDING_DEFAULTS.get(
        p,
        (
            _env("MODSTORE_EMBEDDING_MODEL") or "text-embedding-3-small",
            int(_env("MODSTORE_EMBEDDING_DIM") or "1536"),
        ),
    )
    dim = int(dim_raw or default_dim)
    return model or default_model, dim


def _resolve_embedding_config(
    *,
    session: Optional[Session] = None,
    user_id: Optional[int] = None,
    provider: Optional[str] = None,
    include_secret: bool = False,
) -> Dict[str, Any]:
    selected_provider = (provider or "").strip().lower()
    api_key = (os.environ.get("MODSTORE_EMBEDDING_API_KEY") or "").strip()
    base_url = (
        os.environ.get("MODSTORE_EMBEDDING_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    ).strip()
    model = (os.environ.get("MODSTORE_EMBEDDING_MODEL") or "text-embedding-3-small").strip()
    dim = int((os.environ.get("MODSTORE_EMBEDDING_DIM") or "1536").strip() or "1536")
    source = "embedding_env" if api_key else "none"

    if not api_key and session is not None and user_id is not None:
        try:
            from modstore_server.llm_key_resolver import (
                OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
                resolve_api_key,
                resolve_base_url,
            )

            candidates = []
            if selected_provider:
                candidates.append(selected_provider)
            candidates.extend(p for p in _EMBEDDING_PROVIDER_ORDER if p not in candidates)
            for candidate in candidates:
                if candidate not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
                    continue
                if not _provider_embedding_configured(candidate):
                    continue
                provider_key, provider_source = resolve_api_key(session, int(user_id), candidate)
                if provider_key:
                    provider_base = resolve_base_url(session, int(user_id), candidate) or ""
                    provider_model, provider_dim = _provider_embedding_model_dim(candidate)
                    api_key = provider_key
                    base_url = provider_base
                    model = provider_model
                    dim = provider_dim
                    source = f"{candidate}:{provider_source}"
                    selected_provider = candidate
                    break
        except Exception:
            # 回退到 MODSTORE_EMBEDDING_* 环境变量，避免状态接口因 BYOK 解密问题中断。
            pass
    out: Dict[str, Any] = {
        "configured": bool(api_key),
        "base_url": base_url or "https://api.openai.com/v1",
        "model": model,
        "dim": dim,
        "provider": selected_provider or "env",
        "source": source,
    }
    if include_secret:
        out["_api_key"] = api_key
    return out


def embedding_config_snapshot(
    *,
    session: Optional[Session] = None,
    user_id: Optional[int] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    return _resolve_embedding_config(
        session=session, user_id=user_id, provider=provider, include_secret=False
    )


def _embeddings_url(base_url: str, *, provider: str = "") -> str:
    b = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
    if provider == "ollama":
        if "/api/embed" in b:
            return b
        return f"{b.rstrip('/')}/api/embed"
    if b.endswith("/embeddings"):
        return b
    path = (urlparse(b).path or "").rstrip("/")
    if path.endswith("/compatible-mode"):
        return f"{b}/v1/embeddings"
    if path.endswith("/v1") or path.endswith("/v2") or path.endswith("/v3") or path.endswith("/v4"):
        return f"{b}/embeddings"
    if path.endswith("/api/v3"):
        return f"{b}/embeddings"
    return f"{b}/v1/embeddings"


async def embed_texts(
    texts: List[str],
    *,
    session: Optional[Session] = None,
    user_id: Optional[int] = None,
    provider: Optional[str] = None,
) -> List[List[float]]:
    cfg = _resolve_embedding_config(
        session=session, user_id=user_id, provider=provider, include_secret=True
    )
    api_key = str(cfg.pop("_api_key", "") or "").strip()
    selected_provider = str(cfg.get("provider") or provider or "").strip().lower()

    if selected_provider == "ollama":
        return await _embed_ollama(texts, cfg)

    if not api_key:
        raise EmbeddingConfigError("未配置可用 Embedding Key；已读取文件内容，但无法写入向量库")

    clean = [(t or "").strip() for t in texts]
    if not clean:
        return []
    body = {"model": cfg["model"], "input": clean}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    try:
        res = await client.post(
            _embeddings_url(str(cfg["base_url"]), provider=selected_provider),
            json=body,
            headers=headers,
            timeout=60.0,
        )
        res.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = (e.response.text or "").strip()
        raise EmbeddingConfigError(
            f"Embedding API 调用失败：HTTP {e.response.status_code}"
            + (f"；{detail[:240]}" if detail else "")
        ) from e
    except httpx.HTTPError as e:
        raise EmbeddingConfigError(f"Embedding API 调用失败：{e}") from e
    data = res.json()

    rows = data.get("data")
    if not isinstance(rows, list):
        raise EmbeddingConfigError("Embedding API 响应缺少 data")
    rows = sorted(rows, key=lambda x: int(x.get("index", 0)) if isinstance(x, dict) else 0)
    vectors: List[List[float]] = []
    for item in rows:
        emb = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(emb, list):
            raise EmbeddingConfigError("Embedding API 响应缺少 embedding")
        if len(emb) != int(cfg["dim"]):
            raise EmbeddingConfigError(f"Embedding 维度 {len(emb)} 与配置 {cfg['dim']} 不一致")
        vectors.append([float(x) for x in emb])
    return vectors


async def _embed_ollama(texts: List[str], cfg: Dict[str, Any]) -> List[List[float]]:
    """Embed texts via Ollama /api/embed endpoint."""
    clean = [(t or "").strip() for t in texts]
    if not clean:
        return []
    base_url = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip().rstrip("/")
    url = _embeddings_url(base_url, provider="ollama")
    body = {"model": cfg["model"], "input": clean}
    headers = {"Content-Type": "application/json"}
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    try:
        res = await client.post(url, json=body, headers=headers, timeout=120.0)
        res.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise EmbeddingConfigError(
            f"Ollama Embedding 调用失败：HTTP {e.response.status_code}"
        ) from e
    except httpx.HTTPError as e:
        raise EmbeddingConfigError(f"Ollama Embedding 调用失败：{e}") from e
    data = res.json()
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list):
        raise EmbeddingConfigError("Ollama 响应缺少 embeddings 字段")
    vectors: List[List[float]] = []
    for emb in embeddings:
        if not isinstance(emb, list):
            raise EmbeddingConfigError("Ollama 响应 embeddings 格式异常")
        vectors.append([float(x) for x in emb])
    return vectors
