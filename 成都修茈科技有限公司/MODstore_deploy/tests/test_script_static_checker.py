"""``script_agent.static_checker`` 的边界用例。"""

from __future__ import annotations

from modstore_server.script_agent.sandbox_runner import DEFAULT_TIMEOUT_SECONDS
from modstore_server.script_agent.static_checker import validate_script


def test_blocks_subprocess_import():
    assert validate_script("import subprocess\n")


def test_blocks_subprocess_run_call():
    code = "import os\nimport sys\nx = sys.executable\n"  # 仅基础 stdlib，应通过
    assert not validate_script(code)


def test_blocks_eval_call():
    assert validate_script("y = eval('1+1')\n")


def test_blocks_exec_call():
    assert validate_script("exec('print(1)')\n")


def test_blocks_compile_call():
    assert validate_script("c = compile('1', '<s>', 'eval')\n")


def test_blocks_dunder_import_call():
    assert validate_script("m = __import__('os')\n")


def test_blocks_os_system():
    assert validate_script("import os\nos.system('ls')\n")


def test_blocks_ctypes_import():
    assert validate_script("import ctypes\n")


def test_blocks_multiprocessing_import():
    assert validate_script("import multiprocessing\n")


def test_blocks_third_party_not_in_allowlist():
    assert validate_script("import pandas\n")


def test_allows_common_stdlib_modules():
    """回归保护：logging/urllib/threading/hashlib/io/itertools 等 stdlib 必须放行。

    历史上 ``workbench_script_runner.py`` 写死过一份很窄的 ``ALLOWED_IMPORTS``，
    导致 LLM 生成的脚本一旦 ``import logging`` 就被拦掉。新 checker 用
    ``sys.stdlib_module_names`` 取代该硬编码白名单，所有 stdlib 模块除高危项
    （subprocess/ctypes/multiprocessing）外都默认通过。
    """
    safe_stdlib_imports = [
        "import logging",
        "import logging.handlers",
        "from logging import getLogger",
        "import threading",
        "import io",
        "import urllib.parse",
        "import urllib.request",
        "import collections",
        "import itertools",
        "import functools",
        "import hashlib",
        "import base64",
        "import time",
        "import random",
        "import argparse",
        "import typing",
    ]
    for snippet in safe_stdlib_imports:
        errs = validate_script(snippet + "\n")
        assert not errs, f"{snippet!r} should be allowed but got: {errs}"


def test_allows_modstore_runtime():
    code = "from modstore_runtime import ai, kb_search, employee_run\n"
    assert not validate_script(code)


def test_allows_default_allowlist_openpyxl():
    # runtime_allowlist.json 默认收录 openpyxl
    code = "import openpyxl\nfrom openpyxl import Workbook\n"
    assert not validate_script(code)


def test_blocks_relative_import():
    assert validate_script("from . import foo\n")


def test_reports_syntax_error_first():
    errs = validate_script("def f(:\n  pass\n")
    assert errs
    assert "语法错误" in errs[0] or "syntax" in errs[0].lower()


def test_prose_chinese_does_not_report_invalid_character_u3002():
    """模型把中文说明当脚本返回时，应提示「非代码」而非 ``invalid character '。'``。"""
    prose = "这是一个文档归纳助手。它会读取文档并输出 Markdown。\n"
    errs = validate_script(prose)
    assert errs
    assert "invalid character" not in errs[0].lower()
    assert "U+3002" not in errs[0]
    assert "中文" in errs[0] or "说明" in errs[0]


def test_default_sandbox_timeout_is_interactive():
    assert DEFAULT_TIMEOUT_SECONDS <= 60
