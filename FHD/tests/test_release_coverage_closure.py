"""Release-gate coverage for CLI streaming and mobile relay boundaries."""

from __future__ import annotations

import io
import json
import sys
import types
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    SuperEmployeeService,
)
from app.infrastructure.skills.label_template_generator.barcode_generator import (
    BarcodeGenerator,
    generate_barcode,
    save_barcode,
)
from app.mod_sdk import erp_domain_dispatch as erp_dispatch
from app.services import mobile_relay_service as relay
from app.services.mobile_relay_desktop_client import _extract_tool_calls
from app.services.tools_execution import registry as tool_registry
from app.utils import secure_filename as secure_filename_module
from app.utils.listen_port import resolve_listen_port
from app.utils.safe_download_path import UnsafeDownloadPathError, resolve_under_allowed_dirs


class _AsyncStream:
    def __init__(self, lines=(), *, read_data=b"", read_error: BaseException | None = None):
        self._lines = list(lines)
        self._read_data = read_data
        self._read_error = read_error

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        value = self._lines.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def read(self) -> bytes:
        if self._read_error is not None:
            raise self._read_error
        return self._read_data


class _AsyncProcess:
    def __init__(self, *, stdout=None, stderr=None, returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.killed = False
        self.waited = False

    async def wait(self) -> int:
        self.waited = True
        return self.returncode

    def kill(self) -> None:
        self.killed = True


async def _collect_cli_events(service, process, tmp_path):
    with patch(
        "app.application.super_employee_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        return [
            event
            async for event in service._run_cli_streaming("/fake/cli", "prompt", str(tmp_path))
        ]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("not-json", ""),
        ("[]", ""),
        ('{"type":"assistant","message":null}', ""),
        (
            '{"type":"assistant","message":{"content":[null,{"type":"tool"},'
            '{"type":"text","text":""},{"type":"text","text":"甲"}]}}',
            "甲",
        ),
        ('{"type":"result","result":null}', ""),
        ('{"type":"result","result":"  "}', ""),
        ('{"type":"result","result":"乙"}', "乙"),
        ('{"type":"content_block_delta","delta":null}', ""),
        ('{"type":"content_block_delta","delta":{"text":"丙"}}', "丙"),
        ('{"type":"message_delta","text":"丁"}', "丁"),
        ('{"type":"unknown"}', ""),
    ],
)
def test_parse_stream_json_line_boundaries(tmp_path, line, expected) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    assert service._parse_stream_json_line(line) == expected


