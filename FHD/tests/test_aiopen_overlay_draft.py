"""AIOPEN 语义草稿流水线测试：解析校验、候选排序、草稿落盘与审核后加载。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

_FHD = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "aiopen_overlay_draft", _FHD / "scripts" / "dev" / "aiopen_overlay_draft.py"
)
assert _spec and _spec.loader
draft_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(draft_tool)

from app.application.aiopen import catalog_builder


def _operation(operation_id: str, risk: str, *, described: bool = False) -> dict:
    return {
        "operation_id": operation_id,
        "method": "GET" if risk == "read" else "POST",
        "path": "/api/" + operation_id.replace(".", "/"),
        "risk": risk,
        "domain": operation_id.split(".", maxsplit=1)[0],
        "summary": operation_id,
        "described": described,
    }


def test_parse_drafts_drops_unknown_and_invalid_entries():
    raw = """```json
    [
      {"operation_id": "products.list", "when_to_use": "浏览商品", "side_effects": [], "preconditions": ["已登录"], "returns": "商品列表"},
      {"operation_id": "ghost.op", "when_to_use": "编造", "side_effects": [], "preconditions": [], "returns": ""},
      {"operation_id": "orders.create", "when_to_use": "", "side_effects": [], "preconditions": [], "returns": ""}
    ]
    ```"""
    drafts = draft_tool.parse_drafts(raw, {"products.list", "orders.create"})
    assert [item["operation_id"] for item in drafts] == ["products.list"]
    assert drafts[0]["preconditions"] == ["已登录"]


def test_parse_drafts_handles_non_json_output():
    assert draft_tool.parse_drafts("模型拒绝回答", {"products.list"}) == []


def test_parse_drafts_normalizes_scalar_lists():
    raw = '[{"operation_id":"orders.create","when_to_use":"创建订单","side_effects":"写数据库","preconditions":[],"returns":""}]'
    drafts = draft_tool.parse_drafts(raw, {"orders.create"})
    assert drafts[0]["side_effects"] == ["写数据库"]


def test_select_targets_prefers_read_and_skips_described():
    operations = [
        _operation("orders.delete", "danger"),
        _operation("orders.create", "write"),
        _operation("products.list", "read"),
        _operation("products.search", "read", described=True),
    ]
    targets = draft_tool.select_targets(operations, limit=2, domains=set())
    assert [item["operation_id"] for item in targets] == ["products.list", "orders.create"]


def test_select_targets_respects_domains():
    operations = [_operation("products.list", "read"), _operation("orders.list", "read")]
    targets = draft_tool.select_targets(operations, limit=0, domains={"orders"})
    assert [item["operation_id"] for item in targets] == ["orders.list"]


@pytest.mark.asyncio
async def test_generate_writes_draft_file(monkeypatch, tmp_path):
    async def fake_completion(messages, **kwargs):
        batch = yaml.safe_load(messages[1]["content"])
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [
                                {
                                    "operation_id": item["operation_id"],
                                    "when_to_use": "查看" + item["operation_id"],
                                    "side_effects": [],
                                    "preconditions": ["已登录"],
                                    "returns": "",
                                }
                                for item in batch
                            ],
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "app.infrastructure.llm.invoke.chat_completion_openai_format", fake_completion
    )
    monkeypatch.setattr(draft_tool, "DRAFT_DIR", tmp_path)
    catalog = {"operations": [_operation("products.list", "read")]}
    path = await draft_tool.generate(
        catalog, batch_size=5, limit=10, domains=set(), profile="default", dry_run=False
    )
    assert path is not None and path.exists()
    document = yaml.safe_load(path.read_text(encoding="utf-8").split("\n", 1)[1])
    assert document["reviewed"] is False
    assert document["operations"][0]["operation_id"] == "products.list"
    assert document["operations"][0]["reviewed"] is False


def test_loader_reads_generated_but_not_drafts(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    generated = overlay / "generated"
    drafts = overlay / "drafts"
    for directory in (generated, drafts):
        directory.mkdir(parents=True)
    (overlay / "operations.yaml").write_text(
        yaml.safe_dump(
            {
                "glossary": {"products": ["商品"]},
                "operations": [{"operation_id": "products.list", "when_to_use": "人工条目"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (generated / "batch-01.yaml").write_text(
        yaml.safe_dump(
            {"operations": [{"operation_id": "orders.create", "when_to_use": "已审核条目"}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (drafts / "draft-01.yaml").write_text(
        yaml.safe_dump(
            {"operations": [{"operation_id": "ghost.op", "when_to_use": "未审核"}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog_builder, "_OVERLAY_DIR", overlay)
    monkeypatch.setattr(catalog_builder, "_OVERLAY_PATH", overlay / "operations.yaml")
    monkeypatch.setattr(catalog_builder, "_OVERLAY_GENERATED_DIR", generated)
    monkeypatch.setitem(catalog_builder._OVERLAY_CACHE, "signature", None)
    entries = catalog_builder.load_overlay()
    assert set(entries) == {"products.list", "orders.create"}
    assert catalog_builder.load_glossary() == {"products": ["商品"]}
