"""无邮箱占位邮箱 SSOT 守卫。"""

from __future__ import annotations

from app.utils.no_email import (
    NO_EMAIL_DISPLAY,
    email_display,
    is_no_email_address,
    synth_no_email_address,
)


def test_synth_uses_auto_domain():
    assert synth_no_email_address("wuxinghua1") == "wuxinghua1@auto.xiu-ci.com"
    assert synth_no_email_address("  bob  ") == "bob@auto.xiu-ci.com"


def test_is_no_email_by_suffix():
    assert is_no_email_address("wuxinghua1@auto.xiu-ci.com") is True
    assert is_no_email_address("X@AUTO.XIU-CI.COM") is True  # 大小写不敏感
    assert is_no_email_address("real@gmail.com") is False
    assert is_no_email_address("") is False
    assert is_no_email_address(None) is False


def test_email_display_maps_placeholder_to_label():
    assert email_display("wuxinghua1@auto.xiu-ci.com") == NO_EMAIL_DISPLAY
    assert email_display("real@gmail.com") == "real@gmail.com"
    assert email_display("") == ""


def test_synth_roundtrips_to_no_email():
    addr = synth_no_email_address("acme")
    assert is_no_email_address(addr)
    assert email_display(addr) == NO_EMAIL_DISPLAY