@pytest.mark.asyncio
async def test_stream_json_cli_emits_tokens_and_final_text(tmp_path) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    process = _AsyncProcess(
        stdout=_AsyncStream(
            [
                b"\n",
                b"plain log\n",
                b'{"type":"assistant","message":{"content":[{"type":"text","text":"hello "}]}}\n',
                b'{"type":"result","result":"world"}\n',
                b"",
            ]
        ),
        stderr=_AsyncStream(read_data=b"unused"),
    )

    events = await _collect_cli_events(service, process, tmp_path)

    assert events == [
        {"type": "token", "text": "hello "},
        {"type": "token", "text": "world"},
        {"type": "done", "text": "hello world"},
    ]
    assert process.waited is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("returncode", "stderr", "expected_type"),
    [
        (0, _AsyncStream(), "done"),
        (7, None, "error"),
        (8, _AsyncStream(read_data=b"private failure"), "error"),
        (9, _AsyncStream(read_error=TimeoutError()), "error"),
    ],
)
async def test_stream_json_cli_empty_and_error_results(
    tmp_path, returncode, stderr, expected_type
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    process = _AsyncProcess(stdout=_AsyncStream(), stderr=stderr, returncode=returncode)

    events = await _collect_cli_events(service, process, tmp_path)

    assert events[-1]["type"] == expected_type
    assert "private failure" not in str(events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("idle_timeout", "hard_cap", "message_fragment"),
    [(0.000000001, 0, "静默"), (0, 0.000000001, "运行超过")],
)
async def test_stream_json_cli_kills_timed_out_process(
    tmp_path, idle_timeout, hard_cap, message_fragment
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    process = _AsyncProcess(stdout=_AsyncStream([TimeoutError()]), stderr=_AsyncStream())

    with (
        patch.object(service, "_cli_idle_timeout_seconds", return_value=idle_timeout),
        patch.object(service, "_cli_hard_cap_seconds", return_value=hard_cap),
    ):
        events = await _collect_cli_events(service, process, tmp_path)

    assert process.killed is True
    assert events[-1]["type"] == "error"
    assert message_fragment in events[-1]["message"]


@pytest.mark.asyncio
async def test_stream_json_cli_continues_after_non_terminal_read_timeout(tmp_path) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    process = _AsyncProcess(
        stdout=_AsyncStream([TimeoutError(), b""]),
        stderr=_AsyncStream(),
    )

    with (
        patch.object(service, "_cli_idle_timeout_seconds", return_value=0),
        patch.object(service, "_cli_hard_cap_seconds", return_value=0),
    ):
        events = await _collect_cli_events(service, process, tmp_path)

    assert events == [{"type": "done", "text": ""}]
    assert process.killed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "returncode", "expected_type", "expected_text"),
    [
        ("完成", 0, "done", "完成"),
        ("", 0, "done", ""),
        ("", 4, "error", None),
    ],
)
async def test_output_file_cli_result_paths(
    tmp_path, body, returncode, expected_type, expected_text
) -> None:
    def command_builder(cli_path, prompt, output_path, cwd):
        if body:
            output_path.write_text(f" {body} \n", encoding="utf-8")
        return [cli_path, prompt, cwd]

    profile = replace(CODEX_PROFILE, cli_command_builder=command_builder)
    service = SuperEmployeeService(profile, storage_root=tmp_path)
    process = _AsyncProcess(
        stdout=_AsyncStream([b"diagnostic only\n", b""]),
        stderr=_AsyncStream(read_data=b"secret diagnostics"),
        returncode=returncode,
    )

    events = await _collect_cli_events(service, process, tmp_path)

    assert events[-1]["type"] == expected_type
    if expected_text is not None:
        assert events[-1]["text"] == expected_text
    assert "secret diagnostics" not in str(events)


@pytest.mark.asyncio
async def test_cli_with_missing_stdout_finishes_cleanly(tmp_path) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    process = _AsyncProcess(stdout=None, stderr=None)
    assert await _collect_cli_events(service, process, tmp_path) == [{"type": "done", "text": ""}]


@pytest.mark.parametrize(
    ("assistant", "expected_actions"),
    [({}, []), ({"content": "普通回复"}, []), ({"body": "闭环结果"}, ["cli_run"])],
)
def test_extract_tool_calls_empty_and_minimal_paths(assistant, expected_actions) -> None:
    calls = _extract_tool_calls(assistant, "Codex")
    assert [item["action"] for item in calls] == expected_actions


@pytest.mark.parametrize(
    ("verification", "push", "verify_success", "push_success"),
    [
        ("通过（42 tests）", "成功 origin/feature", True, True),
        ("未通过(failed: 1)", "权限不足", False, False),
        ("通过（ok）", "已推送 feature", True, True),
    ],
)
def test_extract_tool_calls_full_release_timeline(
    verification, push, verify_success, push_success
) -> None:
    assistant = {"body": f"闭环结果\n分支：feature/release\n验证：{verification}\n推送：{push}\n"}
    calls = _extract_tool_calls(assistant, "Claude")

    assert [item["action"] for item in calls] == [
        "cli_run",
        "create_branch",
        "verify",
        "push",
    ]
    assert calls[2]["success"] is verify_success
    assert calls[3]["success"] is push_success
    assert calls[0]["label"] == "Claude CLI 执行"


