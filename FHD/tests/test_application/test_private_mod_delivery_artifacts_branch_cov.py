"""分支覆盖测试：app.application.private_mod_delivery_artifacts 模块。

策略：
- 用 patch 隔离 httpx.AsyncClient（网络）、catalog_client、market_account、
  mods.employee_registry / mod_manager / artifact_package / package。
- 异步测试依赖 pyproject 的 asyncio_mode=auto，无需手写 asyncio marker。
- 覆盖每个公共函数 / 纯函数 / 条件分支 / 异常路径 / 成功路径。
"""

from __future__ import annotations

import io
import json
import zipfile
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application import private_mod_delivery_artifacts as mod
from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK

BASE = "app.application.private_mod_delivery_artifacts"


def _zip_bytes(manifest: dict, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def _async_client(
    *,
    get_resp=None,
    request_resp=None,
    get_error=None,
    request_error=None,
) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    if get_error is not None:
        client.get = AsyncMock(side_effect=get_error)
    else:
        client.get = AsyncMock(return_value=get_resp)
    if request_error is not None:
        client.request = AsyncMock(side_effect=request_error)
    else:
        client.request = AsyncMock(return_value=request_resp)
    return client


def _resp(status_code=200, body=None, content=b"data", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = headers or {}
    resp.json.return_value = body
    return resp


# ---------------------------------------------------------------------------
# version_key / is_newer_version / _auth_header
# ---------------------------------------------------------------------------


class TestVersionHelpers:
    def test_version_key_semver(self):
        assert mod.version_key("1.2.3") < mod.version_key("1.10.0")
        assert mod.version_key("v1.0.0") == mod.version_key("1.0.0")
        assert mod.version_key("V2.0.0") == mod.version_key("2.0.0")

    def test_version_key_alpha_tokens(self):
        assert mod.version_key("1.0.0-beta") < mod.version_key("1.0.0-rc")
        # tuple ordering quirk：带后缀的版本在元组比较中更长，故大于不带后缀的版本
        assert mod.version_key("1.0.0-rc") > mod.version_key("1.0.0")

    def test_version_key_empty_and_none(self):
        assert mod.version_key("") == ((0, 0),)
        assert mod.version_key(None) == ((0, 0),)
        assert mod.version_key("   ") == ((0, 0),)

    def test_version_key_mixed(self):
        assert mod.version_key("legacy-2") > mod.version_key("legacy-1")

    def test_is_newer_version_true_false_empty(self):
        assert mod.is_newer_version("2.0.0", "1.0.0") is True
        assert mod.is_newer_version("1.0.0", "2.0.0") is False
        assert mod.is_newer_version("1.0.0", "1.0.0") is False
        assert mod.is_newer_version("", "1.0.0") is False
        assert mod.is_newer_version(None, "1.0.0") is False
        assert mod.is_newer_version("   ", "1.0.0") is False

    def test_auth_header_variants(self):
        assert mod._auth_header("abc") == "Bearer abc"
        assert mod._auth_header("Bearer xyz") == "Bearer xyz"
        assert mod._auth_header("bearer xyz") == "bearer xyz"
        assert mod._auth_header("") == "Bearer "
        assert mod._auth_header(None) == "Bearer "
        assert mod._auth_header("  tok  ") == "Bearer tok"


# ---------------------------------------------------------------------------
# custom_delivery_remote_json
# ---------------------------------------------------------------------------


class TestCustomDeliveryRemoteJson:
    async def test_missing_token_raises_permission(self):
        with pytest.raises(PermissionError):
            await mod.custom_delivery_remote_json("", "/foo")

    async def test_success_get_default(self):
        client = _async_client(request_resp=_resp(200, {"ok": True}))
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            result = await mod.custom_delivery_remote_json("tok", "/foo")
        assert result == {"ok": True}

    async def test_path_without_leading_slash_and_payload(self):
        client = _async_client(request_resp=_resp(200, {"id": 1}))
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            result = await mod.custom_delivery_remote_json(
                "tok", "foo/bar", method="post", payload={"a": 1}
            )
        assert result == {"id": 1}
        client.request.assert_awaited_once()
        args, kwargs = client.request.call_args
        assert args[0] == "POST"
        assert kwargs["json"] == {"a": 1}

    async def test_request_error_raises_connection_error(self):
        client = _async_client(
            request_error=httpx_connect_error(),
        )
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            with pytest.raises(ConnectionError):
                await mod.custom_delivery_remote_json("tok", "/foo")

    async def test_json_decode_error_still_returns_body(self):
        resp = _resp(200, body=None)
        resp.json.side_effect = ValueError("bad json")
        client = _async_client(request_resp=resp)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            result = await mod.custom_delivery_remote_json("tok", "/foo")
        assert result == {}

    async def test_http_error_dict_detail(self):
        resp = _resp(404, body={"detail": "not found"})
        client = _async_client(request_resp=resp)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            with pytest.raises(RuntimeError) as ei:
                await mod.custom_delivery_remote_json("tok", "/foo")
        assert "not found" in str(ei.value)

    async def test_http_error_dict_message_fallback(self):
        resp = _resp(500, body={"message": "boom"})
        client = _async_client(request_resp=resp)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            with pytest.raises(RuntimeError) as ei:
                await mod.custom_delivery_remote_json("tok", "/foo")
        assert "boom" in str(ei.value)

    async def test_http_error_non_dict_uses_status(self):
        resp = _resp(403, body="plain")
        client = _async_client(request_resp=resp)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            with pytest.raises(RuntimeError) as ei:
                await mod.custom_delivery_remote_json("tok", "/foo")
        assert "403" in str(ei.value)

    async def test_http_error_dict_empty_detail_uses_status(self):
        resp = _resp(400, body={"detail": ""})
        client = _async_client(request_resp=resp)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            with pytest.raises(RuntimeError) as ei:
                await mod.custom_delivery_remote_json("tok", "/foo")
        assert "400" in str(ei.value)

    async def test_non_dict_ok_body_raises(self):
        resp = _resp(200, body=[1, 2])
        client = _async_client(request_resp=resp)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ):
            with pytest.raises(RuntimeError) as ei:
                await mod.custom_delivery_remote_json("tok", "/foo")
        assert "格式无效" in str(ei.value)


def httpx_connect_error():
    import httpx

    return httpx.ConnectError("boom", request=httpx.Request("GET", "http://x"))


# ---------------------------------------------------------------------------
# install_custom_delivery_artifact
# ---------------------------------------------------------------------------


class TestInstallCustomDeliveryArtifact:
    def _patch_common(self, client):
        return [
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://m.example.com",
            ),
        ]

    def _enter(self, stack: ExitStack, client, *extra):
        for cm in self._patch_common(client):
            stack.enter_context(cm)
        for cm in extra:
            stack.enter_context(cm)

    def _extract_mod(self, manifest):
        ModPackage = __import__("app.infrastructure.mods.package", fromlist=["ModPackage"]).ModPackage
        return patch.object(
            ModPackage,
            "extract_package",
            classmethod(lambda cls, *a, **k: ("/tmp/x", manifest)),
        )

    async def test_invalid_kind(self):
        with pytest.raises(ValueError):
            await mod.install_custom_delivery_artifact("tok", 1, "bundle")

    async def test_download_request_error(self):
        client = _async_client(get_error=httpx_connect_error())
        with ExitStack() as stack:
            self._enter(stack, client)
            with pytest.raises(ConnectionError):
                await mod.install_custom_delivery_artifact("tok", 1, "module")

    async def test_http_error_with_detail(self):
        client = _async_client(get_resp=_resp(404, body={"detail": "gone"}))
        with ExitStack() as stack:
            self._enter(stack, client)
            with pytest.raises(RuntimeError) as ei:
                await mod.install_custom_delivery_artifact("tok", 1, "module")
        assert "gone" in str(ei.value)

    async def test_http_error_json_decode_fallback(self):
        resp = _resp(500, body=None)
        resp.json.side_effect = ValueError("bad")
        client = _async_client(get_resp=resp)
        with ExitStack() as stack:
            self._enter(stack, client)
            with pytest.raises(RuntimeError) as ei:
                await mod.install_custom_delivery_artifact("tok", 1, "module")
        assert "500" in str(ei.value)

    async def test_missing_receipt_token(self):
        resp = _resp(200, content=b"data", headers={})
        client = _async_client(get_resp=resp)
        with ExitStack() as stack:
            self._enter(stack, client)
            with pytest.raises(RuntimeError) as ei:
                await mod.install_custom_delivery_artifact("tok", 1, "module")
        assert "回执凭证" in str(ei.value)

    async def test_empty_content(self):
        resp = _resp(200, content=b"", headers={"X-Delivery-Receipt-Token": "a" * 20})
        client = _async_client(get_resp=resp)
        with ExitStack() as stack:
            self._enter(stack, client)
            with pytest.raises(RuntimeError) as ei:
                await mod.install_custom_delivery_artifact("tok", 1, "module")
        assert "为空" in str(ei.value)

    async def test_employee_success(self):
        token = "a" * 20
        download = _resp(200, content=_zip_bytes({"id": "emp-1", "version": "1.2.3"}),
                         headers={"X-Delivery-Receipt-Token": token})
        receipt = _resp(200, body={"ok": True, "id": 99})
        client = _async_client(get_resp=download, request_resp=receipt)
        registry = MagicMock()
        registry.install_from_package.return_value = (True, "ok")
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.artifact_package.peek_artifact",
                    return_value=ARTIFACT_EMPLOYEE_PACK,
                ),
                patch(
                    "app.infrastructure.mods.employee_registry.get_employee_registry",
                    return_value=registry,
                ),
            )
            result = await mod.install_custom_delivery_artifact("tok", 7, "employee")
        assert result["success"] is True
        assert result["artifact_id"] == "emp-1"
        assert result["installed_version"] == "1.2.3"
        assert result["delivery"]["ok"] is True
        registry.install_from_package.assert_called_once()
        client.request.assert_awaited_once()

    async def test_employee_wrong_artifact_kind(self):
        token = "a" * 20
        download = _resp(200, content=b"x", headers={"X-Delivery-Receipt-Token": token})
        client = _async_client(get_resp=download)
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.artifact_package.peek_artifact",
                    return_value="mod_pack",
                ),
            )
            with pytest.raises(ValueError) as ei:
                await mod.install_custom_delivery_artifact("tok", 7, "employee")
        assert "期望 AI 员工包" in str(ei.value)

    async def test_employee_install_fail(self):
        token = "a" * 20
        download = _resp(200, content=_zip_bytes({"id": "emp-1", "version": "1.2.3"}),
                         headers={"X-Delivery-Receipt-Token": token})
        client = _async_client(get_resp=download)
        registry = MagicMock()
        registry.install_from_package.return_value = (False, "install boom")
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.artifact_package.peek_artifact",
                    return_value=ARTIFACT_EMPLOYEE_PACK,
                ),
                patch(
                    "app.infrastructure.mods.employee_registry.get_employee_registry",
                    return_value=registry,
                ),
            )
            with pytest.raises(RuntimeError) as ei:
                await mod.install_custom_delivery_artifact("tok", 7, "employee")
        assert "install boom" in str(ei.value)

    async def test_employee_missing_id(self):
        token = "a" * 20
        download = _resp(200, content=_zip_bytes({"version": "1.0.0"}),
                         headers={"X-Delivery-Receipt-Token": token})
        client = _async_client(get_resp=download)
        registry = MagicMock()
        registry.install_from_package.return_value = (True, "ok")
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.artifact_package.peek_artifact",
                    return_value=ARTIFACT_EMPLOYEE_PACK,
                ),
                patch(
                    "app.infrastructure.mods.employee_registry.get_employee_registry",
                    return_value=registry,
                ),
            )
            with pytest.raises(ValueError) as ei:
                await mod.install_custom_delivery_artifact("tok", 7, "employee")
        assert "缺少 ID" in str(ei.value)

    async def test_module_success(self):
        token = "a" * 20
        download = _resp(200, content=b"modbytes",
                         headers={"X-Delivery-Receipt-Token": token})
        receipt = _resp(200, body={"ok": True})
        client = _async_client(get_resp=download, request_resp=receipt)
        manager = MagicMock()
        manager.install_mod_package.return_value = (True, "installed", SimpleNamespace(version="2.0.0"))
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=manager,
                ),
                patch(
                    "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                    return_value=True,
                ),
                self._extract_mod({"id": "mod-1", "version": "2.0.0"}),
            )
            result = await mod.install_custom_delivery_artifact("tok", 9, "module")
        assert result["success"] is True
        assert result["artifact_id"] == "mod-1"
        assert result["installed_version"] == "2.0.0"
        manager.install_mod_package.assert_called_once()

    async def test_module_install_fail(self):
        token = "a" * 20
        download = _resp(200, content=b"modbytes",
                         headers={"X-Delivery-Receipt-Token": token})
        client = _async_client(get_resp=download)
        manager = MagicMock()
        manager.install_mod_package.return_value = (False, "mod install boom", None)
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=manager,
                ),
                self._extract_mod({"id": "mod-1", "version": "2.0.0"}),
            )
            with pytest.raises(RuntimeError) as ei:
                await mod.install_custom_delivery_artifact("tok", 9, "module")
        assert "mod install boom" in str(ei.value)

    async def test_module_metadata_version_empty_falls_back(self):
        token = "a" * 20
        download = _resp(200, content=b"modbytes",
                         headers={"X-Delivery-Receipt-Token": token})
        receipt = _resp(200, body={"ok": True})
        client = _async_client(get_resp=download, request_resp=receipt)
        manager = MagicMock()
        manager.install_mod_package.return_value = (True, "ok", SimpleNamespace(version=""))
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=manager,
                ),
                patch(
                    "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                    return_value=True,
                ),
                self._extract_mod({"id": "mod-1", "version": "0.9.0"}),
            )
            result = await mod.install_custom_delivery_artifact("tok", 9, "module")
        assert result["installed_version"] == "0.9.0"

    async def test_module_api_ready_recoverable_error_logged(self):
        token = "a" * 20
        download = _resp(200, content=b"modbytes",
                         headers={"X-Delivery-Receipt-Token": token})
        receipt = _resp(200, body={"ok": True})
        client = _async_client(get_resp=download, request_resp=receipt)
        manager = MagicMock()
        manager.install_mod_package.return_value = (True, "ok", SimpleNamespace(version="2.0.0"))
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=manager,
                ),
                patch(
                    "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                    side_effect=RuntimeError("flush failed"),
                ),
                self._extract_mod({"id": "mod-1", "version": "2.0.0"}),
            )
            result = await mod.install_custom_delivery_artifact("tok", 9, "module")
        assert result["success"] is True

    async def test_module_missing_id(self):
        token = "a" * 20
        download = _resp(200, content=b"modbytes",
                         headers={"X-Delivery-Receipt-Token": token})
        client = _async_client(get_resp=download)
        manager = MagicMock()
        manager.install_mod_package.return_value = (True, "ok", SimpleNamespace(version="1.0.0"))
        with ExitStack() as stack:
            self._enter(
                stack,
                client,
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=manager,
                ),
                self._extract_mod({"version": "1.0.0"}),
            )
            with pytest.raises(ValueError) as ei:
                await mod.install_custom_delivery_artifact("tok", 9, "module")
        assert "缺少 ID" in str(ei.value)

    async def test_finally_unlink_oserror_swallowed(self, monkeypatch):
        token = "a" * 20
        download = _resp(200, content=b"modbytes",
                         headers={"X-Delivery-Receipt-Token": token})
        client = _async_client(get_resp=download, request_resp=_resp(200, body={"ok": True}))
        manager = MagicMock()
        manager.install_mod_package.return_value = (True, "ok", SimpleNamespace(version="1.0.0"))

        import pathlib

        real_unlink = pathlib.Path.unlink

        def _boom_unlink(self, *a, **k):
            raise OSError("busy")

        monkeypatch.setattr(pathlib.Path, "unlink", _boom_unlink)
        try:
            with ExitStack() as stack:
                self._enter(
                    stack,
                    client,
                    patch(
                        "app.infrastructure.mods.mod_manager.get_mod_manager",
                        return_value=manager,
                    ),
                    patch(
                        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                        return_value=True,
                    ),
                    self._extract_mod({"id": "mod-1", "version": "1.0.0"}),
                )
                result = await mod.install_custom_delivery_artifact("tok", 9, "module")
            assert result["success"] is True
        finally:
            monkeypatch.setattr(pathlib.Path, "unlink", real_unlink)


