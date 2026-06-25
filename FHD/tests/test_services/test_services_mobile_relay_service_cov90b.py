"""真实行为测试（第二波）：mobile_relay_service 未覆盖分支/边界。

只针对 app/services/mobile_relay_service.py 中尚未覆盖的纯函数分支、
错误/边界路径（未找到/已撤销/已过期/空 token/不属于用户等），不重复
已有的成功路径 round-trip（见 tests/test_mobile_relay_service.py）。

外部依赖仅 get_db（SQLite，临时文件，离线确定性），全部 monkeypatch。
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def relay_mod(monkeypatch, tmp_path):
    """加载模块并把 get_db 指向临时 SQLite，返回 (module, service)。"""
    from app.services import mobile_relay_service as relay

    engine = create_engine(f"sqlite:///{tmp_path / 'relay_cov90b.db'}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_db():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(relay, "get_db", test_db)
    service = relay.MobileRelayService()
    return relay, service, test_db


# --------------------------------------------------------------------------
# 纯辅助函数分支（行 33-34, 43, 46-47, 66, 68）
# --------------------------------------------------------------------------


def test_epoch_from_iso_invalid_falls_back_to_now(relay_mod, monkeypatch):
    relay, _service, _ = relay_mod
    monkeypatch.setattr(relay.time, "time", lambda: 1234567890.9)
    # 非法 ISO 字符串触发 ValueError -> 走 except 分支返回 int(time.time())
    assert relay._epoch_from_iso("not-a-date") == 1234567890


def test_epoch_from_iso_none_raises_attribute_error(relay_mod):
    relay, _service, _ = relay_mod
    # 实际行为：None 在 value.replace(...) 处先抛 AttributeError，
    # 而 except 只捕获 (TypeError, ValueError) -> 不会兜底，直接抛出。
    # （类型注解声明 value: str，None 属边界外输入；见 suspected_bugs。）
    with pytest.raises(AttributeError):
        relay._epoch_from_iso(None)


def test_epoch_from_iso_valid_z_suffix(relay_mod):
    relay, _service, _ = relay_mod
    # 成功路径：带 Z 的 ISO 被规范化解析
    got = relay._epoch_from_iso("1970-01-01T00:00:00Z")
    assert got == 0


def test_json_loads_empty_returns_empty_dict(relay_mod):
    relay, _service, _ = relay_mod
    # 行 43：falsy 直接返回 {}
    assert relay._json_loads("") == {}
    assert relay._json_loads(None) == {}
    assert relay._json_loads(0) == {}


def test_json_loads_invalid_json_returns_empty_dict(relay_mod):
    relay, _service, _ = relay_mod
    # 行 46-47：JSONDecodeError -> {}
    assert relay._json_loads("{not json") == {}


def test_json_loads_non_dict_json_returns_empty_dict(relay_mod):
    relay, _service, _ = relay_mod
    # 合法 JSON 但非 dict（list）-> {}
    assert relay._json_loads("[1, 2, 3]") == {}


def test_json_loads_valid_dict(relay_mod):
    relay, _service, _ = relay_mod
    assert relay._json_loads('{"a": 1}') == {"a": 1}


def test_public_base_url_empty_uses_default(relay_mod):
    relay, _service, _ = relay_mod
    # 行 66：空 -> 默认域名，且尾部补 /
    assert relay._public_base_url("") == "https://xiu-ci.com/fhd-api/"
    assert relay._public_base_url("   ") == "https://xiu-ci.com/fhd-api/"


def test_public_base_url_adds_https_scheme(relay_mod):
    relay, _service, _ = relay_mod
    # 行 68：无 scheme -> 补 https://
    assert relay._public_base_url("relay.example.test/api") == "https://relay.example.test/api/"


def test_public_base_url_keeps_existing_scheme_and_strips_trailing_slash(relay_mod):
    relay, _service, _ = relay_mod
    assert relay._public_base_url("http://x.test/api///") == "http://x.test/api/"


# --------------------------------------------------------------------------
# confirm_mobile 错误分支（行 216, 219, 221）
# --------------------------------------------------------------------------


def test_confirm_mobile_row_not_found_returns_none(relay_mod):
    relay, service, _ = relay_mod
    # 行 216：relay_id/code 不存在 -> None
    assert (
        service.confirm_mobile(user_id=1, username="u", relay_id="missing", code="000000") is None
    )


def test_confirm_mobile_revoked_returns_none(relay_mod):
    relay, service, test_db = relay_mod
    reg = service.register_desktop(label="L", device_id="d1")
    # 直接把该桌面置为 revoked
    with test_db() as db:
        db.execute(
            text("UPDATE mobile_relay_desktops SET status='revoked' WHERE relay_id=:r"),
            {"r": reg["relay_id"]},
        )
    # 行 218-219：status == revoked -> None
    assert (
        service.confirm_mobile(
            user_id=2,
            username="u",
            relay_id=reg["relay_id"],
            code=reg["pairing_code"],
        )
        is None
    )


def test_confirm_mobile_pending_expired_returns_none(relay_mod):
    relay, service, test_db = relay_mod
    reg = service.register_desktop(label="L", device_id="d2")
    # 把 expires_at 设为过去，status 仍 pending
    with test_db() as db:
        db.execute(
            text(
                "UPDATE mobile_relay_desktops "
                "SET expires_at='2000-01-01T00:00:00+00:00' WHERE relay_id=:r"
            ),
            {"r": reg["relay_id"]},
        )
    # 行 220-221：pending 且 expires_at < now -> None
    assert (
        service.confirm_mobile(
            user_id=3,
            username="u",
            relay_id=reg["relay_id"],
            code=reg["pairing_code"],
        )
        is None
    )


# --------------------------------------------------------------------------
# confirm_mobile_by_code（行 257-263, 279-287, 305, 313）
# --------------------------------------------------------------------------


def test_confirm_mobile_by_code_empty_code_returns_none(relay_mod):
    relay, service, _ = relay_mod
    # 行 257-259：空 code -> None（不查库）
    assert service.confirm_mobile_by_code(user_id=1, username="u", code="   ") is None


def test_confirm_mobile_by_code_not_found_returns_none(relay_mod):
    relay, service, _ = relay_mod
    # 行 279-280：找不到行 -> None
    assert service.confirm_mobile_by_code(user_id=1, username="u", code="123456") is None


def test_confirm_mobile_by_code_pending_expired_returns_none(relay_mod):
    relay, service, test_db = relay_mod
    reg = service.register_desktop(label="L", device_id="d3")
    with test_db() as db:
        db.execute(
            text(
                "UPDATE mobile_relay_desktops "
                "SET expires_at='2000-01-01T00:00:00+00:00' WHERE relay_id=:r"
            ),
            {"r": reg["relay_id"]},
        )
    # 行 282-283：pending 且过期 -> None
    assert service.confirm_mobile_by_code(user_id=4, username="u", code=reg["pairing_code"]) is None


def test_confirm_mobile_by_code_success_pairs(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(label="L", device_id="d4")
    # 行 284-313：成功路径 -> 配对并返回 public_desktop
    paired = service.confirm_mobile_by_code(
        user_id=99, username="  alice  ", code=reg["pairing_code"]
    )
    assert paired is not None
    assert paired["status"] == "paired"
    assert paired["relay_id"] == reg["relay_id"]
    # username 被 strip 后写入；通过 list_desktops 复核 mobile_user_id 命中
    desktops = service.list_desktops(user_id=99)
    assert len(desktops) == 1
    assert desktops[0]["relay_id"] == reg["relay_id"]


# --------------------------------------------------------------------------
# list_desktops（行 315-318, 332）
# --------------------------------------------------------------------------


def test_list_desktops_empty_when_no_pairing(relay_mod):
    relay, service, _ = relay_mod
    # 行 316-332：无配对桌面 -> 空列表
    assert service.list_desktops(user_id=12345) == []


# --------------------------------------------------------------------------
# create_task 守卫（行 342-343）
# --------------------------------------------------------------------------


def test_create_task_unpaired_desktop_returns_none(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(label="L", device_id="d5")
    # 桌面尚未配对到该用户 -> _desktop_belongs_to_user False -> 行 343 None
    assert (
        service.create_task(
            user_id=7,
            relay_id=reg["relay_id"],
            kind="codex.invoke",
            payload={"x": 1},
        )
        is None
    )


def test_create_task_kind_defaults_when_blank(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(label="L", device_id="d5b")
    service.confirm_mobile(
        user_id=8,
        username="u",
        relay_id=reg["relay_id"],
        code=reg["pairing_code"],
    )
    # 空白 kind -> 默认 codex.invoke（行 346 分支）
    created = service.create_task(user_id=8, relay_id=reg["relay_id"], kind="   ", payload=None)
    assert created is not None
    assert created["kind"] == "codex.invoke"
    assert created["status"] == "queued"
    assert created["payload"] == {}


# --------------------------------------------------------------------------
# poll_desktop / complete_desktop_task token 守卫（行 406, 464, 474）
# --------------------------------------------------------------------------


def test_poll_desktop_bad_token_returns_none(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(label="L", device_id="d6")
    # 行 404-406：token 不匹配 -> _desktop_for_token None -> None
    assert service.poll_desktop(relay_id=reg["relay_id"], desktop_token="wrong-token") is None


def test_complete_desktop_task_bad_token_returns_none(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(label="L", device_id="d7")
    # 行 472-474：token 不匹配 -> None
    assert (
        service.complete_desktop_task(
            relay_id=reg["relay_id"],
            desktop_token="wrong-token",
            task_id="any",
            status="completed",
            result={"ok": True},
        )
        is None
    )


def test_complete_desktop_task_done_alias_maps_to_completed(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(
        label="L", device_id="d8", capabilities={"host": "10.0.0.2", "port": 9000}
    )
    service.confirm_mobile(
        user_id=11,
        username="u",
        relay_id=reg["relay_id"],
        code=reg["pairing_code"],
    )
    created = service.create_task(
        user_id=11, relay_id=reg["relay_id"], kind="codex.invoke", payload={"m": "go"}
    )
    service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    # 行 463-464："done" -> 归一为 "completed"
    done = service.complete_desktop_task(
        relay_id=reg["relay_id"],
        desktop_token=reg["desktop_token"],
        task_id=created["task_id"],
        status="done",
        result={"ok": True},
    )
    assert done is not None
    assert done["status"] == "completed"


def test_complete_desktop_task_unknown_status_defaults_to_completed(relay_mod):
    relay, service, _ = relay_mod
    reg = service.register_desktop(label="L", device_id="d8b")
    service.confirm_mobile(
        user_id=12,
        username="u",
        relay_id=reg["relay_id"],
        code=reg["pairing_code"],
    )
    created = service.create_task(
        user_id=12, relay_id=reg["relay_id"], kind="codex.invoke", payload={}
    )
    service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    # 未知状态（不在白名单）-> 兜底 completed
    done = service.complete_desktop_task(
        relay_id=reg["relay_id"],
        desktop_token=reg["desktop_token"],
        task_id=created["task_id"],
        status="weird-status",
        result={},
    )
    assert done is not None
    assert done["status"] == "completed"


# --------------------------------------------------------------------------
# _desktop_for_token 空 token 守卫（行 540-541）
# --------------------------------------------------------------------------


def test_desktop_for_token_empty_token_returns_none(relay_mod):
    relay, service, test_db = relay_mod
    reg = service.register_desktop(label="L", device_id="d9")
    with test_db() as db:
        # 行 540-541：空 token 直接返回 None（不查库）
        assert service._desktop_for_token(db, relay_id=reg["relay_id"], desktop_token="  ") is None


# --------------------------------------------------------------------------
# _fresh_pairing_code 100 次碰撞后兜底（行 507-518）
# --------------------------------------------------------------------------


def test_fresh_pairing_code_fallback_after_100_collisions(relay_mod, monkeypatch):
    relay, service, _ = relay_mod
    # 让 randbelow 恒定 -> 注册一个占用该 code 的桌面，使后续循环 100 次全碰撞，
    # 触发行 518 的兜底 return。
    monkeypatch.setattr(relay.secrets, "randbelow", lambda n: 0)
    first = service.register_desktop(label="L", device_id="dA")
    assert first["pairing_code"] == "100000"
    # 第二次注册：循环里 100 次全部命中 existing -> 兜底返回同一 code（行 518）
    second_code = service._fresh_pairing_code()
    assert second_code == "100000"
