"""_force_stdio_utf8：Windows 打包后端 stdio 编码兜底（W4 乱码修复）。

win32 字节取证：后端 stderr 以 GBK(cp936) 写出 WinError 消息，Electron 按
UTF-8 解码产生 U+FFFD。修复在 main() 入口显式 reconfigure stdio 为 UTF-8。
"""

from __future__ import annotations

from XCAGI import run_fastapi


class _FakeStream:
    def __init__(self, name: str, calls: list[tuple[str, str]]):
        self.name = name
        self._calls = calls

    def reconfigure(self, encoding: str = "") -> None:
        self._calls.append((self.name, encoding))


def test_force_stdio_utf8_reconfigures_on_windows(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(run_fastapi.sys, "platform", "win32")
    monkeypatch.setattr(run_fastapi.sys, "stdout", _FakeStream("stdout", calls))
    monkeypatch.setattr(run_fastapi.sys, "stderr", _FakeStream("stderr", calls))

    run_fastapi._force_stdio_utf8()

    assert calls == [("stdout", "utf-8"), ("stderr", "utf-8")]


def test_force_stdio_utf8_noop_on_non_windows(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(run_fastapi.sys, "platform", "darwin")
    monkeypatch.setattr(run_fastapi.sys, "stdout", _FakeStream("stdout", calls))
    monkeypatch.setattr(run_fastapi.sys, "stderr", _FakeStream("stderr", calls))

    run_fastapi._force_stdio_utf8()

    assert calls == []


def test_force_stdio_utf8_survives_streams_without_reconfigure(monkeypatch):
    class Plain:
        pass

    monkeypatch.setattr(run_fastapi.sys, "platform", "win32")
    monkeypatch.setattr(run_fastapi.sys, "stdout", Plain())
    monkeypatch.setattr(run_fastapi.sys, "stderr", None)

    run_fastapi._force_stdio_utf8()