def _install_fake_barcode_modules(monkeypatch, *, fail=False) -> None:
    barcode_module = types.ModuleType("barcode")
    writer_module = types.ModuleType("barcode.writer")

    class FakeWriter:
        pass

    class FakeBarcode:
        def __init__(self, data, *, writer):
            self.data = data
            self.writer = writer

        def write(self, buffer, *, options):
            Image.new("RGB", (8, 4), f"#{options['background']}").save(buffer, format="PNG")

    def get_barcode(_barcode_type):
        if fail:
            raise ValueError("unsupported data")
        return FakeBarcode

    barcode_module.get_barcode = get_barcode
    writer_module.ImageWriter = FakeWriter
    monkeypatch.setitem(sys.modules, "barcode", barcode_module)
    monkeypatch.setitem(sys.modules, "barcode.writer", writer_module)


@pytest.mark.parametrize(
    ("data", "barcode_type", "expected"),
    [
        ("", "code128", ""),
        (" a B-12 ", "code128", "aB12"),
        ("a1 b2", "itf", "12"),
        ("123", "ean13", "123000000000"),
        ("12345678901234", "ean13", "1234567890123"),
        ("123", "ean8", "1230000"),
        ("123456789", "ean8", "12345678"),
        ("123", "upca", "12300000000"),
        ("1234567890123", "upca", "123456789012"),
    ],
)
def test_barcode_data_normalization(data, barcode_type, expected) -> None:
    generator = BarcodeGenerator(barcode_type)
    assert generator._clean_barcode_data(data, barcode_type) == expected


def test_barcode_generation_fallback_and_save_paths(monkeypatch, tmp_path) -> None:
    _install_fake_barcode_modules(monkeypatch)
    generator = BarcodeGenerator("unknown")
    image = generator.generate(
        "ABC 123",
        {"width": 1, "height": 12, "show_text": False, "foreground": "111111"},
    )
    assert image is not None and image.size == (8, 4)
    assert generator.generate("") is None

    _install_fake_barcode_modules(monkeypatch, fail=True)
    fallback = generator.generate("fallback", {"height": 20, "show_text": True})
    assert fallback is not None and fallback.size == (400, 40)

    monkeypatch.setitem(sys.modules, "barcode", None)
    monkeypatch.setitem(sys.modules, "barcode.writer", None)
    assert generate_barcode("fallback", options={"show_text": False}).size == (400, 70)

    output = tmp_path / "barcode.png"
    monkeypatch.setattr(generator, "generate", lambda *_args, **_kwargs: fallback)
    assert generator.save(str(output), "value") is True
    assert output.exists()
    monkeypatch.setattr(generator, "generate", lambda *_args, **_kwargs: None)
    assert generator.save(str(output), "value") is False

    bad_image = MagicMock()
    bad_image.save.side_effect = OSError("disk full")
    monkeypatch.setattr(generator, "generate", lambda *_args, **_kwargs: bad_image)
    assert generator.save(str(output), "value") is False

    monkeypatch.setattr(BarcodeGenerator, "save", lambda *_args, **_kwargs: True)
    assert save_barcode(str(output), "value", "code39") is True
    assert "ean13" in BarcodeGenerator.get_supported_types()
    assert "国际商品" in BarcodeGenerator.get_type_description("EAN13")
    assert "未知类型" in BarcodeGenerator.get_type_description("custom")


@pytest.mark.parametrize(
    ("action", "params", "expected"),
    [
        ("", None, "view"),
        ("查询", None, "query"),
        ("SEARCH", None, "query"),
        ("update", None, "update"),
        ("outer", {"action": "新增"}, "create"),
        ("outer", {"action": "READ"}, "read"),
        ("outer", {"action": "unsupported"}, "outer"),
        ("outer", {}, "outer"),
    ],
)
def test_tool_action_normalization(action, params, expected) -> None:
    assert tool_registry._normalize_action(action, params) == expected


@pytest.mark.parametrize(
    ("tool", "action", "params", "expected_ok"),
    [
        ("unknown", "view", None, True),
        ("products", "create", {}, False),
        ("products", "create", {"name_or_model": " ", "unit_name": "件"}, False),
        ("products", "create", {"name_or_model": "A", "unit_name": None}, False),
        ("products", "batch_delete", {"ids": []}, False),
        ("products", "batch_delete", {"ids": [1]}, True),
        ("products", "create", {"name_or_model": "A", "unit_name": "件"}, True),
    ],
)
def test_required_tool_parameter_validation(tool, action, params, expected_ok) -> None:
    ok, message = tool_registry._validate_required_params(tool, action, params)
    assert ok is expected_ok
    assert bool(message) is (not expected_ok)


