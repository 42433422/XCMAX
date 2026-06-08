from __future__ import annotations


class _NoopSession:
    def query(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


def test_xiaomi_chat_model_falls_back_to_embedding_provider(monkeypatch):
    from modstore_server.embedding_service import embedding_config_snapshot

    monkeypatch.delenv("MODSTORE_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("MODSTORE_EMBEDDING_MODEL_XIAOMI", raising=False)
    monkeypatch.delenv("MODSTORE_EMBEDDING_DIM_XIAOMI", raising=False)
    monkeypatch.setenv("XIAOMI_API_KEY", "tp-chat-only")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-embedding")

    cfg = embedding_config_snapshot(session=_NoopSession(), user_id=1, provider="xiaomi")

    assert cfg["configured"] is True
    assert cfg["provider"] == "siliconflow"
    assert cfg["model"] == "BAAI/bge-m3"
    assert cfg["dim"] == 1024


def test_xiaomi_embedding_enabled_only_with_model_and_dim(monkeypatch):
    from modstore_server.embedding_service import embedding_config_snapshot

    monkeypatch.setenv("MODSTORE_EMBEDDING_API_KEY", "tp-embedding")
    monkeypatch.setenv("MODSTORE_EMBEDDING_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("MODSTORE_EMBEDDING_MODEL", "mimo-embedding-test")
    monkeypatch.setenv("MODSTORE_EMBEDDING_DIM", "1024")

    cfg = embedding_config_snapshot(session=_NoopSession(), user_id=1, provider="xiaomi")

    assert cfg["configured"] is True
    assert cfg["provider"] == "xiaomi"
    assert cfg["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
    assert cfg["model"] == "mimo-embedding-test"
    assert cfg["dim"] == 1024


def test_global_embedding_env_wins(monkeypatch):
    from modstore_server.embedding_service import embedding_config_snapshot

    monkeypatch.setenv("MODSTORE_EMBEDDING_API_KEY", "emb-global")
    monkeypatch.setenv("MODSTORE_EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("MODSTORE_EMBEDDING_MODEL", "custom-embedding")
    monkeypatch.setenv("MODSTORE_EMBEDDING_DIM", "768")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-embedding")

    cfg = embedding_config_snapshot(session=_NoopSession(), user_id=1, provider="siliconflow")

    assert cfg["provider"] == "siliconflow"
    assert cfg["source"] == "embedding_env"
    assert cfg["base_url"] == "https://embedding.example/v1"
    assert cfg["model"] == "custom-embedding"
    assert cfg["dim"] == 768
