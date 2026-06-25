"""device_identity 不变量（Wall 2 / docs §十）：

设备标识是身份非标签 —— 跨重启 / 换端口 / 更新不变、可显式覆盖、永不返回空。
"""

from __future__ import annotations

import app.utils.device_identity as di


def _reset_cache() -> None:
    di._cached = None


def test_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DEVICE_ID", "fixed-override-123")
    _reset_cache()
    assert di.get_stable_device_id() == "fixed-override-123"


def test_persisted_and_stable_across_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_DEVICE_ID", raising=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    _reset_cache()

    first = di.get_stable_device_id()
    assert first and len(first) >= 16
    assert (tmp_path / "device_id").is_file()

    # 模拟进程重启：清进程缓存，应从落盘文件读回同一值
    _reset_cache()
    assert di.get_stable_device_id() == first


def test_never_empty_even_if_unwritable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_DEVICE_ID", raising=False)
    # data dir 解析成一个“文件” → 其下 device_id 既读不到也写不进
    afile = tmp_path / "not_a_dir"
    afile.write_text("x", encoding="utf-8")
    monkeypatch.setattr(di, "get_app_data_dir", lambda: str(afile))
    _reset_cache()
    assert di.get_stable_device_id()  # 落盘失败也返回非空进程内值