def test_workflow_registry_delegates_to_ssot(monkeypatch) -> None:
    expected = {"products": {"actions": ["view"]}}
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.get_workflow_tools_from_registry",
        lambda: expected,
    )
    assert tool_registry.get_workflow_tool_registry() is expected


def test_download_path_stays_inside_allowed_roots(tmp_path) -> None:
    first = tmp_path / "downloads"
    second = tmp_path / "exports"
    first.mkdir()
    second.mkdir()

    assert resolve_under_allowed_dirs("report.pdf", [first, second]) == first / "report.pdf"
    assert (
        resolve_under_allowed_dirs(str(second / "data.csv"), [first, second]) == second / "data.csv"
    )
    with pytest.raises(UnsafeDownloadPathError, match="no allowed roots"):
        resolve_under_allowed_dirs("report.pdf", [])
    with pytest.raises(UnsafeDownloadPathError, match="empty path"):
        resolve_under_allowed_dirs(" ", [first])
    with pytest.raises(UnsafeDownloadPathError, match="not under allowed dirs"):
        resolve_under_allowed_dirs("../secret.txt", [first])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("My cool movie.mov", "My_cool_movie.mov"),
        ("../../../etc/passwd", "etc_passwd"),
        ("i contain cool ümläuts.txt", "i_contain_cool_umlauts.txt"),
        (123, "123"),
    ],
)
def test_secure_filename_normalizes_untrusted_names(value, expected) -> None:
    assert secure_filename_module.secure_filename(value) == expected


def test_secure_filename_handles_windows_devices_and_alt_separator(monkeypatch) -> None:
    monkeypatch.setattr(secure_filename_module.os, "name", "nt")
    monkeypatch.setattr(secure_filename_module.os.path, "altsep", "/")
    assert secure_filename_module.secure_filename("folder/CON.txt") == "folder_CON.txt"
    assert secure_filename_module.secure_filename("AUX") == "_AUX"


def test_listen_port_precedence_and_validation(monkeypatch) -> None:
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        monkeypatch.delenv(key, raising=False)
    assert resolve_listen_port(5011) == 5011
    monkeypatch.setenv("FASTAPI_PORT", "invalid")
    monkeypatch.setenv("XCAGI_API_PORT", "70000")
    monkeypatch.setenv("PORT", "17500")
    assert resolve_listen_port() == 17500
    monkeypatch.setenv("FASTAPI_PORT", " 5011 ")
    assert resolve_listen_port() == 5011


def test_erp_handler_enablement_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_dispatch, "_truthy_env", lambda name: name == "XCAGI_DISABLE_ERP_DOMAIN_HANDLERS"
    )
    assert erp_dispatch.is_erp_domain_handlers_enabled() is False

    monkeypatch.setattr(
        erp_dispatch, "_truthy_env", lambda name: name == "XCAGI_ERP_DOMAIN_HANDLERS"
    )
    assert erp_dispatch.is_erp_domain_handlers_enabled() is True

    monkeypatch.setattr(erp_dispatch, "_truthy_env", lambda _name: False)
    monkeypatch.setattr(erp_dispatch, "is_erp_domain_via_mod_enabled", lambda: False)
    assert erp_dispatch.is_erp_domain_handlers_enabled() is False
    monkeypatch.setattr(erp_dispatch, "is_erp_domain_via_mod_enabled", lambda: True)
    monkeypatch.setattr(erp_dispatch, "_mod_domain_handler_domains", lambda: [])
    assert erp_dispatch.is_erp_domain_handlers_enabled() is False
    monkeypatch.setattr(erp_dispatch, "_mod_domain_handler_domains", lambda: ["products"])
    assert erp_dispatch.is_erp_domain_handlers_enabled() is True


