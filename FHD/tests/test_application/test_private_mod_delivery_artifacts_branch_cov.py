"""分支覆盖测试：app.application.private_mod_delivery_artifacts 模块。

策略：
- 网络、账号和运行激活隔离；包使用真实 Ed25519 签名、解压、Mod/员工安装和持久回执。
- 异步测试依赖 pyproject 的 asyncio_mode=auto，无需手写 asyncio marker。
- 覆盖每个公共函数 / 纯函数 / 条件分支 / 异常路径 / 成功路径。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application import private_mod_delivery_artifacts as mod
from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK

BASE = "app.application.private_mod_delivery_artifacts"


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


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    """Real signature, extraction, installation and outbox; isolated network/runtime."""
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.infrastructure.mods import mod_manager, trusted_keys
    from app.infrastructure.mods.employee_registry import EmployeeRegistry
    from app.infrastructure.mods.package import ModPackage

    key = Ed25519PrivateKey.generate()
    secret = tmp_path / "synthetic-signing.pem"
    secret.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    monkeypatch.setattr(trusted_keys, "TRUSTED_MOD_PUBLIC_KEYS_PEM", (public,))
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "1")
    private_tmp = tmp_path / "temporary"
    private_tmp.mkdir()
    monkeypatch.setattr(mod.tempfile, "tempdir", str(private_tmp))
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(data))
    monkeypatch.setattr(
        "app.application.desktop_delivery_receipt.desktop_installation_id",
        lambda: "synthetic-desktop-instance-123456",
    )
    monkeypatch.setattr("app.build_identity.build_identity", lambda: {"git_sha": "a" * 40})
    mods_root = tmp_path / "mods"
    mods_root.mkdir()
    manager = mod_manager.ModManager(mods_root=str(mods_root))
    assert Path(manager.mods_root) == mods_root
    registry = MagicMock()
    registry.get_mod_metadata.return_value = None
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: manager)
    # Activation itself is a boundary: no arbitrary Mod code or HTTP routes execute.
    activation = MagicMock(return_value=True)
    monkeypatch.setattr(manager, "load_mod", activation)
    install = MagicMock(wraps=manager.install_mod_package)
    monkeypatch.setattr(manager, "install_mod_package", install)
    api_ready = MagicMock(return_value=False)
    monkeypatch.setattr(mod_manager, "ensure_mod_api_ready", api_ready)
    employees = EmployeeRegistry(manager.mods_root)
    employee_install = MagicMock(wraps=employees.install_from_package)
    monkeypatch.setattr(employees, "install_from_package", employee_install)
    monkeypatch.setattr(
        "app.infrastructure.mods.employee_registry.get_employee_registry",
        lambda: employees,
    )
    monkeypatch.setattr("app.mod_sdk.employee_runtime.refresh_employee_pack_runtime", MagicMock())
    monkeypatch.setattr(
        "app.fastapi_routes.market_account._market_base_url",
        lambda: "https://synthetic-market.invalid",
    )
    client = _async_client()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    counter = 0

    def package(
        *,
        kind="module",
        mid="fixture-mod",
        version="2.0.0",
        signed=True,
        content="fixture code",
    ):
        nonlocal counter
        counter += 1
        source = tmp_path / ("source-" + str(counter))
        source.mkdir()
        manifest = {"id": mid, "name": "Fixture", "version": version}
        if kind == "employee":
            manifest.update(
                artifact=ARTIFACT_EMPLOYEE_PACK,
                scope="global",
                employee={"id": "fixture-employee"},
            )
        (source / "manifest.json").write_text(json.dumps(manifest))
        (source / "logic.py").write_text(content)
        path = ModPackage(str(source)).create_package(
            str(tmp_path / ("packages-" + str(counter))),
            include_signature=signed,
            private_key=str(secret) if signed else None,
        )
        return Path(path).read_bytes()

    def response(raw, *, version="2.0.0", headers=None):
        values = {
            "X-Delivery-Receipt-Token": "synthetic-delivery-grant-123456",
            "X-Delivery-Artifact-SHA256": hashlib.sha256(raw).hexdigest(),
            "X-Delivery-Artifact-Version": version,
        }
        values.update(headers or {})
        return httpx.Response(200, content=raw, headers=values)

    def outbox_rows():
        return [
            json.loads(path.read_text()) for path in data.glob("mod-delivery-receipts/*/*.json")
        ]

    return SimpleNamespace(
        root=tmp_path,
        data=data,
        manager=manager,
        install=install,
        activation=activation,
        api_ready=api_ready,
        employees=employees,
        employee_install=employee_install,
        client=client,
        package=package,
        response=response,
        outbox_rows=outbox_rows,
    )


class TestInstallCustomDeliveryArtifact:
    async def test_invalid_kind(self):
        with pytest.raises(ValueError, match="artifact_kind"):
            await mod.install_custom_delivery_artifact("tok", 1, "bundle", owner_scope="tenant:1")

    async def test_owner_is_required_before_download(self, delivery):
        with pytest.raises(ValueError, match="工作空间"):
            await mod.install_custom_delivery_artifact("tok", 1, "module")
        delivery.client.get.assert_not_awaited()
        delivery.install.assert_not_called()

    async def test_token_required_before_download(self, delivery):
        with pytest.raises(PermissionError):
            await mod.install_custom_delivery_artifact("", 1, "module", owner_scope="tenant:1")
        delivery.client.get.assert_not_awaited()
        delivery.install.assert_not_called()

    async def test_download_request_error(self, delivery):
        delivery.client.get.side_effect = httpx_connect_error()
        with pytest.raises(ConnectionError):
            await mod.install_custom_delivery_artifact("tok", 1, "module", owner_scope="tenant:1")
        delivery.install.assert_not_called()
        assert delivery.outbox_rows() == []

    @pytest.mark.parametrize("invalid_json", [False, True])
    async def test_http_error_preserves_detail_or_status(self, delivery, invalid_json):
        response = _resp(404, body={"detail": "gone"})
        if invalid_json:
            response.json.side_effect = ValueError("bad")
        delivery.client.get.return_value = response
        with pytest.raises(RuntimeError, match="404" if invalid_json else "gone"):
            await mod.install_custom_delivery_artifact("tok", 1, "module", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    async def test_missing_receipt_token(self, delivery):
        delivery.client.get.return_value = delivery.response(
            delivery.package(), headers={"X-Delivery-Receipt-Token": ""}
        )
        with pytest.raises(RuntimeError, match="回执凭证"):
            await mod.install_custom_delivery_artifact("tok", 1, "module", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    async def test_empty_content(self, delivery):
        delivery.client.get.return_value = delivery.response(b"")
        with pytest.raises(RuntimeError, match="为空"):
            await mod.install_custom_delivery_artifact("tok", 1, "module", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    @pytest.mark.parametrize("kind", ["module", "employee"])
    @pytest.mark.parametrize(
        "headers",
        [
            {"X-Delivery-Artifact-SHA256": "0" * 64},
            {"X-Delivery-Artifact-SHA256": ""},
            {"X-Delivery-Artifact-Version": ""},
            {"X-Delivery-Artifact-Version": "9.9.9"},
        ],
    )
    async def test_bad_digest_or_version_never_installs(self, delivery, kind, headers):
        raw = delivery.package(kind=kind)
        delivery.client.get.return_value = delivery.response(raw, headers=headers)
        with pytest.raises(RuntimeError, match="摘要|版本"):
            await mod.install_custom_delivery_artifact("tok", 7, kind, owner_scope="tenant:1")
        delivery.install.assert_not_called()
        delivery.employee_install.assert_not_called()
        assert delivery.outbox_rows() == []
        assert not (delivery.root / "mods" / "fixture-mod").exists()
        assert not (delivery.root / "mods" / "_employees" / "fixture-mod").exists()

    async def test_selected_artifact_is_in_download_url_and_must_match_signed_manifest(
        self, delivery
    ):
        raw = delivery.package()
        delivery.client.get.return_value = delivery.response(raw)
        with pytest.raises(RuntimeError, match="身份"):
            await mod.install_custom_delivery_artifact(
                "tok", 7, "module", owner_scope="tenant:1", artifact_id="another-module"
            )
        assert "artifact_id=another-module" in delivery.client.get.await_args.args[0]
        delivery.install.assert_not_called()
        assert delivery.outbox_rows() == []

    @pytest.mark.parametrize("kind", ["module", "employee"])
    async def test_signed_success_persists_installed_not_verified(self, delivery, kind):
        raw = delivery.package(kind=kind)
        delivery.client.get.return_value = delivery.response(raw)
        result = await mod.install_custom_delivery_artifact("tok", 7, kind, owner_scope="tenant:1")
        assert result["success"] is True
        assert result["artifact_id"] == "fixture-mod"
        assert result["installed_version"] == "2.0.0"
        assert result["package_sha256"] == hashlib.sha256(raw).hexdigest()
        assert result["runtime_verified"] is False
        (row,) = delivery.outbox_rows()
        assert row["owner"] == "tenant:1"
        assert row["payload"]["stage"] == "installed"
        assert row["payload"]["package_sha256"] == result["package_sha256"]
        assert row["installed_reported"] is False
        assert row["runtime_reported"] is False
        assert row["payload"]["receipt_id"] == result["receipt_id"] + ":installed"
        delivery.client.request.assert_not_awaited()
        if kind == "module":
            from app.infrastructure.mods.install_receipts import read_verified_install

            receipt = read_verified_install("fixture-mod", mods_root=delivery.manager.mods_root)
            assert receipt["owner_scope"] == "tenant:1"
            assert receipt["signature_verified"] is True
            assert receipt["package_sha256"] == result["package_sha256"]
            archive = (
                delivery.root
                / "mods/.install-receipts/fixture-mod"
                / (result["package_sha256"] + ".zip")
            )
            assert archive.read_bytes() == raw
            with zipfile.ZipFile(archive) as stored:
                assert "META-INF/signature.json" in stored.namelist()
            assert delivery.install.call_args.kwargs == {
                "verify_signature": True,
                "activate": True,
                "owner_scope": "tenant:1",
            }
        else:
            receipt = json.loads(
                (
                    delivery.root / "mods/_employees/fixture-mod/.xcagi-install-receipt.json"
                ).read_text()
            )
            assert receipt["signature_verified"] is True
            assert delivery.employee_install.call_args.kwargs["verify_signature"] is True

    async def test_employee_wrong_artifact_kind(self, delivery):
        delivery.client.get.return_value = delivery.response(delivery.package())
        with pytest.raises(ValueError, match="期望 AI 员工包"):
            await mod.install_custom_delivery_artifact("tok", 7, "employee", owner_scope="tenant:1")
        delivery.employee_install.assert_not_called()

    @pytest.mark.parametrize("kind", ["module", "employee"])
    async def test_install_failure_keeps_module_grant_pending_without_claiming_installed(
        self, delivery, kind
    ):
        delivery.client.get.return_value = delivery.response(delivery.package(kind=kind))
        if kind == "module":
            delivery.install.return_value = (False, "install boom", None)
        else:
            delivery.employee_install.return_value = (False, "install boom")
        with pytest.raises(RuntimeError, match="install boom"):
            await mod.install_custom_delivery_artifact("tok", 7, kind, owner_scope="tenant:1")
        rows = delivery.outbox_rows()
        if kind == "module":
            assert len(rows) == 1
            assert rows[0]["installed_reported"] is False
            assert rows[0]["runtime_reported"] is False
        else:
            assert rows == []

    @pytest.mark.parametrize("signed", [False, True])
    async def test_unsigned_or_wrong_key_never_installs(self, delivery, monkeypatch, signed):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from app.infrastructure.mods.package import ModSignatureError

        raw = delivery.package(signed=signed)
        if signed:
            monkeypatch.setattr(
                "app.infrastructure.mods.trusted_keys.load_trusted_public_keys",
                lambda: [Ed25519PrivateKey.generate().public_key()],
            )
        delivery.client.get.return_value = delivery.response(raw)
        with pytest.raises(ModSignatureError):
            await mod.install_custom_delivery_artifact("tok", 7, "module", owner_scope="tenant:1")
        delivery.install.assert_not_called()
        assert delivery.outbox_rows() == []

    async def test_module_api_ready_failure_does_not_claim_running(self, delivery):
        delivery.client.get.return_value = delivery.response(delivery.package())
        delivery.api_ready.side_effect = RuntimeError("flush failed")
        result = await mod.install_custom_delivery_artifact(
            "tok", 9, "module", owner_scope="tenant:1"
        )
        assert result["success"] is True
        assert result["runtime_verified"] is False
        assert delivery.outbox_rows()[0]["runtime_reported"] is False

    async def test_download_response_loss_retries_without_duplicate_activation(self, delivery):
        raw = delivery.package()
        delivery.client.get.side_effect = [
            httpx_connect_error(),
            delivery.response(raw),
        ]
        with pytest.raises(ConnectionError):
            await mod.install_custom_delivery_artifact("tok", 9, "module", owner_scope="tenant:1")
        delivery.activation.assert_not_called()
        delivery.install.assert_not_called()
        assert delivery.outbox_rows() == []
        result = await mod.install_custom_delivery_artifact(
            "tok", 9, "module", owner_scope="tenant:1"
        )
        assert result["runtime_verified"] is False
        assert delivery.client.get.await_count == 2
        delivery.activation.assert_called_once_with("fixture-mod")
        assert delivery.install.call_count == 1
        assert len(delivery.outbox_rows()) == 1

    async def test_receipt_response_loss_retries_saved_body_without_reinstall(
        self, delivery, monkeypatch
    ):
        import copy

        from fastapi import Request

        from app.application import mod_delivery_receipt_outbox as outbox
        from app.infrastructure.mods.install_receipts import read_verified_install

        delivery.client.get.return_value = delivery.response(delivery.package())
        await mod.install_custom_delivery_artifact("tok", 9, "module", owner_scope="tenant:1")
        monkeypatch.setattr(
            "app.infrastructure.auth.dependencies.get_logged_in_user",
            lambda request: SimpleNamespace(id=1),
        )
        monkeypatch.setattr(
            "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
            lambda request, user: "tenant:1",
        )
        monkeypatch.setattr(
            "app.infrastructure.mods.install_receipts.read_verified_install",
            lambda mid: read_verified_install(mid, mods_root=delivery.manager.mods_root),
        )
        sent = []

        async def post(token, path, *, method, payload):
            assert token == "current-token"
            sent.append(copy.deepcopy(payload))
            if len(sent) == 1:
                raise ConnectionError("receipt response lost")
            return {"record": {"verified": False}}

        monkeypatch.setattr(mod, "custom_delivery_remote_json", post)
        request = Request({"type": "http", "headers": []})
        assert (await outbox.retry_delivery_receipts(request, "current-token"))["pending"] == 1
        summary = await outbox.retry_delivery_receipts(request, "current-token")
        assert summary["installed_reported"] == 1
        assert summary["runtime_reported"] == 0
        assert sent[0] == sent[1]
        assert sent[0]["stage"] == "installed"
        delivery.activation.assert_called_once_with("fixture-mod")
        assert delivery.install.call_count == 1
        assert delivery.client.get.await_count == 1
        assert delivery.outbox_rows()[0]["runtime_reported"] is False

    async def test_finally_unlink_oserror_does_not_change_install_result(
        self, delivery, monkeypatch
    ):
        raw = delivery.package()
        delivery.client.get.return_value = delivery.response(raw)
        real_unlink = Path.unlink
        failed_paths = []

        def unlink(path, *args, **kwargs):
            if path.name.startswith("xcagi-custom-delivery-"):
                failed_paths.append(path)
                raise OSError("busy")
            return real_unlink(path, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "unlink", unlink)
            result = await mod.install_custom_delivery_artifact(
                "tok", 9, "module", owner_scope="tenant:1"
            )
        assert result["success"] is True
        assert failed_paths
        for path in failed_paths:
            real_unlink(path, missing_ok=True)


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
    @pytest.fixture
    def library(self, delivery, monkeypatch):
        raw = delivery.package()
        rows = [
            {
                "id": "fixture-mod",
                "version": "2.0.0",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "delivery_ticket_id": 9,
            }
        ]
        export_headers = dict(delivery.response(raw).headers)
        export_headers["x-delivery-ticket-id"] = "9"
        fetch = AsyncMock(return_value=rows)

        async def download(path, destination, *, headers):
            assert path == "/v1/mod-sync/export-zip/fixture-mod"
            assert headers == {"Authorization": "Bearer tok"}
            destination.write_bytes(raw)
            return dict(export_headers)

        download_mock = AsyncMock(side_effect=download)
        monkeypatch.setattr(mod, "fetch_private_mod_library", fetch)
        monkeypatch.setattr(mod, "catalog_download_to", download_mock)
        return SimpleNamespace(
            raw=raw,
            rows=rows,
            headers=export_headers,
            fetch=fetch,
            download=download_mock,
        )

    async def test_invalid_id(self):
        for bad in ("", None, "a/b", "a\\b"):
            with pytest.raises(ValueError):
                await mod.update_private_mod_from_library(bad, "tok", owner_scope="tenant:1")

    async def test_owner_required_before_fetch(self, delivery, library):
        with pytest.raises(ValueError, match="工作空间|owner"):
            await mod.update_private_mod_from_library("fixture-mod", "tok")
        library.fetch.assert_not_awaited()
        library.download.assert_not_awaited()
        delivery.install.assert_not_called()

    async def test_background_install_rejects_a_signed_global_package(self, delivery, library):
        with pytest.raises(ValueError):
            await mod.update_private_mod_from_library(
                "fixture-mod", "tok", owner_scope="tenant:1", require_account_scope=True
            )
        delivery.install.assert_not_called()
        delivery.activation.assert_not_called()
        assert delivery.outbox_rows() == []

    async def test_remote_not_found(self, delivery, library):
        library.rows.clear()
        with pytest.raises(LookupError):
            await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        library.download.assert_not_awaited()

    async def test_remote_version_missing(self, delivery, library):
        library.rows[0]["version"] = " "
        with pytest.raises(ValueError):
            await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    async def test_expected_version_mismatch(self, delivery, library):
        with pytest.raises(ValueError):
            await mod.update_private_mod_from_library(
                "fixture-mod", "tok", expected_version="1.0.0", owner_scope="tenant:1"
            )
        library.download.assert_not_awaited()

    async def test_already_latest_local(self, delivery, library):
        await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        library.download.reset_mock()
        delivery.install.reset_mock()
        result = await mod.update_private_mod_from_library(
            "fixture-mod", "tok", owner_scope="tenant:1"
        )
        assert result["success"] is True
        assert result["updated"] is False
        library.download.assert_not_awaited()
        delivery.install.assert_not_called()
        delivery.activation.assert_called_once_with("fixture-mod")

    async def test_empty_token_raises_permission(self, delivery, library):
        with pytest.raises(PermissionError):
            await mod.update_private_mod_from_library("fixture-mod", "", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    async def test_successful_update_preserves_signed_bytes_and_owner(self, delivery, library):
        from app.infrastructure.mods.install_receipts import read_verified_install

        result = await mod.update_private_mod_from_library(
            "fixture-mod", "tok", owner_scope="tenant:1"
        )
        assert result["success"] is True
        assert result["updated"] is True
        assert result["current_version"] == "2.0.0"
        receipt = read_verified_install("fixture-mod", mods_root=delivery.manager.mods_root)
        assert receipt["signature_verified"] is True
        assert receipt["owner_scope"] == "tenant:1"
        assert receipt["package_sha256"] == hashlib.sha256(library.raw).hexdigest()
        archive = (
            delivery.root
            / "mods/.install-receipts/fixture-mod"
            / (receipt["package_sha256"] + ".zip")
        )
        assert archive.read_bytes() == library.raw
        (row,) = delivery.outbox_rows()
        assert row["ticket_id"] == result["delivery_ticket_id"] == 9
        assert row["payload"]["receipt_id"] == result["receipt_id"] + ":installed"
        assert row["owner"] == "tenant:1"
        assert row["payload"]["stage"] == "installed"
        assert row["payload"]["receipt_token"] == library.headers["x-delivery-receipt-token"]
        assert row["payload"]["package_sha256"] == receipt["package_sha256"]
        assert row["runtime_reported"] is False
        assert delivery.install.call_args.kwargs == {
            "verify_signature": True,
            "activate": True,
            "owner_scope": "tenant:1",
        }

    @pytest.mark.parametrize(
        "header,value",
        [
            ("x-delivery-receipt-token", ""),
            ("x-delivery-artifact-sha256", "0" * 64),
            ("x-delivery-artifact-version", "9.9.9"),
            ("x-delivery-ticket-id", ""),
            ("x-delivery-ticket-id", "10"),
        ],
    )
    async def test_export_grant_must_match_before_install(self, delivery, library, header, value):
        library.headers[header] = value
        with pytest.raises((ValueError, RuntimeError)):
            await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        delivery.install.assert_not_called()
        delivery.activation.assert_not_called()
        assert delivery.outbox_rows() == []

    @pytest.mark.parametrize("digest", ["", "0" * 64])
    async def test_catalog_digest_missing_or_wrong_never_installs(self, delivery, library, digest):
        library.rows[0]["sha256"] = digest
        with pytest.raises((ValueError, RuntimeError), match="摘要|digest|SHA"):
            await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    @pytest.mark.parametrize("identity", [{"mid": "other"}, {"version": "9.9.9"}])
    async def test_signed_manifest_must_match_catalog(self, delivery, library, identity):
        raw = delivery.package(**identity)
        library.rows[0]["sha256"] = hashlib.sha256(raw).hexdigest()
        library.headers["x-delivery-artifact-sha256"] = hashlib.sha256(raw).hexdigest()

        async def download(path, destination, *, headers):
            destination.write_bytes(raw)
            return dict(library.headers)

        library.download.side_effect = download
        with pytest.raises(ValueError, match="身份校验|不一致"):
            await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        delivery.install.assert_not_called()

    async def test_install_fail(self, delivery, library):
        delivery.install.return_value = (False, "boom", None)
        with pytest.raises(RuntimeError, match="boom"):
            await mod.update_private_mod_from_library("fixture-mod", "tok", owner_scope="tenant:1")
        rows = delivery.outbox_rows()
        assert len(rows) == 1
        assert rows[0]["installed_reported"] is False
        assert rows[0]["runtime_reported"] is False

    async def test_api_ready_recoverable_error_logged(self, delivery, library):
        delivery.api_ready.side_effect = RuntimeError("flush failed")
        result = await mod.update_private_mod_from_library(
            "fixture-mod", "tok", owner_scope="tenant:1"
        )
        assert result["updated"] is True

    async def test_previous_version_from_local(self, delivery, library):
        old = delivery.package(version="1.0.0", content="old")
        path = delivery.root / "old.zip"
        path.write_bytes(old)
        assert delivery.manager.install_mod_package(
            str(path), activate=False, owner_scope="tenant:1"
        )[0]
        result = await mod.update_private_mod_from_library(
            "fixture-mod", "tok", owner_scope="tenant:1"
        )
        assert result["previous_version"] == "1.0.0"
        assert result["current_version"] == "2.0.0"

    async def test_active_update_keeps_old_code_until_restart(self, delivery, library):
        from app.infrastructure.mods.install_receipts import read_verified_install

        old = delivery.package(version="1.0.0", content="old running code")
        old_path = delivery.root / "old.zip"
        old_path.write_bytes(old)
        assert delivery.manager.install_mod_package(
            str(old_path), activate=False, owner_scope="tenant:1"
        )[0]
        delivery.manager._loaded_mods.append("fixture-mod")
        delivery.install.reset_mock()
        result = await mod.update_private_mod_from_library(
            "fixture-mod", "tok", owner_scope="tenant:1"
        )
        assert result["updated"] is True
        assert result["requires_restart"] is True
        assert result["runtime_status"] == "restart_required"
        assert (delivery.root / "mods/fixture-mod/logic.py").read_text() == "old running code"
        receipt = read_verified_install("fixture-mod", mods_root=delivery.manager.mods_root)
        assert receipt["package_sha256"] == hashlib.sha256(library.raw).hexdigest()
        assert receipt["package_version"] == "2.0.0"
        assert receipt["requires_restart"] is True
        assert (Path(receipt["installed_root"]) / "logic.py").read_text() == "fixture code"
        delivery.api_ready.assert_not_called()
        delivery.activation.assert_not_called()
