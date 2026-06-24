"""第二波真实行为测试：app/ai_engines/rasa/nlu_service.py。

聚焦此前未覆盖的分支：
- ``_find_latest_local_model`` 命中目录/有 tar / 空 tar。
- ``__init__`` 置信度阈值 ValueError 回退。
- ``load_model`` 的 disabled / server / embedded(import 失败 / load 成功 / load 失败) 各分支。
- ``parse`` 走 embedded 路径(180)。
- ``_parse_via_server`` 的 requests 缺失 / 不可达 / 非200 / 坏 JSON。
- ``_parse_via_embedded`` 成功 / RuntimeError 兜底 / RECOVERABLE_ERRORS。

全部离线、确定性：mock 文件系统 / requests / rasa Agent / asyncio.run。
不触碰任何源码。
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.ai_engines.rasa.nlu_service import (
    RasaNLUService,
    _find_latest_local_model,
)

MOD = "app.ai_engines.rasa.nlu_service"


# ---------------------------------------------------------------------------
# _find_latest_local_model — 命中目录、按 mtime 排序、空目录
# ---------------------------------------------------------------------------


def test_find_latest_local_model_picks_newest_tar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第一个候选目录存在且含 *.tar.gz 时，返回 mtime 最新者(覆盖 66/71-72)。"""

    old_tar = "20240101-old.tar.gz"
    new_tar = "20240601-new.tar.gz"

    # 第一个候选目录(<repo>/rasa/models)存在即命中第一轮循环。
    monkeypatch.setattr(
        f"{MOD}.os.path.isdir",
        lambda p: p.replace(os.sep, "/").endswith("rasa/models"),
    )
    monkeypatch.setattr(f"{MOD}.glob.glob", lambda pat: [old_tar, new_tar])
    # new_tar 的 mtime 更大 → 应排在前。
    mtimes = {old_tar: 100.0, new_tar: 200.0}
    monkeypatch.setattr(f"{MOD}.os.path.getmtime", lambda p: mtimes[p])

    result = _find_latest_local_model()
    assert result == new_tar


def test_find_latest_local_model_dir_exists_but_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录存在但无 tar 文件 → 继续，最终返回 None(覆盖 66 的 falsey 分支)。"""

    monkeypatch.setattr(f"{MOD}.os.path.isdir", lambda p: True)
    monkeypatch.setattr(f"{MOD}.glob.glob", lambda pat: [])
    assert _find_latest_local_model() is None


# ---------------------------------------------------------------------------
# __init__ — 置信度阈值 ValueError 回退
# ---------------------------------------------------------------------------


def test_confidence_threshold_invalid_env_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RASA_CONFIDENCE_THRESHOLD 非数值时回退到默认 0.7(覆盖 107-108)。"""

    monkeypatch.setenv("RASA_CONFIDENCE_THRESHOLD", "not-a-number")
    svc = RasaNLUService(enabled=True)
    assert svc.confidence_threshold == 0.7