# ---------------------------------------------------------------------------
# fetch_private_mod_library / _library_row_by_id
# ---------------------------------------------------------------------------


class TestFetchPrivateModLibrary:
    async def test_empty_token_returns_empty(self):
        assert await mod.fetch_private_mod_library("") == []
        assert await mod.fetch_private_mod_library(None) == []

    async def test_data_list(self):
        with patch(
            f"{BASE}.catalog_get_json",
            AsyncMock(return_value={"data": [{"id": "m1", "version": "1.0.0"}]}),
        ):
            result = await mod.fetch_private_mod_library("tok")
        assert result == [{"id": "m1", "version": "1.0.0"}]

    async def test_data_not_list_falls_back_to_mods(self):
        with patch(
            f"{BASE}.catalog_get_json",
            AsyncMock(return_value={"data": "nope", "mods": [{"id": "m2"}]}),
        ):
            result = await mod.fetch_private_mod_library("tok")
        assert result == [{"id": "m2"}]

    async def test_filters_non_dict_and_empty(self):
        with patch(
            f"{BASE}.catalog_get_json",
            AsyncMock(return_value={"data": [{"id": "m1"}, "junk", None, 3, {"id": 5}]}),
        ):
            result = await mod.fetch_private_mod_library("tok")
        assert result == [{"id": "m1"}, {"id": 5}]

    async def test_no_list_at_all_returns_empty(self):
        with patch(
            f"{BASE}.catalog_get_json",
            AsyncMock(return_value={"x": 1}),
        ):
            assert await mod.fetch_private_mod_library("tok") == []

    def test_library_row_by_id(self):
        rows = [{"id": "m1", "v": 1}, {"id": "m2", "v": 2}]
        assert mod._library_row_by_id(rows, "m2") == {"id": "m2", "v": 2}
        assert mod._library_row_by_id(rows, "  m1  ") is not None
        assert mod._library_row_by_id(rows, "nope") is None
        assert mod._library_row_by_id([], "m1") is None
        assert mod._library_row_by_id(rows, "") is None
        assert mod._library_row_by_id(rows, None) is None
        assert mod._library_row_by_id([{"id": "m1"}], "m1") is not None


