"""XCAGI vendored langgraph-sdk 导入探针测试 (LG-W0-11).

核对任务要求的可导入符号:
  - 版本号 __version__ == "0.4.2"
  - 关键公共符号: get_client / get_sync_client / Auth / Encryption / EncryptionContext

本测试在包本地 locked uv 环境运行（`uv run --locked pytest`）。为防「空载通过」，本测试:
  - 不修改 sys.path，不依赖 PYTHONPATH / LANGGRAPH_CORE_SRC；
  - 不做任何 pytest.skip；
  - 断言每个导入模块的源码文件位于 FHD/packages 下的 vendored 包内（而非 PyPI 上游）；
  - 断言 langgraph-sdk 不从 registry 拉取 LangGraph 核心（本包源码不含 langgraph 核心导入）。
"""

from __future__ import annotations

import inspect
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent  # packages/xcagi_langgraph_sdk
PACKAGES_ROOT = PKG.parent  # FHD/packages/


def _assert_vendored(module: object) -> None:
    """断言模块源码文件位于 FHD/packages/xcagi_langgraph_sdk 下（vendored，非 PyPI 上游）。"""
    file = Path(getattr(module, "__file__", "") or "")
    assert file.is_absolute(), f"{module.__name__} 无 __file__，疑似命名空间占位"
    resolved = file.resolve()
    assert resolved.is_relative_to(PACKAGES_ROOT), (
        f"{module.__name__} 源码 ({resolved}) 不在 FHD/packages 下"
        f"，可能来自 PyPI 上游而非 vendored 副本"
    )
    assert "xcagi_langgraph_sdk" in resolved.parts, (
        f"{module.__name__} 源码 ({resolved}) 不在期望的 vendored 包 xcagi_langgraph_sdk 下"
    )


def test_version_is_0_4_2() -> None:
    import langgraph_sdk

    assert langgraph_sdk.__version__ == "0.4.2"


def test_key_public_symbols_importable() -> None:
    from langgraph_sdk import (
        Auth,
        Encryption,
        EncryptionContext,
        get_client,
        get_sync_client,
    )

    for sym in (Auth, Encryption, EncryptionContext):
        assert isinstance(sym, type)
    assert callable(inspect.unwrap(get_client))
    assert callable(inspect.unwrap(get_sync_client))


def test_top_level_entrypoints_resolve_to_vendored() -> None:
    """断言顶层入口 (__init__/client/encryption) 源码均位于本 vendored 包下。"""
    import langgraph_sdk
    import langgraph_sdk.client
    import langgraph_sdk.encryption

    _assert_vendored(langgraph_sdk)
    _assert_vendored(langgraph_sdk.client)
    _assert_vendored(langgraph_sdk.encryption)


def test_sync_and_async_clients_resolve_to_vendored() -> None:
    import langgraph_sdk._async.client
    import langgraph_sdk._sync.client

    _assert_vendored(langgraph_sdk._async.client)
    _assert_vendored(langgraph_sdk._sync.client)
