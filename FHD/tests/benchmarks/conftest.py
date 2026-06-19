"""Benchmarks 测试隔离 fixture。

重置 intent 服务全局状态，避免前序测试污染缓存导致准确率下降。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_intent_service():
    """每个测试前重置 intent 服务全局状态（缓存 + 反射弧 + 配置）。

    根因：app.services.intent_service 模块级全局变量 _intent_cache / _reflex_arc
    在全量套件中被前序测试污染，导致 golden set 准确率从 95%+ 降至 91.67%。
    通过 reload_intent_service() 公开 API 重置，保证测试隔离性。
    """
    from app.services.intent_service import reload_intent_service

    reload_intent_service()