def test_erp_manifest_domain_discovery(monkeypatch, tmp_path) -> None:
    from app.mod_sdk import erp_domain_compat

    monkeypatch.setattr(erp_domain_compat, "_resolve_mod_dir", lambda: None)
    assert erp_dispatch._mod_domain_handler_domains() == []

    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(erp_domain_compat, "_resolve_mod_dir", lambda: tmp_path)
    manifest.write_text(
        json.dumps({"config": {"mod_domain_handlers": [" products ", "", 3]}}),
        encoding="utf-8",
    )
    assert erp_dispatch._mod_domain_handler_domains() == ["products", "3"]
    manifest.write_text(json.dumps({"config": {"erp_domain_handlers": "bad"}}), encoding="utf-8")
    assert erp_dispatch._mod_domain_handler_domains() == []
    manifest.write_text("not-json", encoding="utf-8")
    assert erp_dispatch._mod_domain_handler_domains() == []


def test_erp_mod_path_resolution(monkeypatch, tmp_path) -> None:
    from app.infrastructure.mods import mod_manager
    from app.mod_sdk import erp_domain_compat

    manager = MagicMock()
    manager.get_mod.return_value = SimpleNamespace(mod_path=tmp_path)
    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: manager)
    assert erp_dispatch._resolve_mod_path()[1] == str(tmp_path)

    manager.get_mod.side_effect = OSError("manager offline")
    monkeypatch.setattr(erp_domain_compat, "_resolve_mod_dir", lambda: tmp_path)
    assert erp_dispatch._resolve_mod_path()[1] == str(tmp_path)
    monkeypatch.setattr(erp_domain_compat, "_resolve_mod_dir", lambda: None)
    assert erp_dispatch._resolve_mod_path() == (None, None)


def test_erp_handler_dispatch_boundaries(monkeypatch) -> None:
    monkeypatch.setattr(erp_dispatch, "is_erp_domain_handlers_enabled", lambda: False)
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "view") is None

    monkeypatch.setattr(erp_dispatch, "is_erp_domain_handlers_enabled", lambda: True)
    assert erp_dispatch.try_invoke_erp_domain_handler("", "view") is None
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "") is None

    monkeypatch.setattr(erp_dispatch, "_mod_domain_handler_domains", lambda: ["customers"])
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "view") is None

    monkeypatch.setattr(erp_dispatch, "_mod_domain_handler_domains", lambda: [])
    monkeypatch.setattr(erp_dispatch, "_resolve_mod_path", lambda: (None, None))
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "view") is None

    monkeypatch.setattr(erp_dispatch, "_resolve_mod_path", lambda: ("mod", "/mod"))
    monkeypatch.setattr(erp_dispatch, "_load_domain_handlers_module", lambda *_args: object())
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "view") is None

    module = SimpleNamespace(run_domain_handler=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(erp_dispatch, "_load_domain_handlers_module", lambda *_args: module)
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "view") is None

    module.run_domain_handler = lambda domain, action, **kwargs: {"domain": domain, **kwargs}
    assert erp_dispatch.try_invoke_erp_domain_handler("products", "view", page=2) == {
        "domain": "products",
        "page": 2,
    }
    assert erp_dispatch.invoke_erp_domain_handler("products", "view") == {"domain": "products"}

    module.run_domain_handler = MagicMock(side_effect=ValueError("bad mod"))
    failed = erp_dispatch.try_invoke_erp_domain_handler("products", "view")
    assert failed["error"] == "erp_domain_handler_failed"

    monkeypatch.setattr(
        erp_dispatch, "try_invoke_erp_domain_handler", lambda *_args, **_kwargs: None
    )
    with pytest.raises(RuntimeError, match="products.view"):
        erp_dispatch.invoke_erp_domain_handler("products", "view")


