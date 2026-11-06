"""桌面父进程看门狗：Electron 消失后后端必须退出，避免占住 17500。"""

from __future__ import annotations

import asyncio

import pytest

import importlib

life = importlib.import_module("app.fastapi_app.lifespan")


def test_watchdog_stays_off_without_parent_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_PARENT_PID", raising=False)
    assert life._start_parent_watchdog() is None


def test_watchdog_exits_after_parent_disappears(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = {"n": 0}
    checks = {"n": 0}
    exits: list[int] = []

    async def fast_sleep(_seconds: float) -> None:
        sleeps["n"] += 1

    def alive(_pid: int) -> bool:
        checks["n"] += 1
        return checks["n"] < 2

    def _exit(code: int) -> None:
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(life.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(life, "_pid_is_alive", alive)
    monkeypatch.setattr(life.os, "_exit", _exit)

    with pytest.raises(SystemExit):
        asyncio.run(life._watch_parent_process(4242))

    assert sleeps["n"] == 2
    assert exits == [0]
