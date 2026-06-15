# -*- coding: utf-8 -*-
"""
意图识别测试脚本（遗留 standalone，非 pytest 套件）

原 Windows 路径硬编码；完整意图栈见 tests/benchmarks/test_intent_accuracy.py
"""

import pytest

pytest.skip(
    "legacy standalone script; use tests/benchmarks/test_intent_accuracy.py with INTENT_BENCHMARK_RUN=1",
    allow_module_level=True,
)