def test_erp_handler_summary_paths(monkeypatch) -> None:
    monkeypatch.setattr(erp_dispatch, "_mod_domain_handler_domains", lambda: ["products"])
    monkeypatch.setattr(erp_dispatch, "_resolve_mod_path", lambda: (None, None))
    monkeypatch.setattr(erp_dispatch, "is_erp_domain_handlers_enabled", lambda: False)
    assert erp_dispatch.list_erp_domain_handlers_summary()["action_count"] == 0

    module = SimpleNamespace(list_registered_actions=lambda: ["products.view"])
    monkeypatch.setattr(erp_dispatch, "_resolve_mod_path", lambda: ("mod", "/mod"))
    monkeypatch.setattr(erp_dispatch, "_load_domain_handlers_module", lambda *_args: module)
    summary = erp_dispatch.list_erp_domain_handlers_summary()
    assert summary["actions"] == ["products.view"]

    module.list_registered_actions = MagicMock(side_effect=OSError("broken"))
    assert erp_dispatch.list_erp_domain_handlers_summary()["actions"] == []


def _db_with_first(row, *, additional_results=()):
    db = MagicMock()
    selection = MagicMock()
    selection.mappings.return_value.first.return_value = row
    db.execute.side_effect = [selection, *additional_results]
    return db


def _install_db(monkeypatch, service, db) -> None:
    @contextmanager
    def fake_db():
        yield db

    monkeypatch.setattr(relay, "get_db", fake_db)
    monkeypatch.setattr(service, "ensure_tables", lambda _db: None)
    monkeypatch.setattr(relay, "_utc_now", lambda: "2026-01-01T00:00:00+00:00")


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"relay_id": "r", "status": "revoked"},
        {"relay_id": "r", "status": "pending", "expires_at": "2025-01-01"},
    ],
)
def test_confirm_mobile_rejects_invalid_rows(monkeypatch, row) -> None:
    service = relay.MobileRelayService()
    _install_db(monkeypatch, service, _db_with_first(row))
    assert service.confirm_mobile(user_id=1, username="u", relay_id="r", code="1") is None


def test_confirm_mobile_pairs_valid_desktop(monkeypatch) -> None:
    service = relay.MobileRelayService()
    row = {
        "relay_id": "r",
        "status": "paired",
        "expires_at": "2027-01-01",
        "capabilities_json": '{"host":"10.0.0.2","port":5011}',
    }
    db = _db_with_first(row, additional_results=[MagicMock()])
    _install_db(monkeypatch, service, db)

    paired = service.confirm_mobile(
        user_id=2,
        username=" user ",
        relay_id=" r ",
        code=" 123 ",
    )

    assert paired["status"] == "paired"
    assert paired["local_base_url"] == "http://10.0.0.2:5011"
    assert db.execute.call_count == 2


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"relay_id": "r", "status": "pending", "expires_at": "2025-01-01"},
        {"relay_id": "", "status": "paired", "expires_at": "2027-01-01"},
    ],
)
def test_confirm_mobile_by_code_rejects_invalid_rows(monkeypatch, row) -> None:
    service = relay.MobileRelayService()
    _install_db(monkeypatch, service, _db_with_first(row))
    assert service.confirm_mobile_by_code(user_id=1, username="u", code="123") is None


def test_confirm_mobile_by_code_empty_and_success(monkeypatch) -> None:
    service = relay.MobileRelayService()
    assert service.confirm_mobile_by_code(user_id=1, username="u", code=" ") is None

    row = {"relay_id": "r", "status": "paired", "expires_at": "2027-01-01"}
    db = _db_with_first(row, additional_results=[MagicMock()])
    _install_db(monkeypatch, service, db)
    assert service.confirm_mobile_by_code(user_id=3, username="u", code="123")["status"] == "paired"


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"relay_id": "r", "status": "pending", "expires_at": "2025-01-01"},
        {
            "relay_id": "r",
            "status": "paired",
            "expires_at": "2027-01-01",
            "mobile_user_id": 99,
        },
    ],
)
def test_account_binding_rejects_invalid_rows(monkeypatch, row) -> None:
    service = relay.MobileRelayService()
    _install_db(monkeypatch, service, _db_with_first(row))
    assert service.bind_mobile_by_account(user_id=1, username="u", relay_id="r") is None