def test_confidence_threshold_valid_env_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合法数值时直接采用(基线对照,确保不是恒回退)。"""

    monkeypatch.setenv("RASA_CONFIDENCE_THRESHOLD", "0.42")
    svc = RasaNLUService(enabled=True)
    assert svc.confidence_threshold == 0.42


# ---------------------------------------------------------------------------
# load_model — disabled / server / embedded 各分支
# ---------------------------------------------------------------------------


def test_load_model_disabled() -> None:
    """disabled → 记录 _load_error='disabled' 并 False(覆盖 132-133)。"""

    svc = RasaNLUService(enabled=False)
    assert svc.load_model() is False
    assert svc._load_error == "disabled"


def test_load_model_server_mode() -> None:
    """server 模式 → 记录 target_url 并 True(覆盖 135-137)。"""

    svc = RasaNLUService(enabled=True, use_server=True, rasa_url="http://rasa.test:9999")
    assert svc.load_model() is True
    assert svc._last_status["mode"] == "server"
    assert svc._last_status["target_url"] == "http://rasa.test:9999"


def test_load_model_embedded_model_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """嵌入式且 model_path 探测不到 → model_not_found(覆盖 139-145)。"""

    svc = RasaNLUService(enabled=True, use_server=False)
    monkeypatch.setattr(f"{MOD}._find_latest_local_model", lambda: None)
    assert svc.load_model() is False
    assert svc._load_error is not None
    assert svc._load_error.startswith("model_not_found")
    # 也覆盖 _last_status['model_path'] 写入。
    assert svc._last_status["model_path"] is None


def test_load_model_embedded_import_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rasa.core.agent 导入失败 → rasa_import_failed(覆盖 147-151)。"""

    svc = RasaNLUService(enabled=True, use_server=False, model_path="/tmp/model.tar.gz")
    monkeypatch.setattr(f"{MOD}.os.path.exists", lambda p: True)

    real_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name == "rasa.core.agent" or name.startswith("rasa"):
            raise ImportError("no rasa installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert svc.load_model() is False
    assert svc._load_error is not None
    assert svc._load_error.startswith("rasa_import_failed")


def test_load_model_embedded_agent_load_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent.load 成功 → agent_loaded True 并返回 True(覆盖 153-156)。"""

    svc = RasaNLUService(enabled=True, use_server=False, model_path="/tmp/model.tar.gz")
    monkeypatch.setattr(f"{MOD}.os.path.exists", lambda p: True)

    fake_agent = MagicMock(name="loaded_agent")
    fake_agent_cls = MagicMock()
    fake_agent_cls.load.return_value = fake_agent
    fake_module = types.ModuleType("rasa.core.agent")
    fake_module.Agent = fake_agent_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rasa.core.agent", fake_module)

    assert svc.load_model() is True
    assert svc._agent is fake_agent
    assert svc._last_status["agent_loaded"] is True
    fake_agent_cls.load.assert_called_once_with("/tmp/model.tar.gz")


def test_load_model_embedded_agent_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent.load 抛 RECOVERABLE_ERRORS → agent_load_failed,_agent None(覆盖 157-160)。"""

    svc = RasaNLUService(enabled=True, use_server=False, model_path="/tmp/model.tar.gz")
    monkeypatch.setattr(f"{MOD}.os.path.exists", lambda p: True)

    fake_agent_cls = MagicMock()
    fake_agent_cls.load.side_effect = OSError("corrupt tarball")
    fake_module = types.ModuleType("rasa.core.agent")
    fake_module.Agent = fake_agent_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rasa.core.agent", fake_module)

    assert svc.load_model() is False
    assert svc._agent is None
    assert svc._load_error is not None
    assert svc._load_error.startswith("agent_load_failed")


# ---------------------------------------------------------------------------
# parse — 走 embedded 路径(180)
# ---------------------------------------------------------------------------


def test_parse_lazy_loads_then_calls_embedded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """嵌入式 _agent 为 None 时 parse 先 load_model 成功,再走 embedded(覆盖 177-180)。"""

    svc = RasaNLUService(enabled=True, use_server=False)

    def fake_load() -> bool:
        svc._agent = MagicMock(name="agent")
        return True

    monkeypatch.setattr(svc, "load_model", fake_load)
    embedded_result = {"intent": {"name": "greet", "confidence": 0.88}, "entities": []}
    monkeypatch.setattr(svc, "_parse_via_embedded", lambda t: embedded_result)

    out = svc.parse("你好")
    assert out is embedded_result


def test_parse_returns_empty_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """嵌入式 load 失败 → 返回 empty,带 _load_error 原因(覆盖 178-179)。"""

    svc = RasaNLUService(enabled=True, use_server=False)
    svc._load_error = "boom"
    monkeypatch.setattr(svc, "load_model", lambda: False)

    out = svc.parse("你好")
    assert out["intent"]["name"] is None
    assert out["message"] == "boom"


# ---------------------------------------------------------------------------
# _parse_via_server — requests 缺失 / 不可达 / 非200 / 坏 JSON
# ---------------------------------------------------------------------------


def test_parse_via_server_requests_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """import requests 失败 → requests_unavailable(覆盖 189-191)。"""

    svc = RasaNLUService(enabled=True, use_server=True)
    real_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name == "requests":
            raise ImportError("requests gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    out = svc.parse("hi")
    assert out["intent"]["name"] is None
    assert out["message"].startswith("requests_unavailable")


@patch("requests.post")
def test_parse_via_server_unreachable(mock_post: MagicMock) -> None:
    """requests.post 抛 ConnectionError → server_unreachable + 标记不可达(覆盖 199-201)。"""

    mock_post.side_effect = ConnectionError("connection refused")
    svc = RasaNLUService(enabled=True, use_server=True)
    out = svc.parse("hi")
    assert out["message"].startswith("server_unreachable")
    assert svc._last_status["server_reachable"] is False


@patch("requests.post")
def test_parse_via_server_non_200(mock_post: MagicMock) -> None:
    """HTTP 非 200 → server_status_<code>(覆盖 203-205)。"""

    resp = MagicMock()
    resp.status_code = 503
    mock_post.return_value = resp
    svc = RasaNLUService(enabled=True, use_server=True)
    out = svc.parse("hi")
    assert out["message"] == "server_status_503"
    assert svc._last_status["server_reachable"] is False


@patch("requests.post")
def test_parse_via_server_bad_json(mock_post: MagicMock) -> None:
    """200 但 json() 抛 ValueError → server_bad_json(覆盖 207-210)。"""

    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("not json")
    mock_post.return_value = resp
    svc = RasaNLUService(enabled=True, use_server=True)
    out = svc.parse("hi")
    assert out["message"].startswith("server_bad_json")
    assert svc._last_status["server_reachable"] is True


# ---------------------------------------------------------------------------
# _parse_via_embedded — 成功 / RuntimeError 兜底 / RECOVERABLE_ERRORS
# ---------------------------------------------------------------------------


def test_parse_via_embedded_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """asyncio.run 直接成功 → 返回 agent 结果(覆盖 213-216)。"""

    svc = RasaNLUService(enabled=True, use_server=False)
    svc._agent = MagicMock()
    expected = {"intent": {"name": "buy", "confidence": 0.9}, "entities": []}

    monkeypatch.setattr(f"{MOD}.asyncio.run", lambda coro: expected)
    out = svc._parse_via_embedded("买一个")
    assert out is expected


def test_parse_via_embedded_runtime_error_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """asyncio.run 抛 RuntimeError(已在 loop) → 新建 loop 兜底(覆盖 217-223)。"""

    svc = RasaNLUService(enabled=True, use_server=False)

    async def fake_parse_message(text: str) -> dict[str, Any]:
        return {"intent": {"name": "fallback", "confidence": 0.5}, "entities": [], "text": text}

    agent = MagicMock()
    agent.parse_message = fake_parse_message
    svc._agent = agent

    def boom(coro: Any) -> Any:
        # 关闭未消费的协程,避免 RuntimeWarning。
        coro.close()
        raise RuntimeError("asyncio.run cannot be called from a running loop")

    monkeypatch.setattr(f"{MOD}.asyncio.run", boom)

    closed: dict[str, bool] = {"closed": False}
    real_new_loop = asyncio.new_event_loop

    def tracking_new_loop():
        loop = real_new_loop()
        orig_close = loop.close

        def close_wrapper() -> None:
            closed["closed"] = True
            orig_close()

        loop.close = close_wrapper  # type: ignore[method-assign]
        return loop

    monkeypatch.setattr(f"{MOD}.asyncio.new_event_loop", tracking_new_loop)

    out = svc._parse_via_embedded("你好")
    assert out["intent"]["name"] == "fallback"
    assert closed["closed"] is True


def test_parse_via_embedded_recoverable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """asyncio.run 抛 RECOVERABLE_ERRORS(非 RuntimeError) → parse_failed(覆盖 224-225)。"""

    svc = RasaNLUService(enabled=True, use_server=False)
    svc._agent = MagicMock()

    def boom(coro: Any) -> Any:
        if hasattr(coro, "close"):
            coro.close()
        raise ValueError("bad model output")

    monkeypatch.setattr(f"{MOD}.asyncio.run", boom)
    out = svc._parse_via_embedded("你好")
    assert out["intent"]["name"] is None
    assert out["message"].startswith("parse_failed")
