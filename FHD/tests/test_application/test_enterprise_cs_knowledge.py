from __future__ import annotations

import pytest

from app.application import dataset_rag_app_service
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.enterprise_cs_automation import retrieve_product_knowledge
from app.infrastructure.rag.enterprise_cs_knowledge import cite_product_reply


@pytest.mark.asyncio
async def test_enterprise_support_uses_only_public_first_party_knowledge(tmp_path, monkeypatch):
    service = dataset_rag_app_service.DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    context = DatasetAccessContext(
        actor_id="product-publisher",
        tenant_id="product",
        permissions=frozenset({"dataset.read", "dataset.write", "dataset.admin"}),
        is_admin=False,
    )
    help_url = "https://www.xiu-ci.com/docs/install"
    for dataset, source, visibility, detail in (
        ("support", help_url, "public", "安装完成后打开产品并登录。"),
        ("support", "https://www.xiu-ci.com/admin", "private", "不可公开的安装内容。"),
        ("support", "https://xiu-ci.com.example.org/install", "public", "外站牛油果饲料建议。"),
        ("internal", "https://www.xiu-ci.com/docs/internal", "public", "内部安装建议。"),
    ):
        ingested = service.ingest_document(
            dataset_id=dataset,
            source=source,
            text=f"XCAGI 安装指南：{detail}" * 6,
            tenant_id="product",
            metadata={"visibility": visibility},
            chunk_strategy="fixed",
            access_context=context,
        )
        assert ingested["success"]

    key = service.create_api_key("support", access_context=context)
    monkeypatch.setenv("XCAGI_ENTERPRISE_CS_KB_KEY", key["key"])
    monkeypatch.setattr(dataset_rag_app_service, "get_dataset_rag_app_service", lambda: service)

    evidence = await retrieve_product_knowledge("XCAGI 安装")
    prompt = evidence.format_for_prompt()
    assert "安装完成后打开产品并登录" in prompt
    assert all(marker not in prompt for marker in ("不可公开", "牛油果饲料", "内部安装"))
    assert cite_product_reply("安装完成后打开产品并登录。[1]", evidence).endswith(help_url)
    assert cite_product_reply("安装完直接登录。", evidence) == ""
    assert cite_product_reply("安装完直接登录。[1][99]", evidence) == ""
    assert cite_product_reply("访问 https://example.org 安装。[1]", evidence) == ""

    assert not (await retrieve_product_knowledge("牛油果饲料")).format_for_prompt()

    service.revoke_api_key("support", key["token_id"], access_context=context)
    prompt = (await retrieve_product_knowledge("XCAGI 安装")).format_for_prompt()
    assert "安装完成后打开产品并登录" not in prompt


@pytest.mark.asyncio
async def test_enterprise_support_can_cite_the_packaged_product_guide(monkeypatch):
    monkeypatch.delenv("XCAGI_ENTERPRISE_CS_KB_KEY", raising=False)
    evidence = await retrieve_product_knowledge("XCAGI 下载和安装包")
    assert "安装前核对页面显示的 SHA-256" in evidence.format_for_prompt()
    assert cite_product_reply("下载后在安装前核对 SHA-256。[1]", evidence).endswith(
        "https://xiu-ci.com/download"
    )
    assert not (await retrieve_product_knowledge("蘑菇养殖")).format_for_prompt()