def test_account_binding_empty_and_success(monkeypatch) -> None:
    service = relay.MobileRelayService()
    assert service.bind_mobile_by_account(user_id=1, username="u", relay_id=" ") is None
    row = {
        "relay_id": "r",
        "status": "paired",
        "expires_at": "2027-01-01",
        "mobile_user_id": 1,
    }
    db = _db_with_first(row, additional_results=[MagicMock()])
    _install_db(monkeypatch, service, db)
    assert (
        service.bind_mobile_by_account(user_id=1, username="u", relay_id="r")["status"] == "paired"
    )


def test_list_desktops_decodes_rows(monkeypatch) -> None:
    service = relay.MobileRelayService()
    selection = MagicMock()
    selection.mappings.return_value.all.return_value = [
        {"relay_id": "one", "status": "paired", "capabilities_json": "{}"},
        {"relay_id": "two", "status": "paired", "capabilities_json": "bad"},
    ]
    db = MagicMock()
    db.execute.return_value = selection
    _install_db(monkeypatch, service, db)
    assert [item["relay_id"] for item in service.list_desktops(user_id=4)] == ["one", "two"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (None, None),
        ({"task_id": "t", "status": "completed"}, "completed"),
        ({"task_id": "t", "status": "queued"}, "cancelled"),
    ],
)
def test_cancel_task_boundaries(monkeypatch, row, expected) -> None:
    service = relay.MobileRelayService()
    extras = [MagicMock()] if row and row["status"] == "queued" else []
    db = _db_with_first(row, additional_results=extras)
    _install_db(monkeypatch, service, db)
    result = service.cancel_task(user_id=1, task_id="t")
    assert (result or {}).get("status") == expected


def test_poll_desktop_reclaims_and_claims_tasks(monkeypatch) -> None:
    service = relay.MobileRelayService()
    desktop = {"relay_id": "r", "status": "paired", "capabilities": {"host": "0.0.0.0"}}
    monkeypatch.setattr(service, "_desktop_for_token", lambda *_args, **_kwargs: desktop)
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = [
        {"task_id": "t", "status": "queued", "payload_json": '{"message":"go"}'}
    ]
    db = MagicMock()
    db.execute.side_effect = [MagicMock(), MagicMock(), rows, MagicMock()]
    _install_db(monkeypatch, service, db)
    monkeypatch.setenv("XCAGI_RELAY_RUNNING_TTL_SEC", "invalid")

    result = service.poll_desktop(relay_id="r", desktop_token="token", max_tasks=99)

    assert result["task_count"] == 1
    assert result["tasks"][0]["status"] == "running"
    assert result["desktop"]["local_base_url"] == ""


def test_poll_desktop_rejects_bad_token(monkeypatch) -> None:
    service = relay.MobileRelayService()
    monkeypatch.setattr(service, "_desktop_for_token", lambda *_args, **_kwargs: None)
    db = MagicMock()
    _install_db(monkeypatch, service, db)
    assert service.poll_desktop(relay_id="r", desktop_token="bad") is None


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("done", "completed"), ("failed", "failed"), ("unexpected", "completed")],
)
def test_complete_desktop_task_status_normalization(monkeypatch, requested, expected) -> None:
    service = relay.MobileRelayService()
    monkeypatch.setattr(
        service,
        "_desktop_for_token",
        lambda *_args, **_kwargs: {"relay_id": "r"},
    )
    selection = MagicMock()
    selection.mappings.return_value.first.return_value = {
        "task_id": "t",
        "status": expected,
        "result_json": '{"summary":"done"}',
    }
    db = MagicMock()
    db.execute.side_effect = [MagicMock(), selection]
    _install_db(monkeypatch, service, db)
    notified = []
    monkeypatch.setattr(service, "_notify_task_creator", notified.append)

    result = service.complete_desktop_task(
        relay_id="r",
        desktop_token="token",
        task_id="t",
        status=requested,
        result={"summary": "done"},
    )

    assert result["status"] == expected
    assert notified == [result]