# ---------------------------------------------------------------------------
# update_private_mod_from_library
# ---------------------------------------------------------------------------


class TestUpdatePrivateModFromLibrary:
    def _manager(self, scan_rows=None, install_result=None):
        manager = MagicMock()
        manager.scan_mods.return_value = scan_rows or []
        manager.install_mod_package.return_value = install_result or (True, "ok", SimpleNamespace(version="2.0.0"))
        return manager

    def _extract(self, manifest):
        ModPackage = __import__("app.infrastructure.mods.package", fromlist=["ModPackage"]).ModPackage
        return patch.object(
            ModPackage,
            "extract_package",
            classmethod(lambda cls, *a, **k: ("/tmp/x", manifest)),
        )

    async def test_invalid_id(self):
        for bad in ("", None, "a/b", "a\\b"):
            with pytest.raises(ValueError):
                await mod.update_private_mod_from_library(bad, "tok")

    async def test_remote_not_found(self):
        with patch(
            f"{BASE}.fetch_private_mod_library", AsyncMock(return_value=[{"id": "other"}])
        ):
            with pytest.raises(LookupError):
                await mod.update_private_mod_from_library("m1", "tok")

    async def test_remote_version_missing(self):
        with patch(
            f"{BASE}.fetch_private_mod_library",
            AsyncMock(return_value=[{"id": "m1", "version": "  "}]),
        ):
            with pytest.raises(ValueError):
                await mod.update_private_mod_from_library("m1", "tok")

    async def test_expected_version_mismatch(self):
        with patch(
            f"{BASE}.fetch_private_mod_library",
            AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
        ):
            with pytest.raises(ValueError):
                await mod.update_private_mod_from_library("m1", "tok", expected_version="1.0.0")

    async def test_already_latest_local(self):
        with patch(
            f"{BASE}.fetch_private_mod_library",
            AsyncMock(return_value=[{"id": "m1", "version": "1.0.0"}]),
        ), patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=self._manager(scan_rows=[SimpleNamespace(id="m1", version="1.0.0")]),
        ):
            result = await mod.update_private_mod_from_library("m1", "tok")
        assert result["success"] is True
        assert result["updated"] is False

    async def test_empty_token_raises_permission(self):
        with patch(
            f"{BASE}.fetch_private_mod_library",
            AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
        ), patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=self._manager(scan_rows=[]),
        ):
            with pytest.raises(PermissionError):
                await mod.update_private_mod_from_library("m1", "")

    async def test_successful_update(self):
        manager = self._manager(scan_rows=[], install_result=(True, "installed", SimpleNamespace(version="2.0.0")))
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=manager,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                return_value=True,
            ),
            self._extract({"id": "m1", "version": "2.0.0"}),
        ):
            result = await mod.update_private_mod_from_library("m1", "tok")
        assert result["success"] is True
        assert result["updated"] is True
        assert result["current_version"] == "2.0.0"
        manager.install_mod_package.assert_called_once()
        _, kwargs = manager.install_mod_package.call_args
        assert kwargs["verify_signature"] is False

    async def test_verify_signature_env_enabled(self, monkeypatch):
        monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "1")
        manager = self._manager(scan_rows=[], install_result=(True, "ok", SimpleNamespace(version="2.0.0")))
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=manager,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                return_value=True,
            ),
            self._extract({"id": "m1", "version": "2.0.0"}),
        ):
            await mod.update_private_mod_from_library("m1", "tok")
        _, kwargs = manager.install_mod_package.call_args
        assert kwargs["verify_signature"] is True

    async def test_manifest_id_mismatch(self):
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._manager(scan_rows=[]),
            ),
            self._extract({"id": "OTHER", "version": "2.0.0"}),
        ):
            with pytest.raises(ValueError) as ei:
                await mod.update_private_mod_from_library("m1", "tok")
        assert "身份校验失败" in str(ei.value)

    async def test_manifest_version_mismatch(self):
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._manager(scan_rows=[]),
            ),
            self._extract({"id": "m1", "version": "9.9.9"}),
        ):
            with pytest.raises(ValueError) as ei:
                await mod.update_private_mod_from_library("m1", "tok")
        assert "不一致" in str(ei.value)

    async def test_install_fail(self):
        manager = self._manager(scan_rows=[], install_result=(False, "boom", None))
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=manager,
            ),
            self._extract({"id": "m1", "version": "2.0.0"}),
        ):
            with pytest.raises(RuntimeError):
                await mod.update_private_mod_from_library("m1", "tok")

    async def test_api_ready_recoverable_error_logged(self):
        manager = self._manager(scan_rows=[], install_result=(True, "ok", SimpleNamespace(version="2.0.0")))
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=manager,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                side_effect=RuntimeError("flush failed"),
            ),
            self._extract({"id": "m1", "version": "2.0.0"}),
        ):
            result = await mod.update_private_mod_from_library("m1", "tok")
        assert result["updated"] is True

    async def test_previous_version_from_local(self):
        manager = self._manager(
            scan_rows=[SimpleNamespace(id="m1", version="1.0.0")],
            install_result=(True, "ok", SimpleNamespace(version="2.0.0")),
        )
        with (
            patch(
                f"{BASE}.fetch_private_mod_library",
                AsyncMock(return_value=[{"id": "m1", "version": "2.0.0"}]),
            ),
            patch(
                f"{BASE}.catalog_download_to",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=manager,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
                return_value=True,
            ),
            self._extract({"id": "m1", "version": "2.0.0"}),
        ):
            result = await mod.update_private_mod_from_library("m1", "tok")
        assert result["previous_version"] == "1.0.0"
        assert result["current_version"] == "2.0.0"