def test_complete_desktop_task_rejects_token_and_missing_row(monkeypatch) -> None:
    service = relay.MobileRelayService()
    db = MagicMock()
    _install_db(monkeypatch, service, db)
    monkeypatch.setattr(service, "_desktop_for_token", lambda *_args, **_kwargs: None)
    assert (
        service.complete_desktop_task(relay_id="r", desktop_token="bad", task_id="t", status="done")
        is None
    )

    monkeypatch.setattr(service, "_desktop_for_token", lambda *_args, **_kwargs: {"relay_id": "r"})
    selection = MagicMock()
    selection.mappings.return_value.first.return_value = None
    db.execute.side_effect = [MagicMock(), selection]
    assert (
        service.complete_desktop_task(
            relay_id="r", desktop_token="token", task_id="t", status="done"
        )
        is None
    )


def test_relay_helpers_and_public_desktop_branches(monkeypatch) -> None:
    assert relay._epoch_from_iso("2026-01-01T00:00:00+00:00") > 0
    monkeypatch.setattr(relay.time, "time", lambda: 123.9)
    assert relay._epoch_from_iso("bad") == 123
    assert relay._json_dumps("bad") == "{}"
    assert relay._json_loads(None) == {}
    assert relay._json_loads("[]") == {}
    assert relay._json_loads("bad") == {}
    assert relay._public_base_url("example.com") == "https://example.com/"
    assert relay._public_base_url("http://example.com/") == "http://example.com/"

    service = relay.MobileRelayService()
    defaulted = service._public_desktop({"capabilities": [], "status": ""})
    assert defaulted["status"] == "pending"
    host_only = service._public_desktop(
        {"capabilities": {"host": "127.0.0.1", "port": 0}, "status": "paired"}
    )
    assert host_only["local_base_url"] == "http://127.0.0.1"
    assert host_only["paired_at"] is None


def test_desktop_token_lookup_boundaries(monkeypatch) -> None:
    service = relay.MobileRelayService()
    db = MagicMock()
    assert service._desktop_for_token(db, relay_id="r", desktop_token=" ") is None
    selection = MagicMock()
    selection.mappings.return_value.first.return_value = None
    db.execute.return_value = selection
    assert service._desktop_for_token(db, relay_id="r", desktop_token="token") is None
    selection.mappings.return_value.first.return_value = {
        "relay_id": "r",
        "capabilities_json": "{}",
    }
    assert service._desktop_for_token(db, relay_id="r", desktop_token="token")["relay_id"] == "r"


def test_task_completion_notifications(monkeypatch) -> None:
    notified = []
    monkeypatch.setattr(
        "app.services.mobile_push.notify_user",
        lambda *args, **kwargs: notified.append((args, kwargs)),
    )
    service = relay.MobileRelayService()

    service._notify_task_creator(
        {"created_by_user_id": "bad", "kind": "codex.invoke", "status": "completed"}
    )
    service._notify_task_creator(
        {"created_by_user_id": 1, "kind": "git.merge", "status": "completed"}
    )
    service._notify_task_creator(
        {"created_by_user_id": 1, "kind": "codex.invoke", "status": "cancelled"}
    )
    service._notify_task_creator(
        {
            "created_by_user_id": 1,
            "kind": "codex.invoke",
            "status": "completed",
            "task_id": "one",
            "result": {"summary": "ready"},
        }
    )
    service._notify_task_creator(
        {
            "created_by_user_id": 2,
            "kind": "claude.invoke",
            "status": "failed",
            "task_id": "two",
            "result_json": "bad",
        }
    )

    assert len(notified) == 2
    assert notified[0][1]["body"] == "ready"
    assert "已结束" in notified[1][1]["body"]

    monkeypatch.setattr(
        "app.services.mobile_push.notify_user", MagicMock(side_effect=OSError("offline"))
    )
    service._notify_task_creator(
        {
            "created_by_user_id": 3,
            "kind": "cursor.invoke",
            "status": "blocked",
            "task_id": "three",
            "result": {"error": "blocked"},
        }
    )
